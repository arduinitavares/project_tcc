"""Input and output schemas for the Sprint Planner agent."""

import re
from typing import Annotated, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from utils.task_metadata import StructuredTaskSpec


class SprintPlannerStory(BaseModel):
    """A candidate user story for sprint planning.

    NOTE: No strict config or validation constraints here.
    ADK automatic function-calling cannot parse ge/le/min_length
    on input schemas. Constraints belong on output schemas only.
    """

    story_id: Annotated[int, Field(description="User story ID from the database.")]
    story_title: Annotated[
        str,
        Field(description="Short user story title (at least 3 chars)."),
    ]
    priority: Annotated[
        int,
        Field(description="Priority rank (1 is highest, must be >= 1)."),
    ]
    story_points: Annotated[
        Optional[int],
        Field(
            default=None,
            description="Optional story points estimate (>= 1 when provided).",
        ),
    ]
    story_description: Annotated[
        str,
        Field(description="Detailed user story description."),
    ]
    acceptance_criteria_items: Annotated[
        List[str],
        Field(default_factory=list, description="List of acceptance criteria items."),
    ]
    persona: Annotated[
        Optional[str],
        Field(default=None, description="Target persona for the story."),
    ]
    source_requirement: Annotated[
        Optional[str],
        Field(default=None, description="Original source requirement or reference."),
    ]
    evaluated_invariant_ids: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Invariant IDs already evaluated for this story and allowed for task binding.",
        ),
    ]
    story_compliance_boundary_summaries: Annotated[
        List[str],
        Field(
            default_factory=list,
            description="Summaries of compliance boundaries or architectural constraints applicable to this story.",
        ),
    ]


class SprintPlannerInput(BaseModel):
    """Schema for Sprint Planner input.

    NOTE: No ge/le/min_length constraints here.
    ADK automatic function-calling cannot parse Annotated constraints
    on input schemas. Validation constraints belong on output schemas.
    """

    available_stories: Annotated[
        List[SprintPlannerStory],
        Field(description="Prioritized list of available stories for this sprint."),
    ]
    team_velocity_assumption: Annotated[
        Literal["Low", "Medium", "High"],
        Field(description="Velocity band for capacity planning."),
    ]
    sprint_duration_days: Annotated[
        int,
        Field(
            description="Sprint duration in days (1-31).",
        ),
    ]
    user_context: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Optional user context or focus for the sprint.",
        ),
    ]
    max_story_points: Annotated[
        Optional[int],
        Field(
            default=None,
            description="Optional story points cap (>= 1) for capacity planning.",
        ),
    ]
    include_task_decomposition: Annotated[
        bool,
        Field(
            default=True,
            description="Whether to generate task decomposition per story.",
        ),
    ]


class SprintPlannerSelectedStory(BaseModel):
    """A selected story with justification and tasks."""

    model_config = ConfigDict(extra="forbid")

    story_id: Annotated[int, Field(description="User story ID selected for the sprint.")]
    story_title: Annotated[
        str,
        Field(min_length=3, description="Story title.")
    ]
    tasks: Annotated[
        List[StructuredTaskSpec],
        Field(
            default_factory=list,
            description="Optional structured task list for the story.",
        ),
    ]
    reason_for_selection: Annotated[
        str,
        Field(min_length=3, description="Reason this story supports the sprint goal."),
    ]


class SprintPlannerDeselectedStory(BaseModel):
    """A story not selected for the sprint."""

    model_config = ConfigDict(extra="forbid")

    story_id: Annotated[int, Field(description="User story ID not selected.")]
    reason: Annotated[
        str,
        Field(min_length=3, description="Reason this story was not selected."),
    ]


class SprintPlannerCapacityAnalysis(BaseModel):
    """Capacity analysis summary for sprint planning."""

    model_config = ConfigDict(extra="forbid")

    velocity_assumption: Annotated[
        Literal["Low", "Medium", "High"],
        Field(description="Velocity band used in the plan."),
    ]
    capacity_band: Annotated[
        str,
        Field(description="Human-readable capacity band, e.g., '2-3 stories'."),
    ]
    selected_count: Annotated[
        int,
        Field(ge=0, description="Number of stories selected."),
    ]
    story_points_used: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=0,
            description="Total story points selected when available.",
        ),
    ]
    max_story_points: Annotated[
        Optional[int],
        Field(
            default=None,
            ge=1,
            description="Optional story points cap used for planning.",
        ),
    ]
    commitment_note: Annotated[
        str,
        Field(
            min_length=3,
            description="Commitment check asking if scope is achievable.",
        ),
    ]
    reasoning: Annotated[
        str,
        Field(
            min_length=3,
            description="Explanation for why the sprint scope is feasible.",
        ),
    ]


