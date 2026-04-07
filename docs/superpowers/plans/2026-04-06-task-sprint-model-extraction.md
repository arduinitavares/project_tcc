# Task And Sprint Model Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the real `Task` and `Sprint` SQLModel classes out of `agile_sqlmodel.py` and into the models package without breaking the current service/tool boundaries or the lazy DB-import guarantees restored during the `UserStory` slice.

**Architecture:** Extract `Task` first and `Sprint` second. `Task` has the smaller runtime fanout and follows the already-proven `UserStory`/`TeamMember` relationship pattern, so it is the safer first move. After `Task` is stable, move `Sprint` as the heavier second phase, then repoint the read/query/export/planner consumers while keeping `agile_sqlmodel.py` as the compatibility shim and preserving the current `import models.core` no-env behavior.

**Tech Stack:** SQLModel, SQLAlchemy relationship inspection, pytest, FastAPI-adjacent services, ADK tool modules

---

### Task 1: Add Red Boundary Tests For The `Task` Package Move

**Files:**
- Modify: `tests/test_model_package_boundary.py`
- Add: `tests/test_task_model_import_boundary.py`
- Modify: `tests/test_tool_runtime_import_boundary.py`
- Modify: `tests/test_backlog_sprint_runtime_import_boundary.py`
- Test: `tests/test_model_package_boundary.py`
- Test: `tests/test_task_model_import_boundary.py`

- [ ] **Step 1: Add failing model-boundary assertions for `Task`**

Add coverage for:
- `models.core.Task.__module__ == "models.core"`
- `agile_sqlmodel.Task is models.core.Task`
- relationship contract after the move:
  - `UserStory.tasks`
  - `TeamMember.tasks`
  - `Task.story`
  - `Task.assignee`
- the existing no-env package guarantee:
  - `import models.core` still succeeds without `PROJECT_TCC_DB_URL`
  - `python agile_sqlmodel.py` still works when `PROJECT_TCC_DB_URL` is explicitly set

- [ ] **Step 2: Add failing import-boundary checks for the first `Task` consumers**

Create `tests/test_task_model_import_boundary.py` and scope it to the first `Task` runtime consumers only:
- `api.py`
- `tools/db_tools.py`
- `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`

The guard should assert exact keep-vs-move import sets:
- `Task` must move to `models.core`
- `Sprint` must stay on `agile_sqlmodel` for now
- `Product` and `UserStory` must stay on their current boundaries
- reject both `from agile_sqlmodel import Task` and `agile_sqlmodel.Task`

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py \
  tests/test_task_model_import_boundary.py \
  tests/test_tool_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py -q
```

Expected: FAIL because `Task` still lives in `agile_sqlmodel.py` and the selected runtime consumers still import it from the shim.


### Task 2: Move `Task` Into `models/core.py`

**Files:**
- Modify: `models/core.py`
- Modify: `agile_sqlmodel.py`
- Test: `tests/test_model_package_boundary.py`

- [ ] **Step 1: Add the real `Task` model to `models/core.py`**

Move the existing `Task` class definition from `agile_sqlmodel.py` into `models/core.py`, preserving:
- all fields including `metadata_json`
- enum usage via `models.enums`
- foreign keys to `user_stories` and `team_members`
- relationships to `UserStory` and `TeamMember`
- existing `canonical_task_metadata_json` default behavior

Update `models/core.py` relationship typing so:
- `UserStory.tasks` points at the package-owned `Task`
- `TeamMember.tasks` points at the package-owned `Task`
- `Task.story` points at package-owned `UserStory`
- `Task.assignee` points at package-owned `TeamMember`

- [ ] **Step 2: Convert `agile_sqlmodel.py` into a `Task` shim for this class**

Remove the local `Task` class definition from `agile_sqlmodel.py` and re-export `Task` from `models.core`, while keeping:
- `Sprint` defined locally for now
- the current lazy DB-helper export behavior
- the current `__main__` alias and script-entrypoint safety
- the current no-env `import models.core` behavior

- [ ] **Step 3: Run focused model-boundary tests**

Run:

```bash
uv run pytest tests/test_model_package_boundary.py -q
```

Expected: PASS


### Task 3: Repoint `Task` Runtime Consumers

**Files:**
- Modify: `api.py`
- Modify: `tools/db_tools.py`
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`
- Modify: `tests/test_task_model_import_boundary.py`
- Modify: `tests/test_tool_runtime_import_boundary.py`
- Modify: `tests/test_backlog_sprint_runtime_import_boundary.py`
- Test: `tests/test_db_tools.py`
- Test: `tests/test_sprint_planner_tools.py`
- Test: `tests/test_api_task_execution.py`
- Test: `tests/test_api_story_close.py`
- Test: `tests/test_task_model_import_boundary.py`

