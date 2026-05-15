# Sprint Planner Task Kind Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make sprint generation resilient to harmless `task_kind` drift while keeping decomposition-quality validation strict and exposing clear retry guidance across runtime, API history, and the sprint UI.

**Architecture:** Put `task_kind` canonicalization in a shared helper inside `utils/task_metadata.py` and reuse it from both `StructuredTaskSpec` and `TaskMetadata` so ADK-time and runtime-time validation see the same behavior. Keep planner guidance preventive in `instructions.txt`, keep structural decomposition enforcement in existing validators, and split failure handling into public `validation_errors: list[str]` on sprint artifacts versus full structured validation details in persisted failure artifacts.

**Tech Stack:** Python 3.11, Pydantic v2, FastAPI, Google ADK runner wrapper, pytest, plain JavaScript, HTML, Node test runner

---

## File Structure

- Modify: `utils/task_metadata.py`
  Canonicalize `task_kind` values with a shared helper used by both task models.
- Create: `tests/test_task_metadata.py`
  Pin helper behavior, model-boundary normalization, and legacy parse behavior.
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt`
  Make the planner contract explicit about canonical task kinds, `other`, and decomposition anti-patterns.
- Create: `tests/test_sprint_planner_prompt_contract.py`
  Lock the prompt text that matters for the new contract.
- Modify: `utils/failure_artifacts.py`
  Extend `AgentInvocationError` so ADK-time structured validation details can survive into sprint runtime when available.
- Modify: `utils/adk_runner.py`
  Preserve structured validation details from runner exceptions instead of reducing everything to text.
- Modify: `services/sprint_runtime.py`
  Generate public `validation_errors: list[str]`, keep full structured details in failure artifacts, and attach retry hints to failed sprint artifacts.
- Modify: `tests/test_sprint_runtime.py`
  Cover synonym normalization, invocation-time validation hint shaping, and strict structural failures.
- Modify: `tests/test_runtime_failure_artifacts.py`
  Confirm persisted failure artifacts still keep structured validation detail.
- Modify: `tests/test_api_sprint_flow.py`
  Pin the failed sprint response and `/sprint/history` contract for `output_artifact.validation_errors`.
- Modify: `frontend/project.html`
  Rename the retry input affordance from `Planning Notes` to `Planning or Retry Notes` and update its helper text.
- Modify: `frontend/project.js`
  Render retry guidance from `artifact.validation_errors` in the sprint failure card.
- Modify: `tests/test_sprint_workspace_display.mjs`
  Verify retry guidance rendering and the clarified retry-notes affordance.

## Task 1: Canonicalize `task_kind` at the Shared Schema Boundary

**Files:**
- Modify: `utils/task_metadata.py`
- Create: `tests/test_task_metadata.py`

- [ ] **Step 1: Write the failing helper and model-boundary tests**

```python
import json

import pytest
from pydantic import ValidationError

from utils.task_metadata import (
    StructuredTaskSpec,
    TaskMetadata,
    parse_task_metadata,
)


@pytest.mark.parametrize(
    ("raw_kind", "expected"),
    [
        ("testing", "testing"),
        (" review ", "testing"),
        ("REVIEW", "testing"),
        ("qa", "testing"),
        ("validation", "testing"),
    ],
)
def test_structured_task_spec_normalizes_task_kind(raw_kind: str, expected: str) -> None:
    task = StructuredTaskSpec(
        description="Verify persistence behavior",
        task_kind=raw_kind,
        artifact_targets=["unit test suite"],
        workstream_tags=["testing"],
        relevant_invariant_ids=[],
        checklist_items=["Cover the persistence path"],
    )

    assert task.task_kind == expected


def test_task_metadata_normalizes_task_kind() -> None:
    metadata = TaskMetadata(task_kind="review")

    assert metadata.task_kind == "testing"


def test_parse_task_metadata_normalizes_legacy_review_payload() -> None:
    raw = json.dumps(
        {
            "version": "task_metadata.v1",
            "task_kind": " Review ",
            "artifact_targets": [],
            "workstream_tags": [],
            "relevant_invariant_ids": [],
            "checklist_items": [],
        }
    )

    parsed = parse_task_metadata(raw)

    assert parsed.task_kind == "testing"


