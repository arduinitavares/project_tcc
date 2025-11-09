# Current Implementation Analysis
## Detailed breakdown of the actual codebase as of October 2025

---

## Executive Summary

The TCC codebase is in an **early prototype phase** with a focused, exploratory implementation. Rather than building the complete target system described in the approved proposal, the current code demonstrates two workflow patterns using only two agents (Product Vision and Product Roadmap) that operate in series.

This document provides developers with:
1. What actually exists in the code today
2. How the two agents interact
3. The technology choices and why they were made
4. Clear path from current state to target architecture
5. Key architectural patterns to maintain during expansion

---

## Current System Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  USER INTERACTION LAYER                      │
├─────────────────────────────────────────────────────────────┤
│  Interactive (main.py)  │  Automated (product_workflow.py)   │
│  Multi-turn chat        │  Single-pass orchestration         │
└────────────┬────────────┴──────────────────────┬─────────────┘
             │                                   │
             ▼                                   ▼
┌─────────────────────────┐      ┌───────────────────────────┐
│    Session Management   │      │   Orchestration Layer     │
├─────────────────────────┤      ├───────────────────────────┤
│ DatabaseSessionService  │      │  LoopAgent (for Product  │
│ (Google ADK)            │      │   Workflow orchestrator)  │
│ Persists to SQLite      │      │  Runner (for main.py)    │
└────────┬────────────────┘      └──────────┬────────────────┘
         │                                  │
         ▼                                  ▼
    ┌──────────────────────────────────────────────────┐
    │          AGENT LAYER (Current Agents)            │
    ├──────────────────────────────────────────────────┤
    │  Vision Agent ──→ Roadmap Agent                  │
    │  (if vision complete, switch to roadmap)         │
    └──────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
    ┌──────────────────────────────────────────────────┐
    │      RESPONSE PROCESSING & VALIDATION            │
    ├──────────────────────────────────────────────────┤
    │ Parser ──→ Pydantic Validator ──→ Persistence    │
    └──────────────────────────────────────────────────┘
         │
         ▼
    ┌──────────────────────────────────────────────────┐
    │    PERSISTENCE LAYER (SQLite Database)           │
    ├──────────────────────────────────────────────────┤
    │  my_agent_data.db (persistent session state)     │
    └──────────────────────────────────────────────────┘
```

---

## Two Workflow Patterns

### Pattern 1: Interactive Session-Based Workflow (`main.py`)

**Purpose**: Multi-turn conversational interaction where the user can engage in back-and-forth dialogue with clarifying questions.

**Entry Point**: `python main.py`

**Key Characteristics**:
- Session persists across program restarts (retrieved from SQLite)
- User can provide partial requirements and refine them
- Agent asks clarifying questions when information is missing
- When vision is complete, system switches to roadmap agent
- All user input accumulated across turns (context preservation)

**Control Flow** (per user turn):

```
1. Load existing session from DB or create new one
   └─ Session ID: Stored in SQLite
   └─ User ID: "user_123" (hardcoded in main.py)
   └─ App Name: "ProductManager" (hardcoded)

2. Fetch current session state from database
   └─ State includes: vision_statement, roadmap, requirements, is_complete, questions

3. User enters text in terminal
   └─ Accumulate text into "unstructured_requirements" field
   └─ Important: Accumulate, DON'T replace previous requirements

4. Call Product Vision Agent
   └─ Pass: Full accumulated requirements (not just latest message)
   └─ Receive: JSON with {product_vision_statement, is_complete, clarifying_questions}

5. Stream and process agent response
   └─ Parse JSON using Pydantic OutputSchema
   └─ Display parsed results to user
   └─ Show clarifying questions if vision is incomplete

6. Update session state in-memory
   └─ Set: product_vision_statement, is_complete, clarifying_questions

7. Persist updated state to SQLite
   └─ DatabaseSessionService.update_session_state()

8. Check is_complete flag
   └─ If False: Continue loop with Vision Agent
   └─ If True: Switch Runner to Roadmap Agent
   └─ Next iteration calls Roadmap Agent with same flow

