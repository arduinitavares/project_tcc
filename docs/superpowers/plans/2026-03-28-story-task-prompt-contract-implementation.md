# Story and Task Prompt Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split story-level and task-level prompt contracts so story prompts bootstrap sessions, task prompts use planner-generated task checklists instead of story acceptance criteria, and the UI only offers executable task prompts when checklist-backed task context exists.

**Architecture:** Extend structured task metadata with planner-generated `checklist_items`, validate those items deterministically during sprint planning, and surface them through sprint/task APIs as executable task-local contracts. Introduce a new canonical `story_packet.v1` for session bootstrap, bump task packets to `task_packet.v2` so task renderers stop treating story acceptance criteria as the task done checklist, and reuse the existing task execution log model for task evidence instead of adding new persistence tables.

**Tech Stack:** FastAPI, SQLModel, Pydantic, vanilla JavaScript frontend, pytest

---

## File Map

- Modify: `utils/task_metadata.py`
  Responsibility: add persisted `checklist_items` to task metadata and sprint planner structured task output.
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt`
  Responsibility: teach the planner to generate task-local checklist items and forbid copying/paraphrasing story AC.
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py`
  Responsibility: validate checklist presence/shape and enforce deterministic anti-scope-leak guardrails.
- Modify: `services/sprint_runtime.py`
  Responsibility: apply the new checklist-aware quality gate during runtime validation.
- Modify: `api.py`
  Responsibility: expose checklist-aware sprint task summaries, build `task_packet.v2`, build `story_packet.v1`, and add the story packet endpoint.
- Modify: `services/packet_renderer.py`
  Responsibility: split story-bootstrap rendering from task-delta rendering and update static prompt text.
- Modify: `frontend/project.js`
  Responsibility: add `Copy Story Prompt`, gate `Copy Task Prompt` on executability, and relabel task execution UX to match task-checklist semantics.
- Modify: `docs/task-packet-vision.md`
  Responsibility: document the story-bootstrap/task-delta model.
- Create: `docs/task-packet-schema-v2.md`
  Responsibility: document the new task packet contract.
- Create: `docs/story-packet-schema-v1.md`
  Responsibility: document the new story packet contract.
- Modify: `tests/test_sprint_planner_schemes.py`
  Responsibility: validate checklist-aware planner output and anti-duplication rules.
- Modify: `tests/test_sprint_planner_tools.py`
  Responsibility: verify persisted task metadata includes checklist items.
- Modify: `tests/test_sprint_runtime.py`
  Responsibility: keep runtime validation aligned with checklist-aware planner output.
- Modify: `tests/test_packet_renderer.py`
  Responsibility: verify story vs. task prompt rendering semantics.
- Modify: `tests/test_api_sprint_flow.py`
  Responsibility: verify sprint summary serialization, task packet v2 payloads, story packet v1 payloads, and rendered prompt text.

### Task 1: Add Planner-Generated Task Checklists to Structured Task Metadata

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/utils/task_metadata.py`
- Modify: `/Users/aaat/projects/project_tcc/orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt`
- Modify: `/Users/aaat/projects/project_tcc/orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_sprint_planner_schemes.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_sprint_planner_tools.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_sprint_runtime.py`

- [ ] **Step 1: Write failing schema tests for checklist-aware planner output**

```python
def test_output_schema_requires_checklist_items_on_structured_tasks():
    payload = _build_output_payload()
    payload["selected_stories"][0]["tasks"][0]["checklist_items"] = [
        "Persist auth schema draft",
        "Attach migration artifact reference",
    ]
    payload["selected_stories"][0]["tasks"][1]["checklist_items"] = [
        "Render login UI in the sprint demo build",
    ]

    model = SprintPlannerOutput.model_validate(payload)
    assert model.selected_stories[0].tasks[0].checklist_items == [
        "Persist auth schema draft",
        "Attach migration artifact reference",
    ]


def test_validate_task_decomposition_quality_rejects_story_ac_duplicates():
    payload = _build_output_payload()
    payload["selected_stories"][0]["tasks"][0]["checklist_items"] = ["include user_id"]
    payload["selected_stories"][0]["tasks"][1]["checklist_items"] = ["reject invalid payloads"]
    model = SprintPlannerOutput.model_validate(payload)

    errors = validate_task_decomposition_quality(
        model,
        include_task_decomposition=True,
        has_acceptance_criteria_by_story={101: True},
        acceptance_criteria_items_by_story={
            101: ["include user_id", "reject invalid payloads"],
        },
    )

    assert "duplicates story acceptance criteria" in errors[0]
