# Development Standards for project_tcc

## Development Best Practices

### Test-Driven Development (TDD)

**All new code MUST follow TDD workflow:**

1. **Write Test First** – Before implementing any feature or fix:
   - Create test file in `tests/` directory (use `test_*.py` naming)
   - Write failing test that describes expected behavior
   - Run test to confirm it fails: `pytest tests/test_your_feature.py -v`

2. **Implement Minimum Code** – Write simplest code to make test pass:
   - Focus on making the test green, not perfect code
   - Avoid over-engineering or premature optimization

3. **Refactor** – Improve code while keeping tests green:
   - Extract functions, improve naming, remove duplication
   - Run tests after each refactor: `pytest tests/ -v`

**Testing Standards:**

- **Unit Tests** (`tests/unit/` or `tests/test_*.py`):
  - Test individual functions/classes in isolation
  - Use mocks for database/external dependencies
  - Each test should be independent (no shared state)
  - Test fixtures in `tests/conftest.py` for reusable setup

- **Integration Tests** (`tests/integration/`):
  - Test agent interactions end-to-end
  - Test database operations with fresh SQLite engine (see `conftest.py`)
  - Validate JSON schema compliance for agent outputs

- **Coverage Requirements:**
  - Minimum 80% code coverage for new features
  - Run: `pytest --cov=. --cov-report=html tests/`
  - Critical paths (agent pipelines, database mutations) require 100% coverage

**Test Patterns:**

```python
# Unit test example (with mocks)
def test_save_vision_tool_creates_product(mock_session):
    result = save_vision_tool(
        product_name="Test Product",
        vision_statement="Clear vision",
        tool_context=None
    )
    assert result["success"] is True
    mock_session.add.assert_called_once()

# Integration test example (with real DB)
def test_story_pipeline_generates_invest_compliant_stories(test_engine):
    session = Session(test_engine)
    result = process_feature_for_stories(
        feature_id=1,
        include_story_points=True
    )
    assert result["validation_score"] >= 80
    stories = session.exec(select(UserStory)).all()
    assert len(stories) > 0
```

**Test Organization:**
- Group related tests in classes: `class TestVisionAgent:`
- Use descriptive test names: `test_vision_agent_rejects_incomplete_requirements`
- Add docstrings for complex test scenarios
- Use `pytest.mark.parametrize` for testing multiple inputs

**Pre-Commit Checklist:**
- [ ] All tests pass: `pytest tests/ -v`
- [ ] No test skips without documented reason
- [ ] New features have corresponding tests
- [ ] Test coverage meets minimum threshold

### Tech Stack and Dependencies

**Core Technologies (Fixed – DO NOT change):**
- **Python 3.11+** – All async/await features available
- **Google ADK 0.0.42** – Agent orchestration framework
- **LiteLLM 1.64.3** – LLM abstraction (OpenRouter API)
- **SQLModel 0.0.22** – ORM with Pydantic integration
- **SQLite 3.37+** – Embedded database with foreign key support
- **Pydantic 2.10.6** – Schema validation and serialization
- **Pytest 8.3.4** – Testing framework

**Dependency Management:**
- Use `pyproject.toml` for all dependencies (managed via Poetry)
- Pin major versions to prevent breaking changes
- Test dependency updates in isolated branch before merging
- Run `poetry lock` after changing dependencies

### Code Quality Standards

**Style and Formatting:**
- Follow PEP 8 (enforced by Ruff/Black if configured)
- Maximum line length: 100 characters
- Use type hints for all function signatures:
  ```python
  def process_feature(feature_id: int, context: Optional[ToolContext] = None) -> dict[str, Any]:
  ```
- Docstrings for public functions (Google style):
  ```python
  def save_vision_tool(product_name: str) -> dict[str, Any]:
      """Save product vision to database.
      
      Args:
          product_name: Unique product identifier
          
      Returns:
          Dict with 'success' (bool) and 'product_id' (int) keys
      """
  ```

**Error Handling:**
- Use explicit exception types (avoid bare `except:`)
- Log errors with context: `logger.error(f"Failed to save vision: {e}")`
- Return structured error responses:
  ```python
  return {"success": False, "error": str(e), "details": {"product_id": None}}
  ```

**Naming Conventions:**
- Files: `snake_case.py`
- Classes: `PascalCase` (e.g., `ProductVisionAgent`)
- Functions/variables: `snake_case` (e.g., `process_feature_for_stories`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `MAX_ITERATIONS`)
- Private methods: `_leading_underscore`

**Performance Optimization:**
- Use SQLModel `select()` with filtering, not `session.exec(select(Table)).all()` then filter in Python
- Batch database operations when possible (see `batch_update_story_status`)
- Cache expensive operations via `ToolContext` (see `orchestrator_tools.py`)
- Limit query results with pagination (default: 100 max)

