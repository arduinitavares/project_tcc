# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a TCC (thesis/capstone) project titled **"Plataforma de Gestão Ágil com Agentes Autônomos"** (Autonomous Agile Management Platform). The goal is to create a multi-agent system that simulates complete Scrum roles to mitigate methodological overload for small software teams (1-4 developers).

### ⚠️ Current Status: Early Prototype Phase

**Important:** The current codebase contains an early exploration with vision and roadmap agents. This is NOT the final TCC implementation described in the approved proposal (`Proposta_TCC_Alexandre_Tavares.docx`).

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

### Current Implementation (Prototype)

The existing codebase demonstrates:
- Basic agent orchestration using Google ADK and LiteLLM
- Session-based state management with SQLite persistence
- Two exploratory agents (vision + roadmap) that may inform the final PO agent design

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

### Current Prototype Agents

The existing codebase has two exploratory agents (this will change to align with the proposal):

1. **Product Vision Agent** (`product_vision_agent/`)
   - Generates product vision statements from unstructured requirements
   - Returns draft visions and clarifying questions when information is missing
   - Uses `InputSchema` and `OutputSchema` from `utils/schemes.py`
   - Instructions loaded from `product_vision_agent/instructions.txt`

2. **Product Roadmap Agent** (`product_roadmap_agent/`)
   - Creates high-level agile roadmaps from completed product visions
   - Organizes features into themes with time frames (Now/Next/Later)
   - Has its own `InputSchema` and `OutputSchema` (defined in `agent.py`)
   - Instructions loaded from `product_roadmap_agent/instructions.txt`

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

Sessions are user-scoped (`USER_ID = "user_123"`) and application-scoped (`APP_NAME = "ProductManager"`). The system reuses existing sessions across restarts to maintain conversation continuity.

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

Session data stored in `my_agent_data.db` (SQLite). The database is created automatically by `DatabaseSessionService` and persists:
- Session IDs
- User IDs and app names
- Complete session state dictionaries

## LLM Configuration

The project uses LiteLLM for model abstraction:
```python
model = LiteLlm(
    model="openrouter/openai/gpt-5-nano",
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

## Gap Analysis: Current vs. Target

**What exists:** Vision + Roadmap agents (exploratory prototype)
**What's needed:** PO + SM + Dev Support agents simulating full Scrum cycle

**What exists:** Simple linear workflow
**What's needed:** Multi-agent collaboration with formal protocols

**What exists:** Basic session persistence
**What's needed:** Scrum artifacts (Product/Sprint Backlog, DoD) and event tracking

**What exists:** No evaluation framework
**What's needed:** NASA-TLX, INVEST validation, cycle time metrics, baseline comparison