```

- [ ] **Step 2: Run checklist-aware planner tests to verify they fail**

Run: `pytest tests/test_sprint_planner_schemes.py tests/test_sprint_planner_tools.py tests/test_sprint_runtime.py -q`

Expected: FAIL with missing `checklist_items` fields and/or the old `validate_task_decomposition_quality` signature.

- [ ] **Step 3: Extend persisted task metadata and structured task output with `checklist_items`**

```python
class TaskMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Keep task_metadata.v1 so existing rows continue to parse with defaults.
    version: Literal["task_metadata.v1"] = TASK_METADATA_VERSION
    task_kind: TaskKind = "other"
    artifact_targets: List[str] = Field(default_factory=list)
    workstream_tags: List[str] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)
    relevant_invariant_ids: List[str] = Field(default_factory=list)

    @field_validator(
        "artifact_targets",
        "workstream_tags",
        "checklist_items",
        "relevant_invariant_ids",
        mode="before",
    )
    @classmethod
    def _validate_lists(cls, value: Any) -> List[str]:
        return _normalize_string_list(value)


class StructuredTaskSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1, description="Concrete task description.")
    task_kind: TaskKind = Field(description="Primary task category.")
    artifact_targets: List[str] = Field(default_factory=list)
    workstream_tags: List[str] = Field(default_factory=list)
    checklist_items: List[str] = Field(default_factory=list)
    relevant_invariant_ids: List[str] = Field(default_factory=list)
```

- [ ] **Step 4: Update `metadata_from_structured_task` and sprint planner instructions**

```python
def metadata_from_structured_task(task: StructuredTaskSpec) -> TaskMetadata:
    return TaskMetadata(
        task_kind=task.task_kind,
        artifact_targets=list(task.artifact_targets),
        workstream_tags=list(task.workstream_tags),
        checklist_items=list(task.checklist_items),
        relevant_invariant_ids=list(task.relevant_invariant_ids),
    )
```

```text
* `checklist_items`: REQUIRED for executable work (usually 1-4). Each item must describe a
  task-local completion condition or observable outcome. Do NOT copy or paraphrase story
  acceptance criteria into task checklists.
```

- [ ] **Step 5: Add deterministic checklist guardrails to `validate_task_decomposition_quality`**

```python
def validate_task_decomposition_quality(
    output: "SprintPlannerOutput",
    *,
    include_task_decomposition: bool,
    has_acceptance_criteria_by_story: Dict[int, bool],
    acceptance_criteria_items_by_story: Dict[int, List[str]],
) -> List[str]:
    errors: List[str] = []

    broad_completion_phrases = {
        "completethestory",
        "satisfyallacceptancecriteria",
        "meetallstorycriteria",
    }

    for story in output.selected_stories:
        story_ac_norm = {
            re.sub(r"[^a-z0-9]", "", item.lower())
            for item in acceptance_criteria_items_by_story.get(story.story_id, [])
        }
        for task in story.tasks:
            if not task.checklist_items:
                errors.append(
                    f"Story {story.story_id} task '{task.description}': Must specify at least one checklist_item."
                )
            for item in task.checklist_items:
                norm_item = re.sub(r"[^a-z0-9]", "", item.lower())
                if norm_item in story_ac_norm:
                    errors.append(
                        f"Story {story.story_id} task '{task.description}': checklist item '{item}' duplicates story acceptance criteria."
                    )
                if norm_item in broad_completion_phrases:
                    errors.append(
                        f"Story {story.story_id} task '{task.description}': checklist item '{item}' is too broad."
                    )
```

- [ ] **Step 6: Update runtime wiring to pass story AC into the quality gate**

```python
acceptance_criteria_items_by_story = {
    story.story_id: list(story.acceptance_criteria_items)
    for story in payload.available_stories
}
decomp_errors = validate_task_decomposition_quality(
    output_model,
    include_task_decomposition=include_task_decomposition,
    has_acceptance_criteria_by_story=has_acceptance_criteria_by_story,
    acceptance_criteria_items_by_story=acceptance_criteria_items_by_story,
)
```

- [ ] **Step 7: Run checklist-aware planner tests again**

Run: `pytest tests/test_sprint_planner_schemes.py tests/test_sprint_planner_tools.py tests/test_sprint_runtime.py -q`

Expected: PASS

- [ ] **Step 8: Commit planner checklist support**

```bash
git add utils/task_metadata.py \
  orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt \
  orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py \
  services/sprint_runtime.py \
  tests/test_sprint_planner_schemes.py \
  tests/test_sprint_planner_tools.py \
  tests/test_sprint_runtime.py
