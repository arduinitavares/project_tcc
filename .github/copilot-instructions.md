# AI Agent Instructions for project_tcc

This codebase implements an **Autonomous Agile Management Platform** – a multi-agent system that simulates Scrum roles to reduce cognitive load for small teams (1-4 developers).

## Project Context

**TCC Status:** Early prototype phase. Current implementation demonstrates agent orchestration; the approved proposal targets three agents (Product Owner, Scrum Master, Developer Support) simulating a complete Scrum workflow. See `CLAUDE.md` for detailed requirements and design science research methodology.

**Key Technologies:**
- Google ADK (Agent Development Kit) for agent orchestration
- LiteLLM for LLM abstraction (OpenRouter API)
- SQLModel for ORM with SQLite persistence
- Pydantic for schema validation

## Architecture Patterns

### Agent Structure

All agents follow this pattern:
1. **Schema Definition** – Pydantic `InputSchema` and `OutputSchema` (see `utils/schemes.py`)
2. **Instruction File** – External `instructions.txt` loaded via `load_instruction()` (from `utils/helper.py`)
3. **Agent Creation** – `Agent()` or `LoopAgent()` with `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True`
4. **Response Parsing** – Structured JSON validated by `parse_agent_output()` from `utils/response_parser.py`

**Example:**
```python
# product_vision_agent/agent.py
root_agent = Agent(
    name="product_vision_agent",
    model=LiteLlm(...),
    input_schema=InputSchema,
    output_schema=OutputSchema,
    instruction=load_instruction(Path("product_vision_agent/instructions.txt")),
    disallow_transfer_to_parent=True,
)
```

### Root Orchestrator with App Object

The orchestrator is the **root agent** for the entire application:
```python
# orchestrator_agent/agent.py
from google.adk.apps import App
from google.adk.tools import AgentTool

root_agent = Agent(
    name="orchestrator_agent",
    model=LiteLlm(...),
    tools=[
        AgentTool(agent=vision_agent),  # Other agents as tools
        AgentTool(agent=roadmap_agent),
        FunctionTool(func=count_projects),  # Database queries
        # ... more tools
    ],
    instruction=load_instruction(...),
)

# Export as app (required for ADK web)
app = App(name="project_tcc", root_agent=root_agent)
```

**Key Pattern:**
- Child agents (vision, roadmap) are **wrapped in `AgentTool`** and included in root's `tools` list
- Root agent calls them explicitly as tools, passing input and capturing output
- Database query tools also wrapped as `FunctionTool`
- Root agent must export `app = App(...)` object for ADK web CLI

### Orchestration Patterns

**Pattern 1: Sequential via LoopAgent** (`product_workflow.py`)
- Root `LoopAgent` calls sub-agents in sequence via `ORCHESTRATOR_INSTRUCTIONS`
- Each sub-agent returns structured output
- Root agent passes previous agent's output to next agent
- **Key:** Instructions tell the orchestrator how to call sub-agents; no explicit `add_edge()` calls

**Pattern 2: Session-Based Interactive** (`main.py`)
- User-scoped sessions with persistent state (`DatabaseSessionService`)
- State accumulates requirements across multiple turns
- System switches agents when conditions are met (e.g., vision complete → roadmap)
- **State keys:** `product_vision_statement`, `product_roadmap`, `unstructured_requirements`, `is_complete`, `clarifying_questions`

### Multi-Turn Context Handling (Critical)

**The agent must receive ALL accumulated requirements, not just the latest message:**

```python
# Correct: Pass full accumulated history
append_user_text_to_requirements(state, user_text)  # Accumulate
response = await run_vision_agent(
    accumulated_requirements=str(state["unstructured_requirements"])  # Full history
)
```

This ensures agents maintain context across clarifying question rounds.

## Database Schema

**Core Tables** (from `agile_sqlmodel.py`):
- `products` – Top-level container (has `vision`, `roadmap` fields)
  - **Specification fields**: `technical_spec` (Text), `spec_file_path`, `spec_loaded_at`
