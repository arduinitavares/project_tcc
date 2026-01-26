# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a TCC (thesis/capstone) project titled **"Plataforma de Gestão Ágil com Agentes Autônomos"** (Autonomous Agile Management Platform). The goal is to create a multi-agent system that simulates complete Scrum roles to mitigate methodological overload for small software teams (1-4 developers).

### ⚠️ Current Status: Production-Ready Features with Gaps

**Important:** The codebase contains **production-ready implementations** of key TCC features:
- ✅ **Product Owner Agent** (vision + roadmap + story generation with INVEST validation)
- ✅ **Sprint Planning Tools** (draft → review → commit pattern)
- ✅ **Sprint Execution Tools** (status updates, completion tracking, audit logging)
- 🚧 **Scrum Master Event Orchestration** (Sprint Planning complete; Daily, Review, Retrospective planned)
- 📋 **Developer Support Agent** (not yet started)

The system is **ready for TCC evaluation** for implemented features. See `PLANNING_WORKFLOW.md` for complete workflow documentation.

### Target Architecture (From Approved Proposal)

The final system must implement three specialized agents simulating Scrum roles:

1. **Product Owner Agent** - Interprets natural language requirements and generates structured Product Backlog (user stories with INVEST criteria, acceptance criteria, prioritization)

2. **Scrum Master Agent** - Facilitates Scrum events (Sprint Planning, Daily Scrum, Sprint Review, Sprint Retrospective), monitors process, detects impediments, ensures timeboxing

3. **Developer Support Agent** - Assists with task execution, updates task status, ensures adherence to Definition of Done (DoD)

### Evaluation Requirements

The TCC will be validated using:
- **Cognitive Load**: NASA-TLX questionnaire applied to users
- **Artifact Quality**: INVEST criteria evaluation for user stories
- **Workflow Efficiency**: Cycle time and lead time measurements
- **Baseline Comparison**: Performance vs. solo developer using traditional tools

### Current Implementation

The existing codebase demonstrates:
- **Agent orchestration** using Google ADK and LiteLLM
- **Session-based state management** with SQLite persistence
- **7 specialized agents:**
  1. **Product Vision Agent** - Multi-turn vision building (7 components)
  2. **Product Roadmap Agent** - Theme-based roadmap planning
  3. **Story Draft Agent** - INVEST-compliant story generation via schema validation
  4. **Spec Validator Agent** - Domain-aware technical specification compliance
  5. **Story Refiner Agent** - Iterative refinement (max 4 loops)
  6. **Orchestrator Agent** - Root coordinator with all tools
  7. **Story Pipeline Orchestrator** (LoopAgent) - Manages draft → validate → refine cycle
- **INVEST enforcement** - Draft Agent's Pydantic validators enforce INVEST principles
- **Vision alignment enforcement** - Deterministic constraint checking via `alignment_checker.py`
- **Sprint planning** - Draft → review → commit pattern with team auto-creation
- **Sprint execution** - 7 tools for status updates, AC changes, completion tracking
- **Audit logging** - `StoryCompletionLog` and `WorkflowEvent` tables for TCC metrics

## Development Environment

- **Python Version**: 3.12+
- **Package Manager**: uv (recommended) or pip
- **Dependencies Management**: Dependencies defined in `pyproject.toml`
- **Virtual Environment**: `.venv/` (use `uv` to manage)

### Setup Commands

```bash
# Install dependencies with uv
uv sync

# Or with pip
pip install -e .

# Run the main interactive application
python main.py

# Run the workflow example (demonstrates LoopAgent orchestration)
python product_workflow.py
```

### Environment Configuration

Create a `.env` file with:
```
OPEN_ROUTER_API_KEY=your_key_here
```

The application uses OpenRouter to access LLM models (currently configured for `openrouter/openai/gpt-5-nano`).

## Architecture

### Current Agent System (7 Agents)

The codebase implements a sophisticated multi-agent system:

1. **Orchestrator Agent** (`orchestrator_agent/agent.py`)
   - Root coordinator with all sub-agents as tools
   - Manages workflow state and phase transitions
   - Exposes `app = App(...)` object for ADK web CLI