9. Repeat from step 2
```

**Key Functions** (all in `/Users/alexandrearduinitavares/projects/project_tcc/main.py`):

| Function | Lines | Purpose |
|----------|-------|---------|
| `load_or_create_session()` | 38-61 | Get session ID from DB or create new one |
| `get_session_state()` | 64-78 | Fetch current state from database |
| `append_user_text_to_requirements()` | 81-95 | Accumulate user input into unstructured_requirements |
| `save_state()` | 98-111 | Persist state back to SQLite |
| `run_vision_agent()` | 114-132 | Call agent with accumulated requirements |
| `main_async()` | 135-272 | Main event loop (lines 159-272 are the core loop) |

**State Schema**:
```python
{
    "product_vision_statement": str,      # Current vision from agent
    "product_roadmap": str,               # Roadmap (populated when switching to roadmap agent)
    "unstructured_requirements": str,     # All user input accumulated across turns
    "is_complete": bool,                  # From latest agent call
    "clarifying_questions": list[str]     # From latest agent call
}
```

**Important Implementation Detail - Context Accumulation**:

The system intentionally preserves ALL user input across multiple turns:

```python
# In append_user_text_to_requirements():
current_req = str(state.get("unstructured_requirements", "")).strip()
if current_req:
    updated = current_req + " " + user_text_clean  # APPEND, don't replace
else:
    updated = user_text_clean
state["unstructured_requirements"] = updated
```

This is CRITICAL because:
1. The agent needs full context to make good decisions
2. Clarifying questions might reference earlier requirements
3. Maintains coherence across multi-turn conversations

---

### Pattern 2: Automated Orchestration Workflow (`product_workflow.py`)

**Purpose**: Non-interactive, single-pass execution where the complete requirements are provided upfront and the system orchestrates the full workflow automatically.

**Entry Point**: `python product_workflow.py`

**Key Characteristics**:
- No user interaction during execution
- Requires complete requirements upfront
- Uses `LoopAgent` as the orchestrator (not `Runner`)
- Orchestration logic defined via natural language instructions
- Returns complete roadmap if vision is complete

**Control Flow**:

```
1. Define orchestrator instructions (ORCHESTRATOR_INSTRUCTIONS)
   └─ Tell LoopAgent how to sequence the sub-agents

2. Create LoopAgent with sub-agents
   └─ root_agent = LoopAgent(
        sub_agents=[product_vision_agent, product_roadmap_agent],
        instruction=ORCHESTRATOR_INSTRUCTIONS
      )

3. Prepare input
   └─ InputSchema: {unstructured_requirements: str}

4. Call root_agent.run(workflow_input)
   └─ LoopAgent orchestrates:
     ├─ Step 1: Call product_vision_agent(requirements)
     ├─ Step 2: Check is_complete flag
     ├─ Step 3a (if incomplete): Return questions to user
     └─ Step 3b (if complete): Call product_roadmap_agent(vision + requirements)

5. Return OutputSchema
   └─ {final_roadmap: RoadmapOutputSchema}
```

**Key Differences from Interactive Workflow**:

| Aspect | Interactive (main.py) | Automated (product_workflow.py) |
|--------|----------------------|----------------------------------|
| **Control** | User-driven per turn | Orchestrator-driven sequencing |
| **Interaction** | Multi-turn chat loop | Single-pass execution |
| **Persistence** | Session stored across restarts | No persistence (demo only) |
| **Agent Selection** | Manual Runner switching | LoopAgent decides via instructions |
| **Error Handling** | Parse errors show to user, continue | Parse errors bubble up |
| **Use Case** | Daily workflow, refinement | Demo, testing, validation |

**Orchestrator Instructions** (product_workflow.py, lines 70-105):

The natural language instructions tell LoopAgent:
1. What the workflow goal is
2. Which sub-agents to call and in what order
3. How to handle conditional logic (is_complete flag)
4. What inputs to pass to each sub-agent

This is a declarative approach: you describe WHAT you want (not HOW to code it), and LoopAgent figures out the sequencing.

---

## Agent Details

### Product Vision Agent

**Location**: `/Users/alexandrearduinitavares/projects/project_tcc/product_vision_agent/agent.py`

**Responsibility**: Generate a product vision statement from unstructured requirements. If information is missing, return a draft vision with placeholders and ask clarifying questions.

**Input Schema** (`utils/schemes.py`):
```python
class InputSchema(BaseModel):
    unstructured_requirements: Annotated[
        str,
        Field(description="Raw, unstructured text containing product requirements and ideas.")
    ]
