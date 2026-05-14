# Agent CLI Workbench Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Phase 1 read-only agent CLI workbench: stable JSON envelopes, command registry, read projections, authority status/invariants, context packs, schema-readiness errors, and task status normalization for the later Phase 2 mutation.

**Architecture:** Add a narrow `services.agent_workbench` package as the first `AgentWorkbenchApplication` facade. The facade exposes read-only projections through `ReadProjectionService`, authority projections through `AuthorityProjectionService`, and deterministic CLI output contracts through envelope/fingerprint helpers. The CLI is a thin `argparse` transport over the facade; it does not import FastAPI router handlers and does not mutate business or workflow session state.

**Tech Stack:** Python 3.12, argparse, SQLModel/SQLAlchemy, sqlite3 session repository, pytest, existing project models/services.

---

## Scope

Implement Phase 1 only:

- `tcc status --project-id 1`
- `tcc project list`
- `tcc project show --project-id 1`
- `tcc workflow state --project-id 1`
- `tcc workflow next --project-id 1`
- `tcc authority status --project-id 1`
- `tcc authority invariants --project-id 1`
- `tcc story show --story-id 42`
- `tcc sprint candidates --project-id 1`
- `tcc context pack --project-id 1 --phase sprint-planning`

Do not implement workflow mutations, LLM-backed generation, or Phase 2 task logging in this plan. Add the pure task-status normalization helper now so Phase 2 has a pinned input contract.

## Projection Matrix

| Command | Business Tables Read | Session Fields Read | Fingerprint Inputs | Forbidden Side Effects |
| --- | --- | --- | --- | --- |
| `tcc status --project-id` | `products`, latest `sprints`, latest `spec_registry`, `compiled_spec_authority`, latest `spec_authority_acceptance` | full project session state for `fsm_state`, `setup_status`, `setup_error` | command, args, product id/update, latest sprint id/update/status, latest spec id/hash/status, authority id/compiled_at, acceptance id/decided_at/status, session state hash | migrations, compile, authority backfill, session update |
| `tcc project list` | `products`, grouped `user_stories`, grouped `sprints` | none | command, args, product ids/update timestamps, story/sprint counts | session reads/writes, migrations |
| `tcc project show --project-id` | `products`, `themes`, `epics`, `features`, `user_stories`, `sprints`, latest approved `spec_registry` | none | command, args, product id/update, structure counts, latest approved spec id/hash | active-project hydration, authority backfill |
| `tcc workflow state --project-id` | `products` existence only | full project session state | command, args, product id/update, session state hash | session creation/update |
| `tcc workflow next --project-id` | same as `status` | same as `status` | same as `status`, installed command names | advertising unimplemented commands as next-valid |
| `tcc authority status --project-id` | `products`, all project `spec_registry`, project `compiled_spec_authority`, latest `spec_authority_acceptance` | none | command, args, product id/update, spec ids/hash/status, authority ids/compiled_at, acceptance ids/decided_at/status, disk spec hash result | compile, accept, product cache backfill |
| `tcc authority invariants --project-id` | same as `authority status`, selected `compiled_spec_authority` | none | command, args, authority fingerprint | choosing arbitrary authority when none is accepted |
| `tcc story show --story-id` | `user_stories`, optional `features`, `epics`, `themes`, `products` | none | command, args, story id/update, accepted spec version id, validation evidence hash | validation run, story mutation |
| `tcc sprint candidates --project-id` | `user_stories`, `sprints`, `sprint_stories` | none | command, args, candidate story ids/update/status/refinement flags, open sprint ids/update/status | sprint planning generation |
| `tcc context pack --project-id --phase sprint-planning` | composed from `status`, `authority status`, `sprint candidates` | same as `status` | command, args, included section names, child projection fingerprints, authority fingerprint | compile, repair, mutations, unbounded raw spec inclusion |

## Canonical Hashing Rules

Use one helper for all fingerprints:

- Convert datetimes to UTC ISO-8601 strings with `Z` suffix.
- Sort mapping keys recursively.
- Preserve list order when the list order is semantically meaningful.
- Omit no keys solely because the value is `None`; include `null`.
- Serialize with `json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`.
- Hash with SHA-256 and return `sha256:<64 lowercase hex chars>`.

## Schema-Readiness Behavior

Read projections must check required tables and columns before querying. If schema is missing or incomplete, return an envelope error:

```json
{
  "code": "SCHEMA_NOT_READY",
  "message": "Database schema is missing required tables or columns for this read-only command.",
  "details": {"missing": {"products": ["product_id"]}},
  "remediation": ["Run the application startup or migration command before using the CLI."],
  "exit_code": 1,
  "retryable": false
}
```

Read-only CLI startup must not call migrations, `ensure_business_db_ready()`, `create_db_and_tables()`, authority compilation, active-project hydration, or ADK session creation.

## Task Status Normalization Contract For Phase 2

`--expected-status` accepts these labels case-insensitively after trimming and converting `_`/`-` to spaces:

- `to do` -> `TaskStatus.TO_DO`
- `in progress` -> `TaskStatus.IN_PROGRESS`
- `done` -> `TaskStatus.DONE`
- `cancelled` -> `TaskStatus.CANCELLED`

Invalid labels fail before any write with exit code `2` and an error code `INVALID_TASK_STATUS`.

---

### Task 1: Envelope And Command Registry

**Files:**
- Create: `services/agent_workbench/__init__.py`
- Create: `services/agent_workbench/envelope.py`
- Create: `services/agent_workbench/command_registry.py`
- Test: `tests/test_agent_workbench_envelope.py`

- [ ] **Step 1: Write failing envelope and registry tests**

Create `tests/test_agent_workbench_envelope.py`:

```python
"""Tests for agent workbench CLI envelopes and command registry."""

from __future__ import annotations

from services.agent_workbench.command_registry import (
    command_is_available,
    installed_command_names,
)
from services.agent_workbench.envelope import (
    WorkbenchError,
    WorkbenchWarning,
    error_envelope,
    success_envelope,
)


def test_success_envelope_has_stable_shape() -> None:
    """Verify success envelope has stable machine-readable shape."""
    envelope = success_envelope(
        command="tcc project list",
        data={"items": []},
        warnings=[
            WorkbenchWarning(
                code="EMPTY_PROJECTS",
                message="No projects exist.",
                details={"count": 0},
                remediation=["tcc project create --name Example --spec-file specs/app.md"],
            )
        ],
        generated_at="2026-05-14T00:00:00Z",
    )

    assert envelope == {
        "ok": True,
        "data": {"items": []},
        "warnings": [
            {
                "code": "EMPTY_PROJECTS",
                "message": "No projects exist.",
                "details": {"count": 0},
                "remediation": ["tcc project create --name Example --spec-file specs/app.md"],
            }
        ],
        "errors": [],
        "meta": {
            "schema_version": "tcc.cli.v1",
            "command": "tcc project list",
            "generated_at": "2026-05-14T00:00:00Z",
        },
    }


def test_error_envelope_has_retryable_exit_code_error() -> None:
    """Verify error envelope serializes retry and exit-code fields."""
    envelope = error_envelope(
        command="tcc authority status",
        error=WorkbenchError(
            code="SCHEMA_NOT_READY",
            message="Database schema is missing required tables.",
            details={"missing": {"products": ["product_id"]}},
            remediation=["Run migrations."],
            exit_code=1,
            retryable=False,
        ),
        generated_at="2026-05-14T00:00:00Z",
    )

    assert envelope["ok"] is False
    assert envelope["data"] is None
    assert envelope["warnings"] == []
    assert envelope["errors"] == [
        {
            "code": "SCHEMA_NOT_READY",
            "message": "Database schema is missing required tables.",
            "details": {"missing": {"products": ["product_id"]}},
            "remediation": ["Run migrations."],
            "exit_code": 1,
            "retryable": False,
        }
    ]


def test_registry_exposes_only_phase_1_commands() -> None:
    """Verify installed commands exclude future workflow mutations."""
    commands = installed_command_names()

    assert "tcc sprint candidates" in commands
    assert "tcc context pack" in commands
    assert "tcc sprint generate" not in commands
    assert command_is_available("tcc sprint candidates") is True
    assert command_is_available("tcc sprint generate") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --frozen pytest tests/test_agent_workbench_envelope.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'services.agent_workbench'`.

- [ ] **Step 3: Create package marker**

Create `services/agent_workbench/__init__.py`:

```python
"""Agent-facing CLI workbench application services."""
```

- [ ] **Step 4: Implement envelope helpers**

Create `services/agent_workbench/envelope.py`:

```python
"""Stable JSON envelope helpers for the agent workbench CLI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

SCHEMA_VERSION: Final[str] = "tcc.cli.v1"


def utc_now_iso() -> str:
    """Return current UTC time in CLI envelope format."""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WorkbenchWarning:
    """Machine-readable CLI warning item."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the warning item."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class WorkbenchError:
    """Machine-readable CLI error item."""

    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)
    remediation: list[str] = field(default_factory=list)
    exit_code: int = 1
    retryable: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize the error item."""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "remediation": self.remediation,
            "exit_code": self.exit_code,
            "retryable": self.retryable,
        }


def success_envelope(
    *,
    command: str,
    data: dict[str, Any] | list[Any],
    warnings: list[WorkbenchWarning] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a successful CLI response envelope."""
    return {
        "ok": True,
        "data": data,
        "warnings": [warning.to_dict() for warning in warnings or []],
        "errors": [],
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "generated_at": generated_at or utc_now_iso(),
        },
    }


def error_envelope(
    *,
    command: str,
    error: WorkbenchError,
    warnings: list[WorkbenchWarning] | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a failed CLI response envelope."""
    return {
        "ok": False,
        "data": None,
        "warnings": [warning.to_dict() for warning in warnings or []],
        "errors": [error.to_dict()],
        "meta": {
            "schema_version": SCHEMA_VERSION,
            "command": command,
            "generated_at": generated_at or utc_now_iso(),
        },
    }
```

- [ ] **Step 5: Implement command registry**

Create `services/agent_workbench/command_registry.py`:

```python
"""Installed command metadata for agent workbench context packs."""

from __future__ import annotations

    from collections.abc import Sequence
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True)
class CommandMetadata:
    """CLI command capability metadata."""

    name: str
    mutates: bool
    phase: str


_COMMANDS: Final[Sequence[CommandMetadata]] = (
    CommandMetadata("tcc status", mutates=False, phase="phase_1"),
    CommandMetadata("tcc project list", mutates=False, phase="phase_1"),
    CommandMetadata("tcc project show", mutates=False, phase="phase_1"),
    CommandMetadata("tcc workflow state", mutates=False, phase="phase_1"),
    CommandMetadata("tcc workflow next", mutates=False, phase="phase_1"),
    CommandMetadata("tcc authority status", mutates=False, phase="phase_1"),
    CommandMetadata("tcc authority invariants", mutates=False, phase="phase_1"),
    CommandMetadata("tcc story show", mutates=False, phase="phase_1"),
    CommandMetadata("tcc sprint candidates", mutates=False, phase="phase_1"),
    CommandMetadata("tcc context pack", mutates=False, phase="phase_1"),
)


def installed_commands() -> Sequence[CommandMetadata]:
    """Return installed command metadata."""
    return _COMMANDS


def installed_command_names() -> set[str]:
    """Return installed command names."""
    return {command.name for command in _COMMANDS}


def command_is_available(name: str) -> bool:
    """Return whether a command exists in this CLI phase."""
    return name in installed_command_names()
```

- [ ] **Step 6: Run test to verify it passes**

Run: `uv run --frozen pytest tests/test_agent_workbench_envelope.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/agent_workbench/__init__.py services/agent_workbench/envelope.py services/agent_workbench/command_registry.py tests/test_agent_workbench_envelope.py
git commit -m "feat: add agent workbench envelope"
```

---

### Task 2: Canonical Fingerprints And Status Normalization

**Files:**
- Create: `services/agent_workbench/fingerprints.py`
- Create: `services/agent_workbench/task_status.py`
- Test: `tests/test_agent_workbench_fingerprints.py`
- Test: `tests/test_agent_workbench_task_status.py`

- [ ] **Step 1: Write failing fingerprint tests**

Create `tests/test_agent_workbench_fingerprints.py`:

```python
"""Tests for canonical workbench fingerprints."""

from __future__ import annotations

from datetime import UTC, datetime

from services.agent_workbench.fingerprints import canonical_hash, normalize_for_hash


def test_canonical_hash_is_order_stable_and_prefixed() -> None:
    """Verify mapping key order does not affect hash output."""
    left = {"b": 2, "a": {"z": None, "m": [3, 2, 1]}}
    right = {"a": {"m": [3, 2, 1], "z": None}, "b": 2}

    assert canonical_hash(left) == canonical_hash(right)
    assert canonical_hash(left).startswith("sha256:")
    assert len(canonical_hash(left)) == len("sha256:") + 64


def test_normalize_for_hash_formats_utc_datetimes_with_z() -> None:
    """Verify datetime normalization uses deterministic UTC strings."""
    value = normalize_for_hash(
        {"created_at": datetime(2026, 5, 14, 12, 30, tzinfo=UTC)}
    )

    assert value == {"created_at": "2026-05-14T12:30:00Z"}


def test_canonical_hash_preserves_null_values() -> None:
    """Verify null values remain part of the hash payload."""
    with_null = canonical_hash({"a": None})
    without_key = canonical_hash({})

    assert with_null != without_key
```

- [ ] **Step 2: Write failing task status tests**

Create `tests/test_agent_workbench_task_status.py`:

```python
"""Tests for task status CLI normalization."""

from __future__ import annotations

import pytest

from models.enums import TaskStatus
from services.agent_workbench.task_status import normalize_task_status


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("To Do", TaskStatus.TO_DO),
        ("to do", TaskStatus.TO_DO),
        ("to-do", TaskStatus.TO_DO),
        ("IN_PROGRESS", TaskStatus.IN_PROGRESS),
        ("in progress", TaskStatus.IN_PROGRESS),
        ("Done", TaskStatus.DONE),
        ("cancelled", TaskStatus.CANCELLED),
    ],
)
def test_normalize_task_status_accepts_display_and_cli_labels(
    raw: str,
    expected: TaskStatus,
) -> None:
    """Verify task status normalization accepts documented labels."""
    assert normalize_task_status(raw) == expected


def test_normalize_task_status_rejects_invalid_label() -> None:
    """Verify invalid labels fail before Phase 2 writes."""
    with pytest.raises(ValueError, match="Invalid task status"):
        normalize_task_status("started")
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_agent_workbench_fingerprints.py tests/test_agent_workbench_task_status.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 4: Implement canonical fingerprint helper**

Create `services/agent_workbench/fingerprints.py`:

```python
"""Canonical hashing helpers for agent workbench projections."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any


def _datetime_to_utc_z(value: datetime) -> str:
    normalized = value if value.tzinfo else value.replace(tzinfo=UTC)
    return normalized.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_for_hash(value: object) -> object:
    """Normalize objects into deterministic JSON-compatible values."""
    if isinstance(value, datetime):
        return _datetime_to_utc_z(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): normalize_for_hash(value[key])
            for key in sorted(value, key=lambda item: str(item))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_for_hash(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    """Serialize a normalized value for hashing."""
    return json.dumps(
        normalize_for_hash(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def canonical_hash(value: object) -> str:
    """Return the canonical SHA-256 fingerprint for a value."""
    digest = hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
```

- [ ] **Step 5: Implement task status normalizer**

Create `services/agent_workbench/task_status.py`:

```python
"""Task status normalization for CLI stale-write checks."""

from __future__ import annotations

from models.enums import TaskStatus

_TASK_STATUS_LABELS: dict[str, TaskStatus] = {
    "to do": TaskStatus.TO_DO,
    "in progress": TaskStatus.IN_PROGRESS,
    "done": TaskStatus.DONE,
    "cancelled": TaskStatus.CANCELLED,
}


def _normalize_label(value: str) -> str:
    return " ".join(value.strip().replace("_", " ").replace("-", " ").split()).lower()


def normalize_task_status(value: str) -> TaskStatus:
    """Normalize a CLI task status label into the persisted enum."""
    normalized = _normalize_label(value)
    try:
        return _TASK_STATUS_LABELS[normalized]
    except KeyError as exc:
        allowed = ", ".join(sorted(status.value for status in _TASK_STATUS_LABELS.values()))
        msg = f"Invalid task status {value!r}. Expected one of: {allowed}."
        raise ValueError(msg) from exc
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_agent_workbench_fingerprints.py tests/test_agent_workbench_task_status.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/agent_workbench/fingerprints.py services/agent_workbench/task_status.py tests/test_agent_workbench_fingerprints.py tests/test_agent_workbench_task_status.py
git commit -m "feat: add workbench fingerprints"
```

---

### Task 3: Schema Readiness And Read-Only Session Access

**Files:**
- Create: `services/agent_workbench/schema_readiness.py`
- Create: `services/agent_workbench/session_reader.py`
- Test: `tests/test_agent_workbench_schema_readiness.py`
- Test: `tests/test_agent_workbench_session_reader.py`

- [ ] **Step 1: Write failing schema readiness tests**

Create `tests/test_agent_workbench_schema_readiness.py`:

```python
"""Tests for read-only schema readiness checks."""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlmodel import SQLModel

from models.core import Product
from services.agent_workbench.schema_readiness import (
    SchemaRequirement,
    check_schema_readiness,
)


def test_check_schema_readiness_reports_missing_table() -> None:
    """Verify missing tables are returned as structured data."""
    engine = create_engine("sqlite:///:memory:")

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "name"))],
    )

    assert result.ok is False
    assert result.missing == {"products": ["product_id", "name"]}


def test_check_schema_readiness_reports_missing_columns() -> None:
    """Verify missing columns are reported without running migrations."""
    engine = create_engine("sqlite:///:memory:")
    Product.__table__.create(engine)

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "not_a_column"))],
    )

    assert result.ok is False
    assert result.missing == {"products": ["not_a_column"]}


def test_check_schema_readiness_accepts_existing_columns() -> None:
    """Verify existing table/columns pass readiness."""
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    result = check_schema_readiness(
        engine,
        [SchemaRequirement(table="products", columns=("product_id", "name"))],
    )

    assert result.ok is True
    assert result.missing == {}
```

- [ ] **Step 2: Write failing session reader tests**

Create `tests/test_agent_workbench_session_reader.py`:

```python
"""Tests for read-only workflow session access."""

from __future__ import annotations

from services.agent_workbench.session_reader import ReadOnlySessionReader


class _FakeSessionRepository:
    def __init__(self) -> None:
        self.updated = False

    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, object]:
        return {
            "app_name": app_name,
            "user_id": user_id,
            "session_id": session_id,
            "fsm_state": "SPRINT_SETUP",
        }

    def update_session_state(self, *_args: object, **_kwargs: object) -> None:
        self.updated = True


def test_read_only_session_reader_fetches_state_without_update() -> None:
    """Verify session reader does not mutate session state."""
    repo = _FakeSessionRepository()
    reader = ReadOnlySessionReader(repository=repo)

    state = reader.get_project_state(project_id=7)

    assert state["fsm_state"] == "SPRINT_SETUP"
    assert state["session_id"] == "7"
    assert repo.updated is False
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_agent_workbench_schema_readiness.py tests/test_agent_workbench_session_reader.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 4: Implement schema readiness**

Create `services/agent_workbench/schema_readiness.py`:

```python
"""Read-only schema readiness checks for CLI projections."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect
from sqlalchemy.engine import Engine