- `themes` – Product groupings (belongs to product, contains epics)
- `epics` – Feature groups (belongs to theme, contains features)
- `features` – User-facing capabilities (belongs to epic)
- `user_stories` – INVEST-compliant stories (belongs to product, linked to sprints)
  - **Completion tracking fields**: `resolution_type`, `completion_notes`, `acceptance_criteria_updates`, `known_gaps`, `evidence_links`, `completion_confidence`, `follow_up_story_id`, `completed_at`
- `story_completion_log` – Audit trail for status changes (who, when, why, evidence)
- `sprints` – Development cycles (tracks `start_date`, `end_date`, status)
- `tasks` – Sprint tasks with assigned members
- `teams` / `team_members` – Organizational structure
- `workflow_events` – TCC evaluation metrics (event_type, duration_seconds, metadata)
- **Link tables:** `TeamMembership`, `ProductTeam`, `SprintStory`

**Key Patterns:**
- Foreign keys enforced via SQLite pragma: `PRAGMA foreign_keys=ON`
- Timestamps use `func.now()` for server defaults
- Many-to-many relationships defined via explicit link tables

## Tool Architecture

### Read-Only Query Tools (`tools/orchestrator_tools.py`)
- `count_projects()` – Count total projects (cached)
- `list_projects()` – List all projects with summaries (cached)
- `get_project_details(product_id)` – Get full hierarchy
- `get_project_by_name(project_name)` – Search by name
- `load_specification_from_file(file_path)` – Load spec from file (legacy, use for initial load)

**Caching Strategy:** Tools accept optional `ToolContext` to transparently cache results in ADK's persistent state. TTL defaults to 5 minutes (configurable). Cache keys: `projects_summary`, `projects_list`, `projects_last_refreshed_utc`.

### Database Mutation Tools (`tools/db_tools.py`)
- `create_or_get_product()` – Create product or return existing
- `save_vision_tool()` – Persist vision statement to database
- `save_roadmap_tool()` – Create theme → epic → feature hierarchy

### Specification Persistence Tools (`tools/spec_tools.py`)
- `save_project_specification(product_id, spec_source, content)` – Save/update specification
  - **spec_source="file"**: Loads from file path, stores path reference (no backup)
  - **spec_source="text"**: Saves pasted content, creates backup in `specs/{safe_name}_{product_id}_spec.md`
  - Validates file size (<100KB), handles UTF-8 encoding
  - Updates existing spec if product already has one
- `read_project_specification()` – Retrieve spec for active project
  - Returns full spec content, file path, token estimate (~chars/4)
  - Extracts markdown headings for navigation (max 20)
  - Agents should call this BEFORE asking questions to check if info exists in spec

**Usage Pattern:**
```python
# During project creation (orchestrator)
spec_content = load_specification_from_file("test_specs/spec.md")
# After vision saved
save_project_specification({
    "product_id": new_product_id,
    "spec_source": "file",
    "content": "test_specs/spec.md"
})

# In downstream agents (roadmap, stories)
spec = read_project_specification(tool_context=context)
if spec["success"]:
    # Search spec_content before asking questions
    if "authentication" in spec["spec_content"].lower():
        # Extract requirements from spec
```

### Story Pipeline Tools (`orchestrator_agent/agent_tools/story_pipeline/tools.py`)
- `process_feature_for_stories()` – Generate stories for single feature with INVEST validation
- `process_features_batch()` – Batch process multiple features (max 10)
- `save_validated_stories()` – Persist pre-validated stories without re-processing

### Sprint Planning Tools (`orchestrator_agent/agent_tools/sprint_planning/tools.py`)
- `get_backlog_for_planning()` – Query TO_DO stories ready for sprint
- `plan_sprint_tool()` – Create draft sprint with validation
- `save_sprint_tool()` – Persist sprint to database with metrics
- `get_sprint_details()` – View sprint information
- `list_sprints()` – List all sprints for product