```

**Output Schema** (`utils/schemes.py`):
```python
class OutputSchema(BaseModel):
    product_vision_statement: str  # The vision (final or draft)
    is_complete: bool              # True if complete, False if needs more info
    clarifying_questions: list[str] # Questions to ask user (empty if complete)
```

**Behavior**:
1. Receives unstructured requirements text
2. Analyzes to extract vision elements (target users, problem, solution, differentiator)
3. If any element is missing:
   - Creates draft vision with placeholders like "[Missing Target User]"
   - Sets is_complete = False
   - Generates specific questions: "Who is the primary target user?"
4. If all elements present:
   - Creates complete vision statement
   - Sets is_complete = True
   - Returns empty questions list

**Instructions**: Loaded from `product_vision_agent/instructions.txt`

**Configuration** (agent.py, lines 33-46):
```python
root_agent: Agent = Agent(
    name="product_vision_agent",
    description="An agent that creates a product vision from unstructured requirements...",
    model=model,                          # LiteLlm configured with gpt-5-nano
    input_schema=InputSchema,             # From utils/schemes.py
    output_schema=OutputSchema,           # From utils/schemes.py
    instruction=instructions,             # From instructions.txt
    output_key="product_vision_assessment",
    disallow_transfer_to_parent=True,     # Prevent transfer to parent agent
    disallow_transfer_to_peers=True,      # Prevent transfer to peer agents
)
```

**Technology**:
- Model: LiteLlm (abstraction)
- Provider: OpenRouter API
- Specific model: gpt-5-nano
- API Key: OPEN_ROUTER_API_KEY from .env

---

### Product Roadmap Agent

**Location**: `/Users/alexandrearduinitavares/projects/project_tcc/product_roadmap_agent/agent.py`

**Responsibility**: Create a high-level agile product roadmap from a completed product vision statement.

**Input Schema** (defined in agent.py, lines 50-67):
```python
class InputSchema(BaseModel):
    product_vision_statement: str  # The completed vision statement
    user_input: str                # Original unstructured requirements for context
```

**Output Schema** (defined in agent.py, lines 110-145):
```python
class OutputSchema(BaseModel):
    roadmap_draft: List[RoadmapTheme]   # Themes with features, justification, time frame
    is_complete: bool                    # True if roadmap is final
    clarifying_questions: list[str]      # Questions if incomplete
```

**Data Structure - RoadmapTheme** (agent.py, lines 70-107):
```python
class RoadmapTheme(BaseModel):
    theme_name: str                # e.g., "User Authentication"
    key_features: List[str]        # Features under theme
    justification: Optional[str]   # Why prioritized (e.g., "Core value prop")
    time_frame: Optional[str]      # "Now", "Next", or "Later"
