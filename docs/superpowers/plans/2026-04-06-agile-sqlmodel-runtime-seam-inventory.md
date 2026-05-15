## Agile SQLModel Runtime Seam Inventory

Date: 2026-04-06
Worktree: `/Users/aaat/projects/agileforge/.worktrees/phase1-route-stabilization`

### Goal

Inventory the remaining `agile_sqlmodel` references in production/runtime Python code after the `api.py` import cleanup, separate intentional compatibility hooks from real migration targets, and choose the next safe slice.

### Search Scope

- `api.py`
- `models/`
- `services/`
- `repositories/`
- `tools/`
- `orchestrator_agent/`
- `utils/`

Tests, scripts, docs, and notebooks are intentionally out of scope for this inventory.

### Current Runtime State

The remaining direct `agile_sqlmodel` references in runtime code are now limited to:

1. `agile_sqlmodel.py`
2. `models/core.py`
3. `services/specs/lifecycle_service.py`
4. `services/specs/story_validation_service.py`
5. `services/specs/compiler_service.py`

There are no remaining direct `agile_sqlmodel` imports in:

- `api.py`
- `repositories/`
- `tools/`
- `orchestrator_agent/`

`utils/runtime_config.py` still contains the string literal `"agile_sqlmodel.db"` in the legacy DB filename guard, but that is not a runtime import dependency.

### Intentional Compatibility Hooks

#### 1. `agile_sqlmodel.py` is now the real compatibility shim

Relevant surface:

- `sys.modules.setdefault("agile_sqlmodel", sys.modules[__name__])`
- re-export imports from `models.core`, `models.events`, `models.enums`, and `models.specs`
- lazy `__getattr__` forwarding for DB symbols from `models.db`
- `__main__` entrypoint calling `create_db_and_tables()`

Why it stays for now:

- legacy imports like `import agile_sqlmodel; agile_sqlmodel.Product` still depend on it
- legacy DB calls like `agile_sqlmodel.get_engine()` still depend on it
- `python agile_sqlmodel.py` is still a supported compatibility path

If removed today:

- legacy runtime imports would fail immediately
- DB helper access through the shim would fail
- the script entrypoint would stop working

#### 2. `models/core.py` keeps a side-effect import of the shim

Relevant surface:

- trailing `import agile_sqlmodel`

Why it stays for now:

- the file comment makes the intent explicit: keep direct `import models.core` safe while legacy re-exports stay wired up

If removed today:

- `models.core` itself should still import cleanly
- but code paths depending on `models.core` import side effects to populate the `agile_sqlmodel` module graph could break

Assessment:

- this is a compatibility convenience seam, not the next high-leverage target

### Safe Migration Targets

The next clean runtime targets are the duplicated `_resolve_engine()` seams in the spec services.

#### 1. `services/specs/lifecycle_service.py`

Relevant surface:

- top-level `import agile_sqlmodel`
- `_resolve_engine()` comparing `get_engine` to `agile_sqlmodel.get_engine`

Why this is safe:

- `agile_sqlmodel` is only used for engine identity/fallback behavior
- no spec models or business models are still sourced from the shim here

What would break if we removed it without replacement:

- tests or callers monkeypatching `tools.spec_tools.engine`
- tests or callers monkeypatching `tools.spec_tools.get_engine`
- any caller still monkeypatching `agile_sqlmodel.get_engine`

#### 2. `services/specs/story_validation_service.py`

Relevant surface:

- top-level `import agile_sqlmodel`
- `_resolve_engine()` comparing `get_engine` to `agile_sqlmodel.get_engine`

Why this is safe:

- same profile as lifecycle service
- the shim is not needed here for model imports anymore

What would break if we removed it without replacement:

- legacy monkeypatch-driven DB routing in validation tests and callers

#### 3. `services/specs/compiler_service.py`

Relevant surface:

- top-level `import agile_sqlmodel`
- `_resolve_engine()` comparing `get_engine` to `agile_sqlmodel.get_engine`

Why this is still safe but slightly heavier:

- same engine-seam duplication pattern
- but compiler service sits in the middle of more spec workflows, so its regression radius is larger than the other two

What would break if we removed it without replacement:

- compile flows that still rely on monkeypatching `agile_sqlmodel.get_engine`
- compile flows that rely on `tools.spec_tools.engine` / `tools.spec_tools.get_engine` steering DB access

### Recommended Next Slice

Target the duplicated spec-service engine seams next.

#### Proposed boundary

- Keep:
  - `agile_sqlmodel.py`
  - `models/core.py` side-effect import
- Change:
  - `services/specs/lifecycle_service.py`
  - `services/specs/story_validation_service.py`
  - `services/specs/compiler_service.py`

#### Goal

Remove direct runtime dependency on `agile_sqlmodel.get_engine` from the three spec services while preserving the existing `tools.spec_tools` monkeypatch seam.

#### Expected outcome

After that slice:

- the only remaining runtime `agile_sqlmodel` dependency should be the intentional shim layer itself plus the `models/core.py` compatibility hook
- all ordinary runtime services should resolve DB access through `models.db`

### Suggested Execution Order

1. Add or tighten boundary coverage for the three spec services so the intended seam is explicit.
2. Extract or centralize the shared engine-resolution behavior behind a helper that prefers:
   - `tools.spec_tools.engine`
   - `tools.spec_tools.get_engine()`
   - `models.db.get_engine()`
3. Remove direct `agile_sqlmodel` import usage from:
   - `services/specs/lifecycle_service.py`
   - `services/specs/story_validation_service.py`
   - `services/specs/compiler_service.py`
4. Re-run the focused specs runtime matrix before widening confidence.

### Decision

The remaining runtime `agile_sqlmodel` surface is now small and understandable.

The shim itself should stay for now.
The next safe migration target is the duplicated spec-service engine fallback, not another model move.
