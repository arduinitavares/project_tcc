# CLI Project Create Phase 2B Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `agileforge project create` and `agileforge project setup retry` so agents can create AgileForge projects from any caller repository through the central CLI shim.

**Architecture:** Keep `cli/main.py` as a thin transport, route mutations through `AgentWorkbenchApplication`, and put project setup orchestration in a focused agent-workbench service. Reuse the Phase 2A mutation ledger for idempotency, progress fencing, and recovery, but do not reuse the existing dashboard `link_spec_to_product` setup path because it auto-accepts authority and auto-runs vision.

**Tech Stack:** Python 3.13, argparse, Pydantic, SQLModel/SQLite, ADK `DatabaseSessionService`, existing AgileForge `services.specs` compiler services, existing Phase 2A CLI envelope and mutation ledger.

---

## Scope

Implement in one branch:

- `agileforge project create --name "Project" --spec-file specs/app.md --idempotency-key create-project-001`
- `agileforge project create --name "Project" --spec-file specs/app.md --dry-run --dry-run-id preview-project-001`
- `agileforge project setup retry --project-id 1 --spec-file specs/app.md --expected-state SETUP_REQUIRED --expected-context-fingerprint abc123 --idempotency-key retry-project-001`
- `agileforge project setup retry --project-id 1 --spec-file specs/app.md --expected-state SETUP_REQUIRED --expected-context-fingerprint abc123 --recovery-mutation-event-id 42 --idempotency-key retry-project-001`
- CLI logging initialization for agent-visible operational logs in `logs/app.log` and `logs/error.log`
- command metadata, command schema, capabilities, help text, and tests
- caller-cwd-safe spec path resolution
- pending compiled authority artifact with no `SpecAuthorityAcceptance`
- no auto-run vision
- mutation ledger replay, stale-pending recovery signaling, and durable progress fields for the declared side-effect boundaries

Explicitly out of scope for this branch:

- `authority accept`
- vision/backlog/roadmap generate/save commands
- project delete
- workflow reset
- browser/dashboard changes
- MCP interface

---

## Critical Design Decisions

1. **Do not call `services.specs.lifecycle_service.link_spec_to_product` from the CLI project-create path.**
   That path delegates to `update_spec_and_compile_authority`, which auto-accepts authority by writing `SpecAuthorityAcceptance`. CLI project creation must compile a reviewable authority artifact but leave it unaccepted.

2. **Use an approved spec version only as a compiler prerequisite.**
   The compiler requires approved `SpecRegistry` rows. Phase 2B must mark the compiler input spec row as `approved` with `approved_by="cli-project-create"` and `approval_notes="Required compiler precondition for pending authority generation"`, but it must not create a `SpecAuthorityAcceptance` row.

3. **Keep workflow state blocked after project creation.**
   `project create` must initialize a session and record setup metadata, but leave `fsm_state="SETUP_REQUIRED"` and `setup_status="authority_pending_review"`. The response must point agents to `agileforge authority status --project-id <id>` and to the future `authority accept` command.

4. **Dry-run does not consume idempotency keys.**
   `--dry-run` validates input and returns a preview envelope without creating mutation ledger rows or domain rows. The parser must reject `--dry-run` combined with `--idempotency-key`; dry-run requests may pass `--dry-run-id` for traceability, but that ID is not part of the mutation ledger.

5. **Request hash normalization is stable.**
   The non-dry-run `project create` request hash includes command name, normalized project name, resolved absolute spec path, SHA-256 spec content hash, and `changed_by`. The non-dry-run `project setup retry` request hash also includes `project_id`, `expected_state`, `expected_context_fingerprint`, and `recovery_mutation_event_id` when present. Both exclude `correlation_id`, lease owner, timestamps, current working directory string, dry-run fields, and envelope metadata. Idempotency replay must be checked before duplicate-name validation so a replayed `project create` does not fail against the row it already created.

6. **Setup retry requires stale-state guards.**
   `project setup retry` must require `--expected-state` and `--expected-context-fingerprint`. `expected_state` comes from `agileforge workflow state --project-id <id>`. `expected_context_fingerprint` comes from `data.guard_tokens.expected_context_fingerprint` in `agileforge context pack --project-id <id> --phase overview`. The runner must re-read both immediately before mutation and fail with `STALE_STATE` or `STALE_CONTEXT_FINGERPRINT` when they differ.

7. **Setup retry is recovery-linked when repairing project create.**
   `project setup retry` must accept optional `--recovery-mutation-event-id`. When provided, retry must load that original `project create` ledger row, verify it is `recovery_required`, verify it belongs to the same `project_id`, acquire a recovery lease on the original row, and finish by marking the original row `superseded` with `superseded_by_mutation_event_id=<retry_event_id>` and a replayable response. Replaying the original `project create` idempotency key after retry must not return `MUTATION_RECOVERY_REQUIRED`; it must return the stored superseded response pointing to the successful retry. When no recovery id is provided and an unresolved `project create` recovery row exists for the same project, setup retry must fail with structured remediation to pass that recovery id. Do not mention a generic recovery command for project setup until a domain-aware project setup resume executor exists.

8. **Retry dry-run is read-only, including recovery linkage.**
   `project setup retry --dry-run` must create no retry ledger row, acquire no recovery lease, update no original ledger fields, and perform no domain writes. With `--recovery-mutation-event-id`, dry-run may validate that the referenced row exists, is `recovery_required`, and belongs to the requested project, but the test must serialize `_row_payload(original_row)` before and after dry-run and assert equality.

9. **Project setup side effects are individually fenced.**
   Pending authority and workflow setup work are not opaque side effects. The runner and services must fence these concrete boundaries: `product_spec_linked`, `spec_registry_written`, `spec_marked_approved`, `compiled_authority_persisted`, `product_authority_cache_persisted`, `workflow_session_created`, and `workflow_session_status_written`. A lease guard must run immediately before every durable write, including authority persistence inside the engine-aware compiler wrapper.

10. **Pending authority must be incapable of leaving accepted authority behind.**
    If an injected or future compiler seam creates a `SpecAuthorityAcceptance` for the pending spec, the pending-authority service must remove or roll back that matching row before returning failure. Tests must assert no matching acceptance row remains after the bad compiler failure path.

11. **Workflow session setup is an idempotent reconciler, not one opaque write.**
    `WorkflowService.initialize_session` calls ADK `create_session`, so the runner must not call it blindly on retry. Workflow setup must go through `ensure_setup_state(project_id, resolved_spec_path)`: read current session state first, create only when the session is absent, then merge required setup fields. Internally it must treat `workflow_session_created` and `workflow_session_status_written` as recoverable substeps before marking `workflow_session_initialized`.

12. **Linked retry state transfer is one ledger transaction.**
    A linked retry must never finalize its retry row and supersede the original row through separate repository calls. Successful linked retry and post-side-effect retry failure must each use a dedicated two-row ledger helper that updates the retry row and original row in one SQL transaction with compare-and-set predicates. If either row predicate fails, roll back both updates and return `MUTATION_RESUME_CONFLICT`.

---

## File Map

- Modify `cli/main.py`
  - configure CLI logging at startup
  - update stale help description
  - add `project create` and `project setup retry` parsers
  - route parsed args to application facade

- Modify `services/agent_workbench/application.py`
  - add `project_create`
  - add `project_setup_retry`
  - lazy-construct the project setup mutation runner
  - update `MUTATION_LEDGER_REQUIREMENTS` for Phase 2B recovery-linkage columns

- Modify `services/agent_workbench/version.py`
  - bump `STORAGE_SCHEMA_VERSION` for the Phase 2B ledger schema

- Create `services/agent_workbench/project_setup.py`
  - Pydantic request models
  - caller-cwd path resolution
  - request hash computation
  - dry-run preview payloads
  - duplicate project-name checks
  - setup retry stale-state and context-fingerprint guard checks
  - project-create and setup-retry runner
  - mutation ledger orchestration
  - idempotent workflow setup reconciler that repairs partial session setup

- Create `services/specs/pending_authority_service.py`
  - engine/session-aware pending authority boundary
  - lease-guarded write boundaries for product spec link, spec registry write, and spec approval
  - progress-recorder callback for each committed pending-authority substep
  - validate/read spec file
  - create/update `Product` spec link in the caller-owned `Session`
  - create or reuse matching `SpecRegistry` in the caller-owned `Session`
  - approve spec for compiler precondition in the caller-owned `Session`
  - call an injected compiler callable that uses the same business DB target
  - assert no acceptance row is created

- Modify `services/specs/compiler_service.py`
  - add an engine-aware compiler wrapper used by the CLI pending-authority path
  - accept a lease guard callback and call it immediately before authority persistence and product cache persistence
  - accept a progress-recorder callback for authority persistence and product cache persistence
  - preserve the existing compiler APIs for dashboard and legacy callers

- Modify `services/agent_workbench/mutation_ledger.py`
  - add session-scoped helper methods needed to update product/spec business rows and ledger progress in one business DB transaction
  - add `MutationStatus.SUPERSEDED` as a terminal replayable status
  - add `set_project_id_in_session` after product creation
  - add `mark_step_complete_in_session` for product-row atomicity
  - add `set_project_id` as a public wrapper when a separate transaction is acceptable
  - keep `supersede_recovered_event` only as a legacy/single-row helper; linked retry paths must not call it
  - add atomic two-row linked retry finalization helpers
  - keep existing fake mutation behavior intact

- Modify `models/agent_workbench.py`
  - add nullable indexed `recovers_mutation_event_id`
  - add nullable indexed `superseded_by_mutation_event_id`

- Modify `db/migrations.py`
  - add both Phase 2B ledger columns to new-table SQL
  - add idempotent migration for existing `cli_mutation_ledger` tables
  - add indexes for both recovery-linkage columns

- Modify `services/agent_workbench/diagnostics.py`
  - make `schema check` report missing required ledger columns, not only missing tables

- Modify `services/agent_workbench/command_registry.py`
  - register `agileforge project create`
  - register `agileforge project setup retry`

- Modify `services/agent_workbench/error_codes.py`
  - add stable error codes for project-create-specific failures

- Modify `services/agent_workbench/command_schema.py`
  - keep schema generation registry-driven
  - update tests for dry-run optional input, setup retry guard policy, and new error codes