```

**Behavior**:
1. Receives completed product vision and original requirements
2. Identifies major themes/epics from vision
3. Groups features by theme
4. Assigns time frames (Now/Next/Later prioritization)
5. Can ask for clarification if roadmap needs more definition

**Instructions**: Loaded from `product_roadmap_agent/instructions.txt`

**Configuration** (agent.py, lines 149-162):
```python
product_roadmap_agent: Agent = Agent(
    name="product_roadmap_agent",
    description="An agent that guides a user to create a high-level agile product roadmap...",
    model=model,                    # Same LiteLlm model as vision agent
    input_schema=InputSchema,
    output_schema=OutputSchema,
    output_key="product_roadmap",
    instruction=ROADMAP_INSTRUCTIONS,
    disallow_transfer_to_parent=True,
    disallow_transfer_to_peers=True,
)
```

---

## Response Processing Pipeline

The system uses a three-stage pipeline to handle agent responses:

### Stage 1: Event Streaming (`utils/agent_io.py`)

**Function**: `call_agent_async()` (lines 80-134)

**Purpose**: Send user input to agent and stream back events

**Process**:
1. Create Content object with user text
2. Call `runner.run_async()` to start agent execution
3. Iterate over streamed events asynchronously
4. For each event, call `process_agent_event()` to handle it
5. Collect final response text when `event.is_final_response()` is True

**Event Types Handled**:
- Executable code (agent-generated Python)
- Code execution results (output from executed code)
- Tool responses (from function calls)
- Text snippets (intermediate thinking)
- Final response (complete structured output)

### Stage 2: JSON Parsing & Validation (`utils/response_parser.py`)

**Function**: `parse_agent_output()` (lines 19-49)

**Purpose**: Parse and validate agent's JSON response using Pydantic

**Process**:
```python
def parse_agent_output(final_response_text: Optional[str]):
    # 1. Check if response exists
    if not final_response_text:
        return None, "No final structured response from agent."

    # 2. Parse JSON and validate against OutputSchema
    try:
        structured = OutputSchema.model_validate_json(final_response_text)
    except ValidationError as e:
        return None, f"Agent response didn't match OutputSchema: {str(e)}"
    except json.JSONDecodeError:
        return None, f"Agent final response was not valid JSON: {final_response_text}"

    # 3. Return validated object or error
    return structured, None
```

**Error Handling**:
- Returns tuple: `(structured_instance, error_message)`
- If successful: `(OutputSchema(...), None)`
- If failed: `(None, error_string)`
- Calling code checks `if err:` to display error without crashing

### Stage 3: State Persistence (`utils/persistence.py`)

**Function**: `persist_product_vision_state()` (lines 8-41)

**Purpose**: Merge validated agent output into session state and save to DB

**Process**:
```python
# 1. Fetch current session
session = await session_service.get_session(app_name, user_id, session_id)

# 2. Merge agent output into session.state
session.state["product_vision_statement"] = structured.product_vision_statement
session.state["product_vision_is_complete"] = structured.is_complete
session.state["product_vision_questions"] = structured.clarifying_questions

# 3. Persist to database
await session_service.save_session(session)
```

**Database Technology**:
- SQLite (lightweight, file-based, no server needed)
- Accessed via Google ADK's DatabaseSessionService
- File path: `./my_agent_data.db` (created automatically)
- Stores: session IDs, user IDs, app names, complete state dictionaries as JSON

---

## Technology Stack Rationale

### Google ADK (Agent Development Kit)

**Why**: Official Google framework for agent development
- Provides Agent and LoopAgent classes
- Handles agent lifecycle and communication
- DatabaseSessionService for session persistence
- Event streaming for async communication

**Current Usage**:
```python
from google.adk.agents import Agent, LoopAgent
from google.adk.runners import Runner
from google.adk.sessions import DatabaseSessionService
from google.adk.models.lite_llm import LiteLlm
```

### LiteLLM

**Why**: Abstracts LLM provider (not tied to specific model/vendor)
- Switch models by changing one string
- Currently: openrouter/openai/gpt-5-nano
- Can change to openrouter/anthropic/claude-3-haiku, etc.

**Usage**:
```python
model = LiteLlm(
    model="openrouter/openai/gpt-5-nano",
    api_key=os.getenv("OPEN_ROUTER_API_KEY")
)
```

### OpenRouter API

**Why**: Provides hosted access to multiple models
- Pay-per-token (no subscription)
- Cost-effective for prototyping
- Easy to switch models
- Good for evaluation study (reproducible)

**Configuration**: OPEN_ROUTER_API_KEY in .env

### SQLite

**Why**: Lightweight, serverless persistence
- No database server needed
- File-based (single ./my_agent_data.db file)
- Perfect for prototyping and small deployments
- Sufficient for TCC evaluation (single/few users)
- Easy to backup and share

**File**: `my_agent_data.db` (created automatically)

### Pydantic

**Why**: Schema validation with excellent error messages
- InputSchema validates incoming data
- OutputSchema validates agent responses
- Rich error messages for debugging
- Type hints for IDE support

**Usage**:
```python
structured = OutputSchema.model_validate_json(json_string)
# Raises ValidationError with detailed field-level messages if invalid
```

---

## Key Architectural Patterns

### Pattern 1: Schema-Driven Design

**Principle**: All agent I/O is structured, not free-text.

**Implementation**:
```python
# Agent receives InputSchema
agent.run(InputSchema(unstructured_requirements="..."))

