"""
Sprint execution tools for managing active sprints.
Provides mutation tools for updating story status and modifying sprint contents.
"""

from typing import Optional, Dict, Any, List, Literal
from datetime import datetime
from sqlmodel import Session, select
from agile_sqlmodel import (
    Sprint, UserStory, SprintStory, WorkflowEvent, WorkflowEventType,
    engine
)
from pydantic import BaseModel, Field
import json


# -----------------------------------------------------------------------------
# Update Story Status
# -----------------------------------------------------------------------------

class UpdateStoryStatusInput(BaseModel):
    """Input schema for updating a story's status."""
    story_id: int = Field(..., description="ID of the story to update")
    new_status: Literal["TO_DO", "IN_PROGRESS", "DONE"] = Field(
        ..., 
        description="New status for the story"
    )
    sprint_id: Optional[int] = Field(
        None,
        description="Sprint ID (for validation that story is in this sprint)"
    )


def update_story_status(status_input: UpdateStoryStatusInput) -> Dict[str, Any]:
    """
    Update a user story's status.
    
    Workflow:
    - TO_DO → IN_PROGRESS: Work begins
    - IN_PROGRESS → DONE: Story completed
    - Can also revert: DONE → IN_PROGRESS, IN_PROGRESS → TO_DO
    
    Returns:
        Dict with success status and updated story info
    """
    # Handle dict input from ADK
    if isinstance(status_input, dict):
        status_input = UpdateStoryStatusInput(**status_input)
    
    print(f"[Tool: update_story_status] Updating story {status_input.story_id} → {status_input.new_status}")
    
    try:
        with Session(engine) as session:
            # Get the story
            story = session.get(UserStory, status_input.story_id)
            if not story:
                return {
                    "success": False,
                    "error": f"Story {status_input.story_id} not found"
                }
            
            old_status = story.status
            
            # If sprint_id provided, verify story is in that sprint
            if status_input.sprint_id:
                sprint_story = session.exec(
                    select(SprintStory)
                    .where(SprintStory.sprint_id == status_input.sprint_id)
                    .where(SprintStory.story_id == status_input.story_id)
                ).first()
                
                if not sprint_story:
                    return {
                        "success": False,
                        "error": f"Story {status_input.story_id} is not in sprint {status_input.sprint_id}"
                    }
            
            # Update the status
            story.status = status_input.new_status
            session.add(story)
            session.commit()
            session.refresh(story)
            
            print(f"   [DB] Story {story.story_id} status: {old_status} → {story.status}")
            
            return {
                "success": True,
                "story_id": story.story_id,
                "title": story.title,
                "old_status": old_status,
                "new_status": story.status,
                "story_points": story.story_points,
                "message": f"✅ Story #{story.story_id} updated: {old_status} → {story.status}"
            }
            
    except Exception as e:
        print(f"   [DB Error] {e}")
        return {
            "success": False,
            "error": f"Database error: {str(e)}"
        }


# -----------------------------------------------------------------------------
# Batch Update Story Status
# -----------------------------------------------------------------------------

class BatchUpdateStatusInput(BaseModel):
    """Input schema for batch updating story statuses."""
    updates: List[Dict[str, Any]] = Field(
        ...,
        description="List of {story_id, new_status} objects"
    )
    sprint_id: Optional[int] = Field(
        None,
        description="Sprint ID (for validation)"
    )


def batch_update_story_status(batch_input: BatchUpdateStatusInput) -> Dict[str, Any]:
    """
    Update multiple stories' statuses in one operation.
    Useful for daily standups or sprint reviews.
    
    Returns:
        Dict with success count and any failures
    """
    # Handle dict input from ADK
    if isinstance(batch_input, dict):
        batch_input = BatchUpdateStatusInput(**batch_input)
    
    print(f"[Tool: batch_update_story_status] Updating {len(batch_input.updates)} stories")
    
    results = []
    success_count = 0
    failure_count = 0
    
    for update in batch_input.updates:
        single_input = UpdateStoryStatusInput(
            story_id=update["story_id"],
            new_status=update["new_status"],
            sprint_id=batch_input.sprint_id
        )
        result = update_story_status(single_input)
        results.append(result)
        
        if result["success"]:
            success_count += 1
        else:
            failure_count += 1
    
    return {
        "success": failure_count == 0,
        "total": len(batch_input.updates),
        "success_count": success_count,
        "failure_count": failure_count,
        "results": results,
        "message": f"Updated {success_count}/{len(batch_input.updates)} stories"
    }


# -----------------------------------------------------------------------------
# Modify Sprint Stories (Add/Remove)
# -----------------------------------------------------------------------------