def test_structured_task_spec_rejects_unknown_task_kind() -> None:
    with pytest.raises(ValidationError):
        StructuredTaskSpec(
            description="Request sign-off",
            task_kind="approval",
            artifact_targets=["release checklist"],
            workstream_tags=["ops"],
            relevant_invariant_ids=[],
            checklist_items=["Obtain sign-off"],
        )
```

- [ ] **Step 2: Run the new tests to verify the current code fails**

Run: `uv run pytest /Users/aaat/projects/agileforge/tests/test_task_metadata.py -q`

Expected: FAIL because `review`, `qa`, and `validation` are still rejected by the current `TaskKind` validation path.

- [ ] **Step 3: Implement the shared `task_kind` canonicalization helper**

```python
from typing import Any, List, Literal, Optional, cast

TASK_KIND_SYNONYMS = {
    "review": "testing",
    "qa": "testing",
    "validation": "testing",
}


def _normalize_task_kind(value: Any) -> TaskKind:
    if not isinstance(value, str):
        raise ValueError("task_kind must be a string.")

    normalized = value.strip().lower()
    canonical = TASK_KIND_SYNONYMS.get(normalized, normalized)
    if canonical in TASK_KIND_VALUES:
        return cast(TaskKind, canonical)

    allowed = ", ".join(TASK_KIND_VALUES)
    raise ValueError(f"task_kind must be one of: {allowed}.")
```

Add this validator to both `TaskMetadata` and `StructuredTaskSpec`:

```python
@field_validator("task_kind", mode="before")
@classmethod
def _validate_task_kind(cls, value: Any) -> TaskKind:
    return _normalize_task_kind(value)
```

- [ ] **Step 4: Re-run the tests to verify normalization works and unknown values still fail**

Run: `uv run pytest /Users/aaat/projects/agileforge/tests/test_task_metadata.py -q`

Expected: PASS with 4 tests green.

- [ ] **Step 5: Commit the shared canonicalization slice**

```bash
git -C /Users/aaat/projects/agileforge add \
  /Users/aaat/projects/agileforge/utils/task_metadata.py \
  /Users/aaat/projects/agileforge/tests/test_task_metadata.py
git -C /Users/aaat/projects/agileforge commit -m "feat: canonicalize sprint task kinds"
```

## Task 2: Harden the Sprint Planner Prompt Contract

**Files:**
- Modify: `orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt`
- Create: `tests/test_sprint_planner_prompt_contract.py`

- [ ] **Step 1: Write a prompt-contract regression test**

```python
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
INSTRUCTIONS_PATH = (
    REPO_ROOT
    / "orchestrator_agent"
    / "agent_tools"
    / "sprint_planner_tool"
    / "instructions.txt"
)


def test_sprint_planner_prompt_pins_task_kind_contract() -> None:
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    assert "The schema literal set is: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`, `other`." in text
    assert "For normal sprint output, emit only: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`." in text
    assert "Do not emit `other` or `review`." in text


def test_sprint_planner_prompt_calls_out_decomposition_anti_patterns() -> None:
    text = INSTRUCTIONS_PATH.read_text(encoding="utf-8")

    assert "Do NOT copy, paraphrase, or lightly reword the parent story's `acceptance_criteria_items` into the task checklist." in text
    assert "Do NOT use exact file paths in `artifact_targets`." in text
    assert "Bad: `artifact_targets: [\"api.py\"]`" in text
    assert "Good: `artifact_targets: [\"auth API\"]`" in text
```

- [ ] **Step 2: Run the prompt-contract test to verify it fails against the current prompt**

Run: `uv run pytest /Users/aaat/projects/agileforge/tests/test_sprint_planner_prompt_contract.py -q`

Expected: FAIL because the prompt does not yet contain the exact contract language or the positive/negative examples.

- [ ] **Step 3: Update `instructions.txt` with the explicit canonical-kind and decomposition guidance**

```text
* `task_kind` uses the shared task schema.
* The schema literal set is: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`, `other`.
* For normal sprint output, emit only: `analysis`, `design`, `implementation`, `testing`, `documentation`, `refactor`.
* Do not emit `other` or `review`.
* If the work is review-like, map it to the closest canonical kind:
    * final verification or validation -> `testing`
    * documenting decisions -> `documentation`
    * inspection or audit -> `analysis`
* Do NOT use exact file paths in `artifact_targets`.
* Bad: `artifact_targets: ["api.py"]`
* Good: `artifact_targets: ["auth API"]`
```

Also update the JSON example so every task uses only canonical kinds and at least one checklist example is clearly task-local rather than story-level.

