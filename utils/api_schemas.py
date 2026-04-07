"""API-facing request/response schemas with ORM-coupled enum dependencies."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator

from models.enums import StoryResolution, TaskAcceptanceResult, TaskStatus


class TaskExecutionWriteRequest(BaseModel):
    """Payload for updating a task's status and logging its outcome."""

    new_status: TaskStatus
    outcome_summary: Optional[str] = None
    artifact_refs: Optional[List[str]] = None
    acceptance_result: Optional[TaskAcceptanceResult] = None
    notes: Optional[str] = None
    changed_by: Optional[str] = None

    @model_validator(mode="after")
    def validate_execution_rules(self) -> "TaskExecutionWriteRequest":
        if self.artifact_refs is not None:
            self.artifact_refs = [
                ref.strip() for ref in self.artifact_refs if ref and ref.strip()
            ]

        has_outcome = bool(self.outcome_summary and self.outcome_summary.strip())
        has_artifacts = bool(self.artifact_refs)
        has_notes = bool(self.notes and self.notes.strip())

        if not (has_outcome or has_artifacts or has_notes):
            if self.new_status != TaskStatus.TO_DO:
                raise ValueError("Must provide outcome_summary, artifact_refs, or notes.")

        if self.new_status == TaskStatus.DONE:
            if not has_outcome:
                raise ValueError("An outcome_summary is required when marking a task Done.")
            if self.acceptance_result == TaskAcceptanceResult.NOT_CHECKED:
                raise ValueError("An acceptance_result must be recorded when mapping a task Done.")
            if not self.acceptance_result:
                self.acceptance_result = TaskAcceptanceResult.NOT_CHECKED
                raise ValueError("An explicit acceptance_result is required when marking a task Done.")

        return self


class TaskExecutionLogEntry(BaseModel):
    log_id: int
    task_id: int
    sprint_id: int
    old_status: Optional[TaskStatus]
    new_status: TaskStatus
    outcome_summary: Optional[str]
    artifact_refs: List[str]
    acceptance_result: TaskAcceptanceResult
    notes: Optional[str]
    changed_by: str
    changed_at: datetime


class TaskExecutionReadResponse(BaseModel):
    success: bool
    task_id: int
    sprint_id: int
    current_status: TaskStatus
    latest_entry: Optional[TaskExecutionLogEntry] = None
    history: List[TaskExecutionLogEntry] = Field(default_factory=list)


class StoryTaskProgressSummary(BaseModel):
    total_tasks: int
    done_tasks: int
    cancelled_tasks: int
    all_actionable_tasks_done: bool


class StoryCloseReadResponse(BaseModel):
    success: bool
    story_id: int
    sprint_id: int
    current_status: str
    resolution: Optional[StoryResolution] = None
    completion_notes: Optional[str] = None
    evidence_links: Optional[str] = None
    completed_at: Optional[datetime] = None
    readiness: StoryTaskProgressSummary
    close_eligible: bool
    ineligible_reason: Optional[str] = None


class StoryCloseWriteRequest(BaseModel):
    resolution: StoryResolution
    completion_notes: str = Field(min_length=1)
    evidence_links: Optional[List[str]] = None
    known_gaps: Optional[str] = None
    follow_up_notes: Optional[str] = None
    changed_by: Optional[str] = Field(default="manual-ui")

    @model_validator(mode="after")
    def validate_story_close(self) -> "StoryCloseWriteRequest":
        if self.evidence_links is not None:
            self.evidence_links = [
                ref.strip() for ref in self.evidence_links if ref and ref.strip()
            ]
        if not self.completion_notes or not self.completion_notes.strip():
            raise ValueError("completion_notes is required to close a story")
        return self


class SprintCloseStorySummary(BaseModel):
    story_id: int
    story_title: str
    story_status: str
    total_tasks: int
    done_tasks: int
    cancelled_tasks: int
    completion_state: Literal["completed", "unfinished"]


class SprintCloseReadiness(BaseModel):
    completed_story_count: int
    open_story_count: int
    unfinished_story_ids: List[int] = Field(default_factory=list)
    stories: List[SprintCloseStorySummary] = Field(default_factory=list)


class SprintCloseReadResponse(BaseModel):
    success: bool
    sprint_id: int
    current_status: str
    completed_at: Optional[datetime] = None
    readiness: SprintCloseReadiness
    close_eligible: bool
    ineligible_reason: Optional[str] = None
    history_fidelity: Literal["snapshotted", "derived"] = "derived"
    close_snapshot: Optional[Dict[str, Any]] = None


class SprintCloseWriteRequest(BaseModel):
    completion_notes: str = Field(min_length=1)
    follow_up_notes: Optional[str] = None
    changed_by: Optional[str] = Field(default="manual-ui")
