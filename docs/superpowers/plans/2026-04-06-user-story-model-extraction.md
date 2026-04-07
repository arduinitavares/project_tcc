# UserStory Model Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the real `UserStory` SQLModel class out of `agile_sqlmodel.py` and into the models package without pulling `Sprint` and `Task` along in the same slice.

**Architecture:** Treat `UserStory` as the next true Phase 6 boundary because it is the remaining core model with the highest read/write coupling across backlog, refinement, query, export, and validation flows. Extract `UserStory` into `models/core.py`, keep `agile_sqlmodel.py` as a compatibility shim that re-exports it, and only repoint the `UserStory`-only consumers in this pass. Leave `Sprint`, `Task`, and the sprint-planner write transaction on the shim for the follow-up slices.

**Tech Stack:** SQLModel, SQLAlchemy relationship inspection, pytest, FastAPI-adjacent services, ADK tool modules

---

### Task 1: Add Red Boundary Tests For The `UserStory` Package Move

**Files:**
- Modify: `tests/test_model_package_boundary.py`
- Add: `tests/test_user_story_model_import_boundary.py`
- Test: `tests/test_model_package_boundary.py`
- Test: `tests/test_user_story_model_import_boundary.py`

- [ ] **Step 1: Add failing boundary assertions**

Add coverage for:
- `models.core.UserStory.__module__ == "models.core"`
- `agile_sqlmodel.UserStory is models.core.UserStory`
- relationship contract updates once `UserStory` moves:
  - `Product.stories`
  - `Feature.stories`
  - `UserStory.product`
  - `UserStory.feature`
  - `UserStory.sprints`
  - `UserStory.tasks`
- runtime import boundary checks for the first repointed `UserStory` consumers:
  - `services/orchestrator_query_service.py`
  - `services/orchestrator_context_service.py`
  - `services/specs/story_validation_service.py`
  - `tools/story_query_tools.py`
  - `tools/orchestrator_tools.py`
  - `orchestrator_agent/agent_tools/backlog_primer/tools.py`
  - `orchestrator_agent/agent_tools/user_story_writer_tool/tools.py`

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py \
  tests/test_user_story_model_import_boundary.py -q
```

Expected: FAIL because `models.core` does not yet export `UserStory`, the shim still owns the class, and the selected runtime consumers still import `UserStory` from `agile_sqlmodel`.


### Task 2: Move `UserStory` Into `models/core.py`

**Files:**
- Modify: `models/core.py`
- Modify: `agile_sqlmodel.py`
- Test: `tests/test_model_package_boundary.py`

- [ ] **Step 1: Add the real `UserStory` model to `models/core.py`**

Move the existing `UserStory` class definition from `agile_sqlmodel.py` into `models/core.py`, preserving:
- all fields, including refinement metadata and spec-validation fields
- enum usage via `models.enums`
- foreign keys to `products`, `features`, and `spec_registry`
- relationships to `Product`, `Feature`, `Sprint`, and `Task`

Update `models/core.py` typing imports so `Product.stories` and `Feature.stories` point at the package-owned `UserStory`, while `Sprint` and `Task` can remain forward references for now.

- [ ] **Step 2: Convert `agile_sqlmodel.py` into a `UserStory` shim for this class**

Remove the local `UserStory` class definition from `agile_sqlmodel.py` and re-export `UserStory` from `models.core`, keeping:
- `Sprint` and `Task` defined locally in `agile_sqlmodel.py`
- `SprintStory`, `Product`, `Feature`, `Team`, `TeamMember`, and spec/event/enums re-export behavior unchanged

- [ ] **Step 3: Run focused model-boundary tests**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py -q
```

Expected: PASS


### Task 3: Repoint Read/Query Consumers To `models.core.UserStory`

**Files:**
- Modify: `services/orchestrator_query_service.py`
- Modify: `services/orchestrator_context_service.py`
- Modify: `services/specs/story_validation_service.py`
- Modify: `tools/story_query_tools.py`
- Modify: `tools/orchestrator_tools.py`
- Test: `tests/test_orchestrator_query_service.py`
- Test: `tests/test_orchestrator_context_service.py`
- Test: `tests/test_story_validation_service.py`
- Test: `tests/test_user_story_model_import_boundary.py`