- [ ] **Step 4: Re-run the prompt-contract test**

Run: `uv run pytest /Users/aaat/projects/agileforge/tests/test_sprint_planner_prompt_contract.py -q`

Expected: PASS with both prompt assertions green.

- [ ] **Step 5: Commit the prompt hardening slice**

```bash
git -C /Users/aaat/projects/agileforge add \
  /Users/aaat/projects/agileforge/orchestrator_agent/agent_tools/sprint_planner_tool/instructions.txt \
  /Users/aaat/projects/agileforge/tests/test_sprint_planner_prompt_contract.py
git -C /Users/aaat/projects/agileforge commit -m "docs: harden sprint planner prompt contract"
```

## Task 3: Split Public Retry Hints from Full Failure-Artifact Details

**Files:**
- Modify: `utils/failure_artifacts.py`
- Modify: `utils/adk_runner.py`
- Modify: `services/sprint_runtime.py`
- Modify: `tests/test_sprint_runtime.py`
- Modify: `tests/test_runtime_failure_artifacts.py`
- Modify: `tests/test_api_sprint_flow.py`

- [ ] **Step 1: Write the failing runtime, artifact, and API tests**

```python
@pytest.mark.asyncio
async def test_runtime_normalizes_review_task_kind_and_returns_canonical_testing(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        return json.dumps(
            {
                "sprint_goal": "goal",
                "sprint_number": 1,
                "duration_days": 14,
                "selected_stories": [
                    {
                        "story_id": 12,
                        "story_title": "Event Delta Persistence",
                        "tasks": [
                            {
                                "description": "Verify persistence path",
                                "task_kind": " review ",
                                "checklist_items": ["Cover the persistence path"],
                                "artifact_targets": ["unit test suite"],
                                "workstream_tags": ["testing"],
                                "relevant_invariant_ids": [],
                            }
                        ],
                        "reason_for_selection": "reason",
                    }
                ],
                "deselected_stories": [],
                "capacity_analysis": {
                    "velocity_assumption": "Medium",
                    "capacity_band": "4-5 stories",
                    "selected_count": 1,
                    "story_points_used": 3,
                    "max_story_points": 5,
                    "commitment_note": "note",
                    "reasoning": "reason",
                },
            }
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=5,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is True
    assert result["output_artifact"]["selected_stories"][0]["tasks"][0]["task_kind"] == "testing"


@pytest.mark.asyncio
async def test_runtime_surfaces_public_task_kind_retry_hint_from_invocation_exception(monkeypatch) -> None:
    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        raise AgentInvocationError(
            "output validation failed",
            partial_output='{"selected_stories": []}',
            validation_errors=[
                {
                    "loc": ("selected_stories", 0, "tasks", 0, "task_kind"),
                    "msg": "Input should be 'analysis', 'design', 'implementation', 'testing', 'documentation', 'refactor' or 'other'",
                    "input": "approval",
                }
            ],
        )

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=None,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    assert result["success"] is False
    assert result["output_artifact"]["validation_errors"] == [
        "Unsupported task_kind `approval`. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]


@pytest.mark.asyncio
async def test_sprint_runtime_output_validation_artifact_keeps_structured_validation_errors(monkeypatch, tmp_path):
    _patch_failure_dir(monkeypatch, tmp_path)

    def fake_fetch_sprint_candidates(*, product_id):
        assert product_id == 7
        return {
            "success": True,
            "count": 1,
            "stories": [
                {
                    "story_id": 12,
                    "story_title": "Event Delta Persistence",
                    "priority": 2,
                    "story_points": 3,
                    "evaluated_invariant_ids": [],
                }
            ],
        }

    async def fake_invoke(_payload):
        return "{}"

    monkeypatch.setattr(sprint_input, "fetch_sprint_candidates", fake_fetch_sprint_candidates)
    monkeypatch.setattr(sprint_runtime, "_invoke_sprint_agent", fake_invoke)

    result = await sprint_runtime.run_sprint_agent_from_state(
        {},
        project_id=7,
        team_velocity_assumption="medium",
        sprint_duration_days=14,
        max_story_points=None,
        include_task_decomposition=True,
        selected_story_ids=[12],
        user_input=None,
    )

    artifact = failure_artifacts.read_failure_artifact(result["failure_artifact_id"])
    assert isinstance(artifact["validation_errors"], list)
    assert isinstance(artifact["validation_errors"][0], dict)


def test_sprint_generate_failure_exposes_validation_errors_in_response_and_history(monkeypatch):
    client, repo, workflow = _build_client(monkeypatch)
    project_id = _seed_sprint_setup_project(repo, workflow)

    async def fake_run_sprint_agent_from_state(
        state,
        *,
        project_id,
        team_velocity_assumption,
        sprint_duration_days,
        max_story_points,
        include_task_decomposition,
        selected_story_ids,
        user_input,
    ):
        return {
            "success": False,
            "input_context": {"available_stories": []},
            "output_artifact": {
                "error": "SPRINT_GENERATION_FAILED",
                "message": "Sprint output validation failed: unsupported task_kind",
                "validation_errors": [
                    "Unsupported task_kind `approval`. Use one of: analysis, design, implementation, testing, documentation, refactor."
                ],
                "is_complete": False,
            },
            "is_complete": None,
            "error": "Sprint output validation failed: unsupported task_kind",
        }

    monkeypatch.setattr(api_module, "run_sprint_agent_from_state", fake_run_sprint_agent_from_state)

    payload = client.post(
        f"/api/projects/{project_id}/sprint/generate",
        json={
            "team_velocity_assumption": "Medium",
            "sprint_duration_days": 14,
            "include_task_decomposition": True,
        },
    ).json()

    assert payload["data"]["output_artifact"]["validation_errors"] == [
        "Unsupported task_kind `approval`. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]
    history = client.get(f"/api/projects/{project_id}/sprint/history").json()["data"]["items"][0]
    assert history["output_artifact"]["validation_errors"] == [
        "Unsupported task_kind `approval`. Use one of: analysis, design, implementation, testing, documentation, refactor."
    ]
```