**Security:**
- Never hardcode API keys (use environment variables)
- Validate all user inputs (Pydantic schemas enforce this)
- Sanitize file paths (use `Path.resolve()` to prevent traversal)
- SQL injection protected by SQLModel parameterization

### File Organization Rules

**When to Create New Files:**
- New agent → new folder in `orchestrator_agent/agent_tools/`
- New tool → add to appropriate file in `tools/` (or create `tools/new_category_tools.py`)
- New schema → add to `utils/schemes.py` (keep all Pydantic schemas centralized)
- Test file → mirror source structure in `tests/` (e.g., `tools/db_tools.py` → `tests/test_db_tools.py`)

**DO NOT Create:**
- Markdown documentation files unless explicitly requested
- Backup files or archives (use Git for version control)
- Duplicate utility functions (check `utils/` first)
- Configuration files for tools not in `pyproject.toml`

**Import Organization:**
```python
# Standard library
import json
from pathlib import Path
from typing import Optional

# Third-party
from pydantic import BaseModel, Field
from sqlmodel import Session, select

# Local
from agile_sqlmodel import Product, UserStory
from utils.helper import load_instruction
```

## Google ADK + Pydantic v2 Structured I/O Standards (Mandatory)

### Core rule: schemas are contracts; instructions enforce compliance
- When using ADK `input_schema` and/or `output_schema`, treat Pydantic models as:
  - **Validation + serialization contracts** (hard constraints).
  - **Not** sufficient “teaching” for the LLM by themselves.
- Therefore, **ALWAYS include explicit format guidance in `instruction`**:
  - For `input_schema`: state the input is a **JSON string** matching the schema and give a minimal example.
  - For `output_schema`: state **return ONLY JSON** matching the schema; no markdown fences; no commentary.

### Instruction patterns (copy/paste)
- **Structured input (required if `input_schema` is set):**
  - Include:
    - “Input is a JSON string matching this schema.”
    - One example payload.
  - Example wording:
    - `The user will provide input as a JSON string like {"field": "value"}.`

- **Structured output (required if `output_schema` is set):**
  - Include:
    - “Return ONLY a JSON object matching the output schema.”
    - “Do not wrap in markdown. Do not include any extra keys.”
    - One example output (optional but recommended).
  - Example wording:
    - `Respond ONLY with JSON matching the schema. No prose. No markdown.`

### Pydantic v2 + typing.Annotated conventions
- All structured schemas MUST be Pydantic v2 `BaseModel`.
- Use `typing.Annotated[...]` + `pydantic.Field(...)` for constraints and documentation:
  - Use `description=` for every public field.
  - Prefer tight bounds (e.g., `min_length`, `max_length`, `ge`, `le`) to reduce model drift.
- Serialization:
  - Use `model_dump()` / `model_dump_json()` for producing JSON.
  - Use `model_validate_json()` for parsing JSON outputs.
- Config:
  - Prefer strictness for external-facing outputs:
    - Consider `model_config = ConfigDict(extra="forbid")` for output models when feasible.
  - If strictness causes frequent failures, handle via retry/repair logic at the orchestrator level, not by loosening schema without tests.

### ADK interaction rules for structured I/O
- If `input_schema` is set:
  - The message content passed into the agent MUST be a JSON string.
  - Upstream code or upstream agent must construct that JSON string from the Pydantic model.
  - Add tests that verify invalid/non-JSON input fails fast.
- If `output_schema` is set:
  - The agent’s final response MUST be JSON conforming to the schema.
  - Add tests that:
    - parse with `OutputModel.model_validate_json(text)`;
    - assert schema constraints (required fields, bounds);
    - assert there is no extra text (no markdown fences).

### Tools vs structured output (avoid conflicts)
- Do NOT combine tool-use behavior and `output_schema` in the same ADK agent unless the current ADK version explicitly supports it.
- Preferred pipeline when tools are needed:
  1) Tool-capable agent (no `output_schema`) writes results into session state
  2) Formatter agent (with `output_schema`, no tools) emits strict JSON

### Testing requirements for structured I/O (in addition to project TDD rules)
- Unit tests:
  - Validate schema constraints for representative payloads (valid/invalid).
  - Validate JSON round-trip: `model_dump_json()` -> `model_validate_json()`.
- Integration tests:
  - Run the ADK agent and assert:
    - input passed is a JSON string (when `input_schema` is used);
    - output event text parses with `model_validate_json()` (when `output_schema` is used).
  - Add at least one test that fails if the model returns:
    - markdown fenced JSON
    - extra commentary
    - missing/renamed keys

### Copilot behavior requirements when generating ADK agents
- When creating/updating an ADK agent using `input_schema`/`output_schema`, Copilot MUST:
  - create/update the Pydantic v2 models with `Annotated` + `Field(description=...)`;
  - include explicit JSON format requirements in `instruction` (input + output);
  - add/extend tests first (TDD) to cover JSON validity and schema conformance.