@dataclass(frozen=True)
class SchemaRequirement:
    """Required table and columns for a projection."""

    table: str
    columns: Sequence[str]


@dataclass(frozen=True)
class SchemaReadiness:
    """Schema readiness result."""

    ok: bool
    missing: dict[str, list[str]]


def check_schema_readiness(
    engine: Engine,
    requirements: list[SchemaRequirement],
) -> SchemaReadiness:
    """Return missing schema elements without creating or migrating anything."""
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    missing: dict[str, list[str]] = {}

    for requirement in requirements:
        if requirement.table not in table_names:
            missing[requirement.table] = list(requirement.columns)
            continue
        columns = {column["name"] for column in inspector.get_columns(requirement.table)}
        missing_columns = [
            column for column in requirement.columns if column not in columns
        ]
        if missing_columns:
            missing[requirement.table] = missing_columns

    return SchemaReadiness(ok=not missing, missing=missing)
```

- [ ] **Step 5: Implement read-only session reader**

Create `services/agent_workbench/session_reader.py`:

```python
"""Read-only workflow session access for agent workbench projections."""

from __future__ import annotations

from typing import Any, Protocol

from repositories.session import WorkflowSessionRepository
from utils.runtime_config import WORKFLOW_RUNNER_IDENTITY


class _SessionRepository(Protocol):
    def get_session_state(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        raise NotImplementedError


class ReadOnlySessionReader:
    """Read project workflow session state without creating or updating sessions."""

    def __init__(self, repository: _SessionRepository | None = None) -> None:
        self._repository = repository or WorkflowSessionRepository()

    def get_project_state(self, project_id: int) -> dict[str, Any]:
        """Return workflow session state for a project id."""
        return self._repository.get_session_state(
            WORKFLOW_RUNNER_IDENTITY.app_name,
            WORKFLOW_RUNNER_IDENTITY.user_id,
            str(project_id),
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_agent_workbench_schema_readiness.py tests/test_agent_workbench_session_reader.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/agent_workbench/schema_readiness.py services/agent_workbench/session_reader.py tests/test_agent_workbench_schema_readiness.py tests/test_agent_workbench_session_reader.py
git commit -m "feat: add read-only workbench guards"
```

---

### Task 4: Authority Projection

**Files:**
- Create: `services/agent_workbench/authority_projection.py`
- Test: `tests/test_agent_workbench_authority_projection.py`

- [ ] **Step 1: Write failing authority projection tests**

Create `tests/test_agent_workbench_authority_projection.py`:

```python
"""Tests for agent workbench Spec Authority projections."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session

from models.core import Product
from models.specs import (
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecRegistry,
)
from services.agent_workbench.authority_projection import AuthorityProjectionService
from tests.typing_helpers import require_id


def _seed_product(session: Session) -> Product:
    product = Product(name="Authority Product", spec_file_path="specs/app.md")
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def test_authority_status_reports_schema_not_ready_for_missing_tables(tmp_path: Path) -> None:
    """Verify authority projection does not run migrations for missing schema."""
    from sqlalchemy import create_engine  # noqa: PLC0415

    service = AuthorityProjectionService(
        engine=create_engine("sqlite:///:memory:"),
        repo_root=tmp_path,
    )

    result = service.status(project_id=1)

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "SCHEMA_NOT_READY"


def test_authority_status_reports_current_accepted_authority(
    session: Session,
    tmp_path: Path,
) -> None:
    """Verify current authority includes accepted version and fingerprint."""
    spec_path = tmp_path / "specs" / "app.md"
    spec_path.parent.mkdir()
    spec_path.write_text("# Spec\n", encoding="utf-8")

    product = _seed_product(session)
    product.spec_file_path = "specs/app.md"
    session.add(product)
    session.commit()

    spec = SpecRegistry(
        product_id=require_id(product.product_id, "product_id"),
        spec_hash="f" * 64,
        content="# Spec\n",
        content_ref="specs/app.md",
        status="approved",
        approved_at=datetime(2026, 5, 14, tzinfo=UTC),
    )
    session.add(spec)
    session.commit()
    session.refresh(spec)

    authority = CompiledSpecAuthority(
        spec_version_id=require_id(spec.spec_version_id, "spec_version_id"),
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
        compiled_artifact_json=json.dumps({"invariants": [{"id": "INV-1"}]}),
        scope_themes="[]",
        invariants=json.dumps([{"id": "INV-1"}]),
        eligible_feature_ids="[]",
    )
    session.add(authority)
    session.commit()
    session.refresh(authority)

    session.add(
        SpecAuthorityAcceptance(
            product_id=require_id(product.product_id, "product_id"),
            spec_version_id=require_id(spec.spec_version_id, "spec_version_id"),
            status="accepted",
            policy="human",
            decided_by="reviewer",
            compiler_version="1.0.0",
            prompt_hash="a" * 64,
            spec_hash="f" * 64,
        )
    )
    session.commit()

    service = AuthorityProjectionService(engine=session.get_bind(), repo_root=tmp_path)
    result = service.status(project_id=require_id(product.product_id, "product_id"))

    assert result["ok"] is True
    data = result["data"]
    assert data["status"] == "current"
    assert data["accepted_spec_version_id"] == spec.spec_version_id
    assert data["authority_id"] == authority.authority_id
    assert data["invariant_count"] == 1
    assert data["authority_fingerprint"].startswith("sha256:")
    assert data["disk_spec"]["resolved_path"] == str(spec_path.resolve())


def test_invariants_requires_accepted_authority(
    session: Session,
    tmp_path: Path,
) -> None:
    """Verify invariants command does not choose arbitrary compiled versions."""
    product = _seed_product(session)

    service = AuthorityProjectionService(engine=session.get_bind(), repo_root=tmp_path)
    result = service.invariants(project_id=require_id(product.product_id, "product_id"))

    assert result["ok"] is False
    assert result["errors"][0]["code"] == "AUTHORITY_NOT_ACCEPTED"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_agent_workbench_authority_projection.py -q`

Expected: FAIL with missing `authority_projection`.

- [ ] **Step 3: Implement authority projection**

Create `services/agent_workbench/authority_projection.py`:

```python
"""Read-only Spec Authority projections for the agent workbench."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast

from sqlalchemy import desc
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from models.core import Product
from models.db import get_engine
from models.specs import (
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecRegistry,
)
from services.agent_workbench.envelope import WorkbenchError, error_envelope
from services.agent_workbench.fingerprints import canonical_hash
from services.agent_workbench.schema_readiness import (
    SchemaRequirement,
    check_schema_readiness,
)

_AUTHORITY_REQUIREMENTS = [
    SchemaRequirement("products", ("product_id", "name", "spec_file_path", "updated_at")),
    SchemaRequirement(
        "spec_registry",
        ("spec_version_id", "product_id", "spec_hash", "content_ref", "status"),
    ),
    SchemaRequirement(
        "compiled_spec_authority",
        (
            "authority_id",
            "spec_version_id",
            "compiler_version",
            "prompt_hash",
            "compiled_artifact_json",
            "invariants",
            "compiled_at",
        ),
    ),
    SchemaRequirement(
        "spec_authority_acceptance",
        (
            "id",
            "product_id",
            "spec_version_id",
            "status",
            "policy",
            "decided_by",
            "decided_at",
            "compiler_version",
            "prompt_hash",
            "spec_hash",
        ),
    ),
]


def _schema_error(command: str, missing: dict[str, list[str]]) -> dict[str, Any]:
    return error_envelope(
        command=command,
        error=WorkbenchError(
            code="SCHEMA_NOT_READY",
            message=(
                "Database schema is missing required tables or columns for this "
                "read-only command."
            ),
            details={"missing": missing},
            remediation=["Run the application startup or migration command before using the CLI."],
            exit_code=1,
            retryable=False,
        ),
    )


class AuthorityProjectionService:
    """Read-only Spec Authority projection service."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        repo_root: Path | None = None,
    ) -> None:
        self._engine = engine or get_engine()
        self._repo_root = repo_root or Path(__file__).resolve().parents[2]

    def _check_schema(self, command: str) -> dict[str, Any] | None:
        readiness = check_schema_readiness(self._engine, _AUTHORITY_REQUIREMENTS)
        if readiness.ok:
            return None
        return _schema_error(command, readiness.missing)

    def _resolve_spec_path(self, value: str | None) -> dict[str, Any]:
        if not value:
            return {
                "path": None,
                "resolved_path": None,
                "exists": False,
                "sha256": None,
            }
        path = Path(value)
        resolved = path if path.is_absolute() else self._repo_root / path
        resolved = resolved.resolve()
        if not resolved.exists() or not resolved.is_file():
            return {
                "path": value,
                "resolved_path": str(resolved),
                "exists": False,
                "sha256": None,
            }
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
        return {
            "path": value,
            "resolved_path": str(resolved),
            "exists": True,
            "sha256": digest,
        }

    def status(self, *, project_id: int) -> dict[str, Any]:
        """Return current Spec Authority status for a project."""
        schema_error = self._check_schema("tcc authority status")
        if schema_error:
            return schema_error

        with Session(self._engine) as session:
            product = session.get(Product, project_id)
            if not product:
                return error_envelope(
                    command="tcc authority status",
                    error=WorkbenchError(
                        code="PROJECT_NOT_FOUND",
                        message=f"Project {project_id} was not found.",
                        details={"project_id": project_id},
                        remediation=["tcc project list"],
                        exit_code=2,
                        retryable=False,
                    ),
                )

            specs = list(
                session.exec(
                    select(SpecRegistry)
                    .where(SpecRegistry.product_id == project_id)
                    .order_by(desc(cast("Any", SpecRegistry.spec_version_id)))
                ).all()
            )
            accepted = session.exec(
                select(SpecAuthorityAcceptance)
                .where(
                    SpecAuthorityAcceptance.product_id == project_id,
                    SpecAuthorityAcceptance.status == "accepted",
                )
                .order_by(desc(cast("Any", SpecAuthorityAcceptance.decided_at)))
            ).first()

            latest_spec = specs[0] if specs else None
            accepted_spec = (
                session.get(SpecRegistry, accepted.spec_version_id)
                if accepted is not None
                else None
            )
            authority = (
                session.exec(
                    select(CompiledSpecAuthority).where(
                        CompiledSpecAuthority.spec_version_id
                        == accepted.spec_version_id
                    )
                ).first()
                if accepted is not None
                else None
            )

            if accepted is None:
                status = "missing" if not specs else "pending_acceptance"
            elif authority is None:
                status = "not_compiled"
            elif latest_spec and latest_spec.spec_hash != accepted.spec_hash:
                status = "stale"
            else:
                status = "current"

            invariant_count = 0
            if authority and authority.invariants:
                try:
                    parsed_invariants = json.loads(authority.invariants)
                    invariant_count = len(parsed_invariants) if isinstance(parsed_invariants, list) else 0
                except json.JSONDecodeError:
                    invariant_count = 0

            disk_spec = self._resolve_spec_path(
                product.spec_file_path
                or (accepted_spec.content_ref if accepted_spec is not None else None)
            )
            if (
                disk_spec["sha256"]
                and accepted is not None
                and disk_spec["sha256"] != accepted.spec_hash
                and status == "current"
            ):
                status = "stale"

            fingerprint_payload = {
                "accepted_spec_version_id": accepted.spec_version_id if accepted else None,
                "authority_id": authority.authority_id if authority else None,
                "spec_hash": accepted.spec_hash if accepted else None,
                "compiled_artifact_json_hash": canonical_hash(authority.compiled_artifact_json)
                if authority and authority.compiled_artifact_json
                else None,
                "compiler_version": accepted.compiler_version if accepted else None,
                "prompt_hash": accepted.prompt_hash if accepted else None,
                "acceptance": {
                    "id": accepted.id,
                    "status": accepted.status,
                    "policy": accepted.policy,
                    "decided_by": accepted.decided_by,
                    "decided_at": accepted.decided_at,
                }
                if accepted
                else None,
            }

            return {
                "ok": True,
                "data": {
                    "project_id": project_id,
                    "status": status,
                    "latest_spec_version_id": latest_spec.spec_version_id if latest_spec else None,
                    "accepted_spec_version_id": accepted.spec_version_id if accepted else None,
                    "authority_id": authority.authority_id if authority else None,
                    "spec_hash": accepted.spec_hash if accepted else None,
                    "compiler_version": accepted.compiler_version if accepted else None,
                    "prompt_hash": accepted.prompt_hash if accepted else None,
                    "invariant_count": invariant_count,
                    "disk_spec": disk_spec,
                    "authority_fingerprint": canonical_hash(fingerprint_payload),
                },
                "warnings": [],
                "errors": [],
            }

    def invariants(
        self,
        *,
        project_id: int,
        spec_version_id: int | None = None,
    ) -> dict[str, Any]:
        """Return invariants for the accepted or explicitly requested authority."""
        schema_error = self._check_schema("tcc authority invariants")
        if schema_error:
            return schema_error

        with Session(self._engine) as session:
            if spec_version_id is None:
                accepted = session.exec(
                    select(SpecAuthorityAcceptance)
                    .where(
                        SpecAuthorityAcceptance.product_id == project_id,
                        SpecAuthorityAcceptance.status == "accepted",
                    )
                    .order_by(desc(cast("Any", SpecAuthorityAcceptance.decided_at)))
                ).first()
                if accepted is None:
                    return error_envelope(
                        command="tcc authority invariants",
                        error=WorkbenchError(
                            code="AUTHORITY_NOT_ACCEPTED",
                            message="No accepted authority exists for this project.",
                            details={"project_id": project_id},
                            remediation=[
                                "tcc authority versions --project-id "
                                f"{project_id}",
                                "tcc authority accept --project-id "
                                f"{project_id} --spec-version-id 3 --policy human --decided-by agent",
                            ],
                            exit_code=4,
                            retryable=False,
                        ),
                    )
                spec_version_id = accepted.spec_version_id

            authority = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == spec_version_id
                )
            ).first()
            if not authority:
                return error_envelope(
                    command="tcc authority invariants",
                    error=WorkbenchError(
                        code="AUTHORITY_NOT_COMPILED",
                        message=f"Spec version {spec_version_id} has no compiled authority.",
                        details={"spec_version_id": spec_version_id},
                        remediation=[
                            f"tcc authority compile --spec-version-id {spec_version_id}"
                        ],
                        exit_code=4,
                        retryable=False,
                    ),
                )

            invariants = json.loads(authority.invariants or "[]")
            return {
                "ok": True,
                "data": {
                    "project_id": project_id,
                    "spec_version_id": spec_version_id,
                    "authority_id": authority.authority_id,
                    "invariants": invariants,
                    "count": len(invariants) if isinstance(invariants, list) else 0,
                    "authority_fingerprint": canonical_hash(
                        {
                            "authority_id": authority.authority_id,
                            "spec_version_id": authority.spec_version_id,
                            "compiler_version": authority.compiler_version,
                            "prompt_hash": authority.prompt_hash,
                            "invariants": invariants,
                        }
                    ),
                },
                "warnings": [],
                "errors": [],
            }
```

- [ ] **Step 4: Run authority tests**

Run: `uv run --frozen pytest tests/test_agent_workbench_authority_projection.py -q`

Expected: PASS.

- [ ] **Step 5: Run targeted spec compiler regression tests**

Run: `uv run --frozen pytest tests/test_specs_compiler_service.py tests/test_select_project_hydration.py -q`

Expected: PASS. This confirms the read-only authority projection did not change existing compile/hydration behavior.

- [ ] **Step 6: Commit**

```bash
git add services/agent_workbench/authority_projection.py tests/test_agent_workbench_authority_projection.py
git commit -m "feat: add authority projection"
```

---

### Task 5: Read Projection Service And Application Facade

**Files:**
- Create: `services/agent_workbench/read_projection.py`
- Create: `services/agent_workbench/application.py`
- Test: `tests/test_agent_workbench_read_projection.py`
- Test: `tests/test_agent_workbench_application.py`

- [ ] **Step 1: Write failing read projection tests**

Create `tests/test_agent_workbench_read_projection.py`:

```python
"""Tests for read-only agent workbench projections."""

from __future__ import annotations

from datetime import date

from sqlmodel import Session

from models.core import Product, Sprint, SprintStory, Task, Team, UserStory
from models.enums import SprintStatus
from services.agent_workbench.read_projection import ReadProjectionService
from tests.typing_helpers import require_id
from utils.task_metadata import TaskMetadata, serialize_task_metadata


def _seed_project_with_story(session: Session) -> tuple[int, int, int, int]:
    product = Product(name="Workbench Project", description="Demo")
    session.add(product)
    session.commit()
    session.refresh(product)
    product_id = require_id(product.product_id, "product_id")

    story = UserStory(
        product_id=product_id,
        title="Implement CLI",
        story_description="As an agent, I can inspect the project.",
        acceptance_criteria="- shows state",
        story_points=3,
        rank="1",
        is_refined=True,
    )
    session.add(story)
    session.commit()
    session.refresh(story)
    story_id = require_id(story.story_id, "story_id")

    task = Task(
        story_id=story_id,
        description="Add read projection",
        metadata_json=serialize_task_metadata(
            TaskMetadata(checklist_items=["Return JSON"])
        ),
    )
    session.add(task)

    team = Team(name="Workbench Team")
    session.add(team)
    session.commit()
    session.refresh(team)

    sprint = Sprint(
        product_id=product_id,
        team_id=require_id(team.team_id, "team_id"),
        goal="Inspect safely",
        start_date=date(2026, 5, 14),
        end_date=date(2026, 5, 28),
        status=SprintStatus.PLANNED,
    )
    session.add(sprint)
    session.commit()
    session.refresh(sprint)
    sprint_id = require_id(sprint.sprint_id, "sprint_id")

    session.add(SprintStory(sprint_id=sprint_id, story_id=story_id))
    session.commit()
    session.refresh(task)
    return product_id, story_id, sprint_id, require_id(task.task_id, "task_id")


def test_project_list_returns_counts_and_fingerprint(session: Session) -> None:
    """Verify project list is a read-only projection."""
    product_id, _story_id, _sprint_id, _task_id = _seed_project_with_story(session)
    service = ReadProjectionService(engine=session.get_bind())

    result = service.project_list()

    assert result["ok"] is True
    assert result["data"]["count"] == 1
    assert result["data"]["items"][0]["product_id"] == product_id
    assert result["data"]["items"][0]["user_stories_count"] == 1
    assert result["data"]["items"][0]["sprint_count"] == 1
    assert result["data"]["source_fingerprint"].startswith("sha256:")


def test_story_show_returns_validation_and_fingerprint(session: Session) -> None:
    """Verify story show exposes story details without validation side effects."""
    _product_id, story_id, _sprint_id, _task_id = _seed_project_with_story(session)
    service = ReadProjectionService(engine=session.get_bind())

    result = service.story_show(story_id=story_id)

    assert result["ok"] is True
    assert result["data"]["story_id"] == story_id
    assert result["data"]["title"] == "Implement CLI"
    assert result["data"]["validation"]["present"] is False
    assert result["data"]["source_fingerprint"].startswith("sha256:")


def test_sprint_candidates_returns_refined_unplanned_stories(session: Session) -> None:
    """Verify sprint candidates delegates eligibility without mutation."""
    product_id, story_id, _sprint_id, _task_id = _seed_project_with_story(session)
    service = ReadProjectionService(engine=session.get_bind())

    result = service.sprint_candidates(project_id=product_id)

    assert result["ok"] is True
    assert result["data"]["count"] == 0
    assert story_id not in [item["story_id"] for item in result["data"]["items"]]
    assert result["data"]["excluded_counts"]["open_sprint"] == 1
```

- [ ] **Step 2: Write failing application facade tests**

Create `tests/test_agent_workbench_application.py`:

```python
"""Tests for the agent workbench application facade."""

from __future__ import annotations

from services.agent_workbench.application import AgentWorkbenchApplication


class _FakeReadProjection:
    def project_list(self) -> dict[str, object]:
        return {"ok": True, "data": {"items": []}, "warnings": [], "errors": []}


class _FakeAuthorityProjection:
    def status(self, *, project_id: int) -> dict[str, object]:
        return {
            "ok": True,
            "data": {"project_id": project_id, "status": "missing"},
            "warnings": [],
            "errors": [],
        }


def test_application_delegates_to_read_projection() -> None:
    """Verify application facade is thin and explicit."""
    app = AgentWorkbenchApplication(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    assert app.project_list()["data"]["items"] == []
    assert app.authority_status(project_id=7)["data"]["status"] == "missing"
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run --frozen pytest tests/test_agent_workbench_read_projection.py tests/test_agent_workbench_application.py -q`

Expected: FAIL with missing modules.

- [ ] **Step 4: Implement read projection service**

Create `services/agent_workbench/read_projection.py`:

```python
"""Read-only project projections for the agent workbench."""

from __future__ import annotations

import json
from typing import Any, cast

from sqlalchemy import desc, func
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from models.core import Product, Sprint, SprintStory, Task, UserStory
from models.db import get_engine
from models.enums import SprintStatus, StoryStatus
from services.agent_workbench.envelope import WorkbenchError, error_envelope
from services.agent_workbench.fingerprints import canonical_hash
from services.agent_workbench.schema_readiness import (
    SchemaRequirement,
    check_schema_readiness,
)
from services.agent_workbench.session_reader import ReadOnlySessionReader
from services.orchestrator_query_service import fetch_sprint_candidates
from utils.spec_schemas import ValidationEvidence

_READ_REQUIREMENTS = [
    SchemaRequirement("products", ("product_id", "name", "description", "updated_at")),
    SchemaRequirement(
        "user_stories",
        (
            "story_id",
            "product_id",
            "title",
            "status",
            "rank",
            "is_refined",
            "is_superseded",
            "updated_at",
        ),
    ),
    SchemaRequirement("sprints", ("sprint_id", "product_id", "status", "updated_at")),
    SchemaRequirement("sprint_stories", ("sprint_id", "story_id")),
]


def _schema_error(command: str, missing: dict[str, list[str]]) -> dict[str, Any]:
    return error_envelope(
        command=command,
        error=WorkbenchError(
            code="SCHEMA_NOT_READY",
            message=(
                "Database schema is missing required tables or columns for this "
                "read-only command."
            ),
            details={"missing": missing},
            remediation=["Run the application startup or migration command before using the CLI."],
            exit_code=1,
            retryable=False,
        ),
    )


def _enum_value(value: object) -> object:
    return value.value if hasattr(value, "value") else value


class ReadProjectionService:
    """Read-only projections for CLI orientation commands."""

    def __init__(
        self,
        *,
        engine: Engine | None = None,
        session_reader: ReadOnlySessionReader | None = None,
    ) -> None:
        self._engine = engine or get_engine()
        self._session_reader = session_reader or ReadOnlySessionReader()

    def _check_schema(self, command: str) -> dict[str, Any] | None:
        readiness = check_schema_readiness(self._engine, _READ_REQUIREMENTS)
        if readiness.ok:
            return None
        return _schema_error(command, readiness.missing)

    def project_list(self) -> dict[str, Any]:
        """Return projects with story and sprint counts."""
        schema_error = self._check_schema("tcc project list")
        if schema_error:
            return schema_error

        with Session(self._engine) as session:
            products = list(session.exec(select(Product).order_by(Product.product_id)).all())
            product_ids = [product.product_id for product in products if product.product_id is not None]
            story_counts = dict(
                session.exec(
                    select(UserStory.product_id, func.count(cast("Any", UserStory.story_id)))
                    .where(cast("Any", UserStory.product_id).in_(product_ids))
                    .group_by(UserStory.product_id)
                ).all()
            ) if product_ids else {}
            sprint_counts = dict(
                session.exec(
                    select(Sprint.product_id, func.count(cast("Any", Sprint.sprint_id)))
                    .where(cast("Any", Sprint.product_id).in_(product_ids))
                    .group_by(Sprint.product_id)
                ).all()
            ) if product_ids else {}
            items = [
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "description": product.description,
                    "user_stories_count": story_counts.get(product.product_id, 0),
                    "sprint_count": sprint_counts.get(product.product_id, 0),
                    "updated_at": product.updated_at,
                }
                for product in products
            ]
            return {
                "ok": True,
                "data": {
                    "items": items,
                    "count": len(items),
                    "source_fingerprint": canonical_hash(
                        {
                            "command": "tcc project list",
                            "items": items,
                        }
                    ),
                },
                "warnings": [],
                "errors": [],
            }

    def project_show(self, *, project_id: int) -> dict[str, Any]:
        """Return project detail counts without active-project hydration."""
        schema_error = self._check_schema("tcc project show")
        if schema_error:
            return schema_error

        with Session(self._engine) as session:
            product = session.get(Product, project_id)
            if not product:
                return error_envelope(
                    command="tcc project show",
                    error=WorkbenchError(
                        code="PROJECT_NOT_FOUND",
                        message=f"Project {project_id} was not found.",
                        details={"project_id": project_id},
                        remediation=["tcc project list"],
                        exit_code=2,
                        retryable=False,
                    ),
                )
            story_count = session.exec(
                select(func.count(cast("Any", UserStory.story_id))).where(
                    UserStory.product_id == project_id
                )
            ).one()
            sprint_count = session.exec(
                select(func.count(cast("Any", Sprint.sprint_id))).where(
                    Sprint.product_id == project_id
                )
            ).one()
            data = {
                "product_id": product.product_id,
                "name": product.name,
                "description": product.description,
                "vision_present": bool(product.vision),
                "roadmap_present": bool(product.roadmap),
                "spec_file_path": product.spec_file_path,
                "structure": {
                    "user_stories": story_count,
                    "sprints": sprint_count,
                },
                "updated_at": product.updated_at,
            }
            data["source_fingerprint"] = canonical_hash(
                {"command": "tcc project show", "data": data}
            )
            return {"ok": True, "data": data, "warnings": [], "errors": []}

    def workflow_state(self, *, project_id: int) -> dict[str, Any]:
        """Return workflow session state without creating or updating sessions."""
        schema_error = self._check_schema("tcc workflow state")
        if schema_error:
            return schema_error
        state = self._session_reader.get_project_state(project_id)
        data = {
            "project_id": project_id,
            "state": state,
            "source_fingerprint": canonical_hash(
                {"command": "tcc workflow state", "project_id": project_id, "state": state}
            ),
        }
        return {"ok": True, "data": data, "warnings": [], "errors": []}

    def story_show(self, *, story_id: int) -> dict[str, Any]:
        """Return story details and parsed validation presence."""
        schema_error = self._check_schema("tcc story show")
        if schema_error:
            return schema_error

        with Session(self._engine) as session:
            story = session.get(UserStory, story_id)
            if not story:
                return error_envelope(
                    command="tcc story show",
                    error=WorkbenchError(
                        code="STORY_NOT_FOUND",
                        message=f"Story {story_id} was not found.",
                        details={"story_id": story_id},
                        remediation=["tcc query backlog --project-id 1"],
                        exit_code=2,
                        retryable=False,
                    ),
                )
            validation_present = bool(story.validation_evidence)
            validation_passed = None
            if story.validation_evidence:
                try:
                    validation_passed = ValidationEvidence.model_validate_json(
                        story.validation_evidence
                    ).passed
                except (TypeError, ValueError):
                    validation_passed = None
            data = {
                "story_id": story.story_id,
                "product_id": story.product_id,
                "title": story.title,
                "description": story.story_description,
                "acceptance_criteria": story.acceptance_criteria,
                "status": _enum_value(story.status),
                "story_points": story.story_points,
                "rank": story.rank,
                "accepted_spec_version_id": story.accepted_spec_version_id,
                "validation": {
                    "present": validation_present,
                    "passed": validation_passed,
                },
                "updated_at": story.updated_at,
            }
            data["source_fingerprint"] = canonical_hash(
                {"command": "tcc story show", "data": data}
            )
            return {"ok": True, "data": data, "warnings": [], "errors": []}

    def sprint_candidates(self, *, project_id: int) -> dict[str, Any]:
        """Return sprint candidates using existing eligibility semantics."""
        schema_error = self._check_schema("tcc sprint candidates")
        if schema_error:
            return schema_error

        # Keep this read-only by temporarily routing the query service through this engine.
        from services import orchestrator_query_service  # noqa: PLC0415

        previous_get_engine = orchestrator_query_service.get_engine
        orchestrator_query_service.get_engine = lambda: self._engine
        try:
            raw = fetch_sprint_candidates(project_id)
        finally:
            orchestrator_query_service.get_engine = previous_get_engine

        data = {
            "items": raw.get("stories", []),
            "count": raw.get("count", 0),
            "excluded_counts": raw.get("excluded_counts", {}),
            "message": raw.get("message"),
        }
        data["source_fingerprint"] = canonical_hash(
            {"command": "tcc sprint candidates", "project_id": project_id, "data": data}
        )
        return {"ok": True, "data": data, "warnings": [], "errors": []}
```

- [ ] **Step 5: Implement application facade**

Create `services/agent_workbench/application.py`:

```python
"""Agent workbench application facade."""

from __future__ import annotations

from typing import Protocol

from services.agent_workbench.authority_projection import AuthorityProjectionService
from services.agent_workbench.read_projection import ReadProjectionService


class _ReadProjection(Protocol):
    def project_list(self) -> dict[str, object]:
        raise NotImplementedError


class _AuthorityProjection(Protocol):
    def status(self, *, project_id: int) -> dict[str, object]:
        raise NotImplementedError


class AgentWorkbenchApplication:
    """Thin facade shared by CLI transport and future API parity paths."""

    def __init__(
        self,
        *,
        read_projection: object | None = None,
        authority_projection: object | None = None,
    ) -> None:
        self._read_projection = read_projection or ReadProjectionService()
        self._authority_projection = authority_projection or AuthorityProjectionService()

    def project_list(self) -> dict[str, object]:
        """Return project list projection."""
        return self._read_projection.project_list()

    def project_show(self, *, project_id: int) -> dict[str, object]:
        """Return project detail projection."""
        return self._read_projection.project_show(project_id=project_id)

    def workflow_state(self, *, project_id: int) -> dict[str, object]:
        """Return workflow session projection."""
        return self._read_projection.workflow_state(project_id=project_id)

    def story_show(self, *, story_id: int) -> dict[str, object]:
        """Return story detail projection."""
        return self._read_projection.story_show(story_id=story_id)

    def sprint_candidates(self, *, project_id: int) -> dict[str, object]:
        """Return sprint candidate projection."""
        return self._read_projection.sprint_candidates(project_id=project_id)

    def authority_status(self, *, project_id: int) -> dict[str, object]:
        """Return authority status projection."""
        return self._authority_projection.status(project_id=project_id)

    def authority_invariants(
        self,
        *,
        project_id: int,
        spec_version_id: int | None = None,
    ) -> dict[str, object]:
        """Return authority invariants projection."""
        return self._authority_projection.invariants(
            project_id=project_id,
            spec_version_id=spec_version_id,
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run --frozen pytest tests/test_agent_workbench_read_projection.py tests/test_agent_workbench_application.py -q`

Expected: PASS.

- [ ] **Step 7: Run regression tests for existing query surfaces**

Run: `uv run --frozen pytest tests/test_orchestrator_query_service.py tests/test_orchestrator_tools.py tests/test_api_sprint_flow.py::test_get_task_packet_returns_task_local_execution_context -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add services/agent_workbench/read_projection.py services/agent_workbench/application.py tests/test_agent_workbench_read_projection.py tests/test_agent_workbench_application.py
git commit -m "feat: add workbench read projections"
```

---

### Task 6: Status, Workflow Next, And Context Pack Composition

**Files:**
- Create: `services/agent_workbench/context_pack.py`
- Modify: `services/agent_workbench/application.py`
- Test: `tests/test_agent_workbench_context_pack.py`

- [ ] **Step 1: Write failing context pack tests**

Create `tests/test_agent_workbench_context_pack.py`:

```python
"""Tests for context pack composition."""

from __future__ import annotations

from services.agent_workbench.context_pack import ContextPackService


class _FakeReadProjection:
    def workflow_state(self, *, project_id: int) -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "state": {"fsm_state": "SPRINT_SETUP", "setup_status": "passed"},
                "source_fingerprint": "sha256:" + "1" * 64,
            },
            "warnings": [],
            "errors": [],
        }

    def sprint_candidates(self, *, project_id: int) -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "items": [{"story_id": 10, "story_title": "Story"}],
                "count": 1,
                "excluded_counts": {},
                "source_fingerprint": "sha256:" + "2" * 64,
            },
            "warnings": [],
            "errors": [],
        }


class _FakeAuthorityProjection:
    def status(self, *, project_id: int) -> dict[str, object]:
        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "status": "current",
                "authority_fingerprint": "sha256:" + "3" * 64,
            },
            "warnings": [],
            "errors": [],
        }


def test_sprint_planning_pack_filters_unimplemented_next_commands() -> None:
    """Verify next commands only include installed capabilities."""
    service = ContextPackService(
        read_projection=_FakeReadProjection(),
        authority_projection=_FakeAuthorityProjection(),
    )

    result = service.pack(project_id=1, phase="sprint-planning")

    assert result["ok"] is True
    data = result["data"]
    assert data["phase"] == "sprint-planning"
    assert data["next_valid_commands"] == ["tcc sprint candidates --project-id 1"]
    assert data["blocked_future_commands"] == [
        "tcc sprint generate --project-id 1 --selected-story-ids 1,2,3"
    ]
    assert data["source_fingerprint"].startswith("sha256:")
    assert data["authority_fingerprint"] == "sha256:" + "3" * 64
    assert "raw_spec" in data["omitted_sections"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --frozen pytest tests/test_agent_workbench_context_pack.py -q`

Expected: FAIL with missing `context_pack`.

- [ ] **Step 3: Implement context pack service**

Create `services/agent_workbench/context_pack.py`:

```python
"""Phase-scoped context pack projections for agents."""

from __future__ import annotations

from typing import Any

from services.agent_workbench.command_registry import command_is_available
from services.agent_workbench.fingerprints import canonical_hash


class ContextPackService:
    """Compose bounded context packs from read-only projections."""

    def __init__(self, *, read_projection: object, authority_projection: object) -> None:
        self._read_projection = read_projection
        self._authority_projection = authority_projection

    def _sprint_planning_commands(self, project_id: int) -> tuple[list[str], list[str]]:
        candidate_command = f"tcc sprint candidates --project-id {project_id}"
        generate_command = f"tcc sprint generate --project-id {project_id} --selected-story-ids 1,2,3"
        next_valid: list[str] = []
        blocked: list[str] = []
        if command_is_available("tcc sprint candidates"):
            next_valid.append(candidate_command)
        else:
            blocked.append(candidate_command)
        if command_is_available("tcc sprint generate"):
            next_valid.append(generate_command)
        else:
            blocked.append(generate_command)
        return next_valid, blocked

    def pack(self, *, project_id: int, phase: str = "overview") -> dict[str, Any]:
        """Return a bounded context pack for a project and phase."""
        workflow = self._read_projection.workflow_state(project_id=project_id)
        authority = self._authority_projection.status(project_id=project_id)
        if not workflow.get("ok"):
            return workflow
        if not authority.get("ok"):
            return authority

        included_sections = ["workflow", "authority"]
        omitted_sections = ["raw_spec", "completed_sprint_history", "authority_full"]
        phase_data: dict[str, Any] = {}

        if phase == "sprint-planning":
            candidates = self._read_projection.sprint_candidates(project_id=project_id)
            if not candidates.get("ok"):
                return candidates
            phase_data["sprint_candidates"] = candidates["data"]
            included_sections.append("sprint_candidates")
            next_valid, blocked = self._sprint_planning_commands(project_id)
        else:
            next_valid = []
            blocked = []

        authority_data = authority["data"]
        workflow_data = workflow["data"]
        source_payload = {
            "command": "tcc context pack",
            "project_id": project_id,
            "phase": phase,
            "included_sections": included_sections,
            "workflow": workflow_data.get("source_fingerprint"),
            "authority": authority_data.get("authority_fingerprint"),
            "phase_data": phase_data,
        }

        return {
            "ok": True,
            "data": {
                "project_id": project_id,
                "phase": phase,
                "fsm_state": workflow_data.get("state", {}).get("fsm_state"),
                "source_fingerprint": canonical_hash(source_payload),
                "authority_fingerprint": authority_data.get("authority_fingerprint"),
                "spec_authority": authority_data,
                "warnings": [],
                "next_valid_commands": next_valid,
                "blocked_future_commands": blocked,
                "included_sections": included_sections,
                "omitted_sections": omitted_sections,
                "truncation": [],
                "phase_data": phase_data,
            },
            "warnings": [],
            "errors": [],
        }
```

- [ ] **Step 4: Wire application facade methods**

Modify `services/agent_workbench/application.py`:

```python
from services.agent_workbench.context_pack import ContextPackService
```

Update `__init__` after projection assignment:

```python
        self._context_pack = ContextPackService(
            read_projection=self._read_projection,
            authority_projection=self._authority_projection,
        )
```

Add methods:

```python
    def context_pack(self, *, project_id: int, phase: str = "overview") -> dict[str, object]:
        """Return a phase-scoped context pack."""
        return self._context_pack.pack(project_id=project_id, phase=phase)

    def status(self, *, project_id: int) -> dict[str, object]:
        """Return cheap project orientation status."""
        workflow = self.workflow_state(project_id=project_id)
        authority = self.authority_status(project_id=project_id)
        project = self.project_show(project_id=project_id)
        if not workflow.get("ok"):
            return workflow
        if not authority.get("ok"):
            return authority
        if not project.get("ok"):
            return project
        data = {
            "project": project["data"],
            "workflow": workflow["data"],
            "authority": authority["data"],
        }
        return {"ok": True, "data": data, "warnings": [], "errors": []}

    def workflow_next(self, *, project_id: int) -> dict[str, object]:
        """Return installed next commands for the current workflow state."""
        pack = self.context_pack(project_id=project_id, phase="sprint-planning")
        if not pack.get("ok"):
            return pack
        data = {
            "project_id": project_id,
            "next_valid_commands": pack["data"]["next_valid_commands"],
            "blocked_future_commands": pack["data"]["blocked_future_commands"],
        }
        return {"ok": True, "data": data, "warnings": [], "errors": []}
```

- [ ] **Step 5: Run tests**

Run: `uv run --frozen pytest tests/test_agent_workbench_context_pack.py tests/test_agent_workbench_application.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add services/agent_workbench/context_pack.py services/agent_workbench/application.py tests/test_agent_workbench_context_pack.py tests/test_agent_workbench_application.py
git commit -m "feat: add workbench context packs"
```

---

### Task 7: CLI Transport

**Files:**
- Create: `cli/__init__.py`
- Create: `cli/main.py`
- Modify: `pyproject.toml`
- Test: `tests/test_agent_workbench_cli.py`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_agent_workbench_cli.py`:

```python
"""Tests for the tcc CLI transport."""

from __future__ import annotations

import json

from cli.main import main


class _FakeApplication:
    def project_list(self) -> dict[str, object]:
        return {"ok": True, "data": {"items": []}, "warnings": [], "errors": []}

    def authority_status(self, *, project_id: int) -> dict[str, object]:
        return {
            "ok": True,
            "data": {"project_id": project_id, "status": "missing"},
            "warnings": [],
            "errors": [],
        }


def test_cli_writes_success_json_to_stdout(capsys) -> None:  # noqa: ANN001
    """Verify CLI emits JSON envelope to stdout."""
    rc = main(["project", "list"], application=_FakeApplication())

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert rc == 0
    assert captured.err == ""
    assert payload["ok"] is True
    assert payload["meta"]["command"] == "tcc project list"


def test_cli_supports_authority_status(capsys) -> None:  # noqa: ANN001
    """Verify authority status command routes project id."""
    rc = main(
        ["authority", "status", "--project-id", "7"],
        application=_FakeApplication(),
    )

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["data"]["project_id"] == 7
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run --frozen pytest tests/test_agent_workbench_cli.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'cli.main'`.

- [ ] **Step 3: Create CLI package marker**

Create `cli/__init__.py`:

```python
"""Command-line entrypoints for project_tcc."""
```

- [ ] **Step 4: Implement argparse CLI**

Create `cli/main.py`:

```python
"""Agent workbench CLI transport."""

from __future__ import annotations

import argparse
import json
from typing import Any

from services.agent_workbench.application import AgentWorkbenchApplication
from services.agent_workbench.envelope import WorkbenchError, error_envelope, success_envelope


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))


def _exit_code(result: dict[str, Any]) -> int:
    if result.get("ok"):
        return 0
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        first = errors[0]
        if isinstance(first, dict):
            return int(first.get("exit_code", 1))
    return 1


def _wrap(command: str, result: dict[str, Any]) -> dict[str, Any]:
    if "meta" in result:
        return result
    if result.get("ok"):
        return success_envelope(
            command=command,
            data=result.get("data", {}),
            warnings=[],
        )
    errors = result.get("errors")
    if isinstance(errors, list) and errors:
        error = errors[0]
        return error_envelope(
            command=command,
            error=WorkbenchError(
                code=str(error.get("code", "COMMAND_FAILED")),
                message=str(error.get("message", "Command failed.")),
                details=dict(error.get("details", {})),
                remediation=list(error.get("remediation", [])),
                exit_code=int(error.get("exit_code", 1)),
                retryable=bool(error.get("retryable", False)),
            ),
        )
    return error_envelope(
        command=command,
        error=WorkbenchError(
            code="COMMAND_FAILED",
            message="Command failed without structured error details.",
            exit_code=1,
            retryable=False,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(prog="tcc")
    subparsers = parser.add_subparsers(dest="group", required=True)

    project = subparsers.add_parser("project")
    project_sub = project.add_subparsers(dest="action", required=True)
    project_sub.add_parser("list")
    project_show = project_sub.add_parser("show")
    project_show.add_argument("--project-id", type=int, required=True)

    workflow = subparsers.add_parser("workflow")
    workflow_sub = workflow.add_subparsers(dest="action", required=True)
    workflow_state = workflow_sub.add_parser("state")
    workflow_state.add_argument("--project-id", type=int, required=True)
    workflow_next = workflow_sub.add_parser("next")
    workflow_next.add_argument("--project-id", type=int, required=True)

    authority = subparsers.add_parser("authority")
    authority_sub = authority.add_subparsers(dest="action", required=True)
    authority_status = authority_sub.add_parser("status")
    authority_status.add_argument("--project-id", type=int, required=True)
    authority_invariants = authority_sub.add_parser("invariants")
    authority_invariants.add_argument("--project-id", type=int, required=True)
    authority_invariants.add_argument("--spec-version-id", type=int)

    story = subparsers.add_parser("story")
    story_sub = story.add_subparsers(dest="action", required=True)
    story_show = story_sub.add_parser("show")
    story_show.add_argument("--story-id", type=int, required=True)

    sprint = subparsers.add_parser("sprint")
    sprint_sub = sprint.add_subparsers(dest="action", required=True)
    sprint_candidates = sprint_sub.add_parser("candidates")
    sprint_candidates.add_argument("--project-id", type=int, required=True)

    context = subparsers.add_parser("context")
    context_sub = context.add_subparsers(dest="action", required=True)
    context_pack = context_sub.add_parser("pack")
    context_pack.add_argument("--project-id", type=int, required=True)
    context_pack.add_argument("--phase", default="overview")

    status = subparsers.add_parser("status")
    status.add_argument("--project-id", type=int, required=True)
    return parser


def _dispatch(args: argparse.Namespace, application: object) -> tuple[str, dict[str, Any]]:
    group = args.group
    action = getattr(args, "action", None)
    if group == "project" and action == "list":
        return "tcc project list", application.project_list()
    if group == "project" and action == "show":
        return "tcc project show", application.project_show(project_id=args.project_id)
    if group == "workflow" and action == "state":
        return "tcc workflow state", application.workflow_state(project_id=args.project_id)
    if group == "workflow" and action == "next":
        return "tcc workflow next", application.workflow_next(project_id=args.project_id)
    if group == "authority" and action == "status":
        return "tcc authority status", application.authority_status(project_id=args.project_id)
    if group == "authority" and action == "invariants":
        return "tcc authority invariants", application.authority_invariants(
            project_id=args.project_id,
            spec_version_id=args.spec_version_id,
        )
    if group == "story" and action == "show":
        return "tcc story show", application.story_show(story_id=args.story_id)
    if group == "sprint" and action == "candidates":
        return "tcc sprint candidates", application.sprint_candidates(project_id=args.project_id)
    if group == "context" and action == "pack":
        return "tcc context pack", application.context_pack(
            project_id=args.project_id,
            phase=args.phase,
        )
    if group == "status":
        return "tcc status", application.status(project_id=args.project_id)
    return "tcc", {
        "ok": False,
        "errors": [
            {
                "code": "COMMAND_NOT_IMPLEMENTED",
                "message": "Command is not implemented.",
                "details": {"group": group, "action": action},
                "remediation": ["Run tcc --help."],
                "exit_code": 2,
                "retryable": False,
            }
        ],
        "warnings": [],
    }


def main(argv: list[str] | None = None, *, application: object | None = None) -> int:
    """Run the CLI and return an exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    app = application or AgentWorkbenchApplication()
    command, result = _dispatch(args, app)
    envelope = _wrap(command, result)
    _print_json(envelope)
    return _exit_code(envelope)


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Add project script entry point**

Modify `pyproject.toml` after `[project]` metadata and dependencies:

```toml
[project.scripts]
tcc = "cli.main:main"
```

- [ ] **Step 6: Run CLI tests**

Run: `uv run --frozen pytest tests/test_agent_workbench_cli.py -q`

Expected: PASS.

- [ ] **Step 7: Run CLI smoke command**

Run: `uv run --frozen tcc --help`

Expected: exits `0` and prints argparse help text containing `project`, `workflow`, `authority`, `story`, `sprint`, `context`, and `status`.

- [ ] **Step 8: Commit**

```bash
git add cli/__init__.py cli/main.py pyproject.toml tests/test_agent_workbench_cli.py
git commit -m "feat: add tcc read-only cli"
```

---

### Task 8: End-To-End Phase 1 Verification

**Files:**
- Test: `tests/test_agent_workbench_phase1_integration.py`

- [ ] **Step 1: Write integration tests**

Create `tests/test_agent_workbench_phase1_integration.py`:

```python
"""Phase 1 integration tests for the agent workbench CLI."""

from __future__ import annotations

import json

from sqlmodel import Session

from cli.main import main
from models.core import Product
from services.agent_workbench.application import AgentWorkbenchApplication
from services.agent_workbench.authority_projection import AuthorityProjectionService
from services.agent_workbench.read_projection import ReadProjectionService
from tests.typing_helpers import require_id


def _app_for_engine(engine) -> AgentWorkbenchApplication:  # noqa: ANN001
    read_projection = ReadProjectionService(engine=engine)
    authority_projection = AuthorityProjectionService(engine=engine)
    return AgentWorkbenchApplication(
        read_projection=read_projection,
        authority_projection=authority_projection,
    )


def test_phase1_project_list_cli_reads_seeded_project(
    session: Session,
    capsys,
) -> None:  # noqa: ANN001
    """Verify CLI can read a seeded project through the facade."""
    product = Product(name="Phase 1 Project")
    session.add(product)
    session.commit()

    rc = main(["project", "list"], application=_app_for_engine(session.get_bind()))
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["data"]["count"] == 1
    assert payload["data"]["items"][0]["name"] == "Phase 1 Project"


def test_phase1_context_pack_returns_installed_next_commands(
    session: Session,
    capsys,
) -> None:  # noqa: ANN001
    """Verify context pack distinguishes installed and future commands."""
    product = Product(name="Pack Project")
    session.add(product)
    session.commit()
    session.refresh(product)
    project_id = require_id(product.product_id, "product_id")

    rc = main(
        ["context", "pack", "--project-id", str(project_id), "--phase", "sprint-planning"],
        application=_app_for_engine(session.get_bind()),
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert f"tcc sprint candidates --project-id {project_id}" in payload["data"]["next_valid_commands"]
    assert payload["data"]["blocked_future_commands"] == [
        f"tcc sprint generate --project-id {project_id} --selected-story-ids 1,2,3"
    ]
```

- [ ] **Step 2: Run integration tests**

Run: `uv run --frozen pytest tests/test_agent_workbench_phase1_integration.py -q`

Expected: PASS.

- [ ] **Step 3: Run all agent workbench tests**

Run: `uv run --frozen pytest tests/test_agent_workbench_*.py -q`

Expected: PASS.

- [ ] **Step 4: Run relevant existing regression tests**

Run:

```bash
uv run --frozen pytest \
  tests/test_runtime_config.py \
  tests/test_orchestrator_query_service.py \
  tests/test_orchestrator_tools.py \
  tests/test_specs_compiler_service.py \
  tests/test_select_project_hydration.py \
  tests/test_task_execution_service.py \
  -q
```

Expected: PASS.

- [ ] **Step 5: Inspect git status**

Run: `git status --short`

Expected: only files from this plan are modified or added.

- [ ] **Step 6: Commit**

```bash
git add tests/test_agent_workbench_phase1_integration.py
git commit -m "test: cover agent workbench phase 1"
```

---

## Implementation Notes

- If ruff flags long lines in planned code, wrap the line without changing behavior.
- If type checking rejects protocol use in `AgentWorkbenchApplication`, replace the protocol annotations with `Any` in that facade only; do not add broad casts elsewhere.
- If `uv run --frozen tcc --help` fails because the lockfile lacks editable script metadata, run the equivalent `uv run --frozen python -m cli.main --help` and then inspect whether the package script is available after normal project installation. Do not modify `uv.lock` unless the package manager requires it.
- Do not add LLM-backed commands in this plan.
- Do not add write commands in this plan.
- Do not call `ensure_business_db_ready()` from CLI read paths.

## Self-Review Checklist

- Spec coverage: Phase 1 commands, projection matrix, schema readiness, canonical hashing, read-only boundary, context pack command filtering, and task status normalization are all covered.
- Specificity: planned steps include concrete commands, code blocks, and expected output.
- Type consistency: `AgentWorkbenchApplication`, `ReadProjectionService`, `AuthorityProjectionService`, `ContextPackService`, `WorkbenchError`, and `WorkbenchWarning` names are defined before use.
