from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, Optional, Sequence


INTERVIEW_RUNTIME_KEY = "interview_runtime"
STORY_PHASE = "story"


def _runtime_root(state: Dict[str, Any]) -> Dict[str, Any]:
    runtime = state.setdefault(INTERVIEW_RUNTIME_KEY, {})
    if not isinstance(runtime, dict):
        raise TypeError(f"{INTERVIEW_RUNTIME_KEY} must be a dict")
    return runtime


def _phase_bucket(state: Dict[str, Any], phase: str) -> Dict[str, Any]:
    runtime = _runtime_root(state)
    bucket = runtime.setdefault(phase, {})
    if not isinstance(bucket, dict):
        raise TypeError(f"{phase} runtime bucket must be a dict")
    return bucket


def _empty_projection(phase: str, subject_key: str) -> Dict[str, Any]:
    return {
        "phase": phase,
        "subject_key": subject_key,
        "attempt_history": [],
        "draft_projection": {},
        "feedback_projection": {"items": [], "next_feedback_sequence": 0},
        "request_projection": {},
    }


def _normalize_feedback_projection(projection: Dict[str, Any]) -> Dict[str, Any]:
    feedback_projection = projection.setdefault("feedback_projection", {})
    if not isinstance(feedback_projection, dict):
        raise TypeError("feedback_projection must be a dict")
    feedback_projection.setdefault("items", [])
    if not isinstance(feedback_projection["items"], list):
        raise TypeError("feedback_projection.items must be a list")
    if "next_feedback_sequence" not in feedback_projection:
        feedback_projection["next_feedback_sequence"] = len(feedback_projection["items"])
    return feedback_projection


def ensure_interview_subject(
    state: Dict[str, Any],
    *,
    phase: str,
    subject_key: str,
) -> Dict[str, Any]:
    phase_bucket = _phase_bucket(state, phase)
    projection = phase_bucket.setdefault(subject_key, _empty_projection(phase, subject_key))
    if not isinstance(projection, dict):
        raise TypeError("interview subject projection must be a dict")

    projection.setdefault("phase", phase)
    projection.setdefault("subject_key", subject_key)
    projection.setdefault("attempt_history", [])
    projection.setdefault("draft_projection", {})
    _normalize_feedback_projection(projection)
    projection.setdefault("request_projection", {})
    return projection


def set_request_projection(
    runtime: Dict[str, Any],
    *,
    request_snapshot_id: str,
    payload: Dict[str, Any],
    request_hash: str,
    created_at: Any,
    draft_basis_attempt_id: Optional[str],
    included_feedback_ids: Sequence[str],
    context_version: str,
) -> Dict[str, Any]:
    request_projection = {
        "request_snapshot_id": request_snapshot_id,
        "payload": deepcopy(payload),
        "request_hash": request_hash,
        "created_at": created_at,
        "draft_basis_attempt_id": draft_basis_attempt_id,
        "included_feedback_ids": list(included_feedback_ids),
        "context_version": context_version,
    }
    runtime["request_projection"] = request_projection
    return request_projection


def append_feedback_entry(
    runtime: Dict[str, Any],
    text: str,
    created_at: Any,
    feedback_id: Optional[str] = None,
) -> Dict[str, Any]:
    feedback_projection = _normalize_feedback_projection(runtime)
    items = feedback_projection["items"]
    sequence = int(feedback_projection.get("next_feedback_sequence", len(items))) + 1
    feedback_projection["next_feedback_sequence"] = sequence
    generated_id = feedback_id or f"feedback-{sequence}"
    entry = {
        "feedback_id": generated_id,
        "text": text,
        "created_at": created_at,
        "status": "unabsorbed",
        "absorbed_by_attempt_id": None,
    }
    items.append(entry)
    return entry


def mark_feedback_absorbed(
    runtime: Dict[str, Any],
    *,
    feedback_ids: Sequence[str],
    attempt_id: str,
) -> list[Dict[str, Any]]:
    feedback_projection = runtime.get("feedback_projection") or {}
    if not isinstance(feedback_projection, dict):
        raise TypeError("feedback_projection must be a dict")
    items = feedback_projection.get("items") or []
    if not isinstance(items, list):
        raise TypeError("feedback_projection.items must be a list")

    absorbed_items: list[Dict[str, Any]] = []
    for entry in items:
        if not isinstance(entry, dict):
            continue
        if entry.get("feedback_id") in feedback_ids:
            entry["status"] = "absorbed"
            entry["absorbed_by_attempt_id"] = attempt_id
            absorbed_items.append(entry)
    return absorbed_items