git commit -m "feat: add planner-generated task checklists"
```

### Task 2: Surface Checklist-Aware Tasks in Sprint Summaries

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/api.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write a failing API serialization test for `checklist_items` and `is_executable`**

```python
def test_list_sprints_returns_checklist_aware_task_objects(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
        task_metadata=TaskMetadata(
            task_kind="design",
            artifact_targets=["sequence diagram"],
            workstream_tags=["architecture"],
            checklist_items=["Capture original entry flow", "Store diagram source"],
            relevant_invariant_ids=[],
        ),
    )

    response = client.get(f"/api/projects/{project_id}/sprints")
    task_obj = response.json()["data"]["items"][0]["selected_stories"][0]["tasks"][0]

    assert task_obj["checklist_items"] == [
        "Capture original entry flow",
        "Store diagram source",
    ]
    assert task_obj["is_executable"] is True
```

- [ ] **Step 2: Run the sprint API serialization test to verify it fails**

Run: `pytest tests/test_api_sprint_flow.py::test_list_sprints_returns_checklist_aware_task_objects -q`

Expected: FAIL because `_serialize_sprint_task` does not expose checklist data.

- [ ] **Step 3: Extend `_serialize_sprint_task` with checklist-aware fields**

```python
def _serialize_sprint_task(task: Task) -> Dict[str, Any]:
    meta = parse_task_metadata(task.metadata_json)
    checklist_items = list(meta.checklist_items)
    return {
        "id": task.task_id,
        "description": task.description,
        "status": task.status,
        "task_kind": meta.task_kind,
        "artifact_targets": meta.artifact_targets,
        "workstream_tags": meta.workstream_tags,
        "checklist_items": checklist_items,
        "is_executable": bool(checklist_items),
    }
```

- [ ] **Step 4: Add a non-executable task case to the same test module**

```python
assert task_obj["checklist_items"] == []
assert task_obj["is_executable"] is False
```

- [ ] **Step 5: Re-run the sprint serialization tests**

Run: `pytest tests/test_api_sprint_flow.py::test_list_sprints_returns_checklist_aware_task_objects -q`

Expected: PASS

- [ ] **Step 6: Commit checklist-aware sprint summaries**

```bash
git add api.py tests/test_api_sprint_flow.py
git commit -m "feat: expose task checklist metadata in sprint summaries"
```

### Task 3: Introduce `story_packet.v1` and Bump Task Packets to `task_packet.v2`

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/api.py`
- Modify: `/Users/aaat/projects/project_tcc/docs/task-packet-vision.md`
- Create: `/Users/aaat/projects/project_tcc/docs/task-packet-schema-v2.md`
- Create: `/Users/aaat/projects/project_tcc/docs/story-packet-schema-v1.md`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write failing API tests for `task_packet.v2` and `story_packet.v1`**

```python
def test_get_task_packet_returns_task_packet_v2(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(
        session,
        repo,
        pinned=True,
        task_metadata=TaskMetadata(
            task_kind="implementation",
            artifact_targets=["payload validator"],
            workstream_tags=["backend"],
            checklist_items=["Validate request payload", "Attach contract test evidence"],
            relevant_invariant_ids=["INV-0123456789abcdef"],
        ),
    )

    response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet"
    )
    payload = response.json()["data"]

    assert payload["schema_version"] == "task_packet.v2"
    assert payload["task"]["checklist_items"] == [
        "Validate request payload",
        "Attach contract test evidence",
    ]
    assert payload["task"]["is_executable"] is True
    assert "acceptance_criteria_items" not in payload["constraints"]


def test_get_story_packet_returns_story_packet_v1(session, monkeypatch):
    client, repo, _workflow = _build_client(monkeypatch)
    project_id, sprint_id, story_id, task_id = _seed_task_packet_context(session, repo, pinned=True)

    response = client.get(
        f"/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet"
    )
    payload = response.json()["data"]

    assert payload["schema_version"] == "story_packet.v1"
    assert payload["story"]["story_id"] == story_id
    assert payload["constraints"]["story_acceptance_criteria_items"] == [
        "include user_id",
        "reject invalid payloads",
    ]
```

