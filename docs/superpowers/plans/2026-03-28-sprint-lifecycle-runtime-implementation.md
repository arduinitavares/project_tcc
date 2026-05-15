# Sprint Lifecycle Runtime and UX Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split one-time planning progression from repeatable sprint runtime so the project shell stays planning-oriented while the sprint workspace supports canonical `Planned`, `Active`, and `Completed` sprints with explicit close, immutable completed history, and clean next-sprint creation.

**Architecture:** Keep the existing `Sprint` row as the canonical runtime record, extend it additively with `completed_at` and `close_snapshot_json`, and derive `history_fidelity` from whether a close snapshot exists. Normalize legacy `SPRINT_COMPLETE` shell state at the API boundary, move sprint selection to a lightweight list plus selected-sprint detail contract, and drive all runtime actions from server-derived `allowed_actions` instead of frontend inference. Under the current story-scoped task model, planned-sprint updates modify the planned sprint row and story links in place while preserving existing story task rows for already-selected stories; completed sprint history comes from close snapshots instead of re-reading mutable live story/task data.

**Tech Stack:** FastAPI, SQLModel, SQLite idempotent migrations, Pydantic, vanilla JavaScript frontend, `pytest`, `node:test`

---

## File Map

- Modify: `/Users/aaat/projects/agileforge/agile_sqlmodel.py`
  Responsibility: extend `Sprint` persistence with completion and snapshot fields.
- Modify: `/Users/aaat/projects/agileforge/db/migrations.py`
  Responsibility: add additive sprint lifecycle migrations for older databases.
- Modify: `/Users/aaat/projects/agileforge/utils/schemes.py`
  Responsibility: add typed sprint-close request and response models.
- Modify: `/Users/aaat/projects/agileforge/orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`
  Responsibility: update planned sprint save semantics to create-or-update one open planned sprint, enforce open-sprint conflicts correctly, and keep updates in place.
- Modify: `/Users/aaat/projects/agileforge/tools/orchestrator_tools.py`
  Responsibility: exclude stories already committed to open planned/active sprints from sprint candidates while still allowing unfinished stories linked only to completed sprints.
- Modify: `/Users/aaat/projects/agileforge/services/sprint_input.py`
  Responsibility: preserve candidate normalization while passing through the refined eligibility result and excluded counts.
- Modify: `/Users/aaat/projects/agileforge/api.py`
  Responsibility: normalize legacy shell state, serialize lightweight sprint list items plus runtime summary, add selected-sprint detail, enforce start invariants, and implement sprint close preview/confirm endpoints.
- Modify: `/Users/aaat/projects/agileforge/frontend/project.js`
  Responsibility: stop inferring sprint mode from `started_at`, load runtime summary plus selected-sprint detail, render planned/active/completed views, and drive actions from server-provided `allowed_actions`.
- Modify: `/Users/aaat/projects/agileforge/frontend/project.html`
  Responsibility: add sprint-runtime summary slots and sprint-close UI containers without turning the shell into a repeated timeline.
- Create: `/Users/aaat/projects/agileforge/tests/test_db_migrations_sprint_lifecycle.py`
  Responsibility: prove new sprint lifecycle columns are added and idempotent on legacy schemas.
- Modify: `/Users/aaat/projects/agileforge/tests/test_sprint_planner_tools.py`
  Responsibility: verify planned sprint update-in-place behavior and open-sprint conflict rules in the persistence tool.
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py`
  Responsibility: verify sprint list/detail/runtime-summary payloads, start invariants, candidate eligibility, and legacy shell-state normalization.
- Create: `/Users/aaat/projects/agileforge/tests/test_api_sprint_close.py`
  Responsibility: verify sprint close preview, close confirmation, snapshot persistence, and `SPRINT_COMPLETED` events.
- Create: `/Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs`
  Responsibility: verify frontend sprint-mode selection, landing priority, and runtime-summary behavior with extracted functions from `frontend/project.js`.

### Task 1: Add Sprint Completion Persistence and Migration Coverage

**Files:**
- Modify: `/Users/aaat/projects/agileforge/agile_sqlmodel.py`
- Modify: `/Users/aaat/projects/agileforge/db/migrations.py`
- Create: `/Users/aaat/projects/agileforge/tests/test_db_migrations_sprint_lifecycle.py`

- [ ] **Step 1: Write failing migration tests for legacy sprint tables**

```python
from sqlalchemy import inspect, text
from sqlmodel import create_engine

from db.migrations import migrate_sprint_lifecycle