### Sprint Execution Tools (`orchestrator_agent/agent_tools/sprint_planning/sprint_execution_tools.py`)
- `update_story_status()` – Change story status (TO_DO/IN_PROGRESS/DONE)
- `complete_story_with_notes()` – Mark story DONE with completion documentation
- `update_acceptance_criteria()` – Update AC mid-sprint with traceability
- `create_followup_story()` – Create descoped work story linked to parent
- `batch_update_story_status()` – Daily standup batch status updates
- `modify_sprint_stories()` – Add/remove stories mid-sprint
- `complete_sprint()` – Mark sprint complete with velocity metrics

## Response Format Contract

All agents must return valid JSON matching their `OutputSchema`. Example:

```json
{
  "product_vision_statement": "Unified inbox for busy professionals...",
  "is_complete": true,
  "clarifying_questions": []
}
```

**Error Handling:** If parsing fails, `parse_agent_output()` returns `(None, error_message)`. The system preserves state and allows users to continue despite parse failures.

## Session Persistence

**How it works:**
1. `DatabaseSessionService` manages sessions in SQLite (`agile_simple.db`)
2. Each session is scoped by `(app_name, user_id, session_id)`
3. State is a dict that persists across runner calls
4. **Note:** Current implementation uses `SESSION_ID = str(uuid.uuid4())` generating new session per run

**Usage in ADK Web:**
```bash
python main.py  # Starts orchestrator with session persistence
```

## Development Workflows

### Run Interactive Orchestrator (Recommended)
```bash
python main.py
```
Starts ADK Web with:
- Session persistence via `DatabaseSessionService`
- Orchestrator agent as root (with App object)
- All sub-agents accessible via AgentTool
- Pre-loaded project state on startup

### Run Full Automated Workflow
```bash
python product_workflow.py
```
Executes vision → roadmap pipeline with complete input. Demonstrates LoopAgent orchestration pattern (legacy, for reference).

### Run Tests
```bash
pytest tests/
```
Test database fixtures in `tests/conftest.py` create fresh SQLite engine for each test.

## Story Pipeline Architecture

### Multi-Agent INVEST Validation System

**Location:** `orchestrator_agent/agent_tools/story_pipeline/`

**Architecture:** LoopAgent + SequentialAgent hybrid
- `story_validation_loop` (LoopAgent) wraps sequential pipeline
- Max 4 iterations with early exit when INVEST score ≥ 90
- Three sub-agents process features in sequence:

#### 1. Story Draft Agent
**File:** `story_pipeline/story_draft_agent/agent.py`
- Generates initial user story from feature description
- Applies vision constraints from alignment checker
- Outputs: story title, description, acceptance criteria (3-5 items)