- Tests:
  - Create `tests/test_agent_workbench_project_setup.py`
  - Extend `tests/test_agent_workbench_cli.py`
  - Extend `tests/test_agent_workbench_command_schema.py`
  - Extend `tests/test_agent_workbench_contract_import_boundary.py`
  - Extend `tests/test_agent_workbench_schema_readiness.py`
  - Extend `tests/test_agent_workbench_diagnostics.py`
  - Extend `tests/test_db_migrations.py`
  - Add/extend specs service tests for pending authority

---

## Task 0: Branch And Baseline

**Files:** none

- [ ] **Step 1: Create the branch**

```bash
git checkout master
git pull --ff-only origin master
git checkout -b dev/cli-project-create-phase-2b
```

Expected: branch `dev/cli-project-create-phase-2b` exists and tracks no remote yet.

- [ ] **Step 2: Confirm current CLI surface**

```bash
agileforge project --help
agileforge capabilities | python -m json.tool
```

Expected: `project` has only `list` and `show`; capabilities includes Phase 2A commands.

- [ ] **Step 3: Run baseline tests**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py tests/test_agent_workbench_command_schema.py tests/test_agent_workbench_fake_mutation.py tests/test_agent_workbench_mutation_ledger.py -q
```

Expected: all selected tests pass before implementation.

- [ ] **Step 4: Use the risk-first checkpoint order**

Execute Task 2 before Task 1. The first meaningful implementation checkpoint must prove the pending-authority path cannot create `SpecAuthorityAcceptance` and cannot write through the wrong business DB engine. Execute Task 3 before Task 4 because recovery linkage changes the storage contract. Task 1 is safe cleanup and can follow those checkpoints.

---

## Task 1: CLI Logging And Help Text

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_agent_workbench_cli.py`

- [ ] **Step 1: Write failing tests**

Add tests that assert:

```python
def test_top_level_help_no_longer_claims_read_only(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["--help"], application=_FakeApplication())
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "read-only" not in output
    assert "agent-facing CLI" in output


def test_cli_configures_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_configure_logging(**kwargs: object) -> None:
        calls.append(dict(kwargs))

    monkeypatch.setattr("cli.main.configure_logging", fake_configure_logging)

    exit_code = main(["project", "list"], application=_FakeApplication())

    assert exit_code == 0
    assert calls == [{"console": False}]
```

- [ ] **Step 2: Run tests and verify failure**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py::test_top_level_help_no_longer_claims_read_only tests/test_agent_workbench_cli.py::test_cli_configures_logging -q
```

Expected: both tests fail because help text still says read-only and `cli/main.py` does not import/call `configure_logging`.

- [ ] **Step 3: Implement minimal CLI logging setup**

In `cli/main.py`, import logging setup:

```python
from utils.logging_config import configure_logging
```

Change:

```python
HELP_DESCRIPTION: str = (
    "AgileForge agent-facing CLI for read-only agile workflow context."
)
```

to:

```python
HELP_DESCRIPTION: str = (
    "AgileForge agent-facing CLI for workflow inspection and guarded mutations."
)
```

At the start of `main`, before building the parser:

```python
configure_logging(console=False)
```

- [ ] **Step 4: Verify tests pass**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py::test_top_level_help_no_longer_claims_read_only tests/test_agent_workbench_cli.py::test_cli_configures_logging -q
```