- [ ] **Step 1: Repoint only the `Task` imports**

Change these modules so only `Task` moves from `agile_sqlmodel` to `models.core`:
- `api.py`
- `tools/db_tools.py`
- `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`

Keep:
- `Sprint` on `agile_sqlmodel` in `api.py` and `sprint_planner_tool/tools.py`
- `Product` on `agile_sqlmodel` where it already remains
- all other current model boundaries unchanged

- [ ] **Step 2: Tighten the exact runtime guards**

Update the runtime boundary tests so they pin the exact keep-vs-move sets for this slice:
- `tests/test_task_model_import_boundary.py` for `api.py`, `db_tools.py`, and `sprint_planner_tool/tools.py`
- `tests/test_tool_runtime_import_boundary.py` for `db_tools.py`
- `tests/test_backlog_sprint_runtime_import_boundary.py` for `sprint_planner_tool/tools.py`

The guards must reject both:
- `from agile_sqlmodel import Task`
- `import agile_sqlmodel; agile_sqlmodel.Task`

- [ ] **Step 3: Run focused regression tests**

Run:

```bash
uv run pytest \
  tests/test_task_model_import_boundary.py \
  tests/test_tool_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py \
  tests/test_db_tools.py \
  tests/test_sprint_planner_tools.py \
  tests/test_api_task_execution.py \
  tests/test_api_story_close.py -q
```

Expected: PASS


### Task 4: Add Red Boundary Tests For The `Sprint` Package Move

**Files:**
- Modify: `tests/test_model_package_boundary.py`
- Add: `tests/test_sprint_model_import_boundary.py`
- Modify: `tests/test_orchestrator_runtime_import_boundary.py`
- Modify: `tests/test_tool_runtime_import_boundary.py`
- Modify: `tests/test_backlog_sprint_runtime_import_boundary.py`
- Test: `tests/test_model_package_boundary.py`
- Test: `tests/test_sprint_model_import_boundary.py`

- [ ] **Step 1: Add failing model-boundary assertions for `Sprint`**

Add coverage for:
- `models.core.Sprint.__module__ == "models.core"`
- `agile_sqlmodel.Sprint is models.core.Sprint`
- relationship contract after the move:
  - `Product.sprints`
  - `Team.sprints`
  - `UserStory.sprints`
  - `Sprint.product`
  - `Sprint.team`
  - `Sprint.stories`
- existing `SprintStory` link model continuity
- the current no-env `import models.core` guarantee remains intact after the `Sprint` move

- [ ] **Step 2: Add failing import-boundary checks for the first `Sprint` consumers**

Create `tests/test_sprint_model_import_boundary.py` and scope it to the `Sprint` runtime consumers:
- `api.py`
- `services/orchestrator_query_service.py`
- `services/orchestrator_context_service.py`
- `tools/export_snapshot.py`
- `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`

The guard should assert exact keep-vs-move import sets:
- `Sprint` must move to `models.core`
- `Task` must already be on `models.core`
- `Product` remains where it is today in each file
- reject both `from agile_sqlmodel import Sprint` and `agile_sqlmodel.Sprint`

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py \
  tests/test_sprint_model_import_boundary.py \
  tests/test_orchestrator_runtime_import_boundary.py \
  tests/test_tool_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py -q
