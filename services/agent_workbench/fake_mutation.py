"""Fake mutation harness for proving Phase 2A mutation contracts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from services.agent_workbench.error_codes import error_metadata
from services.agent_workbench.mutation_ledger import (
    MUTATION_RECOVERY_REQUIRED,
    MUTATION_RESUME_CONFLICT,
    MutationLedgerRepository,
)

FAKE_MUTATION_OWNER_NOT_ACTIVE = "FAKE_MUTATION_OWNER_NOT_ACTIVE"
FAKE_MUTATION_STEP_RECORD_FAILED = "FAKE_MUTATION_STEP_RECORD_FAILED"
FAKE_MUTATION_FINALIZE_FAILED = "FAKE_MUTATION_FINALIZE_FAILED"
FAKE_MUTATION_INVALID_RECOVERY_STATE = "FAKE_MUTATION_INVALID_RECOVERY_STATE"
_FAKE_MUTATION_COMMAND = "agileforge fake mutate"


class FakeMutationCrash(RuntimeError):
    """Raised to simulate a crash after a side-effect boundary."""


@dataclass
class FakeSideEffectSink:
    """In-memory sink simulating two declared side-effect stores."""

    business_markers: list[int] = field(default_factory=list)
    session_markers: list[int] = field(default_factory=list)

    def write_business_marker(self, project_id: int) -> None:
        """Simulate a business DB side effect."""
        self.business_markers.append(project_id)

    def write_session_marker(self, project_id: int) -> None:
        """Simulate a workflow session side effect."""
        self.session_markers.append(project_id)


class FakeMutationRunner:
    """Two-step fake mutation used only by Phase 2A tests."""

    def __init__(
        self,
        *,
        ledger: MutationLedgerRepository,
        side_effects: FakeSideEffectSink,
        lease_seconds: int = 30,
    ) -> None:
        self._ledger: MutationLedgerRepository = ledger
        self._side_effects: FakeSideEffectSink = side_effects
        self._lease_seconds: int = lease_seconds

    def run(
        self,
        project_id: int,
        idempotency_key: str,
        correlation_id: str,
        changed_by: str,
        lease_owner: str,
        now: datetime,
        *,
        crash_after_business_marker: bool = False,
    ) -> dict[str, Any]:
        """Run, replay, or fence the fake mutation."""
        loaded = self._ledger.create_or_load(
            command=_FAKE_MUTATION_COMMAND,
            idempotency_key=idempotency_key,
            request_hash=_request_hash(project_id=project_id, changed_by=changed_by),
            project_id=project_id,
            correlation_id=correlation_id,
            changed_by=changed_by,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        if loaded.response is not None:
            return loaded.response

        event_id = loaded.ledger.mutation_event_id
        if event_id is None:
            raise RuntimeError("Mutation ledger row has no primary key.")
        if loaded.error_code is not None:
            return self._error(loaded.error_code, event_id)

        if not self._require_active_owner(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            now=now,
        ):
            return self._error(FAKE_MUTATION_OWNER_NOT_ACTIVE, event_id)
        self._side_effects.write_business_marker(project_id)
        if not self._mark_step_complete(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            step="business_marker",
            next_step="session_marker",
            now=now,
        ):
            return self._error(FAKE_MUTATION_STEP_RECORD_FAILED, event_id)
        if crash_after_business_marker:
            raise FakeMutationCrash("Simulated crash after business marker.")

        if not self._require_active_owner(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            now=now,
        ):
            return self._error(FAKE_MUTATION_OWNER_NOT_ACTIVE, event_id)
        self._side_effects.write_session_marker(project_id)
        if not self._mark_step_complete(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            step="session_marker",
            next_step="done",
            now=now,
        ):
            return self._error(FAKE_MUTATION_STEP_RECORD_FAILED, event_id)

        response = self._success_response(
            project_id=project_id,
            mutation_event_id=event_id,
            resumed_steps=[],
        )
        if not self._ledger.finalize_success(
            mutation_event_id=event_id,
            lease_owner=lease_owner,
            after={"business_marker": True, "session_marker": True},
            response=response,
            now=now,
        ):
            return self._error(FAKE_MUTATION_FINALIZE_FAILED, event_id)
        return response

    def resume(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
    ) -> dict[str, Any]:
        """Resume the original fake mutation without accepting domain args."""
        acquired = self._ledger.acquire_resume_lease(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        )
        if acquired.error_code is not None:
            return self._error(acquired.error_code, mutation_event_id)

        project_id = acquired.ledger.project_id
        if project_id is None or acquired.ledger.command != _FAKE_MUTATION_COMMAND:
            return self._error(FAKE_MUTATION_INVALID_RECOVERY_STATE, mutation_event_id)

        progress = _resume_progress(
            completed_steps_json=acquired.ledger.completed_steps_json,
            current_step=acquired.ledger.current_step,
        )
        if progress == _ResumeProgress.INVALID:
            return self._error(FAKE_MUTATION_INVALID_RECOVERY_STATE, mutation_event_id)
        resumed_steps: list[str] = []
        if progress == _ResumeProgress.NEEDS_SESSION_MARKER:
            if not self._require_active_owner(
                mutation_event_id=mutation_event_id,
                lease_owner=lease_owner,
                now=now,
            ):
                return self._error(MUTATION_RESUME_CONFLICT, mutation_event_id)
            self._side_effects.write_session_marker(project_id)
            if not self._mark_step_complete(
                mutation_event_id=mutation_event_id,
                lease_owner=lease_owner,
                step="session_marker",
                next_step="done",
                now=now,
            ):
                return self._error(FAKE_MUTATION_STEP_RECORD_FAILED, mutation_event_id)
            resumed_steps.append("session_marker")

        response = self._success_response(
            project_id=project_id,
            mutation_event_id=mutation_event_id,
            resumed_steps=resumed_steps,
        )
        if not self._require_active_owner(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
        ):
            return self._error(MUTATION_RESUME_CONFLICT, mutation_event_id)
        if not self._ledger.finalize_success(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            after={"business_marker": True, "session_marker": True},
            response=response,
            now=now,
        ):
            return self._error(FAKE_MUTATION_FINALIZE_FAILED, mutation_event_id)
        return response

    def _require_active_owner(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        now: datetime,
    ) -> bool:
        return self._ledger.require_active_owner(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            now=now,
            lease_seconds=self._lease_seconds,
        )

    def _mark_step_complete(
        self,
        *,
        mutation_event_id: int,
        lease_owner: str,
        step: str,
        next_step: str,
        now: datetime,
    ) -> bool:
        return self._ledger.mark_step_complete(
            mutation_event_id=mutation_event_id,
            lease_owner=lease_owner,
            step=step,
            next_step=next_step,
            now=now,
        )

    def _success_response(
        self,
        *,
        project_id: int,
        mutation_event_id: int,
        resumed_steps: list[str],
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "project_id": project_id,
            "mutation_event_id": mutation_event_id,
            "next_actions": [],
        }
        if resumed_steps:
            data["resumed_steps"] = resumed_steps
        return {"ok": True, "data": data, "warnings": [], "errors": []}

    def _error(self, code: str, mutation_event_id: int) -> dict[str, Any]:
        exit_code = 1
        retryable = code not in {FAKE_MUTATION_FINALIZE_FAILED}
        try:
            metadata = error_metadata(code)
        except ValueError:
            pass
        else:
            exit_code = metadata.default_exit_code
            retryable = metadata.retryable
        return {
            "ok": False,
            "data": None,
            "warnings": [],
            "errors": [
                {
                    "code": code,
                    "message": "Mutation cannot run.",
                    "details": {"mutation_event_id": mutation_event_id},
                    "remediation": [
                        f"agileforge mutation show --mutation-event-id {mutation_event_id}"
                    ],
                    "exit_code": exit_code,
                    "retryable": retryable,
                }
            ],
        }


def _request_hash(*, project_id: int, changed_by: str) -> str:
    """Return a deterministic fake canonical request hash."""
    return f"sha256:fake:{project_id}:{changed_by}"


class _ResumeProgress:
    NEEDS_SESSION_MARKER = "needs_session_marker"
    READY_TO_FINALIZE = "ready_to_finalize"
    INVALID = "invalid"


def _resume_progress(*, completed_steps_json: str, current_step: str) -> str:
    """Classify fake mutation recovery progress from persisted ledger data."""
    try:
        loaded = json.loads(completed_steps_json)
    except json.JSONDecodeError:
        return _ResumeProgress.INVALID
    if not isinstance(loaded, list):
        return _ResumeProgress.INVALID

    completed_steps = {step for step in loaded if isinstance(step, str)}
    if len(completed_steps) != len(loaded):
        return _ResumeProgress.INVALID
    known_steps = {"business_marker", "session_marker"}
    if not completed_steps <= known_steps:
        return _ResumeProgress.INVALID
    if "business_marker" not in completed_steps:
        return _ResumeProgress.INVALID
    if "session_marker" in completed_steps:
        return (
            _ResumeProgress.READY_TO_FINALIZE
            if current_step == "done"
            else _ResumeProgress.INVALID
        )
    return (
        _ResumeProgress.NEEDS_SESSION_MARKER
        if current_step == "session_marker"
        else _ResumeProgress.INVALID
    )
