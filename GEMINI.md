# Autonomous Agile Management Platform

This is a TCC (thesis/capstone) project implementing an **Autonomous Agile Management Platform** – a multi-agent system that simulates Scrum roles to reduce cognitive load for small software teams (1-4 developers). The system uses AI agents to guide users through vision planning, roadmap creation, user story generation with INVEST validation, and sprint management.

## Project Status

**✅ Production-Ready Features:**
- Product Owner Agent (vision + roadmap + story generation)
- User Story Pipeline with 3-agent INVEST validation
- Vision Alignment Enforcement (deterministic constraint checking)
- Sprint Planning (draft → review → commit pattern)
- Sprint Execution (7 specialized tools for status updates, completion tracking)
- Audit Logging (story completion logs, workflow events for TCC metrics)

**🚧 In Progress:**
- Scrum Master Event Orchestration (Daily Scrum, Sprint Review, Retrospective)
- Developer Support Agent

See `CLAUDE.md` for TCC methodology and `PLANNING_WORKFLOW.md` for complete workflow documentation.

## Key Technologies

*   **Python 3.12+**
*   **Google ADK (Agent Development Kit):** Multi-agent orchestration (`Agent`, `LoopAgent`, `DatabaseSessionService`)
*   **LiteLLM:** LLM abstraction layer (configured with `openrouter/google/gemini-2.5-pro`)
*   **SQLModel:** ORM with SQLite persistence
*   **Pydantic:** Schema validation and structured output parsing
*   **Dotenv:** Environment variable management
*   **SQLite:** Persistent storage for session state and business data (`agile_simple.db`)

## Architecture

### Multi-Agent System (8 Agents)

The system implements a hierarchical agent architecture with specialized roles:

#### 1. Orchestrator Agent (Root)
**File:** `orchestrator_agent/agent.py`
- Root coordinator exposing `app = App(...)` for ADK web CLI
- Manages workflow state and phase transitions
- Calls child agents as tools via `AgentTool` wrappers

#### 2. Product Vision Agent
**File:** `orchestrator_agent/agent_tools/product_vision_tool/agent.py`
- Multi-turn conversational vision building
- Collects 7 required components: project_name, target_user, problem, product_category, key_benefit, competitors, differentiator
- Generates vision statement from template
- State merging across turns (preserves existing data)

#### 3. Product Roadmap Agent
**File:** `orchestrator_agent/agent_tools/product_roadmap_agent/agent.py`
- 4-step roadmap process: Identify → Group → Prioritize → Finalize
- Organizes features into themes with time frames (Now/Next/Later)
- Creates database hierarchy: Product → Theme → Epic → Feature

#### 4-6. Story Pipeline Agents (3-Agent System)

**Story Draft Agent** (`story_draft_agent/agent.py`)
- Generates initial user story from feature description
- Applies vision constraints from alignment checker
- Outputs: title, description, 3-5 acceptance criteria