def _create_min_sprints_schema(engine) -> None:
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE sprints (
                    sprint_id INTEGER PRIMARY KEY,
                    goal TEXT,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    status VARCHAR NOT NULL,
                    product_id INTEGER NOT NULL,
                    team_id INTEGER NOT NULL
                )
                """
            )
        )


def test_migrate_sprint_lifecycle_adds_completion_columns() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_sprints_schema(engine)

    actions = migrate_sprint_lifecycle(engine)

    assert "added column: sprints.started_at" in actions
    assert "added column: sprints.completed_at" in actions
    assert "added column: sprints.close_snapshot_json" in actions
    column_names = {col["name"] for col in inspect(engine).get_columns("sprints")}
    assert {"started_at", "completed_at", "close_snapshot_json"}.issubset(column_names)


def test_migrate_sprint_lifecycle_is_idempotent() -> None:
    engine = create_engine("sqlite:///:memory:")
    _create_min_sprints_schema(engine)
    migrate_sprint_lifecycle(engine)

    actions = migrate_sprint_lifecycle(engine)

    assert actions == []
```

- [ ] **Step 2: Run the sprint lifecycle migration tests to verify they fail**

Run: `pytest tests/test_db_migrations_sprint_lifecycle.py -q`

Expected: FAIL because `migrate_sprint_lifecycle()` only adds `started_at`.

- [ ] **Step 3: Extend `Sprint` with completion and snapshot persistence**

```python
class Sprint(SQLModel, table=True):
    """A time-boxed iteration of work for a team."""

    __tablename__ = "sprints"  # type: ignore
    sprint_id: Optional[int] = Field(default=None, primary_key=True)
    goal: Optional[str] = Field(default=None, sa_type=Text)
    start_date: date = Field(sa_type=Date)
    end_date: date = Field(sa_type=Date)
    status: SprintStatus = Field(default=SprintStatus.PLANNED, nullable=False)
    started_at: Optional[datetime] = Field(default=None)
    completed_at: Optional[datetime] = Field(default=None)
    close_snapshot_json: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
```

- [ ] **Step 4: Expand the additive sprint lifecycle migration**

```python
def migrate_sprint_lifecycle(engine: Engine) -> List[str]:
    """Ensure sprint lifecycle columns exist."""
    actions: List[str] = []

    if _ensure_column_exists(
        engine,
        "sprints",
        "started_at",
        "DATETIME",
    ):
        actions.append("added column: sprints.started_at")

    if _ensure_column_exists(
        engine,
        "sprints",
        "completed_at",
        "DATETIME",
    ):
        actions.append("added column: sprints.completed_at")

    if _ensure_column_exists(
        engine,
        "sprints",
        "close_snapshot_json",
        "TEXT",
    ):
        actions.append("added column: sprints.close_snapshot_json")

    return actions
```

- [ ] **Step 5: Keep the migration registered at app startup**

```python
def ensure_schema_current(engine: Engine) -> None:
    logger.info("db.migration.start", extra={})

    try:
        actions = migrate_spec_authority_tables(engine)
        actions.extend(migrate_product_spec_cache(engine))
        actions.extend(migrate_user_story_refinement_linkage(engine))
        actions.extend(migrate_sprint_lifecycle(engine))
        actions.extend(migrate_task_metadata(engine))
        actions.extend(migrate_task_execution_logs(engine))
        actions.extend(migrate_performance_indexes(engine))
```

- [ ] **Step 6: Run the lifecycle migration tests again**

Run: `pytest tests/test_db_migrations_sprint_lifecycle.py -q`

Expected: PASS

- [ ] **Step 7: Commit the persistence migration work**

```bash
git add agile_sqlmodel.py \
  db/migrations.py \
  tests/test_db_migrations_sprint_lifecycle.py
git commit -m "feat: persist sprint close snapshots"
```

### Task 2: Update Planned-Sprint Persistence and Candidate Eligibility

**Files:**
- Modify: `/Users/aaat/projects/agileforge/orchestrator_agent/agent_tools/sprint_planner_tool/tools.py`
- Modify: `/Users/aaat/projects/agileforge/tools/orchestrator_tools.py`
- Modify: `/Users/aaat/projects/agileforge/services/sprint_input.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_sprint_planner_tools.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write failing tests for planned-sprint update-in-place and candidate filtering**

```python
def test_save_sprint_plan_updates_existing_planned_sprint_in_place(session: Session):
    product_id, team_id, story_ids = _seed_product_team_stories(session)

    existing_sprint = Sprint(
        goal="Old goal",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 14),
        status=SprintStatus.PLANNED,
        product_id=product_id,
        team_id=team_id,
    )
    session.add(existing_sprint)
    session.flush()

    session.add(SprintStory(sprint_id=existing_sprint.sprint_id, story_id=story_ids[0]))
    session.commit()

    tool_context = cast(
        ToolContext,
        SimpleNamespace(state={"sprint_plan": _build_sprint_plan(story_ids)}),
    )
    input_data = SaveSprintPlanInput(
        product_id=product_id,
        team_id=team_id,
        sprint_start_date="2026-02-01",
        sprint_duration_days=14,
    )

    result = save_sprint_plan_tool(input_data, tool_context)

    assert result["success"] is True
    assert result["sprint_id"] == existing_sprint.sprint_id
    assert session.exec(select(Sprint)).all()[0].goal == "Deliver authentication essentials"


def test_sprint_candidates_exclude_open_sprint_stories_but_keep_unfinished_completed_stories(
    session,
    monkeypatch,
):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, planned_sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=False,
        created_title="Open Planned Sprint",
    )

    team = session.exec(select(Team).where(Team.name == f"Team {project_id}")).first()
    rollover_story = UserStory(
        product_id=project_id,
        title="Rollover Story",
        story_description="As a user, I want rollover support",
        acceptance_criteria="- AC",
        status=StoryStatus.TO_DO,
        is_refined=True,
    )
    session.add(rollover_story)
    session.flush()

    completed_sprint = Sprint(
        goal="Completed Sprint",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 14),
        status=SprintStatus.COMPLETED,
        started_at=datetime(2026, 2, 1, 9, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 2, 14, 18, 0, tzinfo=timezone.utc),
        product_id=project_id,
        team_id=team.team_id,
    )
    session.add(completed_sprint)
    session.flush()
    session.add(SprintStory(sprint_id=completed_sprint.sprint_id, story_id=rollover_story.story_id))
    session.commit()

    response = client.get(f"/api/projects/{project_id}/sprint/candidates")

    assert response.status_code == 200
    payload = response.json()["data"]
    candidate_ids = [item["story_id"] for item in payload["items"]]
    assert rollover_story.story_id in candidate_ids
    assert payload["excluded_counts"]["open_sprint"] == 1
```

- [ ] **Step 2: Run the persistence and candidate tests to verify they fail**

Run: `pytest tests/test_sprint_planner_tools.py tests/test_api_sprint_flow.py -q`

Expected: FAIL because `save_sprint_plan_tool()` always creates a new planned sprint and `fetch_sprint_candidates()` ignores open sprint assignments.

- [ ] **Step 3: Add helper functions for one-open-planned-sprint semantics**

```python
def _get_open_planned_sprint(session: Session, product_id: int) -> Optional[Sprint]:
    return session.exec(
        select(Sprint).where(
            Sprint.product_id == product_id,
            Sprint.status == SprintStatus.PLANNED,
        )
    ).first()


def _get_story_conflicts(
    session: Session,
    story_ids: List[int],
    *,
    ignore_sprint_id: Optional[int] = None,
) -> List[int]:
    if not story_ids:
        return []

    statement = (
        select(SprintStory.story_id)
        .join(Sprint, col(Sprint.sprint_id) == col(SprintStory.sprint_id))
        .where(
            col(SprintStory.story_id).in_(story_ids),
            col(Sprint.status).in_([SprintStatus.PLANNED, SprintStatus.ACTIVE]),
        )
    )
    if ignore_sprint_id is not None:
        statement = statement.where(col(Sprint.sprint_id) != ignore_sprint_id)

    existing = session.exec(statement).all()
    return list({row for row in existing})
```

- [ ] **Step 4: Update `save_sprint_plan_tool()` to create-or-update one planned sprint**

```python
open_planned = _get_open_planned_sprint(session, input_data.product_id)
conflicts = _get_story_conflicts(
    session,
    story_ids,
    ignore_sprint_id=open_planned.sprint_id if open_planned else None,
)
if conflicts:
    return {
        "success": False,
        "error_code": "STORY_ALREADY_IN_OPEN_SPRINT",
        "error": (
            "Stories already assigned to active or planned sprints: "
            f"{sorted(conflicts)}"
        ),
    }

if open_planned is None:
    sprint = Sprint(
        goal=validated_plan.sprint_goal,
        start_date=start_date,
        end_date=end_date,
        status=SprintStatus.PLANNED,
        started_at=None,
        completed_at=None,
        close_snapshot_json=None,
        product_id=input_data.product_id,
        team_id=team.team_id,
    )
    session.add(sprint)
    session.flush()
else:
    sprint = open_planned
    sprint.goal = validated_plan.sprint_goal
    sprint.start_date = start_date
    sprint.end_date = end_date
    sprint.team_id = team.team_id
    session.add(sprint)

existing_links = session.exec(
    select(SprintStory).where(SprintStory.sprint_id == sprint.sprint_id)
).all()
existing_story_ids = {link.story_id for link in existing_links}
for link in existing_links:
    session.delete(link)

for story in validated_plan.selected_stories:
    session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story.story_id))
    if story.story_id in existing_story_ids:
        continue
    for task_spec in story.tasks:
        session.add(
            Task(
                story_id=story.story_id,
                description=task_spec.description,
                metadata_json=serialize_task_metadata(
                    metadata_from_structured_task(task_spec)
                ),
            )
        )
```

- [ ] **Step 5: Exclude stories already committed to open sprints from sprint candidates**

```python
open_story_ids = {
    row[0]
    for row in session.exec(
        select(SprintStory.story_id)
        .join(Sprint, Sprint.sprint_id == SprintStory.sprint_id)
        .where(
            Sprint.product_id == product_id,
            Sprint.status.in_([SprintStatus.PLANNED, SprintStatus.ACTIVE]),
        )
    ).all()
}

excluded_open_sprint = 0
for story in stories:
    if story.story_id in open_story_ids:
        excluded_open_sprint += 1
        continue
    if bool(story.is_superseded):
        excluded_superseded += 1
        continue
    if not bool(story.is_refined):
        excluded_non_refined += 1
        continue
    refined.append(story)

return {
    "success": True,
    "count": len(candidate_list),
    "stories": candidate_list,
    "excluded_counts": {
        "non_refined": excluded_non_refined,
        "superseded": excluded_superseded,
        "open_sprint": excluded_open_sprint,
    },
    "message": (
        f"Found {len(candidate_list)} refined sprint candidate(s) in backlog "
        f"(excluded non-refined={excluded_non_refined}, superseded={excluded_superseded}, "
        f"open_sprint={excluded_open_sprint})."
    ),
}
```

- [ ] **Step 6: Map lifecycle save conflicts to `409` in the sprint save endpoint**

```python
if not result.get("success"):
    error_code = result.get("error_code")
    detail = result.get("error", "Failed to save sprint plan")
    if error_code == "STORY_ALREADY_IN_OPEN_SPRINT":
        raise HTTPException(status_code=409, detail=detail)
    raise HTTPException(status_code=500, detail=detail)
```

- [ ] **Step 7: Preserve the new excluded count in normalized sprint input loading**

```python
return {
    "success": True,
    "count": len(stories),
    "stories": stories,
    "excluded_counts": raw_result.get("excluded_counts") or {},
    "message": raw_result.get("message") or f"Found {len(stories)} sprint candidates.",
}
```

- [ ] **Step 8: Run the persistence and candidate tests again**

Run: `pytest tests/test_sprint_planner_tools.py tests/test_api_sprint_flow.py -q`

Expected: PASS

- [ ] **Step 9: Commit the planned-sprint persistence work**

```bash
git add orchestrator_agent/agent_tools/sprint_planner_tool/tools.py \
  tools/orchestrator_tools.py \
  services/sprint_input.py \
  api.py \
  tests/test_sprint_planner_tools.py \
  tests/test_api_sprint_flow.py
git commit -m "feat: enforce open sprint lifecycle rules"
```

### Task 3: Add Lightweight Sprint List, Selected-Sprint Detail, and Shell-State Normalization

**Files:**
- Modify: `/Users/aaat/projects/agileforge/api.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write failing API tests for runtime summary, selected-sprint detail, and legacy shell-state normalization**

```python
def test_list_sprints_returns_runtime_summary_and_allowed_actions(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, planned_sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=False,
        created_title="Planned Sprint",
    )
    team = session.exec(select(Team).where(Team.name == f"Team {project_id}")).first()
    active_story = UserStory(
        product_id=project_id,
        title="Active Sprint Story",
        story_description="As a user, I want active sprint coverage",
        acceptance_criteria="- AC",
    )
    session.add(active_story)
    session.flush()

    active_sprint = Sprint(
        goal="Active Sprint Goal",
        start_date=date(2026, 4, 1),
        end_date=date(2026, 4, 15),
        status=SprintStatus.ACTIVE,
        started_at=datetime(2026, 4, 1, 9, 0, tzinfo=timezone.utc),
        product_id=project_id,
        team_id=team.team_id,
    )
    session.add(active_sprint)
    session.flush()
    session.add(SprintStory(sprint_id=active_sprint.sprint_id, story_id=active_story.story_id))
    session.commit()

    response = client.get(f"/api/projects/{project_id}/sprints")

    assert response.status_code == 200
    payload = response.json()["data"]
    planned_item = next(item for item in payload["items"] if item["id"] == planned_sprint_id)
    assert payload["runtime_summary"]["active_sprint_id"] == active_sprint.sprint_id
    assert payload["runtime_summary"]["planned_sprint_id"] == planned_sprint_id
    assert planned_item["allowed_actions"]["can_start"] is False
    assert "selected_stories" not in planned_item


def test_get_sprint_detail_returns_selected_stories_and_history_fidelity(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=True,
        created_title="Detail Sprint",
    )

    response = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}")

    assert response.status_code == 200
    payload = response.json()["data"]["sprint"]
    assert payload["id"] == sprint_id
    assert payload["history_fidelity"] == "derived"
    assert len(payload["selected_stories"]) == 1


def test_project_state_normalizes_legacy_sprint_complete(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)
    workflow.states[str(project_id)] = {
        "fsm_state": "SPRINT_COMPLETE",
        "setup_status": "passed",
    }

    response = client.get(f"/api/projects/{project_id}/state")

    assert response.status_code == 200
    assert response.json()["data"]["fsm_state"] == "SPRINT_PERSISTENCE"
```

- [ ] **Step 2: Run the sprint read-side tests to verify they fail**

Run: `pytest tests/test_api_sprint_flow.py -q`

Expected: FAIL because the list response still embeds full sprint detail, there is no selected-sprint detail endpoint, and legacy shell state is not normalized.

- [ ] **Step 3: Normalize legacy `SPRINT_COMPLETE` to planning-complete shell state**

```python
def _normalize_shell_fsm_state(value: Optional[str]) -> str:
    state = _normalize_fsm_state(value)
    if state == OrchestratorState.SPRINT_COMPLETE.value:
        return OrchestratorState.SPRINT_PERSISTENCE.value
    return state


def _effective_project_state(project: Any, raw_state: Dict[str, Any]) -> Dict[str, Any]:
    state = dict(raw_state)
    blocker = _setup_blocker(project)
    spec_path = getattr(project, "spec_file_path", None)

    if blocker:
        state["fsm_state"] = OrchestratorState.SETUP_REQUIRED.value
        state["setup_status"] = "failed"
        existing_error = state.get("setup_error")
        state["setup_error"] = existing_error or blocker
    else:
        state["fsm_state"] = _normalize_shell_fsm_state(state.get("fsm_state"))
        state.setdefault("setup_status", "passed")
        state.setdefault("setup_error", None)
```

- [ ] **Step 4: Split sprint serialization into lightweight list items and selected-sprint detail**

```python
def _history_fidelity(sprint: Sprint) -> str:
    return "snapshotted" if bool(sprint.close_snapshot_json) else "derived"


def _allowed_actions_for_sprint(
    sprint: Sprint,
    *,
    runtime_summary: Dict[str, Any],
) -> Dict[str, Any]:
    is_planned = sprint.status == SprintStatus.PLANNED
    is_active = sprint.status == SprintStatus.ACTIVE
    can_start = bool(is_planned and runtime_summary["active_sprint_id"] is None)
    can_close = bool(is_active)
    can_modify_planned = bool(is_planned)
    return {
        "can_start": can_start,
        "start_disabled_reason": None if can_start else "Only planned sprints without another active sprint can be started.",
        "can_close": can_close,
        "close_disabled_reason": None if can_close else "Only active sprints can be closed.",
        "can_modify_planned": can_modify_planned,
        "modify_disabled_reason": None if can_modify_planned else "Only planned sprints can be edited in place.",
    }


def _serialize_sprint_list_item(
    sprint: Sprint,
    *,
    runtime_summary: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "id": sprint.sprint_id,
        "goal": sprint.goal,
        "status": sprint.status.value,
        "created_at": _serialize_temporal(sprint.created_at),
        "updated_at": _serialize_temporal(sprint.updated_at),
        "started_at": _serialize_temporal(sprint.started_at),
        "completed_at": _serialize_temporal(sprint.completed_at),
        "start_date": _serialize_temporal(sprint.start_date),
        "end_date": _serialize_temporal(sprint.end_date),
        "team_id": sprint.team_id,
        "team_name": sprint.team.name if sprint.team else None,
        "story_count": len(sprint.stories),
        "history_fidelity": _history_fidelity(sprint),
        "allowed_actions": _allowed_actions_for_sprint(
            sprint,
            runtime_summary=runtime_summary,
        ),
    }
```

- [ ] **Step 5: Add the selected-sprint detail endpoint and runtime summary**

```python
def _build_sprint_runtime_summary(sprints: List[Sprint]) -> Dict[str, Any]:
    active = next((s for s in sprints if s.status == SprintStatus.ACTIVE), None)
    planned = next((s for s in sprints if s.status == SprintStatus.PLANNED), None)
    completed = sorted(
        [s for s in sprints if s.status == SprintStatus.COMPLETED],
        key=lambda sprint: (sprint.completed_at or sprint.updated_at or sprint.created_at),
        reverse=True,
    )
    return {
        "active_sprint_id": active.sprint_id if active else None,
        "planned_sprint_id": planned.sprint_id if planned else None,
        "latest_completed_sprint_id": completed[0].sprint_id if completed else None,
        "can_create_next_sprint": planned is None,
        "create_next_sprint_disabled_reason": None if planned is None else "A planned sprint already exists. Modify it instead of creating another.",
    }


def _list_saved_sprints(project_id: int) -> Dict[str, Any]:
    with Session(get_engine()) as session:
        sprints = session.exec(
            _saved_sprint_query()
            .where(Sprint.product_id == project_id)
            .order_by(Sprint.created_at.desc())
        ).all()
        runtime_summary = _build_sprint_runtime_summary(sprints)
        items = [
            _serialize_sprint_list_item(
                sprint,
                runtime_summary=runtime_summary,
            )
            for sprint in sprints
        ]
        return {
            "items": items,
            "runtime_summary": runtime_summary,
        }


@app.get("/api/projects/{project_id}/sprints")
async def list_project_sprints(project_id: int):
    payload = _list_saved_sprints(project_id)
    return {
        "status": "success",
        "data": {
            "items": payload["items"],
            "count": len(payload["items"]),
            "runtime_summary": payload["runtime_summary"],
        },
    }


@app.get("/api/projects/{project_id}/sprints/{sprint_id}")
async def get_project_sprint(project_id: int, sprint_id: int):
    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        all_sprints = session.exec(
            _saved_sprint_query().where(Sprint.product_id == project_id)
        ).all()
        runtime_summary = _build_sprint_runtime_summary(all_sprints)
        return {
            "status": "success",
            "data": {
                "sprint": _serialize_sprint_detail(
                    sprint,
                    runtime_summary=runtime_summary,
                ),
                "runtime_summary": runtime_summary,
            },
        }
```

- [ ] **Step 6: Enforce start invariants in the API start endpoint**

```python
other_active = session.exec(
    select(Sprint).where(
        Sprint.product_id == project_id,
        Sprint.status == SprintStatus.ACTIVE,
        Sprint.sprint_id != sprint_id,
    )
).first()
if other_active:
    raise HTTPException(
        status_code=409,
        detail="Another sprint is already active for this project.",
    )

if sprint.status == SprintStatus.COMPLETED:
    raise HTTPException(status_code=409, detail="Completed sprints cannot be restarted.")

if sprint.status == SprintStatus.ACTIVE and sprint.started_at is not None:
    all_sprints = session.exec(
        _saved_sprint_query().where(Sprint.product_id == project_id)
    ).all()
    runtime_summary = _build_sprint_runtime_summary(all_sprints)
    return {
        "status": "success",
        "data": {
            "sprint": _serialize_sprint_detail(
                sprint,
                runtime_summary=runtime_summary,
            )
        },
    }
```

- [ ] **Step 7: Run the sprint read-side tests again**

Run: `pytest tests/test_api_sprint_flow.py -q`

Expected: PASS

- [ ] **Step 8: Commit the sprint read-side API work**

```bash
git add api.py tests/test_api_sprint_flow.py
git commit -m "feat: add sprint runtime summary and detail api"
```

### Task 4: Implement Sprint Close Preview, Close Confirmation, and Snapshot Serialization

**Files:**
- Modify: `/Users/aaat/projects/agileforge/utils/schemes.py`
- Modify: `/Users/aaat/projects/agileforge/api.py`
- Create: `/Users/aaat/projects/agileforge/tests/test_api_sprint_close.py`

- [ ] **Step 1: Write failing API tests for sprint close preview and close confirmation**

```python
def test_get_sprint_close_returns_guidance_for_non_active_sprint(session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_saved_sprint

    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=False,
        created_title="Planned Sprint",
    )

    response = client.get(f"/api/projects/{project_id}/sprints/{sprint_id}/close")

    assert response.status_code == 200
    payload = response.json()
    assert payload["close_eligible"] is False
    assert payload["ineligible_reason"] == "Only active sprints can be closed."


def test_post_sprint_close_persists_snapshot_and_completion_event(session, monkeypatch):
    from tests.test_api_sprint_flow import _build_client, _seed_saved_sprint

    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id = _seed_saved_sprint(
        session,
        repo,
        started=True,
        created_title="Closable Sprint",
    )

    story = session.exec(select(UserStory).where(UserStory.product_id == project_id)).first()
    story.status = StoryStatus.DONE
    story.completed_at = datetime.now(timezone.utc)
    session.add(story)
    session.commit()

    response = client.post(
        f"/api/projects/{project_id}/sprints/{sprint_id}/close",
        json={
            "completion_notes": "Closed after review.",
            "follow_up_notes": "Carry remaining backlog forward manually.",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["current_status"] == SprintStatus.COMPLETED.value
    assert payload["history_fidelity"] == "snapshotted"

    sprint = session.get(Sprint, sprint_id)
    assert sprint.completed_at is not None
    assert sprint.close_snapshot_json is not None

    event = session.exec(
        select(WorkflowEvent).where(
            WorkflowEvent.event_type == WorkflowEventType.SPRINT_COMPLETED
        )
    ).first()
    assert event is not None
```

- [ ] **Step 2: Run the sprint close tests to verify they fail**

Run: `pytest tests/test_api_sprint_close.py -q`

Expected: FAIL because sprint close request/response models and endpoints do not exist yet.

- [ ] **Step 3: Add typed sprint-close request and response models**

```python
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
```

- [ ] **Step 4: Build sprint close preview helpers and the `GET /close` endpoint**

```python
def _build_sprint_close_readiness(stories: List[UserStory]) -> SprintCloseReadiness:
    summaries: List[SprintCloseStorySummary] = []
    completed_story_count = 0
    unfinished_story_ids: List[int] = []

    for story in stories:
        total_tasks, done_tasks, cancelled_tasks, all_actionable_done = _story_task_progress(story.tasks)
        completion_state = "completed" if story.status == StoryStatus.DONE else "unfinished"
        if completion_state == "completed":
            completed_story_count += 1
        else:
            unfinished_story_ids.append(int(story.story_id))
        summaries.append(
            SprintCloseStorySummary(
                story_id=int(story.story_id),
                story_title=story.title,
                story_status=story.status.value,
                total_tasks=total_tasks,
                done_tasks=done_tasks,
                cancelled_tasks=cancelled_tasks,
                completion_state=completion_state,
            )
        )

    return SprintCloseReadiness(
        completed_story_count=completed_story_count,
        open_story_count=len(summaries) - completed_story_count,
        unfinished_story_ids=unfinished_story_ids,
        stories=summaries,
    )


@app.get("/api/projects/{project_id}/sprints/{sprint_id}/close", response_model=SprintCloseReadResponse)
def get_sprint_close(project_id: int, sprint_id: int):
    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")

        readiness = _build_sprint_close_readiness(list(sprint.stories))
        close_eligible = sprint.status == SprintStatus.ACTIVE
        ineligible_reason = None if close_eligible else "Only active sprints can be closed."

        return SprintCloseReadResponse(
            success=True,
            sprint_id=sprint_id,
            current_status=sprint.status.value,
            completed_at=sprint.completed_at,
            readiness=readiness,
            close_eligible=close_eligible,
            ineligible_reason=ineligible_reason,
            history_fidelity=_history_fidelity(sprint),
        )
```

- [ ] **Step 5: Implement `POST /close` to stamp completion and snapshot the sprint**

```python
@app.post("/api/projects/{project_id}/sprints/{sprint_id}/close", response_model=SprintCloseReadResponse)
def post_sprint_close(project_id: int, sprint_id: int, req: SprintCloseWriteRequest):
    with Session(get_engine()) as session:
        sprint = _get_saved_sprint(session, project_id, sprint_id)
        if not sprint:
            raise HTTPException(status_code=404, detail="Sprint not found")
        if sprint.status != SprintStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="Only active sprints can be closed.")

        readiness = _build_sprint_close_readiness(list(sprint.stories))
        snapshot = {
            "closed_at": _now_iso(),
            "completion_notes": req.completion_notes,
            "follow_up_notes": req.follow_up_notes,
            "completed_story_count": readiness.completed_story_count,
            "open_story_count": readiness.open_story_count,
            "unfinished_story_ids": readiness.unfinished_story_ids,
            "stories": [story.model_dump(mode="json") for story in readiness.stories],
        }

        sprint.status = SprintStatus.COMPLETED
        sprint.completed_at = datetime.now(timezone.utc)
        sprint.close_snapshot_json = json.dumps(snapshot)
        session.add(sprint)
        session.add(
            WorkflowEvent(
                event_type=WorkflowEventType.SPRINT_COMPLETED,
                product_id=project_id,
                sprint_id=sprint_id,
                session_id=str(project_id),
                event_metadata=json.dumps(snapshot),
            )
        )
        session.commit()

    return SprintCloseReadResponse(
        success=True,
        sprint_id=sprint_id,
        current_status=SprintStatus.COMPLETED.value,
        completed_at=sprint.completed_at,
        readiness=readiness,
        close_eligible=False,
        ineligible_reason="Sprint is already completed.",
        history_fidelity="snapshotted",
        close_snapshot=snapshot,
    )
```

- [ ] **Step 6: Teach sprint detail serialization to surface snapshots and fidelity**

```python
def _serialize_sprint_detail(
    sprint: Sprint,
    *,
    runtime_summary: Dict[str, Any],
) -> Dict[str, Any]:
    close_snapshot = None
    if sprint.close_snapshot_json:
        close_snapshot = json.loads(sprint.close_snapshot_json)

    return {
        "id": sprint.sprint_id,
        "goal": sprint.goal,
        "status": sprint.status.value,
        "started_at": _serialize_temporal(sprint.started_at),
        "completed_at": _serialize_temporal(sprint.completed_at),
        "history_fidelity": _history_fidelity(sprint),
        "allowed_actions": _allowed_actions_for_sprint(
            sprint,
            runtime_summary=runtime_summary,
        ),
        "selected_stories": [_serialize_sprint_story(story) for story in sprint.stories],
        "close_snapshot": close_snapshot,
    }
```

- [ ] **Step 7: Run the sprint close tests again**

Run: `pytest tests/test_api_sprint_close.py -q`

Expected: PASS

- [ ] **Step 8: Commit the sprint close flow**

```bash
git add utils/schemes.py \
  api.py \
  tests/test_api_sprint_close.py
git commit -m "feat: add sprint close flow"
```

### Task 5: Update the Project Shell and Sprint Workspace to Use Canonical Runtime State

**Files:**
- Modify: `/Users/aaat/projects/agileforge/frontend/project.js`
- Modify: `/Users/aaat/projects/agileforge/frontend/project.html`
- Create: `/Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs`
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py`
- Modify: `/Users/aaat/projects/agileforge/tests/test_api_sprint_close.py`

- [ ] **Step 1: Write failing frontend tests for canonical status handling and landing priority**

```javascript
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import test from 'node:test';

const projectJsPath = path.resolve(import.meta.dirname, '../frontend/project.js');
const projectJsSource = fs.readFileSync(projectJsPath, 'utf8');

function loadFunction(name, pattern) {
    const match = projectJsSource.match(pattern);
    assert.ok(match, `${name} should exist in frontend/project.js`);
    return new Function(`${match[0]}; return ${name};`)();
}

test('getSprintMode uses canonical status instead of started_at inference', () => {
    const getSprintMode = loadFunction(
        'getSprintMode',
        /function getSprintMode\(savedSprint\) \{[\s\S]*?\n\}/,
    );

    assert.equal(getSprintMode({ status: 'Completed', started_at: '2026-03-01T09:00:00Z' }), 'completed');
    assert.equal(getSprintMode({ status: 'Active', started_at: null }), 'active');
    assert.equal(getSprintMode({ status: 'Planned', started_at: '2026-03-01T09:00:00Z' }), 'planned');
});

test('chooseLandingSprint prefers active, then planned, then latest completed', () => {
    const chooseLandingSprint = loadFunction(
        'chooseLandingSprint',
        /function chooseLandingSprint\(\) \{[\s\S]*?\n\}/,
    );

    global.savedSprints = [
        { id: 3, status: 'Completed', completed_at: '2026-03-12T12:00:00Z' },
        { id: 2, status: 'Planned', created_at: '2026-03-13T12:00:00Z' },
        { id: 1, status: 'Active', started_at: '2026-03-14T09:00:00Z' },
    ];

    assert.equal(chooseLandingSprint().id, 1);
});
```

- [ ] **Step 2: Run the frontend runtime tests to verify they fail**

Run: `node --test tests/test_sprint_workspace_display.mjs`

Expected: FAIL because `getSprintMode()` still infers from `started_at` and there is no completed-sprint landing logic.

- [ ] **Step 3: Track runtime summary plus selected-sprint detail separately in `project.js`**

```javascript
let sprintRuntimeSummary = null;
let currentSprintDetail = null;

function getSprintMode(savedSprint) {
    const normalized = String(savedSprint?.status || 'Planned').toLowerCase();
    if (normalized === 'completed') return 'completed';
    if (normalized === 'active') return 'active';
    return 'planned';
}

async function loadSavedSprints() {
    if (!selectedProjectId) {
        savedSprints = [];
        sprintRuntimeSummary = null;
        currentSprintId = null;
        currentSprintDetail = null;
        sprintMode = null;
        renderOverviewPanel();
        renderSprintSavedWorkspace();
        return [];
    }

    const response = await fetch(`/api/projects/${selectedProjectId}/sprints`);
    const data = await response.json();
    savedSprints = Array.isArray(data.data?.items) ? data.data.items : [];
    sprintRuntimeSummary = data.data?.runtime_summary || null;
    await loadSprintDetail(currentSprintId || chooseLandingSprint()?.id || null);
    renderOverviewPanel();
    renderSprintSavedWorkspace();
    updateProjectNavUI();
    return savedSprints;
}

async function loadSprintDetail(sprintId) {
    if (!selectedProjectId || !sprintId) {
        currentSprintDetail = null;
        return null;
    }
    const response = await fetch(`/api/projects/${selectedProjectId}/sprints/${sprintId}`);
    const data = await response.json();
    currentSprintDetail = data.data?.sprint || null;
    sprintRuntimeSummary = data.data?.runtime_summary || sprintRuntimeSummary;
    currentSprintId = currentSprintDetail?.id || sprintId;
    sprintMode = currentSprintDetail ? getSprintMode(currentSprintDetail) : null;
    return currentSprintDetail;
}
```

- [ ] **Step 4: Update overview and sprint workspace rendering to use `status`, `allowed_actions`, and completed history**

```javascript
function renderOverviewPanel() {
    const container = document.getElementById('overview-panel-content');
    if (!container) return;

    const planningComplete = isPlanningCompleteState(activeFsmState);
    const activeSprintId = sprintRuntimeSummary?.active_sprint_id || null;
    const plannedSprintId = sprintRuntimeSummary?.planned_sprint_id || null;
    const latestCompletedSprintId = sprintRuntimeSummary?.latest_completed_sprint_id || null;

    const primaryActionHtml = activeSprintId
        ? `<button type="button" onclick="selectSavedSprintById(${activeSprintId})" class="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-sky-700">
                <span class="material-symbols-outlined text-sm">play_circle</span>
                Open Active Sprint
           </button>`
        : plannedSprintId
            ? `<button type="button" onclick="selectSavedSprintById(${plannedSprintId})" class="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-sky-700">
                    <span class="material-symbols-outlined text-sm">schedule</span>
                    Open Planned Sprint
               </button>`
            : `<button type="button" onclick="openSprintPlanner()" class="inline-flex items-center gap-2 rounded-lg bg-sky-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-sky-700">
                    <span class="material-symbols-outlined text-sm">add_task</span>
                    Create Next Sprint
               </button>`;

    container.innerHTML = `
        <div class="space-y-6">
            <div class="rounded-2xl border border-sky-200 bg-gradient-to-r from-sky-50 via-white to-cyan-50 p-6 shadow-sm">
                <h3 class="text-2xl font-black text-slate-800">Planning is ${planningComplete ? 'complete' : 'still in progress'}</h3>
                <p class="mt-1 text-sm text-slate-600">${planningComplete ? 'Sprint runtime continues in the sprint workspace.' : 'Continue the planning pipeline before sprint runtime begins.'}</p>
                <div class="mt-4 flex flex-wrap gap-3">${primaryActionHtml}</div>
            </div>
            <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div class="text-[10px] font-black uppercase tracking-[0.18em] text-slate-400">Planning Status</div>
                    <div class="mt-3 text-xl font-black text-slate-800">${planningComplete ? 'Ready for Iteration' : 'In Progress'}</div>
                </div>
                <div class="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
                    <div class="text-[10px] font-black uppercase tracking-[0.18em] text-slate-400">Sprint Runtime</div>
                    <div class="mt-3 text-xl font-black text-slate-800">${activeSprintId ? 'Sprint Active' : plannedSprintId ? 'Planned Sprint Ready' : latestCompletedSprintId ? 'Last Sprint Completed' : 'No Sprint Yet'}</div>
                </div>
            </div>
        </div>
    `;
}
```

- [ ] **Step 5: Add close-flow UI hooks and completed-sprint rendering**

```html
<div class="flex flex-wrap gap-3">
    <button id="btn-start-sprint" type="button" onclick="startCurrentSprint()"
        class="hidden inline-flex items-center gap-2 rounded-lg bg-teal-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-teal-700">
        <span class="material-symbols-outlined text-sm">play_circle</span>
        Start Sprint
    </button>
    <button id="btn-close-sprint" type="button" onclick="openSprintClosePanel()"
        class="hidden inline-flex items-center gap-2 rounded-lg bg-emerald-600 px-5 py-2.5 text-sm font-bold text-white shadow-sm transition-colors hover:bg-emerald-700">
        <span class="material-symbols-outlined text-sm">task_alt</span>
        Close Sprint
    </button>
</div>

<div id="sprint-close-panel" class="hidden rounded-2xl border border-emerald-200 bg-emerald-50 p-5 shadow-sm">
    <div class="flex items-start justify-between gap-4">
        <div>
            <h4 class="text-sm font-black text-emerald-900">Sprint Close Readiness</h4>
            <p id="sprint-close-summary" class="mt-1 text-[12px] text-emerald-800"></p>
        </div>
        <button id="btn-confirm-sprint-close" type="button" onclick="confirmSprintClose()"
            class="inline-flex items-center gap-2 rounded-lg bg-emerald-700 px-4 py-2 text-sm font-bold text-white shadow-sm transition-colors hover:bg-emerald-800">
            <span class="material-symbols-outlined text-sm">check_circle</span>
            Confirm Close
        </button>
    </div>
    <textarea id="sprint-close-notes" rows="3"
        class="mt-4 w-full rounded-xl border border-emerald-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-inner"
        placeholder="Add sprint close notes..."></textarea>
    <textarea id="sprint-follow-up-notes" rows="3"
        class="mt-3 w-full rounded-xl border border-emerald-200 bg-white px-4 py-3 text-sm text-slate-800 shadow-inner"
        placeholder="Optional follow-up or rollover notes..."></textarea>
</div>
```

```javascript
async function openSprintClosePanel() {
    if (!selectedProjectId || !currentSprintId) return;
    const response = await fetch(`/api/projects/${selectedProjectId}/sprints/${currentSprintId}/close`);
    const data = await response.json();
    const panel = document.getElementById('sprint-close-panel');
    const summary = document.getElementById('sprint-close-summary');
    const confirmButton = document.getElementById('btn-confirm-sprint-close');

    panel.classList.remove('hidden');
    summary.innerText = data.close_eligible
        ? `${data.readiness.completed_story_count} stories completed, ${data.readiness.open_story_count} still open.`
        : data.ineligible_reason || 'Sprint cannot be closed yet.';
    confirmButton.disabled = !data.close_eligible;
}

async function confirmSprintClose() {
    const completionNotes = document.getElementById('sprint-close-notes')?.value?.trim() || '';
    const followUpNotes = document.getElementById('sprint-follow-up-notes')?.value?.trim() || '';
    const response = await fetch(`/api/projects/${selectedProjectId}/sprints/${currentSprintId}/close`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            completion_notes: completionNotes,
            follow_up_notes: followUpNotes || null,
        }),
    });
    if (response.status >= 400) {
        const body = await response.json().catch(() => null);
        throw new Error(body?.detail || 'Failed to close sprint.');
    }
    await loadSavedSprints();
    await fetchProjectFSMState(selectedProjectId, { preserveView: true });
    selectSavedSprintById(currentSprintId);
}
```

- [ ] **Step 6: Run the frontend and targeted API tests**

Run: `node --test tests/test_sprint_workspace_display.mjs && pytest tests/test_api_sprint_flow.py tests/test_api_sprint_close.py -q`

Expected: PASS

- [ ] **Step 7: Commit the project shell and sprint workspace update**

```bash
git add frontend/project.js \
  frontend/project.html \
  tests/test_sprint_workspace_display.mjs \
  tests/test_api_sprint_flow.py \
  tests/test_api_sprint_close.py
git commit -m "feat: align sprint workspace with runtime lifecycle"
```