- [ ] **Step 2: Run packet API tests to verify they fail**

Run: `pytest tests/test_api_sprint_flow.py -k "task_packet or story_packet" -q`

Expected: FAIL because only `task_packet.v1` exists and there is no story packet route.

- [ ] **Step 3: Implement `task_packet.v2` and add a new story packet builder**

```python
def _build_task_packet(
    session: Session,
    *,
    project_id: int,
    sprint_id: int,
    task_id: int,
) -> Optional[Dict[str, Any]]:
    checklist_items = list(task_metadata.checklist_items)
    packet_id_hash = hashlib.sha256(
        f"task_packet.v2:{sprint_id}:{task_id}".encode()
    ).hexdigest()[:16]

    metadata = {
        "packet_id": f"tp_{packet_id_hash}",
        "generated_at": _serialize_temporal(datetime.now(timezone.utc)),
        "generator_version": "v2",
        "source_fingerprint": _hash_payload(source_snapshot),
    }

    return {
        "schema_version": "task_packet.v2",
        "metadata": metadata,
        "source_snapshot": source_snapshot,
        "task": {
            "task_id": task.task_id,
            "label": _build_task_label(task.description),
            "description": task.description,
            "status": task.status.value,
            "assignee_member_id": task.assigned_to_member_id,
            "assignee_name": task.assignee.name if task.assignee else None,
            "task_kind": task_metadata.task_kind,
            "artifact_targets": list(task_metadata.artifact_targets),
            "workstream_tags": list(task_metadata.workstream_tags),
            "checklist_items": checklist_items,
            "is_executable": bool(checklist_items),
        },
        "context": {
            "story": {
                "story_id": story.story_id,
                "title": story.title,
                "persona": story.persona,
                "story_description": story.story_description,
                "status": story.status.value,
                "story_points": story.story_points,
                "rank": story.rank,
                "source_requirement": story.source_requirement,
            },
            "sprint": {
                "sprint_id": sprint.sprint_id,
                "goal": sprint.goal,
                "status": sprint.status.value,
                "started_at": _serialize_temporal(sprint.started_at),
                "start_date": _serialize_temporal(sprint.start_date),
                "end_date": _serialize_temporal(sprint.end_date),
                "team_id": sprint.team_id,
                "team_name": sprint.team.name if sprint.team else None,
            },
            "product": {
                "product_id": product.product_id,
                "name": product.name,
                "vision_excerpt": _extract_vision_excerpt(product.vision),
            },
        },
        "constraints": {
            "spec_binding": {
                "mode": "pinned_story_authority",
                "binding_status": spec_binding_status,
                "spec_version_id": story.accepted_spec_version_id,
                "authority_artifact_status": authority_status,
            },
            "validation": {
                "present": evidence is not None,
                "passed": evidence.passed if evidence else None,
                "freshness_status": validation_freshness,
                "validated_at": _serialize_temporal(
                    evidence.validated_at if evidence else None
                ),
                "validator_version": evidence.validator_version if evidence else None,
                "current_story_input_hash": current_story_input_hash,
                "validation_input_hash": validation_input_hash,
                "input_hash_matches": input_hash_matches,
                "rules_checked": list(evidence.rules_checked) if evidence else [],
            },
            "task_hard_constraints": _build_task_hard_constraints(
                authority,
                task_metadata=task_metadata,
            ),
            "story_compliance_boundaries": _build_story_compliance_boundaries(
                authority,
                evidence,
            ),
            "findings": _build_packet_findings(evidence),
        },
    }


def _build_story_packet(
    session: Session,
    *,
    project_id: int,
    sprint_id: int,
    story_id: int,
) -> Optional[Dict[str, Any]]:
    packet_id_hash = hashlib.sha256(
        f"story_packet.v1:{sprint_id}:{story_id}".encode()
    ).hexdigest()[:16]
    return {
        "schema_version": "story_packet.v1",
        "metadata": {
            "packet_id": f"sp_{packet_id_hash}",
            "generated_at": _serialize_temporal(datetime.now(timezone.utc)),
            "generator_version": "v1",
            "source_fingerprint": _hash_payload(source_snapshot),
        },
        "source_snapshot": source_snapshot,
        "story": {
            "story_id": story.story_id,
            "title": story.title,
            "persona": story.persona,
            "story_description": story.story_description,
            "status": story.status.value,
            "story_points": story.story_points,
            "rank": story.rank,
            "source_requirement": story.source_requirement,
        },
        "context": {
            "sprint": {
                "sprint_id": sprint.sprint_id,
                "goal": sprint.goal,
                "status": sprint.status.value,
                "started_at": _serialize_temporal(sprint.started_at),
                "start_date": _serialize_temporal(sprint.start_date),
                "end_date": _serialize_temporal(sprint.end_date),
                "team_id": sprint.team_id,
                "team_name": sprint.team.name if sprint.team else None,
            },
            "product": {
                "product_id": product.product_id,
                "name": product.name,
                "vision_excerpt": _extract_vision_excerpt(product.vision),
            },
        },
        "task_plan": {
            "tasks": [_serialize_sprint_task(task) for task in sorted(story.tasks, key=lambda t: t.description.lower())],
        },
        "constraints": {
            "story_acceptance_criteria_text": story.acceptance_criteria,
            "story_acceptance_criteria_items": _normalize_acceptance_criteria(story.acceptance_criteria),
            "spec_binding": {
                "mode": "pinned_story_authority",
                "binding_status": spec_binding_status,
                "spec_version_id": story.accepted_spec_version_id,
                "authority_artifact_status": authority_status,
            },
            "validation": {
                "present": evidence is not None,
                "passed": evidence.passed if evidence else None,
                "freshness_status": validation_freshness,
                "validated_at": _serialize_temporal(
                    evidence.validated_at if evidence else None
                ),
                "validator_version": evidence.validator_version if evidence else None,
                "current_story_input_hash": current_story_input_hash,
                "validation_input_hash": validation_input_hash,
                "input_hash_matches": input_hash_matches,
                "rules_checked": list(evidence.rules_checked) if evidence else [],
            },
            "story_compliance_boundaries": _build_story_compliance_boundaries(authority, evidence),
            "findings": _build_packet_findings(evidence),
        },
    }
```