# Agent returns JSON matching OutputSchema
{
    "product_vision_statement": "...",
    "is_complete": true,
    "clarifying_questions": []
}

# Parsed into Python object
structured = OutputSchema.model_validate_json(json_response)
```

**Benefit**:
- Type safety
- Clear contracts between agents
- Easy to validate and route responses
- Extensible to new agent types

### Pattern 2: Multi-Turn Context Accumulation

**Principle**: Preserve ALL user input across multiple turns; don't replace.

**Implementation**:
```python
# Turn 1
unstructured_requirements = "Build a task manager"

# Turn 2
user_input = "For mobile users"
unstructured_requirements += " " + user_input  # APPEND

# Turn 3
user_input = "With AI prioritization"
unstructured_requirements += " " + user_input  # APPEND

# Agent always receives full accumulated string
```

**Benefit**:
- Agent maintains context across clarifying question exchanges
- Prevents information loss
- Enables multi-turn refinement workflows

### Pattern 3: Runner Switching

**Principle**: Switch between agents dynamically based on completion flags.

**Implementation** (main.py, lines 265-271):
```python
if structured.is_complete and runner.agent is not product_roadmap_agent:
    print("Switching runner to product_roadmap_agent...")
    runner = Runner(
        agent=product_roadmap_agent,
        app_name=APP_NAME,
        session_service=session_service,
    )
```

**Benefit**:
- Enables sequential agent workflows
- No explicit state machine needed (yet)
- Easy to extend with new agents (just add more switches)

### Pattern 4: Graceful Error Handling

**Principle**: Parse failures don't crash; display error, continue loop.

**Implementation** (main.py, lines 203-215):
```python
structured, err = parse_agent_output(final_response_text)

if err:
    print(f"Warning: {err}")
    # Still save state even if parsing failed
    await save_state(...)
    continue  # Don't crash, let user retry