#### 2. INVEST Validator Agent
**File:** `story_pipeline/invest_validator_agent/agent.py`
- Validates against 6 INVEST principles (Independent, Negotiable, Valuable, Estimable, Small, Testable)
- Returns granular scoring: 20 points per dimension (0-120 total → normalized 0-100)
- Checks time-frame alignment ("Now" stories can't reference "Later" features)
- Provides specific improvement suggestions for scores < 90

#### 3. Story Refiner Agent
**File:** `story_pipeline/story_refiner_agent/agent.py`
- Refines story based on validation feedback
- Preserves approved elements, improves weak dimensions
- Re-validates until score ≥ 90 or max iterations reached

### Vision Alignment Enforcement

**File:** `orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py`

**Purpose:** Deterministic constraint enforcement to prevent LLM drift from product vision

**Key Functions:**
- `extract_forbidden_capabilities()` – Maps vision keywords to forbidden story elements
- `check_alignment_before_pipeline()` – FAIL-FAST validation before story generation
- `check_alignment_after_validation()` – Post-pipeline drift detection

**Vision Constraint Patterns** (5 categories):
1. **Platform Constraints**: "mobile-only" → forbids web/desktop mentions
2. **Connectivity**: "offline-first" → forbids real-time sync, cloud storage
3. **UX Philosophy**: "distraction-free" → forbids notifications, gamification
4. **User Segment**: "casual users" → forbids industrial/enterprise terms
5. **Scope Constraints**: "simple" → forbids AI/ML, advanced analytics

**Example:**
```python
# Vision: "offline-first mobile app"
# Feature: "Real-time cloud sync"
# Result: REJECTED before pipeline runs (saves LLM tokens)
alignment_result = check_alignment_before_pipeline(
    vision="offline-first mobile app",
    feature_description="Real-time cloud sync"
)
# Returns: {"aligned": False, "violations": ["Forbidden: real-time (conflicts with offline-first)"]}
```

### Pipeline Iteration Flow

```
Feature Input
    ↓
Alignment Check (FAIL-FAST)
    ↓ (if aligned)
Iteration 1: Draft → Validate (score: 65) → Refine
    ↓
Iteration 2: Validate (score: 85) → Refine
    ↓
Iteration 3: Validate (score: 92) → ACCEPT
    ↓
Post-Validation Alignment Check
    ↓
Save to Database (status: TO_DO, validation_score: 92)
```

## Folder Structure (ADK Best Practices)

```
orchestrator_agent/          # Root agent (entry point)
  ├── agent.py              # Defines root_agent and app (App object)
  ├── instructions.txt      # Orchestrator instructions
  └── agent_tools/
      ├── product_vision_tool/
      │   ├── agent.py      # Vision agent
      │   └── instructions.txt
      ├── product_roadmap_agent/
      │   ├── agent.py      # Roadmap agent
      │   └── instructions.txt
      ├── story_pipeline/
      │   ├── pipeline.py   # LoopAgent orchestrator
      │   ├── tools.py      # process_feature_for_stories, batch
      │   ├── alignment_checker.py  # Vision constraint enforcement
      │   ├── story_draft_agent/
      │   ├── invest_validator_agent/
      │   └── story_refiner_agent/
      └── sprint_planning/
          ├── tools.py      # Sprint planning tools
          ├── sprint_execution_tools.py  # Status updates, completion
          └── sprint_query_tools.py      # Backlog queries

tools/
  ├── orchestrator_tools.py       # Database query tools (FunctionTool)
  ├── db_tools.py                 # Database mutation tools
  └── spec_tools.py               # Specification persistence tools

specs/                       # Auto-created backup files for pasted specs

main.py                      # CLI entry point (calls orchestrator app)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `main.py` | ADK Web bootstrap; session initialization |
| `orchestrator_agent/agent.py` | Root orchestrator with all agent tools |
| `orchestrator_agent/agent_tools/product_vision_tool/agent.py` | Vision agent definition |
| `orchestrator_agent/agent_tools/product_roadmap_agent/agent.py` | Roadmap agent definition |
| `orchestrator_agent/agent_tools/story_pipeline/pipeline.py` | Story validation LoopAgent |
| `orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py` | Vision constraint enforcement |
| `orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py` | Draft generator |
| `orchestrator_agent/agent_tools/story_pipeline/invest_validator_agent/agent.py` | INVEST scorer |
| `orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/agent.py` | Story refiner |
| `orchestrator_agent/agent_tools/sprint_planning/tools.py` | Sprint planning tools |
| `orchestrator_agent/agent_tools/sprint_planning/sprint_execution_tools.py` | Sprint status updates |
| `agile_sqlmodel.py` | SQLModel schema and database initialization |
| `utils/schemes.py` | Shared Pydantic schemas across agents |
| `utils/response_parser.py` | JSON response validation |
| `tools/orchestrator_tools.py` | Read-only project query tools |
| `tools/db_tools.py` | Database mutation tools |
| `tools/spec_tools.py` | Specification persistence and retrieval |

## Common Pitfalls

1. **Agent Transfer Blocking:** Always set `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True` to prevent unwanted agent transfers.

2. **Schema Mismatch:** Agent `OutputSchema` must exactly match the model's `output_schema` parameter. Mismatches cause parsing failures.

3. **Missing Instructions:** Agents require instruction text (typically from external file). Ensure `load_instruction()` path is correct.

4. **Cached Tool Results:** If `ToolContext` is missing (e.g., in unit tests), tools bypass cache and hit DB directly. This is intentional.

5. **Foreign Key Errors:** Always enable SQLite pragmas before creating tables. See `agile_sqlmodel.py` for event listener pattern.

6. **Accumulating State:** Vision agent must receive full requirement history for context, not just the latest user message.

7. **Specification Amnesia:** Specifications are now persisted in the database and retrievable on-demand. Agents should call `read_project_specification()` BEFORE asking questions to check if the answer already exists in the spec. This prevents redundant questioning.

8. **Documentation Files:** Do NOT create `.md` files or documentation files unless the user explicitly asks for it. Focus on code implementation only.

9. **Alignment Violations:** If story generation produces features contradicting the vision (e.g., "web UI" for "mobile-only" app), the alignment checker will reject them BEFORE pipeline runs. Don't try to transform violations—respect vision constraints.

10. **Story Pipeline Early Exit:** Pipeline exits when INVEST score ≥ 90 OR max 4 iterations reached. Low-quality stories (score < 70) should be flagged for manual review, not auto-accepted.

## Evaluation Metrics (For TCC)

The system will be validated using:
- **Cognitive Load:** NASA-TLX questionnaire (captured after sprint planning via `WorkflowEvent`)
- **Artifact Quality:** INVEST criteria for user stories (automated scoring 0-100)
- **Workflow Efficiency:** Cycle time and lead time (tracked via `WorkflowEvent` table)
- **Baseline:** Performance vs. solo developer with traditional tools

### WorkflowEvent Metrics Collection

**Table:** `workflow_events` (in `agile_sqlmodel.py`)

**Event Types:**
- `SPRINT_PLAN_DRAFT` – Draft creation (includes story count, duration)
- `SPRINT_PLAN_SAVED` – Persistence (includes stories linked, tasks created)
- `SPRINT_COMPLETED` – Sprint end (includes velocity, completion rate)
- `STORY_GENERATED` – Story pipeline completion (includes INVEST score, iterations)
- `VISION_SAVED`, `ROADMAP_SAVED` – Artifact creation timestamps

**Querying Metrics:**
```python
# Get average planning duration
events = session.exec(
    select(WorkflowEvent).where(WorkflowEvent.event_type == WorkflowEventType.SPRINT_PLAN_DRAFT)
).all()
avg_duration = sum(e.duration_seconds for e in events) / len(events)

# Get INVEST score distribution
story_events = session.exec(
    select(WorkflowEvent).where(WorkflowEvent.event_type == WorkflowEventType.STORY_GENERATED)
).all()
scores = [e.event_metadata.get("validation_score") for e in story_events]
```

## Current Implementation Status

**✅ Fully Implemented:**
- Product Owner Agent (vision + roadmap generation)
- Specification Persistence (save/read from DB, file/text sources, on-demand access)
- User Story Generation with INVEST validation (3-agent pipeline)
- Sprint Planning Agent (draft → review → commit pattern)
- Sprint Execution Tools (status updates, completion tracking, mid-sprint modifications)
- Vision Alignment Enforcement (deterministic constraint checking)
- Audit Logging (story completion, workflow events)

**🚧 Partially Implemented:**
- Scrum Master Event Orchestration (Sprint Planning complete; Daily, Review, Retrospective planned)
- Definition of Done (DoD) tracking (story completion fields exist; formal DoD checklist not implemented)

**📋 Planned (Not Yet Started):**
- Daily Scrum Agent (automated standup facilitation)
- Sprint Review Agent (demo coordination)
- Sprint Retrospective Agent (improvement suggestion generation)
- Developer Support Agent (task breakdown assistance)

See `CLAUDE.md` for TCC research methodology and `PLANNING_WORKFLOW.md` for complete workflow documentation.