class SprintPlannerOutput(BaseModel):
    """Schema for Sprint Planner output."""

    model_config = ConfigDict(extra="forbid")

    sprint_goal: Annotated[
        str,
        Field(min_length=3, description="Single sprint objective statement."),
    ]
    sprint_number: Annotated[
        int,
        Field(ge=1, description="Sprint number for this product.")
    ]
    duration_days: Annotated[
        int,
        Field(ge=1, le=31, description="Sprint duration in days."),
    ]
    selected_stories: Annotated[
        List[SprintPlannerSelectedStory],
        Field(description="Stories selected for the sprint backlog."),
    ]
    deselected_stories: Annotated[
        List[SprintPlannerDeselectedStory],
        Field(description="Stories not selected and why."),
    ]
    capacity_analysis: Annotated[
        SprintPlannerCapacityAnalysis,
        Field(description="Capacity reasoning and commitment check."),
    ]


def validate_task_invariant_bindings(
    output: "SprintPlannerOutput",
    *,
    allowed_invariant_ids_by_story: Dict[int, List[str]],
) -> List[str]:
    """Validate that each task only binds invariants allowed for its parent story."""

    errors: List[str] = []
    for story in output.selected_stories:
        allowed_ids = set(allowed_invariant_ids_by_story.get(story.story_id, []))
        for task in story.tasks:
            invalid_ids = [
                invariant_id
                for invariant_id in task.relevant_invariant_ids
                if invariant_id not in allowed_ids
            ]
            if invalid_ids:
                errors.append(
                    "Story "
                    f"{story.story_id} task '{task.description}' referenced invalid invariant IDs: "
                    + ", ".join(invalid_ids)
                )
    return errors


def validate_task_decomposition_quality(
    output: "SprintPlannerOutput",
    *,
    include_task_decomposition: bool,
    has_acceptance_criteria_by_story: Dict[int, bool],
) -> List[str]:
    """Validate deterministic quality gates for sprint task decomposition."""
    errors: List[str] = []

    file_extension_pattern = re.compile(r"\.[a-zA-Z0-9]+$")
    path_pattern = re.compile(r"[/\\]")

    for story in output.selected_stories:
        if include_task_decomposition and not story.tasks:
            errors.append(f"Story {story.story_id}: Missing task decomposition.")
            continue

        normalized_descriptions = set()
        
        # for under-decomposition check
        all_same_workstreams = True
        all_same_targets = True
        first_workstreams = None
        first_targets = None

        for task in story.tasks:
            # 1. Base required field quality
            desc = task.description.strip()
            if not desc:
                errors.append(f"Story {story.story_id}: Found task with empty description.")
            
            if task.task_kind == "other":
                errors.append(f"Story {story.story_id} task '{desc}': 'task_kind' cannot be 'other'. Please categorize properly.")
            
            if not task.artifact_targets:
                errors.append(f"Story {story.story_id} task '{desc}': Must specify at least one artifact_target.")
                
            if not task.workstream_tags:
                errors.append(f"Story {story.story_id} task '{desc}': Must specify at least one workstream_tag.")

            # 2. File path heuristic rejections
            for target in task.artifact_targets:
                if file_extension_pattern.search(target) or path_pattern.search(target):
                    errors.append(f"Story {story.story_id} task '{desc}': artifact_target '{target}' looks like an exact file path. Use component/module names instead.")

            # 3. Duplication checks
            norm_desc = re.sub(r'[^a-z0-9]', '', desc.lower())
            if norm_desc:
                if norm_desc in normalized_descriptions:
                    errors.append(f"Story {story.story_id}: Duplicate or identical task description found: '{desc}'.")
                normalized_descriptions.add(norm_desc)

            norm_targets = [re.sub(r'[^a-z0-9]', '', t.lower()) for t in task.artifact_targets]
            if len(norm_targets) != len(set(norm_targets)):
                errors.append(f"Story {story.story_id} task '{desc}': Contains duplicate artifact_targets.")
                
            norm_tags = [re.sub(r'[^a-z0-9]', '', t.lower()) for t in task.workstream_tags]
            if len(norm_tags) != len(set(norm_tags)):
                errors.append(f"Story {story.story_id} task '{desc}': Contains duplicate workstream_tags.")

            # Tracking sets for under-decomposition heuristic
            task_tags_set = frozenset(norm_tags)
            task_targets_set = frozenset(norm_targets)
            
            if first_workstreams is None:
                first_workstreams = task_tags_set
                first_targets = task_targets_set
            else:
                if task_tags_set != first_workstreams:
                    all_same_workstreams = False
                if task_targets_set != first_targets:
                    all_same_targets = False

        # 4. Under-decomposition check
        has_ac = has_acceptance_criteria_by_story.get(story.story_id, False)
        if (
            has_ac 
            and len(story.tasks) > 1 
            and all_same_workstreams 
            and all_same_targets
        ):
            errors.append(f"Story {story.story_id}: Tasks are under-decomposed. All {len(story.tasks)} tasks carry the exact same workstreams and artifact targets.")

    return errors


__all__ = [
    "SprintPlannerStory",
    "SprintPlannerInput",
    "SprintPlannerSelectedStory",
    "SprintPlannerDeselectedStory",
    "SprintPlannerCapacityAnalysis",
    "SprintPlannerOutput",
    "validate_task_invariant_bindings",
    "validate_task_decomposition_quality",
]