class ModifySprintStoriesInput(BaseModel):
    """Input schema for adding or removing stories from a sprint."""
    sprint_id: int = Field(..., description="ID of the sprint to modify")
    add_story_ids: Optional[List[int]] = Field(
        None,
        description="Story IDs to add to the sprint"
    )
    remove_story_ids: Optional[List[int]] = Field(
        None,
        description="Story IDs to remove from the sprint"
    )


def modify_sprint_stories(modify_input: ModifySprintStoriesInput) -> Dict[str, Any]:
    """
    Add or remove stories from an active sprint.
    
    Rules:
    - Can only add TO_DO stories (not already in another active sprint)
    - Removing a story sets its status back to TO_DO
    - Cannot modify COMPLETED sprints
    
    Returns:
        Dict with success status and modification summary
    """
    # Handle dict input from ADK
    if isinstance(modify_input, dict):
        modify_input = ModifySprintStoriesInput(**modify_input)
    
    print(f"[Tool: modify_sprint_stories] Sprint {modify_input.sprint_id}")
    
    try:
        with Session(engine) as session:
            # Get the sprint
            sprint = session.get(Sprint, modify_input.sprint_id)
            if not sprint:
                return {
                    "success": False,
                    "error": f"Sprint {modify_input.sprint_id} not found"
                }
            
            # Check sprint status
            if sprint.status == "COMPLETED":
                return {
                    "success": False,
                    "error": "Cannot modify a completed sprint"
                }
            
            added = []
            add_errors = []
            removed = []
            remove_errors = []
            
            # Process additions
            if modify_input.add_story_ids:
                for story_id in modify_input.add_story_ids:
                    story = session.get(UserStory, story_id)
                    if not story:
                        add_errors.append({"story_id": story_id, "error": "Story not found"})
                        continue
                    
                    # Check if already in this sprint
                    existing = session.exec(
                        select(SprintStory)
                        .where(SprintStory.sprint_id == sprint.sprint_id)
                        .where(SprintStory.story_id == story_id)
                    ).first()
                    
                    if existing:
                        add_errors.append({"story_id": story_id, "error": "Already in sprint"})
                        continue
                    
                    # Check if in another active sprint
                    other_sprint_link = session.exec(
                        select(SprintStory)
                        .join(Sprint, Sprint.sprint_id == SprintStory.sprint_id)
                        .where(SprintStory.story_id == story_id)
                        .where(Sprint.status.in_(["PLANNED", "ACTIVE"]))
                    ).first()
                    
                    if other_sprint_link:
                        add_errors.append({
                            "story_id": story_id, 
                            "error": f"Already in sprint {other_sprint_link.sprint_id}"
                        })
                        continue
                    
                    # Add to sprint
                    sprint_story = SprintStory(
                        sprint_id=sprint.sprint_id,
                        story_id=story_id,
                        added_at=datetime.utcnow()
                    )
                    session.add(sprint_story)
                    
                    # Update story status to IN_PROGRESS
                    story.status = "IN_PROGRESS"
                    session.add(story)
                    
                    added.append({
                        "story_id": story_id,
                        "title": story.title,
                        "story_points": story.story_points
                    })
                    print(f"   [+] Added story {story_id}: {story.title}")
            
            # Process removals
            if modify_input.remove_story_ids:
                for story_id in modify_input.remove_story_ids:
                    # Find the link
                    sprint_story = session.exec(
                        select(SprintStory)
                        .where(SprintStory.sprint_id == sprint.sprint_id)
                        .where(SprintStory.story_id == story_id)
                    ).first()
                    
                    if not sprint_story:
                        remove_errors.append({
                            "story_id": story_id, 
                            "error": "Not in this sprint"
                        })
                        continue
                    
                    story = session.get(UserStory, story_id)
                    if story:
                        # Check if story is already DONE
                        if story.status == "DONE":
                            remove_errors.append({
                                "story_id": story_id,
                                "error": "Cannot remove completed story"
                            })
                            continue
                        
                        # Revert status to TO_DO
                        story.status = "TO_DO"
                        session.add(story)
                    
                    # Remove from sprint
                    session.delete(sprint_story)
                    
                    removed.append({
                        "story_id": story_id,
                        "title": story.title if story else "Unknown"
                    })
                    print(f"   [-] Removed story {story_id}")
            
            session.commit()
            
            # Calculate new sprint totals
            sprint_stories = session.exec(
                select(SprintStory)
                .where(SprintStory.sprint_id == sprint.sprint_id)
            ).all()
            
            total_stories = len(sprint_stories)
            total_points = 0
            for ss in sprint_stories:
                story = session.get(UserStory, ss.story_id)
                if story and story.story_points:
                    total_points += story.story_points
            
            return {
                "success": True,
                "sprint_id": sprint.sprint_id,
                "added": added,
                "add_count": len(added),
                "add_errors": add_errors if add_errors else None,
                "removed": removed,
                "remove_count": len(removed),
                "remove_errors": remove_errors if remove_errors else None,
                "new_totals": {
                    "story_count": total_stories,
                    "total_points": total_points
                },
                "message": f"Sprint updated: +{len(added)} added, -{len(removed)} removed. Now has {total_stories} stories ({total_points} points)."
            }
            
    except Exception as e:
        print(f"   [DB Error] {e}")
        return {
            "success": False,
            "error": f"Database error: {str(e)}"
        }


