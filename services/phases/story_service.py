"""Story phase application service helpers."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from typing import Any

from orchestrator_agent.agent_tools.story_linkage import (
    normalize_requirement_key,
)
from orchestrator_agent.agent_tools.user_story_writer_tool.tools import (
    SaveStoriesInput,
)
from orchestrator_agent.fsm.states import OrchestratorState
from services.interview_runtime import hydrate_story_runtime_from_legacy

VALID_FSM_STATES = {state.value for state in OrchestratorState}


class StoryPhaseError(Exception):
    """Domain-level story phase error for router translation."""

    def __init__(self, detail: str, *, status_code: int = 409) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def get_all_roadmap_requirements(state: dict[str, Any]) -> list[str]:
    """Extract all assigned backlog items from saved roadmap releases."""
    releases = state.get("roadmap_releases") or []
    reqs: list[str] = []
    for release in releases:
        items = release.get("items") or []
        reqs.extend(items)
    return reqs


def ensure_story_runtime(
    state: dict[str, Any],
    *,
    parent_requirement: str,
) -> dict[str, Any]:
    return hydrate_story_runtime_from_legacy(
        state,
        parent_requirement=parent_requirement,
    )


def story_retryable(classification: str | None) -> bool:
    return classification in {
        "nonreusable_provider_failure",
        "nonreusable_transport_failure",
    }


def _find_attempt_by_id(
    runtime: dict[str, Any],
    attempt_id: str,
) -> dict[str, Any] | None:
    for attempt in reversed(runtime.get("attempt_history") or []):
        if not isinstance(attempt, dict):
            continue
        if attempt.get("attempt_id") == attempt_id:
            return attempt
    return None


def _story_current_draft_artifact(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    draft_projection = runtime.get("draft_projection") or {}
    attempt_id = draft_projection.get("latest_reusable_attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return None

    attempt = _find_attempt_by_id(runtime, attempt_id)
    artifact = (attempt or {}).get("output_artifact")
    if not isinstance(artifact, dict):
        return None

    stories = artifact.get("user_stories")
    if not isinstance(stories, list) or len(stories) == 0:
        return None
    return artifact


def _story_merge_recommendation_from_artifact(
    artifact: dict[str, Any],
) -> dict[str, Any] | None:
    stories = artifact.get("user_stories")
    if not isinstance(stories, list):
        return None

    for story in stories:
        if not isinstance(story, dict):
            continue
        if story.get("invest_score") != "Low":
            continue

        warning = story.get("decomposition_warning")
        if not isinstance(warning, str) or not warning.strip():
            continue

        normalized_warning = " ".join(warning.lower().split())
        if not any(
            signal in normalized_warning
            for signal in (
                "recommend consolidating",
                "merge this",
                "retire this separate requirement",
                "retire this requirement",
                "merge into",
                "consolidated into",
                "may be redundant",
                "requirement may be redundant",
            )
        ):
            continue

        owner_match = re.search(r"owned by '([^']+)'", warning, flags=re.IGNORECASE)
        if not owner_match:
            continue

        acceptance_criteria = story.get("acceptance_criteria")
        if not isinstance(acceptance_criteria, list):
            acceptance_criteria = []

        return {
            "action": "merge_into_requirement",
            "owner_requirement": owner_match.group(1).strip(),
            "reason": warning.strip(),
            "acceptance_criteria_to_move": [
                item
                for item in acceptance_criteria
                if isinstance(item, str) and item.strip()
            ],
        }

    return None


def story_save_payload(runtime: dict[str, Any]) -> dict[str, Any] | None:
    draft_projection = runtime.get("draft_projection") or {}
    if draft_projection.get("kind") != "complete_draft":
        return None

    artifact = _story_current_draft_artifact(runtime)
    if not isinstance(artifact, dict):
        return None
    if _story_merge_recommendation_from_artifact(artifact):
        return None
    if not artifact.get("is_complete"):
        return None
    return artifact


def story_current_resolution(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    resolution_projection = runtime.get("resolution_projection") or {}
    if not isinstance(resolution_projection, dict) or not resolution_projection:
        return None
    if resolution_projection.get("status") != "merged":
        return None

    owner_requirement = resolution_projection.get("owner_requirement")
    reason = resolution_projection.get("reason")
    criteria = resolution_projection.get("acceptance_criteria_to_move")
    if not isinstance(owner_requirement, str) or not owner_requirement.strip():
        return None
    if not isinstance(reason, str) or not reason.strip():
        return None
    if not isinstance(criteria, list):
        criteria = []

    return {
        "status": "merged",
        "owner_requirement": owner_requirement,
        "reason": reason,
        "acceptance_criteria_to_move": [
            item for item in criteria if isinstance(item, str) and item.strip()
        ],
        "resolved_at": resolution_projection.get("resolved_at"),
    }


def story_merge_recommendation_payload(
    runtime: dict[str, Any],
) -> dict[str, Any] | None:
    artifact = _story_current_draft_artifact(runtime)
    if not isinstance(artifact, dict):
        return None
    return _story_merge_recommendation_from_artifact(artifact)


def story_resolution_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    current = story_current_resolution(runtime)
    recommendation = None if current else story_merge_recommendation_payload(runtime)
    return {
        "available": bool(recommendation),
        "current": current,
        "recommendation": recommendation,
    }


def story_has_working_state(runtime: dict[str, Any]) -> bool:
    if story_current_resolution(runtime):
        return True

    draft_projection = runtime.get("draft_projection") or {}
    if draft_projection:
        return True

    request_projection = runtime.get("request_projection") or {}
    if isinstance(request_projection.get("payload"), dict):
        return True

    feedback_projection = runtime.get("feedback_projection") or {}
    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        return False

    return any(
        isinstance(item, dict)
        and item.get("status") == "unabsorbed"
        and isinstance(item.get("text"), str)
        and item.get("text").strip()
        for item in items
    )


def story_retry_target_attempt_id(runtime: dict[str, Any]) -> str | None:
    attempts = runtime.get("attempt_history") or []
    latest_attempt = attempts[-1] if attempts else {}
    request_projection = runtime.get("request_projection") or {}
    if not (
        isinstance(latest_attempt, dict)
        and latest_attempt.get("retryable")
        and isinstance(request_projection.get("payload"), dict)
    ):
        return None

    attempt_id = latest_attempt.get("attempt_id")
    if not isinstance(attempt_id, str) or not attempt_id:
        return None
    return attempt_id


def story_interview_summary(runtime: dict[str, Any]) -> dict[str, Any]:
    draft_projection = runtime.get("draft_projection") or {}
    retry_target_attempt_id = story_retry_target_attempt_id(runtime)

    current_draft = None
    if draft_projection:
        current_draft = {
            "attempt_id": draft_projection.get("latest_reusable_attempt_id"),
            "kind": draft_projection.get("kind"),
            "is_complete": bool(draft_projection.get("is_complete", False)),
        }

    return {
        "current_draft": current_draft,
        "retry": {
            "available": bool(retry_target_attempt_id),
            "target_attempt_id": retry_target_attempt_id,
        },
        "save": {
            "available": bool(story_save_payload(runtime)),
        },
        "resolution": story_resolution_summary(runtime),
    }


def story_unabsorbed_feedback_ids(runtime: dict[str, Any]) -> list[str]:
    feedback_projection = runtime.get("feedback_projection") or {}
    if not isinstance(feedback_projection, dict):
        return []

    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        return []

    feedback_ids: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("status") != "unabsorbed":
            continue
        feedback_id = item.get("feedback_id")
        if isinstance(feedback_id, str) and feedback_id:
            feedback_ids.append(feedback_id)
    return feedback_ids


def _normalize_story_requirement(
    state: dict[str, Any],
    parent_requirement: str,
) -> str:
    normalized_parent_requirement = (
        parent_requirement.strip()
        if isinstance(parent_requirement, str)
        else parent_requirement
    )

    candidate_names: list[str] = []
    seen: set[str] = set()

    def add_candidate(name: Any) -> None:
        if not isinstance(name, str) or name in seen:
            return
        seen.add(name)
        candidate_names.append(name)

    for req in get_all_roadmap_requirements(state):
        add_candidate(req)

    interview_runtime = state.get("interview_runtime")
    if isinstance(interview_runtime, dict):
        story_runtime = interview_runtime.get("story")
        if isinstance(story_runtime, dict):
            for key in story_runtime:
                add_candidate(key)

    for key in ("story_saved", "story_outputs", "story_attempts"):
        values = state.get(key)
        if isinstance(values, dict):
            for name in values:
                add_candidate(name)

    if parent_requirement in candidate_names:
        return parent_requirement

    if isinstance(normalized_parent_requirement, str) and normalized_parent_requirement:
        for candidate in candidate_names:
            if candidate.strip() == normalized_parent_requirement:
                return candidate

        if not candidate_names:
            return normalized_parent_requirement

    raise StoryPhaseError(
        f"Requirement '{parent_requirement}' not found in saved story state.",
        status_code=400,
    )


def _story_pending_items(state: dict[str, Any]) -> dict[str, Any]:
    roadmap_releases = state.get("roadmap_releases") or []
    if not isinstance(roadmap_releases, list):
        roadmap_releases = []

    attempts_dict = state.get("story_attempts")
    if not isinstance(attempts_dict, dict):
        attempts_dict = {}

    saved_reqs_dict = state.get("story_saved", {})
    if not isinstance(saved_reqs_dict, dict):
        saved_reqs_dict = {}

    grouped_items = []
    total_count = 0
    saved_count = 0

    for release_index, rel in enumerate(roadmap_releases):
        if not isinstance(rel, dict):
            continue

        reqs = rel.get("items") or []
        if not isinstance(reqs, list):
            reqs = []
        theme = rel.get("theme", "Milestone Context")
        reasoning = rel.get("reasoning", "")

        milestone_group = {
            "group_id": f"milestone_{release_index}",
            "theme": theme,
            "reasoning": reasoning,
            "requirements": [],
        }

        for req in reqs:
            if not isinstance(req, str):
                continue

            runtime = ensure_story_runtime(
                state,
                parent_requirement=req,
            )
            attempts = attempts_dict.get(req, [])
            if not isinstance(attempts, list):
                attempts = []

            if saved_reqs_dict.get(req):
                status = "Saved"
                saved_count += 1
            elif story_current_resolution(runtime):
                status = "Merged"
            elif story_has_working_state(runtime):
                status = "Attempted"
            else:
                status = "Pending"

            milestone_group["requirements"].append(
                {
                    "requirement": req,
                    "status": status,
                    "attempt_count": len(attempts),
                }
            )
            total_count += 1

        grouped_items.append(milestone_group)

    return {
        "grouped_items": grouped_items,
        "total_count": total_count,
        "saved_count": saved_count,
    }


def _story_request_payload(request_payload: Any) -> dict[str, Any]:
    return request_payload if isinstance(request_payload, dict) else {}


def _story_request_hash(request_payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(request_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()


def sync_story_legacy_mirrors(
    state: dict[str, Any],
    *,
    parent_requirement: str,
    runtime: dict[str, Any],
) -> None:
    story_attempts = state.get("story_attempts")
    if not isinstance(story_attempts, dict):
        story_attempts = {}
        state["story_attempts"] = story_attempts

    story_attempts[parent_requirement] = [
        {
            "created_at": attempt.get("created_at"),
            "trigger": attempt.get("trigger"),
            "input_context": (
                attempt.get("input_context")
                if isinstance(attempt.get("input_context"), dict)
                else {}
            ),
            "output_artifact": attempt.get("output_artifact"),
            "is_complete": bool(
                (
                    (attempt.get("output_artifact") or {})
                    if isinstance(attempt, dict)
                    else {}
                ).get("is_complete")
            ),
            "failure_artifact_id": attempt.get("failure_artifact_id"),
            "failure_stage": attempt.get("failure_stage"),
            "failure_summary": attempt.get("failure_summary"),
            "raw_output_preview": attempt.get("raw_output_preview"),
            "has_full_artifact": bool(attempt.get("has_full_artifact", False)),
        }
        for attempt in runtime.get("attempt_history") or []
        if isinstance(attempt, dict) and attempt.get("trigger") != "reset"
    ]

    story_outputs = state.get("story_outputs")
    if not isinstance(story_outputs, dict):
        story_outputs = {}
        state["story_outputs"] = story_outputs

    reusable = story_save_payload(runtime)
    if reusable:
        story_outputs[parent_requirement] = reusable
    else:
        story_outputs.pop(parent_requirement, None)


def _normalize_fsm_state(value: str | None) -> str:
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized in VALID_FSM_STATES:
            return normalized
    return OrchestratorState.SETUP_REQUIRED.value


async def get_story_pending(
    *,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    state = await load_state()
    return _story_pending_items(state)


async def generate_story_draft(
    *,
    project_id: int,
    parent_requirement: str,
    user_input: str | None,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    run_story_agent_from_state: Callable[..., Awaitable[dict[str, Any]]],
    append_feedback_entry: Callable[[dict[str, Any], str, str], dict[str, Any]],
    set_request_projection: Callable[..., dict[str, Any]],
    append_attempt: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    promote_reusable_draft: Callable[..., dict[str, Any]],
    mark_feedback_absorbed: Callable[..., list[dict[str, Any]]],
    failure_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )

    has_attempts = story_has_working_state(runtime)
    normalized_user_input = user_input.strip() if isinstance(user_input, str) else None
    if has_attempts and not normalized_user_input:
        raise StoryPhaseError(
            "User input is required to refine an existing story.",
            status_code=400,
        )

    if normalized_user_input:
        append_feedback_entry(runtime, normalized_user_input, now_iso())

    included_feedback_ids = story_unabsorbed_feedback_ids(runtime)
    story_result = await run_story_agent_from_state(
        state,
        project_id=project_id,
        parent_requirement=normalized_parent_requirement,
        user_input=None if included_feedback_ids else user_input,
    )

    request_payload = _story_request_payload(story_result.get("request_payload"))
    created_at = now_iso()
    draft_basis_attempt_id = (runtime.get("draft_projection") or {}).get(
        "latest_reusable_attempt_id"
    )
    request_projection = set_request_projection(
        runtime,
        request_snapshot_id=(
            f"request-{len(runtime.get('attempt_history') or []) + 1}"
        ),
        payload=request_payload,
        request_hash=_story_request_hash(request_payload),
        created_at=created_at,
        draft_basis_attempt_id=draft_basis_attempt_id
        if isinstance(draft_basis_attempt_id, str)
        else None,
        included_feedback_ids=included_feedback_ids,
        context_version="story-runtime.v1",
    )

    attempt_id = f"attempt-{len(runtime.get('attempt_history') or []) + 1}"
    append_attempt(
        runtime,
        {
            "attempt_id": attempt_id,
            "created_at": created_at,
            "trigger": "manual_refine" if normalized_user_input else "auto_transition",
            "request_snapshot_id": request_projection.get("request_snapshot_id"),
            "draft_basis_attempt_id": request_projection.get("draft_basis_attempt_id"),
            "included_feedback_ids": list(included_feedback_ids),
            "input_context": story_result.get("input_context") or request_payload,
            "classification": story_result.get("classification"),
            "is_reusable": bool(story_result.get("is_reusable", False)),
            "retryable": story_retryable(story_result.get("classification")),
            "draft_kind": story_result.get("draft_kind"),
            "output_artifact": story_result.get("output_artifact") or {},
            **failure_meta(story_result, fallback_summary=story_result.get("error")),
        },
    )

    if story_result.get("is_reusable"):
        runtime["resolution_projection"] = {}
        promote_reusable_draft(
            runtime,
            attempt_id=attempt_id,
            kind=story_result.get("draft_kind") or "incomplete_draft",
            is_complete=bool(story_result.get("is_complete", False)),
            updated_at=created_at,
        )
        mark_feedback_absorbed(
            runtime,
            feedback_ids=included_feedback_ids,
            attempt_id=attempt_id,
        )

    sync_story_legacy_mirrors(
        state,
        parent_requirement=normalized_parent_requirement,
        runtime=runtime,
    )
    save_state(state)

    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "output_artifact": story_result.get("output_artifact"),
            **story_interview_summary(runtime),
        },
    }


async def retry_story_draft(
    *,
    project_id: int,
    parent_requirement: str,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    run_story_agent_request: Callable[..., Awaitable[dict[str, Any]]],
    append_attempt: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    promote_reusable_draft: Callable[..., dict[str, Any]],
    mark_feedback_absorbed: Callable[..., list[dict[str, Any]]],
    failure_meta: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )

    request_projection = runtime.get("request_projection") or {}
    request_payload = request_projection.get("payload")
    if not isinstance(request_payload, dict):
        raise StoryPhaseError(
            "No replayable story request is available.",
            status_code=409,
        )
    if not story_retry_target_attempt_id(runtime):
        raise StoryPhaseError(
            "The latest story attempt is not eligible for retry.",
            status_code=409,
        )

    story_result = await run_story_agent_request(
        request_payload,
        project_id=project_id,
        parent_requirement=normalized_parent_requirement,
    )

    created_at = now_iso()
    included_feedback_ids = list(request_projection.get("included_feedback_ids") or [])
    attempt_id = f"attempt-{len(runtime.get('attempt_history') or []) + 1}"
    append_attempt(
        runtime,
        {
            "attempt_id": attempt_id,
            "created_at": created_at,
            "trigger": "retry_same_input",
            "request_snapshot_id": request_projection.get("request_snapshot_id"),
            "draft_basis_attempt_id": request_projection.get("draft_basis_attempt_id"),
            "included_feedback_ids": included_feedback_ids,
            "input_context": story_result.get("input_context") or request_payload,
            "classification": story_result.get("classification"),
            "is_reusable": bool(story_result.get("is_reusable", False)),
            "retryable": story_retryable(story_result.get("classification")),
            "draft_kind": story_result.get("draft_kind"),
            "output_artifact": story_result.get("output_artifact") or {},
            **failure_meta(story_result, fallback_summary=story_result.get("error")),
        },
    )

    if story_result.get("is_reusable"):
        runtime["resolution_projection"] = {}
        promote_reusable_draft(
            runtime,
            attempt_id=attempt_id,
            kind=story_result.get("draft_kind") or "incomplete_draft",
            is_complete=bool(story_result.get("is_complete", False)),
            updated_at=created_at,
        )
        mark_feedback_absorbed(
            runtime,
            feedback_ids=included_feedback_ids,
            attempt_id=attempt_id,
        )

    sync_story_legacy_mirrors(
        state,
        parent_requirement=normalized_parent_requirement,
        runtime=runtime,
    )
    save_state(state)

    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "output_artifact": story_result.get("output_artifact"),
            **story_interview_summary(runtime),
        },
    }


async def get_story_history(
    *,
    parent_requirement: str,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )
    attempt_history = runtime.get("attempt_history") or []
    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "items": attempt_history,
            "count": len(attempt_history),
            **story_interview_summary(runtime),
        },
    }


async def save_story_draft(
    *,
    project_id: int,
    parent_requirement: str,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    hydrate_context: Callable[[str, int], Awaitable[Any]],
    build_tool_context: Callable[[Any], Any],
    save_stories_tool: Callable[[Any, Any], dict[str, Any]],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )
    assessment = story_save_payload(runtime)

    if not assessment:
        raise StoryPhaseError(
            f"No story draft available for '{normalized_parent_requirement}'",
            status_code=409,
        )

    stories = assessment.get("user_stories")
    if not isinstance(stories, list) or len(stories) == 0:
        raise StoryPhaseError("Stories are empty", status_code=409)

    context = await hydrate_context(str(project_id), project_id)
    result = save_stories_tool(
        SaveStoriesInput(
            product_id=project_id,
            parent_requirement=normalized_parent_requirement,
            stories=stories,
        ),
        build_tool_context(context),
    )

    if not result.get("success"):
        raise StoryPhaseError(
            result.get("error", "Failed to save stories"),
            status_code=500,
        )

    saved_reqs_dict = context.state.get("story_saved", {})
    if not isinstance(saved_reqs_dict, dict):
        saved_reqs_dict = {}
    saved_reqs_dict[normalized_parent_requirement] = True
    context.state["story_saved"] = saved_reqs_dict
    sync_story_legacy_mirrors(
        context.state,
        parent_requirement=normalized_parent_requirement,
        runtime=runtime,
    )

    save_state(context.state)
    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "save_result": result,
        },
    }


async def merge_story_resolution(
    *,
    parent_requirement: str,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )

    recommendation = story_merge_recommendation_payload(runtime)
    if not recommendation:
        raise StoryPhaseError(
            "No merge recommendation is available for this requirement.",
            status_code=409,
        )

    runtime["resolution_projection"] = {
        "status": "merged",
        "owner_requirement": recommendation["owner_requirement"],
        "reason": recommendation["reason"],
        "acceptance_criteria_to_move": recommendation["acceptance_criteria_to_move"],
        "resolved_at": now_iso(),
    }

    sync_story_legacy_mirrors(
        state,
        parent_requirement=normalized_parent_requirement,
        runtime=runtime,
    )
    save_state(state)

    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "resolution": story_resolution_summary(runtime),
        },
    }


async def delete_story_requirement(
    *,
    parent_requirement: str,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
    delete_requirement_stories: Callable[[str], int],
    reset_subject_working_set: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    state = await load_state()
    normalized_parent_requirement = _normalize_story_requirement(
        state,
        parent_requirement,
    )
    normalized_repository_requirement = normalize_requirement_key(
        normalized_parent_requirement
    )
    deleted_count = delete_requirement_stories(normalized_repository_requirement)
    runtime = ensure_story_runtime(
        state,
        parent_requirement=normalized_parent_requirement,
    )
    reset_subject_working_set(
        runtime,
        created_at=now_iso(),
        summary="Stories deleted and state reset by user.",
    )

    story_saved = state.get("story_saved")
    if isinstance(story_saved, dict):
        story_saved.pop(normalized_parent_requirement, None)

    sync_story_legacy_mirrors(
        state,
        parent_requirement=normalized_parent_requirement,
        runtime=runtime,
    )
    save_state(state)

    return {
        "parent_requirement": normalized_parent_requirement,
        "data": {
            "deleted_count": deleted_count,
            "message": "Stories deleted successfully",
        },
    }


async def complete_story_phase(
    *,
    load_state: Callable[[], Awaitable[dict[str, Any]]],
    save_state: Callable[[dict[str, Any]], None],
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    state = await load_state()
    req_names = get_all_roadmap_requirements(state)
    saved_reqs_dict = state.get("story_saved", {})
    if not isinstance(saved_reqs_dict, dict):
        saved_reqs_dict = {}

    saved = [
        requirement for requirement in req_names if saved_reqs_dict.get(requirement)
    ]
    if len(saved) == 0:
        raise StoryPhaseError(
            "Cannot complete phase. No requirements have saved stories.",
            status_code=409,
        )

    current_state = _normalize_fsm_state(state.get("fsm_state"))
    if current_state not in (
        OrchestratorState.SPRINT_SETUP.value,
        OrchestratorState.SPRINT_DRAFT.value,
        OrchestratorState.SPRINT_PERSISTENCE.value,
        OrchestratorState.SPRINT_COMPLETE.value,
    ):
        state["fsm_state"] = OrchestratorState.SPRINT_SETUP.value
        state["fsm_state_entered_at"] = now_iso()
        state["story_phase_completed_at"] = now_iso()
        save_state(state)

    return {
        "fsm_state": state.get("fsm_state"),
    }