- [ ] **Step 2: Run the focused tests to verify the current runtime does not satisfy the public contract**

Run:

```bash
uv run pytest /Users/aaat/projects/agileforge/tests/test_sprint_runtime.py -q
uv run pytest /Users/aaat/projects/agileforge/tests/test_runtime_failure_artifacts.py -q
uv run pytest /Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py -q
```

Expected: FAIL because sprint failures do not yet attach public `validation_errors: list[str]`, ADK-time structured validation detail is not preserved, and the API/history assertions will not find the new field.

- [ ] **Step 3: Implement structured-detail preservation plus public retry-hint shaping**

```python
class AgentInvocationError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        partial_output: Optional[str] = None,
        event_count: int = 0,
        validation_errors: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        super().__init__(message)
        self.partial_output = partial_output
        self.event_count = event_count
        self.validation_errors = validation_errors
```

Replace the current `except Exception as exc` block in `invoke_agent_to_text` with:

```python
except Exception as exc:  # pylint: disable=broad-except
    partial_output = extract_partial_response_text(events) or None
    structured_errors = None
    errors = getattr(exc, "errors", None)
    if callable(errors):
        try:
            candidate = errors()
            if isinstance(candidate, list):
                structured_errors = [item for item in candidate if isinstance(item, dict)]
        except Exception:  # best-effort only
            structured_errors = None
    raise AgentInvocationError(
        str(exc),
        partial_output=partial_output,
        event_count=len(events),
        validation_errors=structured_errors,
    ) from exc
```

```python
ALLOWED_SPRINT_TASK_KINDS = (
    "analysis",
    "design",
    "implementation",
    "testing",
    "documentation",
    "refactor",
)


def _summarize_validation_errors(validation_errors: Optional[List[Dict[str, Any]]]) -> List[str]:
    if not validation_errors:
        return []

    hints: List[str] = []
    for error in validation_errors:
        loc = tuple(str(part) for part in error.get("loc") or ())
        input_value = error.get("input")
        if loc and loc[-1] == "task_kind" and isinstance(input_value, str):
            hint = (
                f"Unsupported task_kind `{input_value.strip()}`. "
                f"Use one of: {', '.join(ALLOWED_SPRINT_TASK_KINDS)}."
            )
        else:
            hint = str(error.get("msg") or "Validation error.")

        if hint not in hints:
            hints.append(hint)
        if len(hints) == 3:
            break
    return hints


def _failure(
    *,
    project_id: int,
    input_context: Dict[str, Any],
    failure_stage: str,
    message: str,
    raw_text: Optional[str] = None,
    validation_errors: Optional[List[Dict[str, Any]]] = None,
    public_validation_errors: Optional[List[str]] = None,
    exception: Optional[BaseException] = None,
) -> Dict[str, Any]:
    artifact_result = write_failure_artifact(
        phase="sprint",
        project_id=project_id,
        failure_stage=failure_stage,
        failure_summary=message,
        raw_output=raw_text,
        context={"input_context": input_context},
        model_info={
            **get_agent_model_info(sprint_agent),
            "app_name": SPRINT_RUNNER_IDENTITY.app_name,
            "user_id": SPRINT_RUNNER_IDENTITY.user_id,
        },
        validation_errors=validation_errors,
        exception=exception,
    )
    artifact: Dict[str, Any] = {
        "error": "SPRINT_GENERATION_FAILED",
        "message": message,
        "validation_errors": list(public_validation_errors or []),
        "is_complete": False,
    }
    artifact.update(artifact_result["metadata"])
    return {
        "success": False,
        "input_context": input_context,
        "output_artifact": artifact,
        "is_complete": None,
        "error": message,
        "validation_errors": list(public_validation_errors or []),
        **artifact_result["metadata"],
    }
```

