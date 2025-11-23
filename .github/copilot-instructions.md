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
- `themes` – Product groupings (belongs to product, contains epics)
- `epics` – Feature groups (belongs to theme, contains features)
- `features` – User-facing capabilities (belongs to epic)
- `user_stories` – INVEST-compliant stories (belongs to product, linked to sprints)
- `sprints` – Development cycles (tracks `start_date`, `end_date`, status)
- `tasks` – Sprint tasks with assigned members
- `teams` / `team_members` – Organizational structure
- **Link tables:** `TeamMembership`, `ProductTeam`, `SprintStory`

**Key Patterns:**
- Foreign keys enforced via SQLite pragma: `PRAGMA foreign_keys=ON`
- Timestamps use `func.now()` for server defaults
- Many-to-many relationships defined via explicit link tables

## Tool Architecture

**Read-only tools** (`tools/orchestrator_tools.py`):
- `count_projects()` – Count total projects (cached)
- `list_projects()` – List all projects with summaries (cached)
- `get_project_details(product_id)` – Get full hierarchy
- `get_project_by_name(project_name)` – Search by name

**Caching Strategy:** Tools accept optional `ToolContext` to transparently cache results in ADK's persistent state. TTL defaults to 5 minutes (configurable). Cache keys: `projects_summary`, `projects_list`, `projects_last_refreshed_utc`.

**Database Tools** (`tools/db_tools.py`):
- `create_or_get_product()` – Create product or return existing
- Agent-facing tools for creating stories, tasks, themes, etc.

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
1. `DatabaseSessionService` manages sessions in SQLite (`agile_sqlmodel.db`)
2. Each session is scoped by `(app_name, user_id, session_id)`
3. State is a dict that persists across runner calls
4. Sessions are reused on restart for conversation continuity

**Usage in ADK Web:**
```bash
adk web --session_service_uri=sqlite:///agile_sqlmodel.db --agent-path=agent.py
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

## Folder Structure (ADK Best Practices)

```
orchestrator_agent/          # Root agent (entry point)
  ├── agent.py              # Defines root_agent and app (App object)
  └── instructions.txt      # Orchestrator instructions

product_vision_agent/
  ├── agent.py              # Defines root_agent (wrapped by AgentTool)
  └── instructions.txt

product_roadmap_agent/
  ├── agent.py              # Defines root_agent (wrapped by AgentTool)
  └── instructions.txt

tools/
  ├── product_vision_tool.py      # AgentTool wrapper for vision agent
  ├── product_roadmap_tool.py     # AgentTool wrapper for roadmap agent
  ├── orchestrator_tools.py       # Database query tools (FunctionTool)
  └── db_tools.py                 # Database mutation tools

main.py                      # CLI entry point (calls orchestrator app)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `main.py` | ADK Web bootstrap; session initialization |
| `product_workflow.py` | LoopAgent orchestration example (vision → roadmap) |
| `product_vision_agent/agent.py` | Vision agent definition |
| `product_roadmap_agent/agent.py` | Roadmap agent definition |
| `orchestrator.py` | Orchestrator routing logic (Claude with tools) |
| `agile_sqlmodel.py` | SQLModel schema and database initialization |
| `utils/schemes.py` | Shared Pydantic schemas across agents |
| `utils/response_parser.py` | JSON response validation |
| `utils/agent_io.py` | High-level agent runner wrapper with event streaming |
| `tools/orchestrator_tools.py` | Read-only project query tools |
| `tools/db_tools.py` | Database mutation tools |

## Common Pitfalls

1. **Agent Transfer Blocking:** Always set `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True` to prevent unwanted agent transfers.

2. **Schema Mismatch:** Agent `OutputSchema` must exactly match the model's `output_schema` parameter. Mismatches cause parsing failures.

3. **Missing Instructions:** Agents require instruction text (typically from external file). Ensure `load_instruction()` path is correct.

4. **Cached Tool Results:** If `ToolContext` is missing (e.g., in unit tests), tools bypass cache and hit DB directly. This is intentional.

5. **Foreign Key Errors:** Always enable SQLite pragmas before creating tables. See `agile_sqlmodel.py` for event listener pattern.

6. **Accumulating State:** Vision agent must receive full requirement history for context, not just the latest user message.

7. **Documentation Files:** Do NOT create `.md` files or documentation files unless the user explicitly asks for it. Focus on code implementation only.

## Evaluation Metrics (For TCC)

The system will be validated using:
- **Cognitive Load:** NASA-TLX questionnaire
- **Artifact Quality:** INVEST criteria for user stories
- **Workflow Efficiency:** Cycle time and lead time
- **Baseline:** Performance vs. solo developer with traditional tools

## Next Steps (Gap Analysis)

**Prototype → Final Implementation:**
- Implement three agents: Product Owner, Scrum Master, Developer Support
- Add Scrum event orchestration (Sprint Planning, Daily, Review, Retrospective)
- Implement Definition of Done (DoD) tracking
- Add sprint artifact management (Product/Sprint Backlog)
- Build evaluation framework (NASA-TLX, INVEST validator, cycle time tracker)

See `CLAUDE.md` for complete target architecture details.