**INVEST Validator Agent** (`invest_validator_agent/agent.py`)
- Validates against 6 INVEST principles (Independent, Negotiable, Valuable, Estimable, Small, Testable)
- Granular scoring: 20 points per dimension (0-120 total → normalized 0-100)
- Checks time-frame alignment ("Now" stories can't reference "Later" features)
- Provides specific improvement suggestions for scores < 90

**Story Refiner Agent** (`story_refiner_agent/agent.py`)
- Refines story based on validation feedback
- Preserves approved elements, improves weak dimensions
- Re-validates until score ≥ 90 or max 4 iterations reached

#### 7. Story Pipeline Orchestrator (LoopAgent)
**File:** `orchestrator_agent/agent_tools/story_pipeline/pipeline.py`
- Manages Draft → Validate → Refine cycle
- Max 4 iterations with early exit when INVEST score ≥ 90
- Enforces vision alignment before and after pipeline

#### 8. Legacy User Story Agent (Deprecated)
To be removed in future cleanup.

### Vision Alignment Enforcement

**File:** `orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py`

**Purpose:** Deterministic constraint enforcement to prevent LLM drift from product vision

**5 Constraint Categories:**
1. **Platform Constraints**: "mobile-only" → forbids web/desktop
2. **Connectivity**: "offline-first" → forbids real-time sync, cloud
3. **UX Philosophy**: "distraction-free" → forbids notifications
4. **User Segment**: "casual users" → forbids industrial/enterprise terms
5. **Scope**: "simple" → forbids AI/ML, advanced analytics

**FAIL-FAST Pattern:**
```python
# BEFORE pipeline runs (save LLM tokens)
alignment_result = check_alignment_before_pipeline(
    vision="offline-first mobile app",
    feature_description="Real-time cloud sync"
)
# Returns: {"aligned": False, "violations": [...]}
```

### Database Schema

**Core Tables** (SQLModel in `agile_sqlmodel.py`):
- `products` – Top-level container (vision, roadmap)
- `themes` → `epics` → `features` – Roadmap hierarchy
- `user_stories` – INVEST-validated stories with completion tracking
  - Completion fields: `resolution_type`, `completion_notes`, `evidence_links`, `known_gaps`, `acceptance_criteria_updates`, `follow_up_story_id`
- `story_completion_log` – Audit trail (who, when, why, evidence)
- `sprints` – Development cycles (start/end dates, status)
- `tasks` – Sprint tasks
- `teams` / `team_members` – Organizational structure
- `workflow_events` – TCC evaluation metrics (event_type, duration_seconds, metadata)
- **Link tables:** `TeamMembership`, `ProductTeam`, `SprintStory`

### Tool Catalog

**Read-Only Query Tools** (`tools/orchestrator_tools.py`):
- `count_projects()`, `list_projects()`, `get_project_details()`, `get_project_by_name()`
- Caching: Optional `ToolContext` for 5min TTL cache

**Database Mutation Tools** (`tools/db_tools.py`):
- `create_or_get_product()`, `save_vision_tool()`, `save_roadmap_tool()`

**Story Pipeline Tools** (`story_pipeline/tools.py`):
- `process_feature_for_stories()` – Single feature with INVEST validation
- `process_features_batch()` – Batch process (max 10 features)
- `save_validated_stories()` – Persist pre-validated stories

**Sprint Planning Tools** (`sprint_planning/tools.py`):
- `get_backlog_for_planning()`, `plan_sprint_tool()`, `save_sprint_tool()`
- `get_sprint_details()`, `list_sprints()`

**Sprint Execution Tools** (`sprint_planning/sprint_execution_tools.py`):
- `update_story_status()` – Simple status changes
- `complete_story_with_notes()` – DONE with documentation (resolution_type, evidence_links)
- `update_acceptance_criteria()` – AC changes with traceability (preserves original)
- `create_followup_story()` – Descoped work tracking (linked to parent)
- `batch_update_story_status()` – Daily standup batch updates
- `modify_sprint_stories()` – Add/remove stories mid-sprint
- `complete_sprint()` – Mark complete with velocity metrics

## Development Conventions

*   **Agent-based architecture:** Hierarchical orchestration with root agent + child agents as tools
*   **Schema-driven communication:** Pydantic schemas for all agent I/O (strict validation)
*   **Instruction-based agents:** External `instructions.txt` files define behavior
*   **Session persistence:** SQLite-backed `DatabaseSessionService` for multi-turn state
*   **Stateless agents with state injection:** Agents receive full context as JSON input (no hidden memory)
*   **Incremental refinement:** Each turn merges new input with preserved data (never replaces)
*   **Vision alignment enforcement:** Deterministic validation before/after story generation
*   **Audit logging:** All story completions logged to `story_completion_log` table

## Workflow Phases

### Phase 1: Vision Planning
User provides unstructured requirements → Vision agent collects 7 components → Generates vision statement

### Phase 2: Roadmap Planning
Vision → Roadmap agent creates themes → 4-step process (Identify, Group, Prioritize, Finalize)

### Phase 3: Database Structure Creation
Roadmap themes → Database hierarchy (Product → Theme → Epic → Feature)

### Phase 4: User Story Generation
Feature → Story Pipeline (Draft → Validate → Refine) → INVEST-validated stories (score ≥ 90)

### Phase 5: Sprint Planning
Backlog stories → Plan sprint (goal, duration, story selection) → Draft → Review → Commit

### Phase 6: Sprint Execution
Sprint starts → Status updates → Completion tracking → Audit logging → Sprint completion with velocity

See `PLANNING_WORKFLOW.md` for detailed workflow documentation with code examples.

## Building and Running

### Dependencies

The project uses `uv` for dependency management:

```bash
uv sync
```

### Environment Configuration

Create a `.env` file:
```
OPEN_ROUTER_API_KEY=your_key_here
```

### Running the Orchestrator (Interactive)

Start ADK web interface with session persistence:

```bash
python main.py
```

This provides:
- Session-based state management
- All agents accessible via orchestrator
- Pre-loaded project state on startup

### Running Tests

```bash
pytest tests/
```

Test fixtures create fresh SQLite engine for each test (see `tests/conftest.py`).

## Key Design Patterns

1. **Stateless Agents with State Injection:** Agents don't maintain memory; state passed as JSON
2. **Bucket Brigade Communication:** Each agent receives, processes, and passes structured state
3. **Incremental Refinement:** Each turn adds/updates data, never discards previous work
4. **Schema-Driven Validation:** All agent I/O validated by Pydantic schemas
5. **Multi-Agent Orchestration via AgentTool:** Child agents wrapped as tools in parent's toolset
6. **Vision Alignment as Code:** Deterministic constraint checking prevents LLM drift
7. **Audit-First Completion:** All story status changes logged with evidence and reasoning

## TCC Evaluation Metrics

The system captures metrics for research evaluation:

**Cognitive Load:**
- NASA-TLX questionnaire (captured after sprint planning via `WorkflowEvent`)

**Artifact Quality:**
- INVEST criteria scores (0-100) for all stories
- Tracked via `user_stories.validation_score` field

**Workflow Efficiency:**
- Cycle time and lead time (via `story_completion_log` timestamps)
- Sprint velocity (via `sprints` metrics)
- Planning duration (via `workflow_events` table)

**Event Types in `workflow_events`:**
- `SPRINT_PLAN_DRAFT`, `SPRINT_PLAN_SAVED`, `SPRINT_COMPLETED`
- `STORY_GENERATED` (includes INVEST score, iterations)
- `VISION_SAVED`, `ROADMAP_SAVED`

## File Structure Reference

```
orchestrator_agent/
  ├── agent.py                          # Root orchestrator
  ├── instructions.txt
  └── agent_tools/
      ├── product_vision_tool/          # Vision agent
      ├── product_roadmap_agent/        # Roadmap agent
      ├── story_pipeline/
      │   ├── pipeline.py               # LoopAgent orchestrator
      │   ├── tools.py                  # Story generation tools
      │   ├── alignment_checker.py      # Vision constraint enforcement
      │   ├── story_draft_agent/
      │   ├── invest_validator_agent/
      │   └── story_refiner_agent/
      └── sprint_planning/
          ├── tools.py                  # Sprint planning tools
          ├── sprint_execution_tools.py # Status updates, completion
          └── sprint_query_tools.py

tools/
  ├── orchestrator_tools.py             # Read-only query tools
  └── db_tools.py                       # Database mutation tools

agile_sqlmodel.py                       # Database schema (SQLModel)
utils/
  ├── schemes.py                        # Pydantic schemas
  ├── response_parser.py                # JSON validation
  └── helper.py                         # Utility functions

main.py                                 # CLI entry point
```

## Common Pitfalls

1. **Agent Transfer Blocking:** Always set `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True`
2. **Schema Mismatch:** Agent `OutputSchema` must exactly match model's `output_schema` parameter
3. **Missing Instructions:** Agents require instruction text from external file
4. **Accumulating State:** Vision agent must receive full requirement history, not just latest message
5. **Alignment Violations:** Don't transform violations—respect vision constraints (alignment checker will reject)
6. **Story Pipeline Early Exit:** Pipeline exits when score ≥ 90 OR max 4 iterations (low-quality stories flagged for manual review)

## Related Documentation

- **CLAUDE.md:** TCC methodology, research objectives, implementation status
- **PLANNING_WORKFLOW.md:** Complete workflow documentation with code examples (1600+ lines)
- **.github/copilot-instructions.md:** AI agent coding conventions and patterns
- **tests/:** Integration tests demonstrating tool usage and workflow patterns