Expected: both tests pass.

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_agent_workbench_cli.py
git commit -m "fix: initialize logging for agent CLI"
```

---

## Task 2: Pending Authority Service

**Files:**
- Modify: `services/specs/compiler_service.py`
- Create: `services/specs/pending_authority_service.py`
- Test: `tests/test_pending_authority_service.py`

- [ ] **Step 1: Write failing tests for the engine-aware compiler seam**

Add tests proving an explicit engine can be used by the pending-authority path:

```python
def test_compile_spec_authority_for_version_with_engine_uses_supplied_engine(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema_current(engine)
    other_engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    ensure_schema_current(other_engine)
    monkeypatch.setattr(
        "services.specs.compiler_service.get_engine",
        lambda: other_engine,
    )

    with Session(engine) as session:
        product = Product(name="Engine Bound Project")
        session.add(product)
        session.commit()
        session.refresh(product)
        spec = SpecRegistry(
            product_id=product.product_id,
            spec_hash="hash",
            content="# Spec",
            content_ref="memory",
            status="approved",
            approved_by="test",
            approved_at=datetime.now(UTC),
        )
        session.add(spec)
        session.commit()
        session.refresh(spec)

    monkeypatch.setattr(
        "services.specs.compiler_service._invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    result = compile_spec_authority_for_version_with_engine(
        engine=engine,
        spec_version_id=spec.spec_version_id,
        force_recompile=False,
    )

    assert result["success"] is True
    with Session(other_engine) as session:
        assert session.exec(select(CompiledSpecAuthority)).all() == []
```

Also add:

```python
def test_compile_spec_authority_for_version_with_engine_runs_lease_guard_before_persist(
    engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema_current(engine)
    # Create approved spec in supplied engine as above.
    guard_calls: list[str] = []

    monkeypatch.setattr(
        "services.specs.compiler_service._invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    result = compile_spec_authority_for_version_with_engine(
        engine=engine,
        spec_version_id=spec_version_id,
        force_recompile=False,
        lease_guard=lambda boundary: guard_calls.append(boundary) or True,
        record_progress=lambda boundary: guard_calls.append(f"progress:{boundary}") or True,
    )

    assert result["success"] is True
    assert "compiled_authority_persisted" in guard_calls
    assert "product_authority_cache_persisted" in guard_calls
    assert "progress:compiled_authority_persisted" in guard_calls
    assert "progress:product_authority_cache_persisted" in guard_calls
```

- [ ] **Step 2: Implement engine-aware compiler wrapper**

Add to `services/specs/compiler_service.py`:

```python
def compile_spec_authority_for_version_with_engine(
    *,
    engine: Engine,
    spec_version_id: int,
    force_recompile: bool | None = None,
    tool_context: ToolContext | None = None,
    lease_guard: Callable[[str], bool] | None = None,
    record_progress: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Compile an approved spec version using the supplied business DB engine."""
```

This wrapper must use extracted helper functions shared with `compile_spec_authority_for_version`; do not copy the full compile flow. All `Session(...)` calls in this wrapper must use the supplied `engine`. Do not change the existing public `compile_spec_authority_for_version` behavior. The wrapper must call `lease_guard("compiled_authority_persisted")` immediately before inserting/updating `CompiledSpecAuthority`, and `lease_guard("product_authority_cache_persisted")` immediately before updating `Product.compiled_authority_json`. After each guarded write commits, call `record_progress(boundary)` when a recorder is provided. If the recorder returns false or raises, stop immediately and return `{"success": False, "error": "MUTATION_PROGRESS_RECORD_FAILED", "error_code": "MUTATION_RECOVERY_REQUIRED"}` so the active mutation can be marked `recovery_required`. If a guard returns false, return `{"success": False, "error": "MUTATION_LEASE_LOST", "error_code": "MUTATION_IN_PROGRESS"}` without writing the guarded row.

- [ ] **Step 3: Write failing tests for pending authority compilation**

Create `tests/test_pending_authority_service.py` with tests that prove:

```python
def test_compile_pending_authority_creates_compiled_artifact_without_acceptance(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    product = Product(name="CLI Pending Authority")
    session.add(product)
    session.commit()
    session.refresh(product)

    spec_path = tmp_path / "app.md"
    spec_path.write_text("# Product Spec\n\nBuild the app.", encoding="utf-8")

    def fake_compile_spec_authority_for_version(
        *,
        spec_version_id: int,
        force_recompile: bool | None = None,
        tool_context: object | None = None,
        lease_guard: Callable[[str], bool] | None = None,
        record_progress: Callable[[str], bool] | None = None,
    ) -> dict[str, object]:
        del force_recompile, tool_context
        if lease_guard is not None and not lease_guard("compiled_authority_persisted"):
            return {"success": False, "error_code": "MUTATION_IN_PROGRESS"}
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="test",
            prompt_hash="prompt:test",
            compiled_artifact_json='{"scope_themes":[],"invariants":[],"gaps":[]}',
            scope_themes="[]",
            invariants="[]",
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)
        if record_progress is not None and not record_progress("compiled_authority_persisted"):
            return {"success": False, "error_code": "MUTATION_RECOVERY_REQUIRED"}
        return {
            "success": True,
            "authority_id": authority.authority_id,
            "spec_version_id": spec_version_id,
            "compiler_version": "test",
            "prompt_hash": "prompt:test",
        }

    result = compile_pending_authority_for_project(
        session=session,
        product_id=product.product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=fake_compile_spec_authority_for_version,
        lease_guard=lambda boundary: True,
        record_progress=lambda boundary: True,
    )

    assert result.ok is True
    assert result.spec_version_id is not None
    assert result.authority_id is not None

    session.expire_all()
    stored_product = session.get(Product, product.product_id)
    assert stored_product is not None
    assert stored_product.spec_file_path == str(spec_path.resolve())
    assert stored_product.spec_loaded_at is not None

    specs = session.exec(select(SpecRegistry)).all()
    assert len(specs) == 1
    assert specs[0].status == "approved"
    assert specs[0].approved_by == "cli-project-create"

    acceptances = session.exec(select(SpecAuthorityAcceptance)).all()
    assert acceptances == []
```

Also add tests for:

- missing spec file returns `ok=False` and `error_code="SPEC_FILE_NOT_FOUND"`
- non-UTF-8 file returns `ok=False` and `error_code="SPEC_FILE_INVALID"`
- compiler failure returns `ok=False` and `error_code="SPEC_COMPILE_FAILED"` with `spec_version_id`
- an injected compiler that writes `SpecAuthorityAcceptance` causes `ok=False` and `error_code="MUTATION_FAILED"`, then a fresh `Session` query proves zero matching acceptance rows remain for that `product_id` and `spec_version_id`
- a lease guard returning false before `product_spec_linked`, `spec_registry_written`, or `spec_marked_approved` prevents that durable write and returns `error_code="MUTATION_IN_PROGRESS"`
- `record_progress` returning false or raising after a durable write returns `error_code="MUTATION_RECOVERY_REQUIRED"` with the boundary name so the runner can mark the active mutation for recovery

- [ ] **Step 4: Run tests and verify failure**

```bash
uv run --frozen python -m pytest tests/test_pending_authority_service.py -q
```

Expected: import failure because the service does not exist.

- [ ] **Step 5: Implement `pending_authority_service.py`**

The service must expose exactly this public API:

```python
class PendingAuthorityCompiler(Protocol):
    def __call__(
        self,
        *,
        spec_version_id: int,
        force_recompile: bool | None = None,
        tool_context: object | None = None,
        lease_guard: Callable[[str], bool] | None = None,
        record_progress: Callable[[str], bool] | None = None,
    ) -> dict[str, object]:
        raise NotImplementedError


@dataclass(frozen=True)
class PendingAuthorityResult:
    ok: bool
    product_id: int
    spec_path: str
    error_code: str | None = None
    spec_hash: str | None = None
    spec_version_id: int | None = None
    authority_id: int | None = None
    compiler_version: str | None = None
    prompt_hash: str | None = None
    error: str | None = None


def compile_pending_authority_for_project(
    *,
    session: Session,
    product_id: int,
    spec_path: Path,
    approved_by: str,
    compile_authority: PendingAuthorityCompiler,
    lease_guard: Callable[[str], bool],
    record_progress: Callable[[str], bool],
) -> PendingAuthorityResult:
    """Compile a reviewable authority artifact without accepting it."""
```

Implementation rules:

- Resolve `spec_path` before persistence.
- Reject missing paths and non-UTF-8 files.
- Enforce the same 100 KB size limit used by lifecycle service.
- Read content and SHA-256 hash.
- In the caller-owned business DB `Session`:
  - call `lease_guard("product_spec_linked")` immediately before committing product spec-link fields
  - load `Product`
  - set `product.spec_file_path = str(spec_path.resolve())`
  - set `product.spec_loaded_at`
  - commit and call `record_progress("product_spec_linked")`; if it returns false or raises, stop and let the runner mark the mutation `recovery_required`
  - call `lease_guard("spec_registry_written")` immediately before inserting or updating `SpecRegistry`
  - create a new `SpecRegistry` row when the latest row has a different hash
  - reuse the latest matching spec row when the hash matches
  - commit and call `record_progress("spec_registry_written")`; if it returns false or raises, stop and let the runner mark the mutation `recovery_required`
  - call `lease_guard("spec_marked_approved")` immediately before committing approval metadata
  - set `SpecRegistry.status = "approved"` for compiler compatibility
  - set `approved_by` to the caller-provided value
  - commit and call `record_progress("spec_marked_approved")`; if it returns false or raises, stop and let the runner mark the mutation `recovery_required`
- Commit the caller-owned `Session` before invoking the compiler so the compiler can read the spec row.
- Call the injected `compile_authority` with the resolved `spec_version_id`, `force_recompile=False`, the same `lease_guard`, and the same `record_progress`.
- Expire or refresh the caller-owned `Session`, then query `SpecAuthorityAcceptance` where both `product_id` and `spec_version_id` match the pending compile. If any matching accepted row was created for this spec, rollback when the acceptance row is still in the active transaction. If a deliberately injected bad-seam test committed the row outside that transaction, delete only the matching `product_id/spec_version_id` row, commit that cleanup, and return `ok=False` with error `"Pending authority path must not accept authority."`. A fresh session query must prove no matching acceptance row remains.

- [ ] **Step 6: Verify pending authority tests pass**

```bash
uv run --frozen python -m pytest tests/test_pending_authority_service.py tests/test_specs_compiler_service.py -q
```

Expected: all pending authority service tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/specs/compiler_service.py services/specs/pending_authority_service.py tests/test_pending_authority_service.py tests/test_specs_compiler_service.py
git commit -m "feat: add pending authority setup service"
```

---

## Task 3: Ledger Schema Migration For Recovery Linkage

**Files:**
- Modify: `models/agent_workbench.py`
- Modify: `db/migrations.py`
- Modify: `services/agent_workbench/mutation_ledger.py`
- Modify: `services/agent_workbench/application.py`
- Modify: `services/agent_workbench/diagnostics.py`
- Modify: `services/agent_workbench/version.py`
- Test: `tests/test_db_migrations.py`
- Test: `tests/test_agent_workbench_application.py`
- Test: `tests/test_agent_workbench_diagnostics.py`

- [ ] **Step 1: Write failing migration tests for pre-Phase-2B ledger tables**

Create a raw SQLite engine that has not run `SQLModel.metadata.create_all()` with an old `cli_mutation_ledger` table that has all current Phase 2A columns except the new recovery-linkage fields. Do not use the repository `engine` fixture for this test unless it first drops and recreates `cli_mutation_ledger`; the fixture already creates current tables. Run `ensure_schema_current(engine)` and assert both new columns and indexes exist:

```python
def test_migration_adds_project_setup_recovery_linkage_columns(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'pre-phase-2b.sqlite3').as_posix()}")
    with engine.begin() as conn:
        conn.execute(text(CLI_MUTATION_LEDGER_CREATE_SQL_PHASE_2A))

    ensure_schema_current(engine)

    columns = {column["name"] for column in inspect(engine).get_columns("cli_mutation_ledger")}
    assert "recovers_mutation_event_id" in columns
    assert "superseded_by_mutation_event_id" in columns

    indexes = {index["name"] for index in inspect(engine).get_indexes("cli_mutation_ledger")}
    assert "ix_cli_mutation_ledger_recovers_mutation_event_id" in indexes
    assert "ix_cli_mutation_ledger_superseded_by_mutation_event_id" in indexes
```

Also assert a freshly created database gets the same columns from `CLI_MUTATION_LEDGER_CREATE_SQL`.

- [ ] **Step 2: Write failing readiness and diagnostics tests**

Add a test that creates the old ledger table, then calls `_mutation_ledger_repository()` and expects `SCHEMA_NOT_READY` with missing columns:

```python
assert envelope["errors"][0]["details"]["missing"] == {
    "cli_mutation_ledger": [
        "recovers_mutation_event_id",
        "superseded_by_mutation_event_id",
    ]
}
```

Add a `schema_check_payload` test that expects `business_db["checks"]` to expose:

```python
{
    "schema_versions_table": True,
    "cli_mutation_ledger_table": True,
    "cli_mutation_ledger_columns": False,
}
```

and `business_db["missing"]` to include `cli_mutation_ledger.recovers_mutation_event_id` and `cli_mutation_ledger.superseded_by_mutation_event_id`.

Also assert `business_db["required_version"] == "2"` after the version bump and that `agent_workbench_schema_versions` stores version `"2"` after migration.

- [ ] **Step 3: Add model fields and migration SQL**

In `models/agent_workbench.py`, add:

```python
recovers_mutation_event_id: int | None = Field(default=None, index=True)
superseded_by_mutation_event_id: int | None = Field(default=None, index=True)
```

In `db/migrations.py`, update `CLI_MUTATION_LEDGER_CREATE_SQL` with:

```sql
recovers_mutation_event_id INTEGER,
superseded_by_mutation_event_id INTEGER,
```

In `migrate_agent_workbench_contract_tables`, add idempotent existing-table migration:

```python
if _ensure_column_exists(
    engine,
    "cli_mutation_ledger",
    "recovers_mutation_event_id",
    "INTEGER",
):
    actions.append("added column: cli_mutation_ledger.recovers_mutation_event_id")

if _ensure_column_exists(
    engine,
    "cli_mutation_ledger",
    "superseded_by_mutation_event_id",
    "INTEGER",
):
    actions.append("added column: cli_mutation_ledger.superseded_by_mutation_event_id")
```

Extend the ledger index map with:

```python
"ix_cli_mutation_ledger_recovers_mutation_event_id": ["recovers_mutation_event_id"],
"ix_cli_mutation_ledger_superseded_by_mutation_event_id": ["superseded_by_mutation_event_id"],
```

Bump `AGENT_WORKBENCH_STORAGE_SCHEMA_VERSION` from `"1"` to `"2"` so migrated stores record the Phase 2B storage contract.

- [ ] **Step 4: Update readiness requirements and diagnostics**

In `services/agent_workbench/application.py`, add both new columns to `MUTATION_LEDGER_REQUIREMENTS`.

In `services/agent_workbench/version.py`, bump `STORAGE_SCHEMA_VERSION` from `"1"` to `"2"` so `schema check` reports the same required version that migrations write.

In `services/agent_workbench/diagnostics.py`, inspect `cli_mutation_ledger` columns when the table exists. `schema_check_payload` must report blocked when required columns are missing, not just when the table is missing.

- [ ] **Step 5: Define superseded status visibility**

In `services/agent_workbench/mutation_ledger.py`, `SUPERSEDED` is a terminal status for retention, `mutation list`, and `mutation show`. `mutation show` for a superseded original row must include:

```python
{
    "status": "superseded",
    "superseded_by_mutation_event_id": retry_event_id,
    "response": {
        "project_id": project_id,
        "mutation_event_id": original_event_id,
        "recovered_by_mutation_event_id": retry_event_id,
        "setup_status": "authority_pending_review",
    },
}
```

Idempotency replay for the original `project create` row must return a project-create-shaped response and include `recovered_by_mutation_event_id`.

- [ ] **Step 6: Verify schema tests pass**

```bash
uv run --frozen python -m pytest \
  tests/test_db_migrations.py \
  tests/test_agent_workbench_application.py::test_mutation_ledger_repository_reports_missing_recovery_linkage_columns \
  tests/test_agent_workbench_diagnostics.py::test_schema_check_reports_missing_mutation_ledger_columns \
  -q
```

Expected: schema migration, readiness, and diagnostics tests pass.

- [ ] **Step 7: Commit**

```bash
git add models/agent_workbench.py db/migrations.py services/agent_workbench/mutation_ledger.py services/agent_workbench/application.py services/agent_workbench/diagnostics.py services/agent_workbench/version.py tests/test_db_migrations.py tests/test_agent_workbench_application.py tests/test_agent_workbench_diagnostics.py
git commit -m "feat: add project setup recovery ledger schema"
```

---

## Task 4: Project Setup Mutation Runner

**Files:**
- Create: `services/agent_workbench/project_setup.py`
- Modify: `services/agent_workbench/mutation_ledger.py`
- Test: `tests/test_agent_workbench_project_setup.py`

- [ ] **Step 1: Write failing tests for dry-run and path resolution**

Create tests that assert:

```python
def test_project_create_dry_run_resolves_spec_from_caller_cwd_without_writes(
    engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ensure_schema_current(engine)
    caller = tmp_path / "caller"
    caller.mkdir()
    spec_file = caller / "specs" / "app.md"
    spec_file.parent.mkdir()
    spec_file.write_text("# App Spec\n", encoding="utf-8")

    monkeypatch.chdir(caller)
    runner = ProjectSetupMutationRunner(engine=engine)

    result = runner.create_project(
        ProjectCreateRequest(
            name="CLI Project",
            spec_file="specs/app.md",
            dry_run=True,
            dry_run_id="dry-run-project-001",
            changed_by="agent",
        )
    )

    assert result["ok"] is True
    assert result["data"]["preview_available"] is True
    assert result["data"]["resolved_spec_path"] == str(spec_file.resolve())

    with Session(engine) as session:
        assert session.exec(select(Product)).all() == []
        assert session.exec(select(CliMutationLedger)).all() == []
```

- [ ] **Step 2: Write failing tests that dry-run rejects idempotency keys**

Add:

```python
def test_project_create_dry_run_rejects_idempotency_key() -> None:
    with pytest.raises(ValidationError, match="idempotency_key is not allowed with dry_run"):
        ProjectCreateRequest(
            name="CLI Project",
            spec_file="specs/app.md",
            dry_run=True,
            dry_run_id="preview-001",
            idempotency_key="create-project-001",
        )
```

- [ ] **Step 3: Write failing tests for successful create**

Test that non-dry-run:

- creates one `Product`
- creates one `SpecRegistry`
- creates one `CompiledSpecAuthority`
- creates zero `SpecAuthorityAcceptance`
- creates or updates workflow session state
- finalizes the mutation ledger as `succeeded`
- returns structured `next_actions` containing command `agileforge authority status` and args `{"project_id": <id>}`

- [ ] **Step 4: Write failing tests for duplicate names, replay, key reuse, and recovery**

Test that:

- creating a project with an existing `Product.name` and a new idempotency key returns `PROJECT_ALREADY_EXISTS` before insert
- same idempotency key and same normalized request returns the original response without duplicate rows
- same idempotency key and different project name or spec hash returns `IDEMPOTENCY_KEY_REUSED`
- a forced crash after `product_created` followed by the same `project create` idempotency key creates no duplicate product and returns deterministic `MUTATION_RECOVERY_REQUIRED` data with `mutation_event_id`, `project_id`, and a `project setup retry` remediation command

- [ ] **Step 5: Write failing setup retry stale-guard tests**

Add tests that:

- `ProjectSetupRetryRequest` requires `expected_state` and `expected_context_fingerprint`
- retry fails with `STALE_STATE` when current workflow state differs from `expected_state`
- retry fails with `STALE_CONTEXT_FINGERPRINT` when the freshly built overview context pack fingerprint differs from `expected_context_fingerprint`
- retry includes both guard fields in its normalized request hash

- [ ] **Step 6: Write failing setup retry recovery-linkage tests**

Add tests that:

- `ProjectSetupRetryRequest` accepts `recovery_mutation_event_id`
- retry with `recovery_mutation_event_id` rejects when the referenced ledger row is not `recovery_required`
- retry with `recovery_mutation_event_id` rejects when the referenced ledger row has a different `project_id`
- successful retry with `recovery_mutation_event_id` marks the original create ledger row as `superseded`, sets `superseded_by_mutation_event_id` to the retry ledger event, and stores a replayable response
- replaying the original `project create` idempotency key after linked retry returns the stored superseded response instead of `MUTATION_RECOVERY_REQUIRED`
- `project setup retry --dry-run` with `recovery_mutation_event_id` creates no retry ledger row, acquires no recovery lease, writes no original ledger fields, and leaves `_row_payload(original_row)` equal before and after the command
- if linked retry fails before any domain side effect, the retry row is `domain_failed_no_side_effects`, the original row remains `recovery_required`, and original replay still returns the original recovery response
- if linked retry fails after any product/spec/session side effect, the retry row is `recovery_required`, the referenced original recovery row is `superseded` with `superseded_by_mutation_event_id=<retry_event_id>`, and original replay points to the retry recovery row
- successful linked retry uses one repository method that atomically marks retry row `succeeded` and original row `superseded`; injected failure between row updates rolls back both rows
- post-side-effect linked retry failure uses one repository method that atomically marks retry row `recovery_required` and original row `superseded`; injected failure between row updates rolls back both rows
- monkeypatch or spy `MutationLedgerRepository.supersede_recovered_event` to raise, then prove linked retry success and post-side-effect linked retry failure still work through `finalize_linked_retry_success` and `transfer_linked_retry_recovery`
- if either two-row compare-and-set predicate fails, the helper returns `MUTATION_RESUME_CONFLICT`, both rows remain unchanged, and neither idempotency replay changes behavior
- after post-side-effect recovery transfer, `mutation list --status recovery_required` includes the retry row and excludes the superseded original row
- replaying the original `project create` idempotency key after post-side-effect recovery transfer returns a response with `recovered_by_mutation_event_id=<retry_event_id>` and `retry_status="recovery_required"`
- replaying the retry idempotency key after pre-side-effect linked retry failure returns the stored retry row response exactly as `data` in the normal CLI envelope; do not recompute the response

- [ ] **Step 7: Write failing workflow session recovery tests**

Use a fake workflow port with explicit `sessions: dict[str, dict[str, Any]]`, `created_sessions: list[str]`, and injectable crash flags. Add tests that cover:

- crash after `workflow_session_created` but before status update: retry must update the existing session and must not call create a second time
- crash after status update but before ledger progress: retry must read the existing session, verify required setup fields, record `workflow_session_status_written`, and finish
- existing session with stale `setup_error`, missing `setup_status`, or stale `setup_spec_file_path`: retry must merge the canonical setup fields instead of replacing unrelated session state
- existing session state with no `workflow_session_created` ledger progress: `ensure_setup_state` must call `record_progress("workflow_session_created")` without calling `initialize_session`
- existing complete setup state with no `workflow_session_status_written` ledger progress: `ensure_setup_state` must call `record_progress("workflow_session_status_written")` without rewriting the session

Expected assertions:

```python
assert fake_workflow.created_sessions == ["7"]
assert fake_workflow.sessions["7"]["setup_status"] == "authority_pending_review"
assert fake_workflow.sessions["7"]["setup_error"] is None
assert fake_workflow.sessions["7"]["setup_spec_file_path"] == str(spec_file.resolve())
assert fake_workflow.sessions["7"]["unrelated_state"] == "preserved"
```

- [ ] **Step 8: Run tests and verify failure**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_project_setup.py -q
```

Expected: import failure because `ProjectSetupMutationRunner` does not exist.

- [ ] **Step 9: Add ledger helpers needed for project create**

In `services/agent_workbench/mutation_ledger.py`, add methods:

```python
def set_project_id(
    self,
    *,
    mutation_event_id: int,
    lease_owner: str,
    project_id: int,
    now: datetime,
) -> bool:
    """Attach the created project id to an active mutation row."""


def set_project_id_in_session(
    session: Session,
    *,
    mutation_event_id: int,
    lease_owner: str,
    project_id: int,
    now: datetime,
) -> bool:
    """Attach the created project id using the caller's transaction."""


def mark_step_complete_in_session(
    session: Session,
    *,
    mutation_event_id: int,
    lease_owner: str,
    step: str,
    next_step: str,
    now: datetime,
) -> bool:
    """Record a completed step using the caller's transaction."""


def acquire_recovery_lease(
    self,
    *,
    mutation_event_id: int,
    expected_project_id: int,
    recovery_lease_owner: str,
    now: datetime,
) -> bool:
    """Acquire ownership of an original recovery_required mutation row."""


def release_recovery_lease(
    self,
    *,
    mutation_event_id: int,
    recovery_lease_owner: str,
    now: datetime,
) -> bool:
    """Clear a retry-owned recovery lease without changing recovery_required status."""


def mark_recovery_required(
    self,
    *,
    mutation_event_id: int,
    lease_owner: str,
    recovery_action: RecoveryAction,
    safe_to_auto_resume: bool,
    last_error: dict[str, Any],
    now: datetime,
) -> bool:
    """Move an owned pending mutation to recovery_required."""


def supersede_recovered_event(
    self,
    *,
    mutation_event_id: int,
    superseded_by_mutation_event_id: int,
    lease_owner: str,
    response: dict[str, Any],
    now: datetime,
) -> bool:
    """Single-row legacy helper; linked retry paths must not call this."""


def finalize_linked_retry_success(
    self,
    *,
    retry_mutation_event_id: int,
    retry_lease_owner: str,
    original_mutation_event_id: int,
    original_recovery_lease_owner: str,
    after: dict[str, Any],
    retry_response: dict[str, Any],
    original_replay_response: dict[str, Any],
    now: datetime,
) -> LedgerLoadResult:
    """Atomically mark retry succeeded and original recovery row superseded."""


def transfer_linked_retry_recovery(
    self,
    *,
    retry_mutation_event_id: int,
    retry_lease_owner: str,
    original_mutation_event_id: int,
    original_recovery_lease_owner: str,
    recovery_action: RecoveryAction,
    safe_to_auto_resume: bool,
    last_error: dict[str, Any],
    retry_response: dict[str, Any],
    original_replay_response: dict[str, Any],
    now: datetime,
) -> LedgerLoadResult:
    """Atomically transfer recovery ownership from original row to retry row."""
```

Boolean helpers must use compare-and-set conditions on `mutation_event_id`, `status`, and `lease_owner`, and they must return `False` when `rowcount != 1`. `acquire_recovery_lease` must compare `status == MutationStatus.RECOVERY_REQUIRED`, `project_id == expected_project_id`, and a stale or empty recovery lease before assigning `lease_owner=recovery_lease_owner`. `release_recovery_lease` must compare `status == MutationStatus.RECOVERY_REQUIRED` and `lease_owner == recovery_lease_owner` before clearing owner and lease timestamps. Use the Phase 2B `MutationStatus.SUPERSEDED`, `superseded_by_mutation_event_id`, and `recovers_mutation_event_id` fields added in Task 3. Update idempotency replay so `succeeded` and `superseded` rows both replay `response_json`.

`finalize_linked_retry_success` must execute both updates in one SQL transaction:

- retry row CAS: `mutation_event_id == retry_mutation_event_id`, `status == pending`, `lease_owner == retry_lease_owner`, and unexpired lease
- original row CAS: `mutation_event_id == original_mutation_event_id`, `status == recovery_required`, and `lease_owner == original_recovery_lease_owner`
- retry row update: `status=succeeded`, store `after_json`, store `retry_response`, clear lease fields, set `recovery_action=none`
- original row update: `status=superseded`, `superseded_by_mutation_event_id=retry_mutation_event_id`, store `original_replay_response`, clear lease fields
- if either update affects anything other than exactly one row, roll back both and return `LedgerLoadResult(..., error_code=MUTATION_RESUME_CONFLICT)`
- returned row contract: on success, `LedgerLoadResult.ledger` is the refreshed retry row and `LedgerLoadResult.response == retry_response`; on conflict, `LedgerLoadResult.ledger` is the unchanged refreshed retry row when it still exists, `response is None`, and `error_code == MUTATION_RESUME_CONFLICT`

`transfer_linked_retry_recovery` must execute both updates in one SQL transaction:

- retry row CAS: `mutation_event_id == retry_mutation_event_id`, `status == pending`, `lease_owner == retry_lease_owner`, and unexpired lease
- original row CAS: `mutation_event_id == original_mutation_event_id`, `status == recovery_required`, and `lease_owner == original_recovery_lease_owner`
- retry row update: `status=recovery_required`, store `recovery_action`, `recovery_safe_to_auto_resume`, `last_error_json`, and `retry_response`, clear lease fields
- original row update: `status=superseded`, `superseded_by_mutation_event_id=retry_mutation_event_id`, store `original_replay_response` pointing at retry recovery, clear lease fields
- if either update affects anything other than exactly one row, roll back both and return `LedgerLoadResult(..., error_code=MUTATION_RESUME_CONFLICT)`
- returned row contract: on success, `LedgerLoadResult.ledger` is the refreshed retry row and `LedgerLoadResult.response == retry_response`; on conflict, `LedgerLoadResult.ledger` is the unchanged refreshed retry row when it still exists, `response is None`, and `error_code == MUTATION_RESUME_CONFLICT`

Add tests with an injected repository test hook, for example `fail_after_retry_update_for_test=True`, that raises after the retry-row update but before the original-row update. The test must assert both rows are unchanged after rollback for both two-row helpers.

The runner must create the `Product` row, assign `project_id` on the ledger, and mark `product_created` in one SQLModel session transaction. If that transaction does not commit, neither the product nor the ledger progress update may be visible.

- [ ] **Step 10: Implement `project_setup.py`**

Create:

```python
class ProjectCreateRequest(BaseModel):
    name: str = Field(min_length=1)
    spec_file: str = Field(min_length=1)
    idempotency_key: str | None = None
    dry_run: bool = False
    dry_run_id: str | None = None
    correlation_id: str | None = None
    changed_by: str = "cli-agent"


class ProjectSetupRetryRequest(BaseModel):
    project_id: int
    spec_file: str = Field(min_length=1)
    expected_state: str
    expected_context_fingerprint: str
    recovery_mutation_event_id: int | None = None
    idempotency_key: str | None = None
    dry_run: bool = False
    dry_run_id: str | None = None
    correlation_id: str | None = None
    changed_by: str = "cli-agent"


class ProjectSetupMutationRunner:
    def __init__(
        self,
        *,
        engine: Engine,
        workflow: ProjectSetupWorkflowPort | None = None,
    ) -> None:
        self._engine = engine
        self._workflow = workflow or SyncProjectSetupWorkflowAdapter(WorkflowService())

    def create_project(self, request: ProjectCreateRequest) -> dict[str, Any]:
        return self._run_create(request)

    def retry_setup(self, request: ProjectSetupRetryRequest) -> dict[str, Any]:
        return self._run_retry(request)
```

Both request models must validate:

- non-dry-run requests require `idempotency_key`
- dry-run requests reject `idempotency_key`
- idempotency keys and dry-run IDs are ASCII, 8-128 characters, and match `[A-Za-z0-9._:-]+`
- `changed_by` defaults to `cli-agent`

Define workflow writes through a port so tests do not need a real ADK session store:

```python
class ProjectSetupWorkflowPort(Protocol):
    def initialize_session(self, session_id: str | None = None) -> str:
        raise NotImplementedError

    def update_session_status(self, session_id: str, partial_update: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_session_status(self, session_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def ensure_setup_state(
        self,
        *,
        project_id: int,
        resolved_spec_path: Path,
        lease_guard: Callable[[str], bool],
        record_progress: Callable[[str], bool],
    ) -> dict[str, Any]:
        raise NotImplementedError
```

`get_session_status(session_id) == {}` is the explicit absent-session contract for this port. If the session exists, the workflow port must return a non-empty state dictionary.

The production adapter must wrap `WorkflowService.initialize_session` without leaking async handling into the runner, and expose idempotent setup reconciliation:

```python
class SyncProjectSetupWorkflowAdapter:
    def __init__(self, workflow: WorkflowService) -> None:
        self._workflow = workflow

    def initialize_session(self, session_id: str | None = None) -> str:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self._workflow.initialize_session(session_id=session_id))
        raise RuntimeError("Project setup runner cannot initialize workflow sessions inside an active event loop")

    def update_session_status(self, session_id: str, partial_update: dict[str, Any]) -> None:
        self._workflow.update_session_status(session_id, partial_update)

    def get_session_status(self, session_id: str) -> dict[str, Any]:
        return self._workflow.get_session_status(session_id)

    def ensure_setup_state(
        self,
        *,
        project_id: int,
        resolved_spec_path: Path,
        lease_guard: Callable[[str], bool],
        record_progress: Callable[[str], bool],
    ) -> dict[str, Any]:
        session_id = str(project_id)
        current = self.get_session_status(session_id)

        if current == {}:
            if not lease_guard("workflow_session_created"):
                return {"ok": False, "error_code": "MUTATION_IN_PROGRESS"}
            self.initialize_session(session_id=session_id)
            current = self.get_session_status(session_id)
        if not record_progress("workflow_session_created"):
            return {"ok": False, "error_code": "MUTATION_RECOVERY_REQUIRED"}

        required_state = {
            "fsm_state": "SETUP_REQUIRED",
            "setup_status": "authority_pending_review",
            "setup_error": None,
            "setup_spec_file_path": str(resolved_spec_path),
        }
        merged = {**current, **required_state}
        if current != merged:
            if not lease_guard("workflow_session_status_written"):
                return {"ok": False, "error_code": "MUTATION_IN_PROGRESS"}
            self.update_session_status(session_id, required_state)
            current = self.get_session_status(session_id)
        if not record_progress("workflow_session_status_written"):
            return {"ok": False, "error_code": "MUTATION_RECOVERY_REQUIRED"}

        return {"ok": True, "session_id": session_id, "state": self.get_session_status(session_id)}
```

Create must perform these declared steps:

1. `product_created`
   - create `Product(name=request.name)`
   - attach `project_id` to ledger
   - mark step complete
   - fail with `PROJECT_ALREADY_EXISTS` before insert when the name already exists

2. `pending_authority_compiled`
   - call `compile_pending_authority_for_project(session=session, product_id=project_id, spec_path=resolved_spec_path, approved_by="cli-project-create", compile_authority=engine_bound_compiler, lease_guard=active_owner_guard, record_progress=mark_boundary_complete)`
   - mark step complete

   Internally this step is split into fenced substeps:

   - `product_spec_linked`
   - `spec_registry_written`
   - `spec_marked_approved`
   - `compiled_authority_persisted`
   - `product_authority_cache_persisted`

   `active_owner_guard` must call `require_active_owner(mutation_event_id=mutation_event_id, lease_owner=lease_owner, boundary=boundary)` and return false without writing when ownership is lost. `mark_boundary_complete` must call `mark_step_complete_in_session` for the same mutation row and boundary after each write commits. Each substep must be appended to durable `completed_steps`; `pending_authority_compiled` can be marked complete only after all five substeps are present or reconciled from durable state.

3. `workflow_session_initialized`
   - call `ProjectSetupWorkflowPort.ensure_setup_state(project_id=project_id, resolved_spec_path=resolved_spec_path, lease_guard=active_owner_guard, record_progress=mark_boundary_complete)`
   - internally reconcile `workflow_session_created`: read current session first, create only when the session state is absent, then record progress
   - internally reconcile `workflow_session_status_written`: merge `fsm_state="SETUP_REQUIRED"`, `setup_status="authority_pending_review"`, `setup_error=None`, and `setup_spec_file_path=<resolved path>` while preserving unrelated session state, then record progress
   - mark step complete

4. `done`
   - finalize success with before/after payload and response

Successful `project create` response data must use this shape:

```python
{
    "project_id": project_id,
    "name": request.name,
    "resolved_spec_path": str(resolved_spec_path),
    "spec_hash": spec_hash,
    "spec_version_id": spec_version_id,
    "authority_id": authority_id,
    "setup_status": "authority_pending_review",
    "fsm_state": "SETUP_REQUIRED",
    "mutation_event_id": mutation_event_id,
    "next_actions": [
        {
            "command": "agileforge authority status",
            "args": {"project_id": project_id},
            "reason": "Review pending compiled authority before acceptance.",
        }
    ],
}
```

Every side-effect boundary must call `require_active_owner(...)` immediately before the write.

Recovery reconciliation rules:

- If ledger progress says `product_created`, reuse the ledger `project_id` instead of creating another product.
- If `project create` fails before `product_created` and before `project_id` exists, mark the ledger `domain_failed_no_side_effects` or `validation_failed` rather than `recovery_required`; `project setup retry` cannot repair a mutation that never created a project id.
- If ledger progress includes `product_spec_linked`, `spec_registry_written`, `spec_marked_approved`, `compiled_authority_persisted`, or `product_authority_cache_persisted`, verify the corresponding durable row/field before skipping or resuming that substep.
- If ledger progress says `pending_authority_compiled`, verify `SpecRegistry` and `CompiledSpecAuthority` exist for the project before moving forward.
- If ledger progress includes `workflow_session_created`, read the existing session and do not call `initialize_session` again.
- If workflow session state exists but lacks `setup_status`, has stale `setup_error`, or has stale/missing `setup_spec_file_path`, merge the canonical setup fields through `ensure_setup_state` and preserve unrelated state.
- If ledger progress includes `workflow_session_status_written`, verify the required setup fields are present before marking `workflow_session_initialized`.
- If compiler failure happens after `Product` or `SpecRegistry` writes, mark the active ledger row `recovery_required` with `recovery_action=RESUME_FROM_STEP`, `safe_to_auto_resume=false`, and `last_error.code="SPEC_COMPILE_FAILED"`. The response must include `mutation_event_id`, `project_id`, `spec_version_id` when known, and remediation to run guarded `project setup retry`.
- If workflow setup fails after business writes, mark the active ledger row `recovery_required` with `recovery_action=RESUME_FROM_STEP`, `safe_to_auto_resume=true`, and `last_error.code="WORKFLOW_SESSION_FAILED"`.

Setup retry recovery-linkage rules:

- If `recovery_mutation_event_id` is provided, retry must acquire a recovery lease on the original ledger row before doing domain writes.
- The original row must be command `agileforge project create`, status `recovery_required`, and `project_id == request.project_id`.
- The retry mutation row must set `recovers_mutation_event_id` to the original event id.
- After retry succeeds, the runner must call `finalize_linked_retry_success`; this single transaction marks retry row `succeeded` and original row `superseded`, with `superseded_by_mutation_event_id` pointing to the retry event and `response_json` containing a replayable successful response.
- If the original `project create` idempotency key is invoked after linked retry succeeds, it must replay the superseded response and not return `MUTATION_RECOVERY_REQUIRED`.
- If `recovery_mutation_event_id` is omitted and an unresolved `project create` ledger row exists with `project_id == request.project_id` and status `recovery_required`, retry must fail before domain writes with `MUTATION_RECOVERY_INVALID` and remediation to pass `--recovery-mutation-event-id <id>`.
- Dry-run retry must not create a retry ledger row, acquire or release a recovery lease, mutate the original ledger row, or write product/spec/session state.
- Non-dry-run retry must validate request shape, expected state, expected context fingerprint, and original-row identity before acquiring the original recovery lease. If validation or stale guards fail before lease acquisition, the retry row is `guard_rejected` or `validation_failed` and the original row is unchanged. If retry domain work fails before any side effect, mark the retry row `domain_failed_no_side_effects`, release the original recovery lease, and leave the original row `recovery_required`. If retry domain work fails after any side effect, the runner must call `transfer_linked_retry_recovery`; this single transaction marks retry row `recovery_required`, marks original row `superseded`, and stores original replay data that points to the retry recovery row. If either two-row helper returns `MUTATION_RESUME_CONFLICT`, return a structured `MUTATION_RESUME_CONFLICT` envelope with retry and original mutation ids, use the exit code from the central registry, and leave both rows unchanged. `mutation list --status recovery_required` must then show the retry row, not both rows.

For linked retry failure before any retry side effect, the retry row response must be replayable and use this shape:

```python
{
    "project_id": request.project_id,
    "mutation_event_id": retry_mutation_event_id,
    "recovery_mutation_event_id": original_mutation_event_id,
    "status": "domain_failed_no_side_effects",
    "side_effects_started": False,
    "original_status": "recovery_required",
    "next_actions": [
        {
            "command": "agileforge project setup retry",
            "args": {
                "project_id": request.project_id,
                "spec_file": request.spec_file,
                "expected_state": request.expected_state,
                "expected_context_fingerprint": request.expected_context_fingerprint,
                "recovery_mutation_event_id": original_mutation_event_id,
            },
            "reason": "Retry setup with a new idempotency key after fixing the reported error.",
        }
    ],
}
```

If `finalize_linked_retry_success` or `transfer_linked_retry_recovery` returns `MUTATION_RESUME_CONFLICT`, the runner must return a structured error envelope using the registry exit code:

```python
workbench_error(
    ErrorCode.MUTATION_RESUME_CONFLICT,
    details={
        "retry_mutation_event_id": retry_mutation_event_id,
        "original_mutation_event_id": original_mutation_event_id,
    },
    remediation=["Re-read mutation state before retrying recovery."],
)
```

Replaying a retry row in `domain_failed_no_side_effects` must return the stored retry row `response_json` as the envelope `data` exactly. The replay path must not rebuild that response from current project or workflow state.

- [ ] **Step 11: Verify runner tests pass**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_project_setup.py -q
```

Expected: all project setup runner tests pass.

- [ ] **Step 12: Commit**

```bash
git add services/agent_workbench/project_setup.py services/agent_workbench/mutation_ledger.py tests/test_agent_workbench_project_setup.py
git commit -m "feat: add CLI project setup mutation runner"
```

---

## Task 5: Application And CLI Routing

**Files:**
- Modify: `services/agent_workbench/application.py`
- Modify: `cli/main.py`
- Test: `tests/test_agent_workbench_cli.py`
- Test: `tests/test_agent_workbench_application.py`

- [ ] **Step 1: Write failing CLI routing tests**

Extend `_FakeApplication` with:

```python
def project_create(
    self,
    *,
    name: str,
    spec_file: str,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    dry_run_id: str | None = None,
    correlation_id: str | None = None,
    changed_by: str = "cli-agent",
) -> JsonObject:
    self.calls.append(
        (
            "project_create",
            {
                "name": name,
                "spec_file": spec_file,
                "idempotency_key": idempotency_key,
                "dry_run": dry_run,
                "dry_run_id": dry_run_id,
                "correlation_id": correlation_id,
                "changed_by": changed_by,
            },
        )
    )
    return {"ok": True, "data": {"project_id": 1}, "warnings": [], "errors": []}
```

Add a test:

```python
def test_cli_routes_project_create_to_application(capsys: pytest.CaptureFixture[str]) -> None:
    app = _FakeApplication()

    exit_code = main(
        [
            "project",
            "create",
            "--name",
            "CLI Project",
            "--spec-file",
            "specs/app.md",
            "--idempotency-key",
            "create-cli-project-001",
            "--changed-by",
            "test-agent",
        ],
        application=app,
    )

    assert exit_code == 0
    assert app.calls[-1] == (
        "project_create",
        {
            "name": "CLI Project",
            "spec_file": "specs/app.md",
            "idempotency_key": "create-cli-project-001",
            "dry_run": False,
            "dry_run_id": None,
            "correlation_id": None,
            "changed_by": "test-agent",
        },
    )
```

- [ ] **Step 2: Add dry-run parser contract tests**

Add tests that:

- `project create --dry-run --dry-run-id preview-001 --name X --spec-file specs/app.md` routes with `idempotency_key=None`
- `project create --dry-run --idempotency-key create-001 --name X --spec-file specs/app.md` exits with `INVALID_COMMAND`
- `project create` without `--dry-run` and without `--idempotency-key` exits with `INVALID_COMMAND`
- `project setup retry --dry-run --recovery-mutation-event-id 42 --project-id 7 --spec-file specs/app.md --expected-state SETUP_REQUIRED --expected-context-fingerprint ctx123` routes with `idempotency_key=None`
- `project setup retry --dry-run --idempotency-key retry-001 ...` exits with `INVALID_COMMAND`

- [ ] **Step 3: Add `project setup retry` routing test**

Expected call:

```python
("project_setup_retry", {
    "project_id": 7,
    "spec_file": "specs/app.md",
    "expected_state": "SETUP_REQUIRED",
    "expected_context_fingerprint": "ctx123",
    "recovery_mutation_event_id": 42,
    "idempotency_key": "retry-cli-project-001",
    "dry_run": False,
    "dry_run_id": None,
    "correlation_id": None,
    "changed_by": "cli-agent",
})
```

The fake application method used by this test must accept and record the recovery id:

```python
def project_setup_retry(
    self,
    *,
    project_id: int,
    spec_file: str,
    expected_state: str,
    expected_context_fingerprint: str,
    recovery_mutation_event_id: int | None = None,
    idempotency_key: str | None = None,
    dry_run: bool = False,
    dry_run_id: str | None = None,
    correlation_id: str | None = None,
    changed_by: str = "cli-agent",
) -> JsonObject:
    self.calls.append(
        (
            "project_setup_retry",
            {
                "project_id": project_id,
                "spec_file": spec_file,
                "expected_state": expected_state,
                "expected_context_fingerprint": expected_context_fingerprint,
                "recovery_mutation_event_id": recovery_mutation_event_id,
                "idempotency_key": idempotency_key,
                "dry_run": dry_run,
                "dry_run_id": dry_run_id,
                "correlation_id": correlation_id,
                "changed_by": changed_by,
            },
        )
    )
    return {"ok": True, "data": {"project_id": project_id}, "warnings": [], "errors": []}
```

- [ ] **Step 4: Run tests and verify failure**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py::test_cli_routes_project_create_to_application -q
```

Expected: parse failure because parser has no `project create`.

- [ ] **Step 5: Implement CLI parser and handlers**

In `build_parser()`, under the existing `project` subparser, add:

```python
project_create = project_sub.add_parser("create", help="Create a project.")
project_create.add_argument("--name", required=True)
project_create.add_argument("--spec-file", required=True)
project_create.add_argument("--idempotency-key")
project_create.add_argument("--dry-run", action="store_true")
project_create.add_argument("--dry-run-id")
project_create.add_argument("--correlation-id")
project_create.add_argument("--changed-by", default="cli-agent")
project_create.set_defaults(command_handler=_project_create)

project_setup = project_sub.add_parser("setup", help="Retry project setup.")
project_setup_sub = project_setup.add_subparsers(dest="setup_action", required=True)
project_setup_retry = project_setup_sub.add_parser("retry", help="Retry setup.")
project_setup_retry.add_argument("--project-id", type=int, required=True)
project_setup_retry.add_argument("--spec-file", required=True)
project_setup_retry.add_argument("--expected-state", required=True)
project_setup_retry.add_argument("--expected-context-fingerprint", required=True)
project_setup_retry.add_argument("--recovery-mutation-event-id", type=int)
project_setup_retry.add_argument("--idempotency-key")
project_setup_retry.add_argument("--dry-run", action="store_true")
project_setup_retry.add_argument("--dry-run-id")
project_setup_retry.add_argument("--correlation-id")
project_setup_retry.add_argument("--changed-by", default="cli-agent")
project_setup_retry.set_defaults(command_handler=_project_setup_retry)
```

Before calling the facade, handlers must enforce:

```python
def _validate_mutation_idempotency_args(args: argparse.Namespace) -> WorkbenchError | None:
    if args.dry_run and args.idempotency_key:
        return WorkbenchError(
            code="INVALID_COMMAND",
            message="--idempotency-key is not allowed with --dry-run.",
            details={"idempotency_key": args.idempotency_key},
            remediation=["Use --dry-run-id for dry-run tracing."],
            exit_code=2,
            retryable=False,
        )
    if not args.dry_run and not args.idempotency_key:
        return WorkbenchError(
            code="INVALID_COMMAND",
            message="--idempotency-key is required for non-dry-run mutations.",
            remediation=["Pass --idempotency-key or use --dry-run."],
            exit_code=2,
            retryable=False,
        )
    return None
```

Add handler functions:

```python
def _project_create(args: argparse.Namespace, application: _Application) -> CommandResult:
    return "agileforge project create", application.project_create(
        name=args.name,
        spec_file=args.spec_file,
        idempotency_key=args.idempotency_key,
        dry_run=args.dry_run,
        dry_run_id=args.dry_run_id,
        correlation_id=args.correlation_id,
        changed_by=args.changed_by,
    )
```

and equivalent `_project_setup_retry`, including `expected_state=args.expected_state`, `expected_context_fingerprint=args.expected_context_fingerprint`, and `recovery_mutation_event_id=args.recovery_mutation_event_id`.

- [ ] **Step 6: Add application facade methods**

`AgentWorkbenchApplication.project_create` must construct `ProjectCreateRequest` and call `ProjectSetupMutationRunner.create_project`.

`AgentWorkbenchApplication.project_setup_retry` must construct `ProjectSetupRetryRequest` and call `ProjectSetupMutationRunner.retry_setup`.

- [ ] **Step 7: Verify routing tests pass**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_cli.py tests/test_agent_workbench_application.py -q
```

Expected: CLI and application facade tests pass.

- [ ] **Step 8: Commit**

```bash
git add cli/main.py services/agent_workbench/application.py tests/test_agent_workbench_cli.py tests/test_agent_workbench_application.py
git commit -m "feat: route project setup mutations through CLI"
```

---

## Task 6: Command Metadata, Schemas, And Error Codes

**Files:**
- Modify: `services/agent_workbench/contract_models.py`
- Modify: `services/agent_workbench/command_schema.py`
- Modify: `services/agent_workbench/error_codes.py`
- Modify: `services/agent_workbench/command_registry.py`
- Test: `tests/test_agent_workbench_error_codes.py`
- Test: `tests/test_agent_workbench_command_schema.py`

- [ ] **Step 1: Add failing schema tests**

Assert:

```python
def test_project_create_is_registered_as_mutating_idempotent_command() -> None:
    schema = command_schema_payload("agileforge project create")

    assert schema["mutates"] is True
    assert schema["idempotency_required"] is True
    assert schema["idempotency_policy"] == {
        "non_dry_run": "required",
        "dry_run": "forbidden",
        "dry_run_trace_field": "dry_run_id",
    }
    assert schema["input"]["required"] == ["name", "spec_file"]
    assert "idempotency_key" in schema["input"]["optional"]
    assert "dry_run" in schema["input"]["optional"]
    assert "dry_run_id" in schema["input"]["optional"]
    assert "PROJECT_ALREADY_EXISTS" in schema["errors"]
```

Also assert `agileforge project setup retry` is registered as mutating and idempotent, has `guard_policy == ["expected_state", "expected_context_fingerprint"]`, requires `project_id`, `spec_file`, `expected_state`, and `expected_context_fingerprint`, declares optional `recovery_mutation_event_id`, and includes `MUTATION_FAILED` plus `MUTATION_RESUME_CONFLICT` in `schema["errors"]`. Assert `agileforge project create` also includes `MUTATION_FAILED` in `schema["errors"]`.

- [ ] **Step 2: Add error codes**

Add to `ErrorCode` and `_ERROR_REGISTRY`:

- `PROJECT_ALREADY_EXISTS`, exit 2, retryable false
- `SPEC_FILE_NOT_FOUND`, exit 2, retryable false
- `SPEC_FILE_INVALID`, exit 2, retryable false
- `SPEC_COMPILE_FAILED`, exit 1, retryable true
- `WORKFLOW_SESSION_FAILED`, exit 1, retryable true
- `MUTATION_RECOVERY_INVALID`, exit 10, retryable false

`MUTATION_FAILED` and `MUTATION_RESUME_CONFLICT` already exist in the central registry; do not re-add them. Phase 2B must publish `MUTATION_FAILED` in both project setup command metadata entries and `MUTATION_RESUME_CONFLICT` in `agileforge project setup retry` metadata.

- [ ] **Step 3: Add idempotency policy to command schemas**

Extend `CommandMetadata` with a dataclass field:

```python
idempotency_policy: dict[str, str] = field(
    default_factory=lambda: {
        "non_dry_run": "not_applicable",
        "dry_run": "not_applicable",
        "dry_run_trace_field": "none",
    }
)
```

Extend `CommandContractSchema` with:

```python
idempotency_policy: dict[str, str]
```

For mutating commands that support dry-run, publish:

```python
{
    "non_dry_run": "required",
    "dry_run": "forbidden",
    "dry_run_trace_field": "dry_run_id",
}
```

- [ ] **Step 4: Register commands**

Add Phase 2B metadata:

```python
_PHASE_2B_COMMANDS: tuple[CommandMetadata, ...] = (
    CommandMetadata(
        name="agileforge project create",
        mutates=True,
        phase="phase_2b",
        requires_idempotency_key=True,
        input_required=("name", "spec_file"),
        input_optional=(
            "idempotency_key",
            "dry_run",
            "dry_run_id",
            "correlation_id",
            "changed_by",
        ),
        errors=(
            ErrorCode.SCHEMA_NOT_READY.value,
            ErrorCode.PROJECT_ALREADY_EXISTS.value,
            ErrorCode.SPEC_FILE_NOT_FOUND.value,
            ErrorCode.SPEC_FILE_INVALID.value,
            ErrorCode.SPEC_COMPILE_FAILED.value,
            ErrorCode.WORKFLOW_SESSION_FAILED.value,
            ErrorCode.MUTATION_FAILED.value,
            ErrorCode.IDEMPOTENCY_KEY_REUSED.value,
            ErrorCode.MUTATION_IN_PROGRESS.value,
            ErrorCode.MUTATION_RECOVERY_REQUIRED.value,
        ),
    ),
    CommandMetadata(
        name="agileforge project setup retry",
        mutates=True,
        phase="phase_2b",
        requires_idempotency_key=True,
        accepts_expected_state=True,
        accepts_expected_context_fingerprint=True,
        input_required=(
            "project_id",
            "spec_file",
            "expected_state",
            "expected_context_fingerprint",
        ),
        input_optional=(
            "recovery_mutation_event_id",
            "idempotency_key",
            "dry_run",
            "dry_run_id",
            "correlation_id",
            "changed_by",
        ),
        errors=(
            ErrorCode.SCHEMA_NOT_READY.value,
            ErrorCode.PROJECT_NOT_FOUND.value,
            ErrorCode.SPEC_FILE_NOT_FOUND.value,
            ErrorCode.SPEC_FILE_INVALID.value,
            ErrorCode.SPEC_COMPILE_FAILED.value,
            ErrorCode.WORKFLOW_SESSION_FAILED.value,
            ErrorCode.MUTATION_FAILED.value,
            ErrorCode.STALE_STATE.value,
            ErrorCode.STALE_CONTEXT_FINGERPRINT.value,
            ErrorCode.IDEMPOTENCY_KEY_REUSED.value,
            ErrorCode.MUTATION_IN_PROGRESS.value,
            ErrorCode.MUTATION_RECOVERY_REQUIRED.value,
            ErrorCode.MUTATION_RECOVERY_INVALID.value,
            ErrorCode.MUTATION_RESUME_CONFLICT.value,
        ),
    ),
)
```

Update `installed_commands()` to include Phase 2B.

- [ ] **Step 5: Verify schema tests pass**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_error_codes.py tests/test_agent_workbench_command_schema.py -q
```

Expected: error registry and command schema tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/agent_workbench/contract_models.py services/agent_workbench/command_schema.py services/agent_workbench/error_codes.py services/agent_workbench/command_registry.py tests/test_agent_workbench_error_codes.py tests/test_agent_workbench_command_schema.py
git commit -m "feat: publish project setup command contracts"
```

---

## Task 7: End-To-End CLI Tests

**Files:**
- Create: `tests/test_agent_workbench_project_create_cli_integration.py`
- Modify only if required: `tests/conftest.py`

- [ ] **Step 1: Add CLI integration test from non-repo cwd**

Test command:

```python
repo_root = Path(__file__).resolve().parents[1]
business_db_path = tmp_path / "business.sqlite3"
session_db_path = tmp_path / "sessions.sqlite3"
env = os.environ.copy()
env["PYTHONPATH"] = str(repo_root)
env["AGILEFORGE_DB_URL"] = f"sqlite:///{business_db_path.as_posix()}"
env["AGILEFORGE_SESSION_DB_URL"] = f"sqlite:///{session_db_path.as_posix()}"
env["ALLOW_PROD_DB_IN_TEST"] = "1"
result = subprocess.run(
    [
        sys.executable,
        "-m",
        "cli.main",
        "project",
        "create",
        "--name",
        "Outside Repo Project",
        "--spec-file",
        "specs/app.md",
        "--idempotency-key",
        "outside-repo-project-001",
    ],
    cwd=caller_dir,
    env=env,
    text=True,
    capture_output=True,
    check=False,
)
```

Assert:

- exit code `0`
- JSON `ok` is true
- returned `project_id` exists
- returned `resolved_spec_path` is inside `caller_dir`
- parent test opens `business_db_path` with `create_engine(f"sqlite:///{business_db_path}")` and verifies no `SpecAuthorityAcceptance` rows exist

- [ ] **Step 2: Add shim smoke test shape for manual verification**

Do not rely on `~/.local/bin/agileforge` inside automated tests. Automated subprocess tests must set `PYTHONPATH`, `AGILEFORGE_DB_URL`, `AGILEFORGE_SESSION_DB_URL`, and `ALLOW_PROD_DB_IN_TEST=1` as above while preserving `cwd=caller_dir`. Use file-backed temp SQLite URLs whenever the parent test must inspect subprocess side effects. The manual smoke in Task 9 uses the real machine-level shim.

- [ ] **Step 3: Add retry integration test**

Use the injected `PendingAuthorityCompiler` seam to force compile failure in-process, capture the returned `mutation_event_id`, then run the retry command through `main(argv, application=fake_app)` with a fake application or subprocess with `PYTHONPATH`. The retry command must include stale-state guards and the recovery linkage id:

```bash
python -m cli.main project setup retry --project-id 1 --spec-file specs/app.md --expected-state SETUP_REQUIRED --expected-context-fingerprint ctx123 --recovery-mutation-event-id 42 --idempotency-key retry-001
```

Assert retry returns successful setup metadata, does not create duplicate project rows, marks the original create ledger row as `superseded`, and makes replay of the original create idempotency key return the stored superseded response.

- [ ] **Step 4: Run integration tests**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_project_create_cli_integration.py -q
```

Expected: integration tests pass.

- [ ] **Step 5: Commit**

```bash
git add tests/test_agent_workbench_project_create_cli_integration.py tests/conftest.py
git commit -m "test: cover project create CLI integration"
```

---

## Task 8: Import Boundary And Regression Sweep

**Files:**
- Modify: `tests/test_agent_workbench_contract_import_boundary.py`
- Possibly modify: `tests/test_spec_schema_modules.py`

- [ ] **Step 1: Add import-boundary assertion**

Assert new Phase 2B modules do not import:

- `api`
- `fastapi`
- dashboard modules
- route handlers

Expected allowed imports:

- `models.*`
- `services.specs.pending_authority_service`
- `services.agent_workbench.*`
- `services.workflow`
- `repositories.session`
- `sqlmodel`
- `sqlalchemy`

- [ ] **Step 2: Run import-boundary tests**

```bash
uv run --frozen python -m pytest tests/test_agent_workbench_contract_import_boundary.py tests/test_spec_schema_modules.py -q
```

Expected: import-boundary tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_agent_workbench_contract_import_boundary.py tests/test_spec_schema_modules.py
git commit -m "test: enforce project setup import boundaries"
```

---

## Task 9: Manual Smoke And Full Verification

**Files:** none unless a defect is found

- [ ] **Step 1: Run focused tests**

```bash
uv run --frozen python -m pytest \
  tests/test_pending_authority_service.py \
  tests/test_agent_workbench_project_setup.py \
  tests/test_agent_workbench_project_create_cli_integration.py \
  tests/test_agent_workbench_cli.py \
  tests/test_agent_workbench_command_schema.py \
  tests/test_agent_workbench_contract_import_boundary.py \
  -q
```

Expected: focused Phase 2B tests pass.

- [ ] **Step 2: Run full test suite**

```bash
uv run --frozen python -m pytest tests/ -q
```

Expected: full test suite passes.

- [ ] **Step 3: Manual CLI smoke from another repo**

```bash
tmp_dir="$(mktemp -d)"
mkdir -p "$tmp_dir/specs"
cat > "$tmp_dir/specs/app.md" <<'EOF'
# Smoke Spec

Build a small CLI-created project.
EOF
cd "$tmp_dir"
agileforge project create \
  --name "CLI Smoke Preview" \
  --spec-file specs/app.md \
  --dry-run \
  --dry-run-id "cli-smoke-preview-$(date +%s)"
agileforge project create \
  --name "CLI Smoke $(date +%s)" \
  --spec-file specs/app.md \
  --idempotency-key "cli-smoke-$(date +%s)"
```

Expected:

- JSON `ok: true`
- data includes `project_id`, `spec_version_id`, `authority_id`, `setup_status: authority_pending_review`
- no vision auto-run field claiming execution
- `logs/app.log` contains project-create boundary logs

- [ ] **Step 4: Inspect resulting project**

```bash
agileforge project list
agileforge authority status --project-id <project_id>
agileforge workflow state --project-id <project_id>
```

Expected:

- project appears in list
- authority status shows compiled but not accepted
- workflow state remains setup-blocked pending manual authority review

- [ ] **Step 5: Final repo checks**

```bash
git diff --check
git status --short --branch
```

Expected: no whitespace errors; branch has only intentional changes.

---

## Acceptance Criteria

- `agileforge project create --help` exists and documents required flags.
- `agileforge project setup retry --help` exists and documents required flags.
- `agileforge capabilities` includes both commands as `phase_2b`, `mutates: true`, `requires_idempotency_key: true`, and an idempotency policy that requires keys for non-dry-run and forbids keys for dry-run.
- `db/migrations.py`, `models/agent_workbench.py`, `MUTATION_LEDGER_REQUIREMENTS`, and `schema check` all know about `recovers_mutation_event_id` and `superseded_by_mutation_event_id`.
- `AGENT_WORKBENCH_STORAGE_SCHEMA_VERSION` and `STORAGE_SCHEMA_VERSION` are bumped to the same Phase 2B version.
- Running `ensure_schema_current` against a pre-Phase-2B `cli_mutation_ledger` table adds both recovery-linkage columns and indexes idempotently.
- `agileforge command schema "agileforge project create"` returns required inputs, optional `idempotency_key`, optional `dry_run_id`, idempotency policy, and error codes.
- `agileforge command schema "agileforge project setup retry"` declares `expected_state` and `expected_context_fingerprint` as required guard inputs and `recovery_mutation_event_id` as an optional recovery-linkage input.
- `agileforge command schema "agileforge project create"` and `agileforge command schema "agileforge project setup retry"` include `MUTATION_FAILED` as a documented error.
- `agileforge command schema "agileforge project setup retry"` includes `MUTATION_RESUME_CONFLICT` as a documented error.
- Running `project create` from outside `/Users/aaat/projects/agileforge` resolves `--spec-file` relative to the caller cwd.
- Running `project create --dry-run` writes no product, spec, authority, session, or ledger rows.
- Running `project create --dry-run --idempotency-key x` fails with `INVALID_COMMAND`.
- Running non-dry-run `project create` without `--idempotency-key` fails with `INVALID_COMMAND`.
- Running `project create` writes `Product`, `SpecRegistry`, `CompiledSpecAuthority`, workflow session state, and mutation ledger response.
- Running `project create` creates zero `SpecAuthorityAcceptance` rows.
- Running `project create` does not auto-run vision.
- Duplicate project names fail with `PROJECT_ALREADY_EXISTS` before insertion.
- Running the same command with the same idempotency key and same normalized request replays the prior response without duplicate writes.
- Reusing the same idempotency key with a different normalized request fails with `IDEMPOTENCY_KEY_REUSED`.
- Setup retry requires `--expected-state` and `--expected-context-fingerprint`, and fails stale values with `STALE_STATE` or `STALE_CONTEXT_FINGERPRINT`.
- Setup retry obtains `expected_context_fingerprint` from `data.guard_tokens.expected_context_fingerprint`, not from envelope metadata.
- Setup retry can complete setup for an existing project without creating a duplicate product.
- Setup retry dry-run with `--recovery-mutation-event-id` does not create a retry ledger row, acquire a recovery lease, mutate the original ledger row, or write domain state.
- Setup retry with `--recovery-mutation-event-id` supersedes the original `project create` recovery row, records `superseded_by_mutation_event_id`, and makes replay of the original create idempotency key return the stored superseded response.
- Linked retry success and post-side-effect linked retry failure update original and retry ledger rows through one SQL transaction; injected mid-transition failure rolls back both rows.
- Two-row linked retry helpers return the refreshed retry row in `LedgerLoadResult.ledger`; retry command converts `MUTATION_RESUME_CONFLICT` into a structured registry-backed error envelope with both mutation ids.
- Linked retry success/failure tests monkeypatch `supersede_recovered_event` to raise and still pass, proving linked retry paths use only atomic two-row helpers.
- Replaying a retry row in `domain_failed_no_side_effects` returns the stored retry response as envelope `data` exactly.
- Project-create compiler failure after product/spec writes returns structured `SPEC_COMPILE_FAILED` data and a recovery-required ledger row instead of pretending rollback occurred.
- Bad compiler seams that create `SpecAuthorityAcceptance` cause failure and leave zero matching acceptance rows behind.
- A retry after crash at `product_created` creates no duplicate product and returns deterministic recovery output.
- Pending authority checks the active ledger owner immediately before product spec link, spec registry write, spec approval, compiled authority persistence, product authority cache persistence, and workflow session initialization.
- Pending authority records each committed substep through a checked `record_progress` callback and stops for recovery if progress recording fails.
- Workflow setup is idempotent: retry after session creation but before status update updates the existing session, retry after status write but before ledger progress records progress, and stale setup fields are merged without losing unrelated state.
- A linked retry failure before side effects leaves the original recovery row active; a linked retry failure after side effects transfers recovery to the retry row and supersedes the original row.
- Subprocess CLI tests use temp file-backed SQLite URLs when the parent test inspects written rows.
- New CLI project setup modules do not import FastAPI or dashboard route handlers.
- Full test suite passes.

---

## Self-Review

- Spec coverage: This plan implements the Phase 2B project setup mutation slice and leaves authority acceptance for a later phase.
- Risk handled: The existing `link_spec_to_product` auto-accepts authority, so the plan creates a separate pending-authority service.
- Dry-run contract handled: dry-run rejects idempotency keys, uses optional `dry_run_id`, and writes no ledger rows.
- Retry dry-run handled: linked retry previews do not acquire leases, mutate original recovery rows, or create retry ledger rows.
- Schema migration handled: Phase 2B recovery-linkage columns and version bump are added to model, migration SQL, readiness checks, diagnostics, and migration tests before runner work.
- Setup retry guards handled: retry requires expected workflow state and context fingerprint and re-checks both before mutation.
- Setup retry recovery ownership handled: linked retries supersede the original recovery row and replay original idempotency keys deterministically.
- Linked retry failure status handled: no-side-effect failures release the original recovery lease, while post-side-effect failures transfer recovery to the retry row.
- Linked retry atomicity handled: successful retry and post-side-effect retry failure use dedicated two-row ledger helpers with rollback on partial update failure.
- Linked retry helper contract handled: helpers return the refreshed retry row, publish conflict details through `MUTATION_RESUME_CONFLICT`, and tests prove `supersede_recovered_event` is not used for linked retry paths.
- Error publication handled: `MUTATION_FAILED` is documented for both Phase 2B project setup commands; `MUTATION_RESUME_CONFLICT` is documented for setup retry.
- Engine boundary handled: pending authority persistence accepts a caller-owned session and injected compiler callable, and the default compiler path uses an explicit business DB engine.
- Acceptance invariant handled: bad compiler seams must leave zero matching `SpecAuthorityAcceptance` rows behind.
- Recovery handled: Product/spec business writes are tracked by the mutation ledger; workflow session writes are fenced; retry recovery is linked to the original ledger row rather than creating an unresolved second recovery path.
- Workflow crash recovery handled: session create and setup-status merge are idempotently reconciled and tracked as `workflow_session_created` and `workflow_session_status_written`.
- Internal fencing handled: pending authority substeps each run an active-owner guard before durable writes and a checked progress recorder after commits, including compiler persistence.
- Integration persistence handled: subprocess tests use temp file-backed SQLite URLs when parent assertions inspect rows.
- JSON contract handled: command registry, schema output, capabilities, stable error codes, and exit code metadata are updated.
- Caller cwd handled: request normalization resolves relative spec files from the process cwd, which the central shim preserves.
- Logging handled: CLI calls configure file logging before command execution; project setup emits side-effect boundary logs.
- No placeholders: All planned tasks have concrete files, command examples, and expected outcomes.