- [ ] **Step 4: Add the story packet route alongside the existing task packet route**

```python
@app.get("/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet")
async def get_project_story_packet(
    project_id: int,
    sprint_id: int,
    story_id: int,
    flavor: Optional[str] = None,
):
    with Session(get_engine()) as session:
        packet = _build_story_packet(
            session,
            project_id=project_id,
            sprint_id=sprint_id,
            story_id=story_id,
        )
        if not packet:
            raise HTTPException(status_code=404, detail="Story packet context not found")

        payload = dict(packet)
        if flavor:
            from services.packet_renderer import render_packet
            payload["render"] = render_packet(packet, flavor)
        return {"status": "success", "data": payload}
```

- [ ] **Step 5: Write the new packet schema docs**

```ts
type PacketSpecBinding = {
  mode: "pinned_story_authority";
  binding_status: "pinned" | "unpinned";
  spec_version_id: number | null;
  authority_artifact_status: "available" | "missing";
};

type PacketValidation = {
  present: boolean;
  passed: boolean | null;
  freshness_status: "current" | "stale" | "missing";
  validated_at: string | null;
  validator_version: string | null;
  current_story_input_hash: string;
  validation_input_hash: string | null;
  input_hash_matches: boolean | null;
  rules_checked: string[];
};

type PacketConstraint = {
  invariant_id: string;
  type: "FORBIDDEN_CAPABILITY" | "REQUIRED_FIELD" | "MAX_VALUE";
  parameters: Record<string, string | number>;
  source_excerpt: string | null;
  source_location: string | null;
};

type PacketFinding = {
  severity: "warning" | "failure";
  source: "validation_failure" | "validation_warning" | "alignment_warning" | "alignment_failure";
  code: string;
  message: string;
  invariant_id: string | null;
  rule: string | null;
  capability: string | null;
};

type TaskPacketV2 = {
  schema_version: "task_packet.v2";
  task: {
    task_id: number;
    label: string;
    description: string;
    checklist_items: string[];
    is_executable: boolean;
  };
  constraints: {
    spec_binding: PacketSpecBinding;
    validation: PacketValidation;
    task_hard_constraints: PacketConstraint[];
    story_compliance_boundaries: PacketConstraint[];
    findings: PacketFinding[];
  };
};
```

