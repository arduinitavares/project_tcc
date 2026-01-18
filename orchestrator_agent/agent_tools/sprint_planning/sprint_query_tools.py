"""
Sprint query tools for retrieving sprint details.
Provides read-only access to sprint information.
"""

from typing import Optional, Dict, Any, List
from sqlmodel import Session, select
from agile_sqlmodel import (
    Sprint,
    UserStory,
    SprintStory,
    Team,
    Product,
    Task,
    engine,
    StoryStatus,
)
from pydantic import BaseModel, Field


class GetSprintDetailsInput(BaseModel):
    """Input schema for getting sprint details."""
    sprint_id: Optional[int] = Field(
        None, 
        description="ID of the sprint to query. If omitted, returns the most recent active sprint for the product."
    )
    product_id: Optional[int] = Field(
        None,
        description="Product ID to find the active sprint for (used when sprint_id is not provided)"
    )


def get_sprint_details(query_input: GetSprintDetailsInput) -> Dict[str, Any]:
    """
    Get detailed information about a sprint including stories, tasks, and progress.
    
    Returns:
    - Sprint metadata (goal, dates, team, status)
    - Stories in the sprint with current status
    - Tasks if any
    - Progress metrics
    """
    # Handle dict input from ADK
    if isinstance(query_input, dict):
        query_input = GetSprintDetailsInput(**query_input)
    
    try:
        with Session(engine) as session:
            # Find the sprint
            sprint = None
            
            if query_input.sprint_id:
                # Query by sprint ID
                sprint = session.get(Sprint, query_input.sprint_id)
                if not sprint:
                    return {
                        "success": False,
                        "error": f"Sprint {query_input.sprint_id} not found"
                    }
            elif query_input.product_id:
                # Find most recent active sprint for product
                stmt = (
                    select(Sprint)
                    .where(Sprint.product_id == query_input.product_id)
                    .where(Sprint.status.in_(["PLANNED", "ACTIVE"]))
                    .order_by(Sprint.start_date.desc())
                )
                sprint = session.exec(stmt).first()
                
                if not sprint:
                    return {
                        "success": False,
                        "error": f"No active sprint found for product {query_input.product_id}"
                    }
            else:
                return {
                    "success": False,
                    "error": "Must provide either sprint_id or product_id"
                }
            
            # Get team info
            team = session.get(Team, sprint.team_id)
            team_name = team.name if team else "Unknown Team"
            
            # Get product info
            product = session.get(Product, sprint.product_id)
            product_name = product.name if product else "Unknown Product"
            
            # FIX: Use a single JOIN to fetch all stories at once
            stories_stmt = (
                select(UserStory)
                .join(SprintStory, UserStory.story_id == SprintStory.story_id)
                .where(SprintStory.sprint_id == sprint.sprint_id)
            )
            sprint_stories_results = session.exec(stories_stmt).all()

            stories = []
            total_points = 0
            completed_points = 0
            status_counts = {status: 0 for status in StoryStatus}

            for story in sprint_stories_results:
                stories.append(
                    {
                        "story_id": story.story_id,
                        "title": story.title,
                        "status": story.status.value,
                        "story_points": story.story_points,
                    }
                )

                if story.story_points:
                    total_points += story.story_points
                    if story.status == StoryStatus.DONE:
                        completed_points += story.story_points

                status_counts[story.status] += 1

            status_counts = {k.value: v for k, v in status_counts.items()}
            
            # Get tasks in sprint
            tasks_stmt = (
                select(Task)
                .join(SprintStory, Task.story_id == SprintStory.story_id)
                .where(SprintStory.sprint_id == sprint.sprint_id)
            )
            tasks = session.exec(tasks_stmt).all()
            
            task_list = []
            task_status_counts = {"To Do": 0, "In Progress": 0, "Done": 0}
            for task in tasks:
                task_list.append({
                    "task_id": task.task_id,
                    "description": task.description,
                    "status": task.status.value if hasattr(task.status, 'value') else task.status,
                    "story_id": task.story_id,
                    "assigned_to_member_id": task.assigned_to_member_id
                })
                status_key = task.status.value if hasattr(task.status, 'value') else task.status
                task_status_counts[status_key] = task_status_counts.get(status_key, 0) + 1
            
            # Calculate progress
            completion_pct = None
            if total_points > 0:
                completion_pct = round((completed_points / total_points) * 100, 1)
            
            return {
                "success": True,
                "sprint": {
                    "sprint_id": sprint.sprint_id,
                    "product_id": sprint.product_id,
                    "product_name": product_name,
                    "team_id": sprint.team_id,
                    "team_name": team_name,
                    "goal": sprint.goal,
                    "start_date": str(sprint.start_date),
                    "end_date": str(sprint.end_date),
                    "status": sprint.status,
                    "created_at": str(sprint.created_at)
                },
                "stories": stories,
                "story_count": len(stories),
                "story_status_breakdown": status_counts,
                "tasks": task_list,
                "task_count": len(task_list),
                "task_status_breakdown": task_status_counts,
                "metrics": {
                    "total_points": total_points,
                    "completed_points": completed_points,
                    "completion_pct": completion_pct
                },
                "message": f"Sprint #{sprint.sprint_id} for {team_name}: {len(stories)} stories, {len(task_list)} tasks"
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Database error: {str(e)}"
        }


def list_sprints(product_id: int) -> Dict[str, Any]:
    """
    List all sprints for a product.
    
    Args:
        product_id: The product ID
    
    Returns:
        List of sprints with summary information
    """
    try:
        with Session(engine) as session:
            # Get product
            product = session.get(Product, product_id)
            if not product:
                return {
                    "success": False,
                    "error": f"Product {product_id} not found"
                }
            
            # Get all sprints for product
            stmt = (
                select(Sprint)
                .where(Sprint.product_id == product_id)
                .order_by(Sprint.start_date.desc())
            )
            sprints = session.exec(stmt).all()
            
            sprint_summaries = []
            for sprint in sprints:
                # Get team
                team = session.get(Team, sprint.team_id)
                
                # Count stories
                sprint_stories_stmt = (
                    select(SprintStory)
                    .where(SprintStory.sprint_id == sprint.sprint_id)
                )
                story_count = len(session.exec(sprint_stories_stmt).all())
                
                sprint_summaries.append({
                    "sprint_id": sprint.sprint_id,
                    "goal": sprint.goal,
                    "start_date": str(sprint.start_date),
                    "end_date": str(sprint.end_date),
                    "status": sprint.status,
                    "team_name": team.name if team else "Unknown",
                    "story_count": story_count
                })
            
            return {
                "success": True,
                "product_id": product_id,
                "product_name": product.name,
                "sprints": sprint_summaries,
                "sprint_count": len(sprint_summaries),
                "message": f"Found {len(sprint_summaries)} sprint(s) for {product.name}"
            }
            
    except Exception as e:
        return {
            "success": False,
            "error": f"Database error: {str(e)}"
        }