Use that split consistently:

- `ValidationError` paths: pass `exc.errors()` as detailed errors and `_summarize_validation_errors(exc.errors())` as public hints
- `AgentInvocationError` paths: pass `exc.validation_errors` if available, otherwise an empty detailed list
- decomposition and invariant failures: keep detailed errors as `[{"msg": error}]`, but expose the plain strings publicly

- [ ] **Step 4: Re-run the focused tests to verify the public/private validation split**

Run:

```bash
uv run pytest /Users/aaat/projects/agileforge/tests/test_sprint_runtime.py -q
uv run pytest /Users/aaat/projects/agileforge/tests/test_runtime_failure_artifacts.py -q
uv run pytest /Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py -q
```

Expected: PASS, with runtime/API now exposing `output_artifact.validation_errors` as `list[str]` while failure artifacts still retain structured dictionaries.

- [ ] **Step 5: Commit the runtime retry-guidance slice**

```bash
git -C /Users/aaat/projects/agileforge add \
  /Users/aaat/projects/agileforge/utils/failure_artifacts.py \
  /Users/aaat/projects/agileforge/utils/adk_runner.py \
  /Users/aaat/projects/agileforge/services/sprint_runtime.py \
  /Users/aaat/projects/agileforge/tests/test_sprint_runtime.py \
  /Users/aaat/projects/agileforge/tests/test_runtime_failure_artifacts.py \
  /Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py
git -C /Users/aaat/projects/agileforge commit -m "feat: expose sprint retry guidance"
```

## Task 4: Render Retry Guidance and Clarify the Retry Input Affordance

**Files:**
- Modify: `frontend/project.html`
- Modify: `frontend/project.js`
- Modify: `tests/test_sprint_workspace_display.mjs`

- [ ] **Step 1: Write the failing frontend regression tests**

```javascript
test('renderSprintValidationErrors renders retry guidance bullets', () => {
    const renderSprintValidationErrors = loadSprintFunction(
        'renderSprintValidationErrors',
        [/function renderSprintValidationErrors\(validationErrors\) \{[\s\S]*?\n\}/],
    );

    const html = renderSprintValidationErrors([
        'Unsupported task_kind `approval`. Use one of: analysis, design, implementation, testing, documentation, refactor.',
        'Artifact target looks like a file path.',
    ]);

    assert.match(html, /What to fix/i);
    assert.match(html, /Unsupported task_kind `approval`/);
    assert.match(html, /Artifact target looks like a file path/);
});


test('sprint planner form labels retry notes clearly', () => {
    const projectHtml = fs.readFileSync(
        path.resolve(import.meta.dirname, '../frontend/project.html'),
        'utf8',
    );

    assert.match(projectHtml, /Planning or Retry Notes/);
    assert.match(projectHtml, /paste or summarize retry guidance/i);
});
```

- [ ] **Step 2: Run the frontend test to verify the current UI lacks the new affordance**

Run: `node --test /Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs`

Expected: FAIL because there is no `renderSprintValidationErrors` helper and the form still says `Planning Notes`.

- [ ] **Step 3: Implement failure-hint rendering and the renamed retry-notes field**