```ts
type StoryPacketV1 = {
  schema_version: "story_packet.v1";
  story: {
    story_id: number;
    title: string;
    story_description: string | null;
  };
  task_plan: {
    tasks: Array<{
      id: number;
      description: string;
      task_kind: string;
      checklist_items: string[];
      is_executable: boolean;
    }>;
  };
  constraints: {
    story_acceptance_criteria_items: string[];
    spec_binding: PacketSpecBinding;
    validation: PacketValidation;
    story_compliance_boundaries: PacketConstraint[];
    findings: PacketFinding[];
  };
};
```

- [ ] **Step 6: Re-run packet API tests**

Run: `pytest tests/test_api_sprint_flow.py -k "task_packet or story_packet" -q`

Expected: PASS

- [ ] **Step 7: Commit canonical packet changes**

```bash
git add api.py \
  docs/task-packet-vision.md \
  docs/task-packet-schema-v2.md \
  docs/story-packet-schema-v1.md \
  tests/test_api_sprint_flow.py
git commit -m "feat: add story packets and task packet v2"
```

### Task 4: Split Story Bootstrap Rendering from Task Delta Rendering

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/services/packet_renderer.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_packet_renderer.py`
- Modify: `/Users/aaat/projects/project_tcc/tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write failing renderer tests for story prompts and task-checklist wording**

```python
def test_task_agent_prompt_uses_task_checklist_language():
    packet = {
        "schema_version": "task_packet.v2",
        "task": {
            "label": "Validate payload",
            "description": "Implement payload validation",
            "task_kind": "implementation",
            "artifact_targets": ["payload validator"],
            "workstream_tags": ["backend"],
            "checklist_items": ["Validate request payload"],
            "is_executable": True,
        },
        "context": {"story": {"title": "Payload Validation Story", "story_description": "As a platform user, I want payload validation so that invalid requests fail safely."}, "sprint": {"goal": "Ship validation"}, "product": {}},
        "constraints": {"task_hard_constraints": [], "story_compliance_boundaries": []},
    }
    output = render_packet(packet, "cursor")
    assert "### Task Checklist" in output
    assert "Verify every task checklist item before claiming completion." in output
    assert "Acceptance Criteria Checklist" not in output


def test_story_agent_prompt_includes_story_acceptance_criteria():
    packet = {
        "schema_version": "story_packet.v1",
        "story": {"title": "Payload Validation Story", "story_description": "As a platform user, I want payload validation so that invalid requests fail safely."},
        "context": {"sprint": {"goal": "Ship validation"}, "product": {"vision_excerpt": "Build trustworthy execution handoffs."}},
        "task_plan": {"tasks": [{"description": "Validate payload", "checklist_items": ["Validate request payload"], "is_executable": True}]},
        "constraints": {"story_acceptance_criteria_items": ["include user_id"]},
    }
    output = render_packet(packet, "cursor")
    assert "<acceptance_criteria>" in output
    assert "include user_id" in output
```

- [ ] **Step 2: Run renderer tests to verify they fail**

Run: `pytest tests/test_packet_renderer.py -q`

Expected: FAIL because `render_packet` only knows the old task packet contract.

- [ ] **Step 3: Split renderer entry points by packet type**