def append_attempt(
    runtime: Dict[str, Any],
    attempt: Dict[str, Any],
) -> Dict[str, Any]:
    stored_attempt = deepcopy(attempt)
    attempts = runtime.setdefault("attempt_history", [])
    if not isinstance(attempts, list):
        raise TypeError("attempt_history must be a list")
    attempts.append(stored_attempt)
    return stored_attempt


def promote_reusable_draft(
    runtime: Dict[str, Any],
    *,
    attempt_id: str,
    kind: str,
    is_complete: bool,
    updated_at: Any,
) -> Dict[str, Any]:
    draft_projection = runtime.setdefault("draft_projection", {})
    if not isinstance(draft_projection, dict):
        raise TypeError("draft_projection must be a dict")
    draft_projection["latest_reusable_attempt_id"] = attempt_id
    draft_projection["kind"] = kind
    draft_projection["is_complete"] = is_complete
    draft_projection["updated_at"] = updated_at
    return draft_projection


def reset_subject_working_set(
    runtime: Dict[str, Any],
    *,
    created_at: Any,
    summary: str,
) -> Dict[str, Any]:
    runtime["request_projection"] = {}
    feedback_projection = _normalize_feedback_projection(runtime)
    feedback_projection["items"] = []
    runtime["draft_projection"] = {}

    attempts = runtime.setdefault("attempt_history", [])
    if not isinstance(attempts, list):
        raise TypeError("attempt_history must be a list")
    reset_attempt = {
        "attempt_id": f"reset-marker-{len(attempts) + 1}",
        "created_at": created_at,
        "trigger": "reset",
        "classification": "reset_marker",
        "is_reusable": False,
        "retryable": False,
        "summary": summary,
        "output_artifact": None,
    }
    attempts.append(reset_attempt)
    return runtime


def _classify_story_attempt(attempt: Dict[str, Any]) -> str:
    output_artifact = attempt.get("output_artifact")
    if (
        isinstance(output_artifact, dict)
        and output_artifact.get("user_stories")
        and not attempt.get("error")
    ):
        return "reusable_content_result"
    if attempt.get("failure_stage") == "invocation_exception":
        return "nonreusable_provider_failure"
    return "nonreusable_schema_failure"


def _normalized_legacy_attempt(
    attempt: Dict[str, Any],
    *,
    attempt_id: str,
) -> Dict[str, Any]:
    classification = _classify_story_attempt(attempt)
    is_reusable = classification == "reusable_content_result"
    legacy_attempt: Dict[str, Any] = {
        "attempt_id": attempt_id,
        "created_at": attempt.get("created_at"),
        "trigger": "legacy",
        "request_snapshot_id": attempt.get("request_snapshot_id"),
        "draft_basis_attempt_id": attempt.get("draft_basis_attempt_id"),
        "included_feedback_ids": list(attempt.get("included_feedback_ids") or []),
        "classification": classification,
        "is_reusable": is_reusable,
        "retryable": False,
        "draft_kind": None,
        "output_artifact": deepcopy(attempt.get("output_artifact")),
        "failure_stage": attempt.get("failure_stage"),
        "failure_artifact_id": attempt.get("failure_artifact_id"),
        "failure_summary": attempt.get("failure_summary") or attempt.get("error"),
        "raw_output_preview": attempt.get("raw_output_preview")
        or attempt.get("raw_output")
        or attempt.get("partial_output"),
    }
    if is_reusable:
        legacy_attempt["draft_kind"] = (
            "complete_draft" if bool(attempt.get("is_complete")) else "incomplete_draft"
        )
    return legacy_attempt


def hydrate_story_runtime_from_legacy(
    state: Dict[str, Any],
    *,
    parent_requirement: str,
) -> Dict[str, Any]:
    runtime = ensure_interview_subject(
        state,
        phase=STORY_PHASE,
        subject_key=parent_requirement,
    )
    if runtime.get("attempt_history"):
        return runtime

    legacy_attempts = state.get("story_attempts") or {}
    if not isinstance(legacy_attempts, dict):
        return runtime

    attempts = legacy_attempts.get(parent_requirement) or []
    if not isinstance(attempts, list):
        return runtime

    for index, attempt in enumerate(attempts, start=1):
        if not isinstance(attempt, dict):
            continue
        normalized_attempt = _normalized_legacy_attempt(
            attempt,
            attempt_id=f"legacy-{index}",
        )
        runtime["attempt_history"].append(normalized_attempt)
        if normalized_attempt["classification"] == "reusable_content_result":
            runtime["draft_projection"] = {
                "latest_reusable_attempt_id": normalized_attempt["attempt_id"],
                "kind": normalized_attempt["draft_kind"],
                "is_complete": bool(attempt.get("is_complete")),
                "updated_at": normalized_attempt.get("created_at"),
            }

    return runtime