# -----------------------------------------------------------------------------
# Complete Sprint
# -----------------------------------------------------------------------------

class CompleteSprintInput(BaseModel):
    """Input schema for completing a sprint."""
    sprint_id: int = Field(..., description="ID of the sprint to complete")
    notes: Optional[str] = Field(
        None,
        description="Optional retrospective notes"
    )


def complete_sprint(complete_input: CompleteSprintInput) -> Dict[str, Any]:
    """
    Mark a sprint as completed.
    
    - Changes sprint status to COMPLETED
    - Records completion metrics
    - Stories not marked DONE remain with their current status
    
    Returns:
        Dict with completion summary and metrics
    """
    # Handle dict input from ADK
    if isinstance(complete_input, dict):
        complete_input = CompleteSprintInput(**complete_input)
    
    print(f"[Tool: complete_sprint] Completing sprint {complete_input.sprint_id}")
    
    try:
        with Session(engine) as session:
            # Get the sprint
            sprint = session.get(Sprint, complete_input.sprint_id)
            if not sprint:
                return {
                    "success": False,
                    "error": f"Sprint {complete_input.sprint_id} not found"
                }
            
            if sprint.status == "COMPLETED":
                return {
                    "success": False,
                    "error": "Sprint is already completed"
                }
            
            # Calculate metrics
            sprint_stories = session.exec(
                select(SprintStory)
                .where(SprintStory.sprint_id == sprint.sprint_id)
            ).all()
            
            total_stories = len(sprint_stories)
            completed_stories = 0
            total_points = 0
            completed_points = 0
            incomplete_stories = []
            
            for ss in sprint_stories:
                story = session.get(UserStory, ss.story_id)
                if story:
                    if story.story_points:
                        total_points += story.story_points
                    
                    if story.status == "DONE":
                        completed_stories += 1
                        if story.story_points:
                            completed_points += story.story_points
                    else:
                        incomplete_stories.append({
                            "story_id": story.story_id,
                            "title": story.title,
                            "status": story.status
                        })
            
            # Update sprint status
            sprint.status = "COMPLETED"
            session.add(sprint)
            
            # Record workflow event
            event = WorkflowEvent(
                event_type=WorkflowEventType.SPRINT_PLAN_SAVED,  # Reusing for now
                timestamp=datetime.utcnow(),
                product_id=sprint.product_id,
                sprint_id=sprint.sprint_id,
                event_metadata=json.dumps({
                    "action": "sprint_completed",
                    "total_stories": total_stories,
                    "completed_stories": completed_stories,
                    "total_points": total_points,
                    "completed_points": completed_points,
                    "notes": complete_input.notes
                })
            )
            session.add(event)
            session.commit()
            
            completion_rate = round((completed_stories / total_stories * 100), 1) if total_stories > 0 else 0
            velocity = completed_points
            
            print(f"   [DB] Sprint {sprint.sprint_id} completed: {completed_stories}/{total_stories} stories")
            
            return {
                "success": True,
                "sprint_id": sprint.sprint_id,
                "status": "COMPLETED",
                "metrics": {
                    "total_stories": total_stories,
                    "completed_stories": completed_stories,
                    "completion_rate": completion_rate,
                    "total_points": total_points,
                    "completed_points": completed_points,
                    "velocity": velocity
                },
                "incomplete_stories": incomplete_stories if incomplete_stories else None,
                "message": f"🏁 Sprint #{sprint.sprint_id} completed! {completed_stories}/{total_stories} stories done ({completion_rate}%). Velocity: {velocity} points."
            }
            
    except Exception as e:
        print(f"   [DB Error] {e}")
        return {
            "success": False,
            "error": f"Database error: {str(e)}"
        }