```python
def render_task_human_brief(packet: Dict[str, Any]) -> str:
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})
    checklist_items = packet.get("task", {}).get("checklist_items", [])
    story = context.get("story", {})
    sprint = context.get("sprint", {})
    product = context.get("product", {})
    parts = [
        f"# Task: {_escape_md(task.get('label', 'Task'))}",
        _escape_md(task.get("description", "")),
        "",
        "## Task Checklist",
    ]
    parts.append("## Task Checklist")
    for item in checklist_items:
        parts.append(f"- [ ] {_escape_md(item)}")
    if sprint.get("goal"):
        parts.append("")
        parts.append(f"**Sprint Goal**: {_escape_md(sprint.get('goal'))}")
    if story.get("title"):
        parts.append(f"**Parent Story**: {_escape_md(story.get('title'))}")
    if product.get("vision_excerpt"):
        parts.append(f"**Product Vision**: {_escape_md(product.get('vision_excerpt'))}")
    return "\n".join(parts)


def render_task_agent_prompt(packet: Dict[str, Any]) -> str:
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})
    checklist_items = task.get("checklist_items", [])
    story = context.get("story", {})
    sprint = context.get("sprint", {})
    parts = []
    parts.append("You are continuing work in an existing story-scoped session.\n")
    parts.append("<context>")
    if sprint.get("goal"):
        parts.append(f"  <sprint_goal>{_escape_xml(sprint.get('goal'))}</sprint_goal>")
    if story.get("title"):
        parts.append(f"  <parent_story>{_escape_xml(story.get('title'))}</parent_story>")
    parts.append("</context>\n")
    parts.append("<warning>")
    parts.append("  This prompt assumes the session was already initialized with the parent story prompt.")
    parts.append("</warning>\n")
    parts.append("<task_checklist>")
    for item in checklist_items:
        parts.append(f"  - {_escape_xml(item)}")
    parts.append("</task_checklist>\n")
    parts.append("5. Verify every task checklist item before claiming completion.")
    parts.append("### Task Checklist")
    return "\n".join(parts)


def render_story_agent_prompt(packet: Dict[str, Any]) -> str:
    story = packet.get("story", {})
    context = packet.get("context", {})
    task_plan = packet.get("task_plan", {})
    constraints = packet.get("constraints", {})
    ac_items = constraints.get("story_acceptance_criteria_items", [])
    parts = []
    parts.append("You are starting a fresh story-scoped execution session.\n")
    parts.append("<story>")
    parts.append(f"  {_escape_xml(story.get('title'))}")
    parts.append("</story>\n")
    parts.append("<acceptance_criteria>")
    for item in ac_items:
        parts.append(f"  - {_escape_xml(item)}")
    parts.append("</acceptance_criteria>\n")
    parts.append("<task_plan>")
    for task in task_plan.get("tasks", []):
        parts.append(f"  - {_escape_xml(task.get('description'))}")
    parts.append("</task_plan>\n")
    return "\n".join(parts)
```

- [ ] **Step 4: Update the dispatcher to route by `schema_version`**

```python
def render_packet(packet: Dict[str, Any], flavor: str) -> str:
    schema_version = str(packet.get("schema_version", ""))
    normalized = flavor.strip().lower()

    if schema_version.startswith("story_packet."):
        return (
            render_story_human_brief(packet)
            if normalized in ("human", "markdown", "brief")
            else render_story_agent_prompt(packet)
        )

    return (
        render_task_human_brief(packet)
        if normalized in ("human", "markdown", "brief")
        else render_task_agent_prompt(packet)
    )
```

- [ ] **Step 5: Update API flavor assertions that still expect story AC in task prompts**

```python
assert "### Task Checklist" in agent_text
assert "- [ ] Validate request payload" in agent_text
assert "### Acceptance Criteria Checklist" not in agent_text
```

- [ ] **Step 6: Re-run renderer and packet-flavor tests**

Run: `pytest tests/test_packet_renderer.py tests/test_api_sprint_flow.py -k "render or flavor or packet_renderer" -q`

Expected: PASS

- [ ] **Step 7: Commit renderer split**

```bash
git add services/packet_renderer.py tests/test_packet_renderer.py tests/test_api_sprint_flow.py
git commit -m "feat: split story and task packet renderers"
```

### Task 5: Wire Story Prompt Copying and Executable Task UX in the Frontend

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/frontend/project.js`

- [ ] **Step 1: Add a story-level copy button to the story card header**

```javascript
<button onclick="copyStoryPrompt(event, ${selectedSprint.id}, ${story.story_id})"
  class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 shadow-sm">
  <span class="material-symbols-outlined text-[12px]">content_copy</span> Copy Story Prompt
</button>
```

- [ ] **Step 2: Gate `Copy Task Prompt` on `task.is_executable`**

```javascript
const promptAction = task.is_executable
  ? `<button onclick="copyTaskPrompt(event, ${selectedSprint.id}, ${task.id})" class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded bg-slate-100 hover:bg-slate-200 text-slate-600 transition-colors dark:bg-slate-800 dark:hover:bg-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 shadow-sm">
        <span class="material-symbols-outlined text-[12px]">content_copy</span> Copy Task Prompt
     </button>`
  : `<span class="inline-flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-900/30 dark:text-amber-300 dark:border-amber-800 shadow-sm">
        <span class="material-symbols-outlined text-[12px]">info</span> Reference Only
     </span>`;