```

Expected: FAIL because `Sprint` still lives in `agile_sqlmodel.py` and the selected runtime consumers still import it from the shim.


### Task 5: Move `Sprint` Into `models/core.py`

**Files:**
- Modify: `models/core.py`
- Modify: `agile_sqlmodel.py`
- Test: `tests/test_model_package_boundary.py`

- [ ] **Step 1: Add the real `Sprint` model to `models/core.py`**

Move the existing `Sprint` class definition from `agile_sqlmodel.py` into `models/core.py`, preserving:
- all fields including close-snapshot and timestamp columns
- enum usage via `models.enums`
- foreign keys to `products` and `teams`
- relationships to `Product`, `Team`, and `UserStory` via `SprintStory`

Update `models/core.py` relationship typing so:
- `Product.sprints` points at package-owned `Sprint`
- `Team.sprints` points at package-owned `Sprint`
- `UserStory.sprints` points at package-owned `Sprint`

- [ ] **Step 2: Convert `agile_sqlmodel.py` into a `Sprint` shim for this class**

Remove the local `Sprint` class definition from `agile_sqlmodel.py` and re-export `Sprint` from `models.core`, while keeping:
- the current lazy DB-helper export surface
- the script-entrypoint alias behavior
- `create_db_and_tables()` script compatibility
- the no-env `import models.core` guarantee

- [ ] **Step 3: Run focused model-boundary tests**

Run:

```bash
uv run pytest tests/test_model_package_boundary.py -q
```

Expected: PASS


### Task 6: Repoint `Sprint` Runtime Consumers

**Files:**
- Modify: `api.py`
- Modify: `services/orchestrator_query_service.py`
- Modify: `services/orchestrator_context_service.py`
- Modify: `tools/export_snapshot.py`
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`
- Modify: `tests/test_sprint_model_import_boundary.py`
- Modify: `tests/test_orchestrator_runtime_import_boundary.py`
- Modify: `tests/test_tool_runtime_import_boundary.py`
- Modify: `tests/test_backlog_sprint_runtime_import_boundary.py`
- Test: `tests/test_orchestrator_query_service.py`
- Test: `tests/test_export_snapshot.py`
- Test: `tests/test_api_sprint_close.py`
- Test: `tests/test_api_sprint_flow.py`
- Test: `tests/test_api_task_execution.py`
- Test: `tests/test_sprint_planner_tools.py`

- [ ] **Step 1: Repoint only the `Sprint` imports**

Change these modules so `Sprint` comes from `models.core`:
- `api.py`
- `services/orchestrator_query_service.py`
- `services/orchestrator_context_service.py`
- `tools/export_snapshot.py`
- `orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`

Keep:
- `Product` on its current boundary in each file
- `Task` on `models.core` from the previous phase
- unrelated runtime/package moves out of scope

- [ ] **Step 2: Tighten the exact runtime guards**

Update the runtime boundary tests so they pin the exact keep-vs-move sets for the `Sprint` slice and reject both:
- `from agile_sqlmodel import Sprint`
- `import agile_sqlmodel; agile_sqlmodel.Sprint`

- [ ] **Step 3: Run focused regression tests**

Run:

```bash
uv run pytest \
  tests/test_sprint_model_import_boundary.py \
  tests/test_orchestrator_runtime_import_boundary.py \
  tests/test_tool_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py \
  tests/test_orchestrator_query_service.py \
  tests/test_export_snapshot.py \
  tests/test_api_sprint_close.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_task_execution.py \
  tests/test_sprint_planner_tools.py -q
```

Expected: PASS


### Task 7: Run Broad Confidence Matrix And Stop

**Files:**
- Modify: `tests/test_model_package_boundary.py`
- Modify: `tests/test_task_model_import_boundary.py`
- Modify: `tests/test_sprint_model_import_boundary.py`
- Verify only: existing API/service/tool regression tests

- [ ] **Step 1: Run the broad matrix**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py \
  tests/test_task_model_import_boundary.py \
  tests/test_sprint_model_import_boundary.py \
  tests/test_tool_runtime_import_boundary.py \
  tests/test_orchestrator_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py \
  tests/test_db_tools.py \
  tests/test_orchestrator_query_service.py \
  tests/test_orchestrator_context_service.py \
  tests/test_orchestrator_tools.py \
  tests/test_orchestrator_tools_unittest.py \
  tests/test_sprint_planner_tools.py \
  tests/test_api_task_execution.py \
  tests/test_api_story_close.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py \
  tests/test_export_snapshot.py \
  tests/test_export_import_labels.py \
  tests/test_business_db_bootstrap.py \
  tests/test_spec_persistence.py -q
```

Expected: PASS

- [ ] **Step 2: Stop the slice at the model boundary**

Do not use this plan to:
- rewrite `task_execution_service.py` business logic
- refactor `sprint_service.py` orchestration
- change sprint/task packet rendering behavior
- redesign `sprint_planner_tool` persistence beyond the import-boundary move

Those are follow-up refactor slices after the `Task` and `Sprint` model boundaries are stable.