2. **Product Vision Agent** (`orchestrator_agent/agent_tools/product_vision_tool/`)
   - Generates product vision statements from unstructured requirements
   - Returns draft visions and clarifying questions when information is missing
   - Uses `InputSchema` and `OutputSchema` from `utils/schemes.py`
   - Multi-turn conversation with state merging (7 required components)

3. **Product Roadmap Agent** (`orchestrator_agent/agent_tools/product_roadmap_agent/`)
   - Creates high-level agile roadmaps from completed product visions
   - Organizes features into themes with time frames (Now/Next/Later)
   - 4-step process: Identify → Group → Prioritize → Finalize

4. **Story Draft Agent** (`orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/`)
   - Generates INVEST-compliant user stories from feature descriptions
   - Pydantic schema validators enforce INVEST principles (story points 1-8, \"As a... I want... so that...\" format)
   - Applies vision constraints from alignment checker
   - Outputs: title, description, 3-5 acceptance criteria

5. **Spec Validator Agent** (`orchestrator_agent/agent_tools/story_pipeline/spec_validator_agent/`)
   - Domain-aware validation against technical specification requirements
   - Binds requirements to stories based on feature context
   - Returns compliance status with specific suggestions for missing artifacts

6. **Story Refiner Agent** (`orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/`)
   - Refines story based on spec validation feedback
   - Preserves approved elements, improves weak dimensions
   - Re-validates until spec-compliant or max 4 iterations reached

7. **Story Pipeline Orchestrator** (`orchestrator_agent/agent_tools/story_pipeline/pipeline.py`)
   - LoopAgent that manages Draft → Spec Validate → Refine cycle
   - Max 4 iterations with early exit when spec-compliant
   - Enforces vision alignment and data integrity contracts before persistence

8. **Legacy User Story Agent** (deprecated, to be removed)

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

**Example FAIL-FAST Validation:**
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

**Drift Detection After Pipeline:**
```python
# AFTER story is generated
alignment_result = check_alignment_after_validation(
    vision="mobile-only app",
    story_title="As a user, I want to access my data from the web dashboard...",
    story_description="...",
    acceptance_criteria=[...]
)
# Returns: {"aligned": False, "violations": ["Forbidden: web dashboard (conflicts with mobile-only)"]}
# Story rejected, pipeline re-runs with stricter constraints
```

### Database Schema

**Core Tables** (from `agile_sqlmodel.py`):
- `products` – Top-level container (has `vision`, `roadmap` fields)
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
- Audit logging for story completion via `StoryCompletionLog`
- Workflow metrics captured via `WorkflowEvent` for TCC evaluation

### Tool Architecture

**Read-Only Query Tools** (`tools/orchestrator_tools.py`):
- `count_projects()` – Count total projects (cached)
- `list_projects()` – List all projects with summaries (cached)
- `get_project_details(product_id)` – Get full hierarchy
- `get_project_by_name(project_name)` – Search by name

**Database Mutation Tools** (`tools/db_tools.py`):
- `create_or_get_product()` – Create product or return existing
- `save_vision_tool()` – Persist vision statement
- `save_roadmap_tool()` – Create theme → epic → feature hierarchy

**Story Pipeline Tools** (`orchestrator_agent/agent_tools/story_pipeline/tools.py`):
- `process_feature_for_stories()` – Generate stories for single feature with INVEST validation
- `process_features_batch()` – Batch process multiple features (max 10)
- `save_validated_stories()` – Persist pre-validated stories

**Sprint Planning Tools** (`orchestrator_agent/agent_tools/sprint_planning/tools.py`):
- `get_backlog_for_planning()` – Query TO_DO stories ready for sprint
- `plan_sprint_tool()` – Create draft sprint with validation
- `save_sprint_tool()` – Persist sprint with metrics
- `get_sprint_details()` – View sprint information
- `list_sprints()` – List all sprints

**Sprint Execution Tools** (`orchestrator_agent/agent_tools/sprint_planning/sprint_execution_tools.py`):
- `update_story_status()` – Change story status (TO_DO/IN_PROGRESS/DONE)
- `complete_story_with_notes()` – Mark DONE with documentation
- `update_acceptance_criteria()` – Update AC mid-sprint with traceability
- `create_followup_story()` – Create descoped work story linked to parent
- `batch_update_story_status()` – Daily standup batch updates
- `modify_sprint_stories()` – Add/remove stories mid-sprint
- `complete_sprint()` – Mark sprint complete with velocity metrics

**Caching Strategy:** Read-only tools accept optional `ToolContext` to cache results (5min TTL).

### Target Architecture (To Be Implemented)

Per the approved TCC proposal, the final system needs:

**Scrum Artifact Management:**
- Product Backlog (ordered list of user stories with INVEST validation)
- Sprint Backlog (selected items + plan for current sprint)
- Increment tracking with Definition of Done (DoD)

**Scrum Event Orchestration:**
- Sprint Planning (8h timebox for 1-month sprint, proportional for shorter)
- Daily Scrum (15min timebox)
- Sprint Review (4h timebox for 1-month sprint)
- Sprint Retrospective (3h timebox for 1-month sprint)

**Three-Agent Collaboration:**
- Formal communication protocol between agents
- Shared memory/context for project state
- Orchestration pattern (likely hierarchical or sequential)

### Two Workflow Implementations

**1. Interactive Session-Based Workflow** (`main.py`)
- User-driven conversational interface
- Persistent state management via SQLite database (`my_agent_data.db`)
- Accumulates requirements across multiple turns
- Switches from vision to roadmap agent when vision is complete
- Key functions:
  - `load_or_create_session()`: Session management
  - `append_user_text_to_requirements()`: Accumulates user inputs
  - `run_vision_agent()`: Calls vision agent with accumulated requirements
  - `save_state()`: Persists state to database

**2. Automated Orchestration Workflow** (`product_workflow.py`)
- Uses `LoopAgent` as master orchestrator
- Chains vision → roadmap agents automatically
- Single-pass execution with complete requirements
- Demonstrates declarative workflow orchestration via agent instructions

### State Management

The session state tracks:
```python
{
    "product_vision_statement": str,      # Current vision
    "product_roadmap": str,               # Current roadmap
    "unstructured_requirements": str,     # Accumulated user input
    "is_complete": bool,                  # Vision completion flag
    "clarifying_questions": list[str]     # Questions needing answers
}
```

State is persisted to SQLite via Google ADK's `DatabaseSessionService`.

### Utility Modules (`utils/`)

- **agent_io.py**: Agent I/O handling with colored terminal output
  - `call_agent_async()`: High-level wrapper for agent execution
  - `process_agent_event()`: Handles streaming events from agents

- **response_parser.py**: Parses and validates agent JSON responses using Pydantic
  - `parse_agent_output()`: Returns `(structured_instance, error_message)` tuple

- **persistence.py**: State persistence helpers
  - `persist_product_vision_state()`: Merges vision data into session state

- **state.py**: Debugging utilities
  - `display_state()`: Pretty-prints session state

- **colors.py**: Terminal color constants for formatted output

- **schemes.py**: Shared Pydantic schemas for agents

### Agent Response Flow

1. User provides input → accumulated in `unstructured_requirements`
2. Agent receives full accumulated requirements (not just latest message)
3. Agent returns structured JSON response
4. Response parsed via `parse_agent_output()`
5. State updated with new vision/roadmap data
6. State persisted to database
7. If vision complete, system switches to roadmap agent

## Important Implementation Details

### Multi-Turn Context Handling

The vision agent must receive ALL accumulated requirements from the session history, not just the latest user message. This is critical for maintaining context across clarifying questions:

```python
# In main.py:
append_user_text_to_requirements(state, user_text)  # Accumulate
response = await run_vision_agent(
    accumulated_requirements=str(state["unstructured_requirements"])  # Pass full history
)
```

### Agent Configuration

Both agents are configured with:
- `disallow_transfer_to_parent=True`
- `disallow_transfer_to_peers=True`

This prevents unwanted agent transfers and keeps workflows controlled.

### Session Management

Sessions are user-scoped (`USER_ID = "user_123"`) and application-scoped (`APP_NAME = "project_tcc"`). **Note:** Current implementation uses `SESSION_ID = str(uuid.uuid4())` generating new session per run (not reused across restarts).

### Error Handling

When agent responses fail to parse:
- Error is displayed to user with details
- State is still persisted (preserves accumulated requirements)
- User can continue conversation despite parse failures

## Key Files Reference

- `main.py:192-198` - Vision agent invocation with accumulated requirements
- `main.py:234-237` - State mirroring from agent output
- `main.py:265-271` - Runner switching logic
- `utils/response_parser.py:19-49` - Response validation with detailed error reporting
- `product_workflow.py:70-105` - LoopAgent orchestration instructions

## Database

Session data stored in `agile_simple.db` (SQLite). The database is created automatically by `DatabaseSessionService` and persists:
- Session IDs
- User IDs and app names
- Complete session state dictionaries

**Business data** stored in same database:
- Products, themes, epics, features
- User stories with INVEST scores and completion tracking
- Sprints with velocity metrics
- Story completion audit logs
- Workflow events for TCC evaluation

## LLM Configuration

The project uses LiteLLM for model abstraction:
```python
model = LiteLlm(
    model="openrouter/google/gemini-2.5-pro",
    api_key=os.getenv("OPEN_ROUTER_API_KEY")
)
```

To change models, update the `model` parameter in agent initialization files.

## TCC Methodology and Timeline

This project follows **Design Science Research (DSR)** methodology with six phases:

1. **Problem Identification** - Small teams face cognitive overload and role conflicts when applying Scrum
2. **Objective Definition** - Create abstraction layer that simulates Scrum roles via agents
3. **Design & Development** - Build PoC with three agents and orchestration
4. **Demonstration** - Apply PoC in controlled test scenario
5. **Evaluation** - Compare against baseline using defined metrics
6. **Communication** - Document findings in TCC monograph

**Timeline:** Approximately 22 weeks total (see Gantt chart in proposal document)

## Key References

- **Proposal Document**: `Proposta_TCC_Alexandre_Tavares.docx` - Contains complete problem statement, related work analysis, methodology, and evaluation criteria
- **Scrum Guide**: The implementation must faithfully simulate Scrum as defined by Schwaber & Sutherland (2020)
- **Related Work**: AgileCoder (Nguyen et al., 2024), CogniSim (Cinkusz & Chudziak, 2025) - These focus on larger teams or code generation; this TCC addresses the unique gap of small team methodological support

## Implementation Status: Current vs. Target

**✅ Fully Implemented (Production-Ready):**
- Product Owner Agent with vision + roadmap generation
- User Story Generation with 3-agent INVEST validation pipeline
- Vision Alignment Enforcement (deterministic constraint checking)
- Sprint Planning with draft → review → commit pattern
- Sprint Execution with 7 specialized tools:
  - `update_story_status()` - Simple status changes
  - `complete_story_with_notes()` - DONE with documentation
  - `update_acceptance_criteria()` - AC changes with traceability
  - `create_followup_story()` - Descoped work tracking
  - `batch_update_story_status()` - Daily standup updates
  - `modify_sprint_stories()` - Mid-sprint scope changes
  - `complete_sprint()` - Sprint completion with velocity
- Story Completion Audit System (`StoryCompletionLog` table)
- Workflow Metrics System (`WorkflowEvent` table for TCC evaluation)

**🚧 Partially Implemented:**
- Scrum Master Event Orchestration (Sprint Planning complete; Daily, Review, Retrospective planned)
- Definition of Done (DoD) tracking (completion fields exist; formal checklist not implemented)

**📋 Planned (Not Yet Started):**
- Daily Scrum Agent (automated standup facilitation)
- Sprint Review Agent (demo coordination)
- Sprint Retrospective Agent (improvement suggestion generation)
- Developer Support Agent (task breakdown assistance)

**Key Achievement:** The system demonstrates **working multi-agent orchestration** with INVEST validation and sprint management, suitable for TCC evaluation of implemented features.