```

- [ ] **Step 3: Implement `copyStoryPrompt` next to `copyTaskPrompt`**

```javascript
async function copyStoryPrompt(event, sprintId, storyId) {
    if (!selectedProjectId) return;
    const btn = event.currentTarget;
    const originalText = btn.innerHTML;

    try {
        btn.innerHTML = '<span class="material-symbols-outlined text-[12px] animate-spin">cycle</span> Fetching';
        btn.disabled = true;

        const res = await fetch(`/api/projects/${selectedProjectId}/sprints/${sprintId}/stories/${storyId}/packet?flavor=cursor`);
        if (!res.ok) throw new Error("Failed to fetch story packet");

        const data = await res.json();
        const output = data.data?.render;
        if (!output) throw new Error("No rendered packet returned");

        await navigator.clipboard.writeText(output);
        btn.innerHTML = '<span class="material-symbols-outlined text-[12px]">check</span> Copied!';
    } catch (err) {
        console.error("Copy Story Prompt Error:", err);
        btn.innerHTML = '<span class="material-symbols-outlined text-[12px]">error</span> Error';
    } finally {
        setTimeout(() => {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }, 2000);
    }
}
```

- [ ] **Step 4: Relabel execution logging UI from acceptance language to checklist language**

```javascript
<label class="flex-1 text-[11px] font-bold text-slate-700 dark:text-slate-300 flex flex-col gap-1">
    Checklist Result
    <select id="task-exc-acceptance-${taskId}" required class="p-1.5 rounded form-select text-xs dark:bg-slate-800 dark:border-slate-700 focus:ring-1 focus:ring-indigo-500">
        <option value="not_checked">Not Checked</option>
        <option value="partially_met">Partially Met</option>
        <option value="fully_met">Fully Met</option>
    </select>
</label>
```

- [ ] **Step 5: Export the new story-copy handler**

```javascript
window.copyStoryPrompt = copyStoryPrompt;
window.copyTaskPrompt = copyTaskPrompt;
window.toggleTaskBrief = toggleTaskBrief;
```

- [ ] **Step 6: Run backend regression plus a manual browser smoke check**

Run: `pytest tests/test_api_sprint_flow.py tests/test_packet_renderer.py -q`

Expected: PASS

Manual check:
1. Run `uvicorn api:app --reload`
2. Open `/dashboard`
3. Open a saved sprint story card
4. Confirm `Copy Story Prompt` appears on each story
5. Confirm tasks with checklist items show `Copy Task Prompt`
6. Confirm tasks without checklist items show `Reference Only`
7. Confirm copied story prompt includes story acceptance criteria
8. Confirm copied task prompt includes `Task Checklist` and the session warning

- [ ] **Step 7: Commit frontend prompt UX**

```bash
git add frontend/project.js
git commit -m "feat: add story prompt copy flow"
```

### Task 6: Run Full Regression and Publish the Final Contract Docs

**Files:**
- Modify: `/Users/aaat/projects/project_tcc/docs/task-packet-vision.md`
- Modify: `/Users/aaat/projects/project_tcc/docs/task-packet-schema-v2.md`
- Modify: `/Users/aaat/projects/project_tcc/docs/story-packet-schema-v1.md`

- [ ] **Step 1: Update the vision doc to describe story bootstrap + task delta flow**

```markdown
The platform now supports a two-layer execution handoff:

- `story_packet.v1` bootstraps a fresh story-scoped session and carries story acceptance criteria.
- `task_packet.v2` carries task-local checklist items and task-local constraints for follow-on execution prompts.
```

- [ ] **Step 2: Run the full targeted regression suite**

Run: `pytest tests/test_sprint_planner_schemes.py tests/test_sprint_planner_tools.py tests/test_sprint_runtime.py tests/test_packet_renderer.py tests/test_api_sprint_flow.py tests/test_api_task_execution.py -q`

Expected: PASS

- [ ] **Step 3: Sanity-check working tree contents before the final commit**

Run: `git status --short`

Expected: Only the planned implementation files are modified.

- [ ] **Step 4: Commit the complete story/task prompt contract implementation**

```bash
git add utils/task_metadata.py \
  orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt \
  orchestrator_agent/agent_tools/sprint_planner_tool/schemes.py \
  services/sprint_runtime.py \
  api.py \
  services/packet_renderer.py \
  frontend/project.js \
  docs/task-packet-vision.md \
  docs/task-packet-schema-v2.md \
  docs/story-packet-schema-v1.md \
  tests/test_sprint_planner_schemes.py \
  tests/test_sprint_planner_tools.py \
  tests/test_sprint_runtime.py \
  tests/test_packet_renderer.py \
  tests/test_api_sprint_flow.py
git commit -m "feat: split story and task prompt contracts"
```