```html
<label for="sprint-user-input"
    class="block text-sm font-bold text-slate-700 dark:text-slate-300 mb-2 mt-4">
    Planning or Retry Notes
</label>
<p class="text-[11px] text-slate-500 mb-2">
    Optional focus for the sprint, or paste or summarize retry guidance from the latest failed attempt.
</p>
<textarea
    id="sprint-user-input"
    rows="3"
    class="w-full text-sm rounded-xl border border-slate-300 dark:border-slate-600 px-4 py-3 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 focus:ring-2 focus:ring-teal-500 focus:border-teal-500 outline-none transition-all placeholder:text-slate-400 resize-none shadow-inner"
    placeholder="Optional sprint guidance, dependency notes, or retry instructions for the next run."
></textarea>
```

```javascript
function renderSprintValidationErrors(validationErrors) {
    const items = Array.isArray(validationErrors)
        ? validationErrors.filter((item) => typeof item === 'string' && item.trim())
        : [];

    if (items.length === 0) {
        return '';
    }

    return `
        <div class="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-3 dark:border-amber-700 dark:bg-amber-900/30">
            <p class="text-[10px] font-bold uppercase tracking-wide text-amber-800 dark:text-amber-300">What to fix</p>
            <ul class="mt-2 list-disc space-y-1 pl-4 text-[11px] text-amber-900 dark:text-amber-200">
                ${items.map((item) => `<li>${item}</li>`).join('')}
            </ul>
        </div>
    `;
}
```

Insert this line inside the existing `if (artifact.error) {` block in `renderSprintArtifactHtml`, immediately after the failure message paragraph and before the raw-output preview block:

```javascript
html += renderSprintValidationErrors(artifact.validation_errors);
```

- [ ] **Step 4: Re-run the frontend test**

Run: `node --test /Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs`

Expected: PASS, with retry guidance rendered in the failure card and the form copy updated.

- [ ] **Step 5: Commit the sprint UI slice**

```bash
git -C /Users/aaat/projects/agileforge add \
  /Users/aaat/projects/agileforge/frontend/project.html \
  /Users/aaat/projects/agileforge/frontend/project.js \
  /Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs
git -C /Users/aaat/projects/agileforge commit -m "feat: show sprint retry guidance"
```

## Task 5: Run the Full Focused Verification Sweep

**Files:**
- Modify: none expected
- Verify: `tests/test_task_metadata.py`
- Verify: `tests/test_sprint_planner_prompt_contract.py`
- Verify: `tests/test_sprint_planner_schemes.py`
- Verify: `tests/test_sprint_runtime.py`
- Verify: `tests/test_runtime_failure_artifacts.py`
- Verify: `tests/test_api_sprint_flow.py`
- Verify: `tests/test_sprint_workspace_display.mjs`

- [ ] **Step 1: Run the focused Python regression suite**

Run:

```bash
uv run pytest \
  /Users/aaat/projects/agileforge/tests/test_task_metadata.py \
  /Users/aaat/projects/agileforge/tests/test_sprint_planner_prompt_contract.py \
  /Users/aaat/projects/agileforge/tests/test_sprint_planner_schemes.py \
  /Users/aaat/projects/agileforge/tests/test_sprint_runtime.py \
  /Users/aaat/projects/agileforge/tests/test_runtime_failure_artifacts.py \
  /Users/aaat/projects/agileforge/tests/test_api_sprint_flow.py \
  -q
```

Expected: PASS with all targeted Python regressions green.

- [ ] **Step 2: Run the sprint workspace display test**

Run: `node --test /Users/aaat/projects/agileforge/tests/test_sprint_workspace_display.mjs`

Expected: PASS with the sprint UI regression suite green.

- [ ] **Step 3: Inspect the final diff for scope control**

Run:

```bash
git -C /Users/aaat/projects/agileforge status --short
git -C /Users/aaat/projects/agileforge diff --stat HEAD~4..HEAD
```

Expected: only the planned files above are changed, with no unrelated drift pulled into the implementation branch.

- [ ] **Step 4: Sanity-check the contract against the approved spec**

Use this checklist before handing off:

- `review`, `qa`, and `validation` normalize to canonical `testing`
- unknown kinds still fail
- the planner prompt tells the model not to emit `other`
- failed sprint artifacts expose `validation_errors: list[str]`
- persisted failure artifacts still keep structured validation details
- the sprint UI shows retry guidance and the retry-notes affordance is explicit

- [ ] **Step 5: Stop and hand off for execution review**

No new code here. If every command above passed, the branch is ready for implementation review or execution by subagents.
