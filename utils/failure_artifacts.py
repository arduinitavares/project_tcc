from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional


REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = REPO_ROOT / "logs"
FAILURES_DIR = LOGS_DIR / "failures"
RAW_OUTPUT_PREVIEW_LIMIT = 500


@dataclass(frozen=True)
class FailureMetadata:
    failure_artifact_id: str
    failure_stage: str
    failure_summary: str
    raw_output_preview: Optional[str]
    has_full_artifact: bool

    def as_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AgentInvocationError(RuntimeError):
    """Raised when an ADK runner fails after producing partial output."""

    def __init__(
        self,
        message: str,
        *,
        partial_output: Optional[str] = None,
        event_count: int = 0,
        validation_errors: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.partial_output = partial_output
        self.event_count = event_count
        self.validation_errors = validation_errors


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _jsonable(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump())
    return str(value)


def _preview_text(raw_output: Optional[str]) -> Optional[str]:
    if not raw_output:
        return None
    return raw_output[:RAW_OUTPUT_PREVIEW_LIMIT]


def build_failure_metadata(
    *,
    artifact_id: str,
    failure_stage: str,
    failure_summary: str,
    raw_output: Optional[str],
) -> FailureMetadata:
    return FailureMetadata(
        failure_artifact_id=artifact_id,
        failure_stage=failure_stage,
        failure_summary=failure_summary,
        raw_output_preview=_preview_text(raw_output),
        has_full_artifact=True,
    )


def _artifact_path(phase: str, artifact_id: str) -> Path:
    return FAILURES_DIR / phase / f"{artifact_id}.json"


def _artifact_id(
    *,
    phase: str,
    project_id: Optional[int],
    failure_stage: str,
    failure_summary: str,
    raw_output: Optional[str],
) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(
        json.dumps(
            {
                "phase": phase,
                "project_id": project_id,
                "failure_stage": failure_stage,
                "failure_summary": failure_summary,
                "raw_output": raw_output or "",
            },
            sort_keys=True,
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()[:12]
    return f"{phase}-{timestamp}-{digest}"


def write_failure_artifact(
    *,
    phase: str,
    project_id: Optional[int],
    failure_stage: str,
    failure_summary: str,
    raw_output: Optional[str] = None,
    context: Optional[Mapping[str, Any]] = None,
    model_info: Optional[Mapping[str, Any]] = None,
    validation_errors: Optional[Any] = None,
    exception: Optional[BaseException] = None,
    traceback_text: Optional[str] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    FAILURES_DIR.mkdir(parents=True, exist_ok=True)

    artifact_id = _artifact_id(
        phase=phase,
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=failure_summary,
        raw_output=raw_output,
    )
    artifact_path = _artifact_path(phase, artifact_id)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)

    exception_type = type(exception).__name__ if exception else None
    exception_message = str(exception) if exception else None
    if traceback_text is None and exception is not None:
        traceback_text = "".join(
            traceback.format_exception(type(exception), exception, exception.__traceback__)
        )

    artifact: Dict[str, Any] = {
        "artifact_id": artifact_id,
        "created_at": _now_iso(),
        "phase": phase,
        "project_id": project_id,
        "failure_stage": failure_stage,
        "failure_summary": failure_summary,
        "raw_output": raw_output,
        "raw_output_length": len(raw_output) if raw_output is not None else 0,
        "context": _jsonable(context),
        "model_info": _jsonable(model_info),
        "validation_errors": _jsonable(validation_errors),
        "exception_type": exception_type,
        "exception_message": exception_message,
        "traceback": traceback_text,
        "extra": _jsonable(extra),
    }
    artifact_path.write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    metadata = build_failure_metadata(
        artifact_id=artifact_id,
        failure_stage=failure_stage,
        failure_summary=failure_summary,
        raw_output=raw_output,
    )
    return {
        "artifact": artifact,
        "artifact_path": artifact_path,
        "metadata": metadata.as_dict(),
    }


def read_failure_artifact(artifact_id: str) -> Optional[Dict[str, Any]]:
    if not artifact_id.strip():
        return None

    for path in FAILURES_DIR.glob(f"*/*{artifact_id}.json"):
        if path.stem == artifact_id:
            return json.loads(path.read_text(encoding="utf-8"))
    return None