```

**Benefit**:
- Resilient to model variability
- User can restate requirements if agent output is malformed
- State is preserved despite errors

---

## File Organization

```
/Users/alexandrearduinitavares/projects/project_tcc/
├── main.py                              # Interactive session workflow
├── product_workflow.py                  # Automated orchestration workflow
│
├── product_vision_agent/
│   ├── agent.py                         # Vision agent definition
│   └── instructions.txt                 # Agent instructions/prompt
│
├── product_roadmap_agent/
│   ├── agent.py                         # Roadmap agent definition
│   └── instructions.txt                 # Agent instructions/prompt
│
├── utils/
│   ├── __init__.py
│   ├── agent_io.py                      # Event streaming & I/O handling
│   ├── response_parser.py               # JSON parsing & validation
│   ├── persistence.py                   # State persistence helpers
│   ├── state.py                         # State display utilities
│   ├── colors.py                        # Terminal color constants
│   ├── schemes.py                       # Shared Pydantic schemas
│   └── helper.py                        # General utilities
│
├── my_agent_data.db                     # SQLite database (created at runtime)
├── .env                                 # Environment variables (not in git)
├── pyproject.toml                       # Python package configuration
├── ARCHITECTURE.md                      # Architecture documentation (updated)
└── CLAUDE.md                            # Developer instructions
```

---

## How to Extend This Architecture

### Adding a New Agent (e.g., Product Backlog Agent)

1. Create directory: `/Users/alexandrearduinitavares/projects/project_tcc/product_backlog_agent/`

2. Create `agent.py` with:
   ```python
   from google.adk.agents import Agent
   from pydantic import BaseModel, Field

   class InputSchema(BaseModel):
       product_vision: str
       product_roadmap: str

   class OutputSchema(BaseModel):
       user_stories: List[str]
       is_complete: bool

   product_backlog_agent = Agent(
       name="product_backlog_agent",
       model=model,
       input_schema=InputSchema,
       output_schema=OutputSchema,
       instruction=instructions,
       disallow_transfer_to_parent=True,
       disallow_transfer_to_peers=True,
   )
   ```

3. Create `instructions.txt` with detailed agent behavior prompt

4. Import in main.py and add runner switch:
   ```python
   from product_backlog_agent.agent import product_backlog_agent

   # In the main loop:
   if structured.is_complete and runner.agent is not product_backlog_agent:
       runner = Runner(agent=product_backlog_agent, ...)
   ```

5. Add to LoopAgent in product_workflow.py:
   ```python
   sub_agents=[
       product_vision_agent,
       product_roadmap_agent,
       product_backlog_agent,  # Add here
   ]
   ```

### Adding Agent Communication (Future)

Current: Agents work in series (Vision → Roadmap)
Future: Agents might need to call each other (e.g., Backlog queries Vision)

**Approach**:
1. Add agent registry: `agents = {name: Agent instance}`
2. Give agents access to registry
3. Agents call other agents via API endpoints
4. Build simple event bus for async communication

---

## Next Steps to Target Architecture

### Phase 1: Product Owner Domain Completion
- [ ] Enhance Product Vision Agent (more validation)
- [ ] Enhance Product Roadmap Agent (add feature details)
- [ ] Create Product Backlog Agent (generate user stories with INVEST)
- [ ] Create Prioritization Agent (rank backlog items)
- [ ] Add persistence layer for Product Backlog (not just session state)

### Phase 2: Developer Support Domain
- [ ] Task Decomposer Agent (break stories into tasks)
- [ ] Progress Monitor Agent (track sprint progress)
- [ ] Quality Validator Agent (enforce Definition of Done)

### Phase 3: Scrum Master Domain
- [ ] Sprint Facilitator Agent (orchestrate Scrum events)
- [ ] Process Coach Agent (monitor adherence)
- [ ] Impediment Detective Agent (identify blockers)
- [ ] State Machine (for Scrum event sequencing)

### Phase 4: Evaluation Framework
- [ ] Metrics Collector Agent
- [ ] NASA-TLX Integration
- [ ] INVEST Validator
- [ ] Cycle Time Tracker

### Phase 5: Cross-Cutting
- [ ] Multi-agent communication protocol
- [ ] Shared knowledge base
- [ ] Session/Sprint artifact persistence
- [ ] Human approval workflows

---

## Troubleshooting & Common Issues

### Issue: "No final structured response from agent"
**Cause**: Agent streaming completed but no structured JSON in response
**Fix**: Check agent instructions - ensure it returns JSON, not natural language

### Issue: "Agent response didn't match OutputSchema"
**Cause**: Agent returned JSON with wrong field names or types
**Fix**: Check instructions and examples in instructions.txt; verify Pydantic schema matches expected output

### Issue: Session not persisting across restarts
**Cause**: DatabaseSessionService not finding my_agent_data.db
**Fix**: Ensure SQLite database file is writable; check DB_URL path in main.py

### Issue: Agent stuck in infinite loop asking same questions
**Cause**: User's input not being accumulated properly
**Fix**: Check append_user_text_to_requirements() - ensure state is updating between turns

### Issue: LiteLLM API errors
**Cause**: Missing or invalid OPEN_ROUTER_API_KEY
**Fix**: Create .env file with valid key; verify key has balance in OpenRouter account

---

## Summary

The current implementation is a **focused, educational prototype** that demonstrates:

1. **Two workflow patterns**: interactive (main.py) and automated (product_workflow.py)
2. **Schema-driven design**: All I/O is structured, validated with Pydantic
3. **Session persistence**: Multi-turn conversations saved to SQLite
4. **Sequential agent orchestration**: Vision → Roadmap via Runner switching or LoopAgent
5. **Robust error handling**: Parse failures don't crash, state persists despite errors

This prototype provides a solid foundation to expand into the full 8+ agent system described in the TCC proposal. The patterns established here (schema-driven I/O, session management, error handling) will scale to support:
- Product Owner domain (backlog, prioritization)
- Scrum Master domain (event facilitation, impediments)
- Developer Support domain (task decomposition, progress tracking)
- Evaluation framework (NASA-TLX, INVEST, metrics)

The architecture prioritizes clarity and extensibility, making it straightforward to add new agents and workflows as the project evolves.