- [ ] **Step 1: Repoint the service/tool imports**

Change these modules to import `UserStory` from `models.core` instead of `agile_sqlmodel`, while leaving their other shim-backed model imports alone if they still depend on `Sprint`, `Product`, or `Task` staying on the shim.

- [ ] **Step 2: Keep the runtime boundary tests narrow**

In `tests/test_user_story_model_import_boundary.py`, assert exact keep-vs-move sets so this slice only moves `UserStory`, not unrelated model names.

- [ ] **Step 3: Run focused regression tests**

Run:

```bash
uv run pytest \
  tests/test_user_story_model_import_boundary.py \
  tests/test_orchestrator_query_service.py \
  tests/test_orchestrator_context_service.py \
  tests/test_story_validation_service.py \
  tests/test_spec_schema_modules.py -q
```

Expected: PASS


### Task 4: Repoint Backlog And Refinement Tool Consumers

**Files:**
- Modify: `orchestrator_agent/agent_tools/backlog_primer/tools.py`
- Modify: `orchestrator_agent/agent_tools/user_story_writer_tool/tools.py`
- Test: `tests/test_backlog_primer_agent.py`
- Test: `tests/test_save_stories_tool.py`
- Test: `tests/test_user_story_writer_tools.py`
- Test: `tests/test_agent_tool_runtime_import_boundary.py`
- Test: `tests/test_backlog_sprint_runtime_import_boundary.py`
- Test: `tests/test_user_story_model_import_boundary.py`

- [ ] **Step 1: Move only the `UserStory` imports**

Update the backlog-primer and story-writer tools so `UserStory` comes from `models.core`, while `Product` remains on `agile_sqlmodel` in the story-writer tool for this slice.

- [ ] **Step 2: Extend the runtime boundary guards**

Add explicit checks so the ADK/runtime boundary tests reject future regressions back to `agile_sqlmodel.UserStory` in these modules.

- [ ] **Step 3: Run tool-level regression tests**

Run:

```bash
uv run pytest \
  tests/test_backlog_primer_agent.py \
  tests/test_save_stories_tool.py \
  tests/test_user_story_writer_tools.py \
  tests/test_agent_tool_runtime_import_boundary.py \
  tests/test_backlog_sprint_runtime_import_boundary.py \
  tests/test_user_story_model_import_boundary.py -q
```

Expected: PASS


### Task 5: Run Broad Confidence Matrix And Stop Before `Sprint` / `Task`

**Files:**
- Modify: `tests/test_model_package_boundary.py`
- Modify: `tests/test_user_story_model_import_boundary.py`
- Verify only: existing API/service/tool regression tests

- [ ] **Step 1: Run the broad matrix**

Run:

```bash
uv run pytest \
  tests/test_model_package_boundary.py \
  tests/test_user_story_model_import_boundary.py \
  tests/test_specs_lifecycle_service.py \
  tests/test_specs_compiler_service.py \
  tests/test_story_validation_service.py \
  tests/test_story_validation_pinning.py \
  tests/test_orchestrator_query_service.py \
  tests/test_orchestrator_context_service.py \
  tests/test_orchestrator_tools.py \
  tests/test_orchestrator_tools_unittest.py \
  tests/test_backlog_primer_agent.py \
  tests/test_save_stories_tool.py \
  tests/test_user_story_writer_tools.py \
  tests/test_api_story_interview_flow.py \
  tests/test_api_sprint_flow.py \
  tests/test_api_story_close.py \
  tests/test_api_task_execution.py \
  tests/test_export_snapshot.py \
  tests/test_export_import_labels.py -q
```

Expected: PASS

- [ ] **Step 2: Stop the slice at `UserStory`**

Do not move:
- `Sprint`
- `Task`
- `sprint_planner_tool/tools.py`
- sprint/task-heavy API endpoints

Those are the next follow-up slices after the `UserStory` boundary is stable.
