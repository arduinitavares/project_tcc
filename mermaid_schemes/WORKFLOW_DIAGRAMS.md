# Workflow Diagrams - Current Implementation

## Overview

This document provides visual representations of the two workflow patterns currently implemented in the system.

---

## 1. Interactive Session-Based Workflow (main.py)

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ USER STARTS SESSION                                                 │
│ python main.py                                                      │
└─────────────┬───────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ LOAD OR CREATE SESSION                                              │
│ - Check if session exists in SQLite                                 │
│ - If yes: Load session ID and state                                 │
│ - If no: Create new session (user_id="user_123")                    │
│ - Session persisted to my_agent_data.db                             │
└─────────────┬───────────────────────────────────────────────────────┘
              │
              ▼
          ┌─────────────────────────────────────────────┐
          │  START MAIN LOOP (while True)               │
          │  Per each user turn:                         │
          │                                              │
          │ 1. Prompt: "You: "                           │
          │ 2. Read user input                           │
          │ 3. Check if "exit" or "quit"                │
          │    └─ If yes: break and end                 │
          │    └─ If no: continue                        │
          │                                              │
          │ 4. Fetch current state from DB              │
          │ 5. Accumulate user input                    │
          │    (append to unstructured_requirements)    │
          │                                              │
          │ 6. Call active agent with accumulated       │
          │    requirements                              │
          │                                              │
          │ 7. Parse agent response (JSON)              │
          │    ├─ If parse error:                        │
          │    │  └─ Show error, save state, continue   │
          │    └─ If success: proceed                   │
          │                                              │
          │ 8. Display results to user                  │
          │ 9. Update in-memory state                   │
          │ 10. Persist state to SQLite                 │
          │ 11. Check is_complete flag                  │
          │     ├─ If False: Continue with Vision Agent │
          │     └─ If True: Switch to Roadmap Agent     │
          │                                              │
          │ 12. Repeat from step 1                       │
          │                                              │
          └────────┬──────────────────────────────────────┘
                   │
                   ▼
              EXIT OR QUIT
```

### Detailed Sequence (Single Turn)

```
TURN N
│
├─ [1] Fetch Session State
│      └─ DatabaseSessionService.get_session()
│         └─ Returns: {vision_statement, roadmap, requirements, is_complete, questions}
│
├─ [2] Read User Input
│      └─ input("You: ")
│         └─ Returns: string
│
├─ [3] Accumulate Requirements
│      └─ append_user_text_to_requirements(state, user_input)
│         └─ state["unstructured_requirements"] += " " + user_input
│
├─ [4] Call Active Agent
│      ├─ If is_complete == False: Call Vision Agent
│      │  └─ run_vision_agent(accumulated_requirements)
│      └─ If is_complete == True: Call Roadmap Agent
│         └─ run_roadmap_agent(vision_statement, requirements)
│
├─ [5] Stream Events
│      ├─ Runner.run_async()
│      ├─ Iterate over events
│      └─ Display executable code, results, text
│
├─ [6] Parse Response
│      ├─ Extract final response JSON
│      ├─ parse_agent_output(json_text)
│      └─ Returns: (OutputSchema instance, error_message)
│
├─ [7] Handle Parse Error (if any)
│      ├─ If error: Print warning
│      ├─ Save accumulated requirements anyway
│      └─ Loop back to [1] for next turn
│
├─ [8] Display Results
│      ├─ Print vision statement
│      ├─ Print is_complete flag
│      └─ Print clarifying questions (if incomplete)
│
├─ [9] Update State
│      └─ state["product_vision_statement"] = structured.vision
│         state["is_complete"] = structured.is_complete
│         state["clarifying_questions"] = structured.questions
│
├─ [10] Persist State
│       └─ save_state(session_id, state)
│          └─ DatabaseSessionService.update_session_state()
│          └─ Writes to my_agent_data.db
│
├─ [11] Check Completion & Switch
│       └─ if structured.is_complete and agent is Vision:
│          └─ runner = Runner(product_roadmap_agent, ...)
│             (Next turn will use Roadmap Agent)
│
└─ [12] Next Turn
         └─ Go back to [1]
```

### Agent Call Sequence (First Few Turns)

```
TURN 1: User says "Need a task manager"
        ▼
        Vision Agent receives: "Need a task manager"
        ▼
        Returns: {
            vision: "[Missing Target Users] task manager for [Missing Use Case]",
            is_complete: False,
            questions: ["Who are your primary users?", "What's the main use case?"]
        }
        ▼
        Print: "We still need answers to:"
               "1. Who are your primary users?"
               "2. What's the main use case?"

TURN 2: User says "Professional task management for busy people"
        ▼
        State accumulated: "Need a task manager Professional task management for busy people"
        ▼
        Vision Agent receives: FULL accumulated text
        ▼
        Returns: {
            vision: "Task manager for busy professionals to centralize task management",
            is_complete: False,
            questions: ["What platforms should it support?"]
        }

TURN 3: User says "Mobile and web"
        ▼
        State accumulated: "Need a task manager Professional... Mobile and web"
        ▼
        Vision Agent receives: FULL accumulated text
        ▼
        Returns: {
            vision: "Mobile and web task manager for busy professionals...",
            is_complete: True,
            questions: []
        }
        ▼
        SWITCH to Roadmap Agent ✓

TURN 4: User says "Now let's plan the roadmap"
        ▼
        Roadmap Agent receives: (vision_statement, accumulated_requirements)
        ▼
        Returns: {
            roadmap_draft: [
                {theme: "User Auth", features: [...], time_frame: "Now"},
                {theme: "Task Sync", features: [...], time_frame: "Now"},
                {theme: "AI Prioritization", features: [...], time_frame: "Next"}
            ],
            is_complete: True,
            questions: []
        }
```

---

## 2. Automated Orchestration Workflow (product_workflow.py)

### High-Level Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│ DEFINE WORKFLOW                                                     │
│ 1. Create LoopAgent as orchestrator                                 │
│ 2. Specify sub-agents: [vision_agent, roadmap_agent]                │
│ 3. Define orchestration instructions (natural language)             │
└─────────────┬───────────────────────────────────────────────────────┘
              │
              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ EXECUTE WORKFLOW                                                    │
│ root_agent = LoopAgent(...)                                         │
│ workflow_input = InputSchema(unstructured_requirements="...")       │
│ output = root_agent.run(workflow_input)                             │
└─────────────┬───────────────────────────────────────────────────────┘
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │ ORCHESTRATOR LOGIC (LoopAgent executes)     │
    │                                              │
    │ 1. Call Vision Agent                        │
    │    └─ Pass: unstructured_requirements       │
    │    └─ Receive: vision, is_complete, questions │
    │                                              │
    │ 2. Check is_complete flag                   │
    │    ├─ If False:                              │
    │    │  └─ Return to user with questions      │
    │    │  └─ STOP workflow                       │
    │    └─ If True:                               │
    │       └─ Continue to step 3                 │
    │                                              │
    │ 3. Call Roadmap Agent                       │
    │    └─ Pass: vision + requirements           │
    │    └─ Receive: roadmap_draft, is_complete   │
    │                                              │
    │ 4. Wrap Roadmap output                      │
    │    └─ final_roadmap = roadmap_output        │
    │    └─ Return OutputSchema                   │
    │                                              │
    └────────┬─────────────────────────────────────┘
             │
             ▼
    ┌─────────────────────────────────────────────┐
    │ RETURN RESULTS                               │
    │                                              │
    │ final_output = OutputSchema(                │
    │    final_roadmap={                           │
    │        roadmap_draft: [...],                 │
    │        is_complete: bool,                    │
    │        clarifying_questions: [...]           │
    │    }                                          │
    │ )                                             │
    │                                              │
    └─────────────────────────────────────────────┘
```

### Orchestrator Instructions (Natural Language)

The LoopAgent executes based on these instructions:

```
You are the master Product Workflow Orchestrator.

1. START: Receive unstructured_requirements from user.

2. STEP 1 - Vision Agent:
   * Call product_vision_agent with unstructured_requirements
   * Receive: product_vision_statement, is_complete, clarifying_questions

3. STEP 2 - Handle Vision Output:
   * If is_complete is False:
     - Vision incomplete, ask user clarifying_questions
     - STOP workflow
   * If is_complete is True:
     - Vision is ready, proceed to next step

4. STEP 3 - Roadmap Agent:
   * Call product_roadmap_agent
   * Pass: product_vision_statement, unstructured_requirements
   * Receive: roadmap_draft, is_complete, clarifying_questions

5. STEP 4 - Final Output:
   * Wrap roadmap output in final_roadmap field
   * Return OutputSchema with final_roadmap
```

### Execution Example

```
INPUT:
├─ unstructured_requirements:
   "We need a mobile-first unified inbox for busy professionals.
    Pulls tasks from email, Slack, calendars.
    AI prioritizes what's important."

ORCHESTRATOR LOGIC:

[Step 1] Call Vision Agent
    ├─ Input: "We need a mobile-first unified inbox..."
    └─ Output: {
        vision: "Mobile-first unified inbox aggregating tasks from email, Slack, calendars...",
        is_complete: True,
        questions: []
       }

[Step 2] Check is_complete
    └─ is_complete == True ✓
    └─ Continue to step 3

[Step 3] Call Roadmap Agent
    ├─ Input: {
    │   vision: "Mobile-first unified...",
    │   user_input: "We need a mobile-first..."
    │ }
    └─ Output: {
        roadmap_draft: [
            {
                theme: "Core Aggregation",
                features: ["Email sync", "Slack sync", "Calendar sync"],
                time_frame: "Now"
            },
            {
                theme: "AI Prioritization",
                features: ["ML priority ranking", "Smart filtering"],
                time_frame: "Next"
            },
            {
                theme: "Mobile Optimization",
                features: ["Offline support", "Push notifications"],
                time_frame: "Later"
            }
        ],
        is_complete: True,
        questions: []
       }

[Step 4] Return Final Output
    └─ OutputSchema(
        final_roadmap={
            roadmap_draft: [3 themes above],
            is_complete: True,
            clarifying_questions: []
        }
       )

RESULT: Workflow completes with full roadmap ✓
```

---

## 3. Comparison Matrix

| Aspect | Interactive (main.py) | Automated (product_workflow.py) |
|--------|----------------------|----------------------------------|
| **Entry Point** | `python main.py` | `python product_workflow.py` |
| **User Control** | User drives turns, can ask questions, refine | User provides requirements upfront, no interaction |
| **Data Persistence** | Session stored in SQLite across runs | No persistence (demo only) |
| **Session Context** | Multi-turn session with history | Single-pass execution |
| **Agent Selection** | Manual runner switching | LoopAgent orchestrates automatically |
| **Error Recovery** | Parse errors don't crash, user retries | Errors bubble up |
| **Database** | Uses SQLite via DatabaseSessionService | No database access |
| **Best For** | Daily workflows, iterative refinement | Testing, demonstrations, scripting |
| **Scalability** | Single user, single session | Can be extended to batch processing |

---

## 4. State Transitions During Interactive Workflow

```
SESSION STATE EVOLUTION (Interactive Workflow)

Initial State:
{
    "product_vision_statement": "",
    "product_roadmap": "",
    "unstructured_requirements": "",
    "is_complete": False,
    "clarifying_questions": []
}

After Turn 1 - User: "Need a task manager"
{
    "product_vision_statement": "[Missing...] task manager",
    "product_roadmap": "",
    "unstructured_requirements": "Need a task manager",
    "is_complete": False,
    "clarifying_questions": ["Who are the users?", "What's the use case?"]
}

After Turn 2 - User: "For busy professionals"
{
    "product_vision_statement": "Task manager for busy professionals",
    "product_roadmap": "",
    "unstructured_requirements": "Need a task manager For busy professionals",
    "is_complete": False,
    "clarifying_questions": ["What platforms should it support?"]
}

After Turn 3 - User: "Mobile and web"
{
    "product_vision_statement": "Mobile and web task manager for busy professionals",
    "product_roadmap": "",
    "unstructured_requirements": "Need a task manager For busy professionals Mobile and web",
    "is_complete": True,                    ◄─── IS_COMPLETE = TRUE
    "clarifying_questions": []              ◄─── RUNNER SWITCHES TO ROADMAP AGENT
}

After Turn 4 - User: "Plan the roadmap"
{
    "product_vision_statement": "Mobile and web task manager for busy professionals",
    "product_roadmap": "[{theme: User Auth...}, ...]",
    "unstructured_requirements": "Need a task manager For busy professionals Mobile and web Plan the roadmap",
    "is_complete": True,
    "clarifying_questions": []
}
```

---

## 5. Data Flow Diagram

```
INPUT FLOW (What Gets Passed Around)
═════════════════════════════════════

User Input (Text String)
    │
    ▼
Accumulated Requirements (Full History)
    │
    ├─────────────────────────────┬──────────────────────────┐
    │                              │                          │
    ▼                              ▼                          ▼
Vision Agent Input    Vision Agent Output    Roadmap Agent Input
    │                      │                      │
    │                      ▼                      │
    │                 JSON Response               │
    │                      │                      │
    │                      ▼                      │
    │              Pydantic Validation             │
    │                      │                      │
    └──────────────────────┼──────────────────────┘
                          │
                          ▼
                    Session State
                    (In-Memory Dict)
                          │
                          ▼
                  SQLite Database
                (my_agent_data.db)
```

---

## 6. Error Handling Flows

### Flow 1: Parse Error (Agent Returns Invalid JSON)

```
Agent Response Received (Not Valid JSON)
    │
    ▼
parse_agent_output(response_text)
    │
    ├─ json.JSONDecodeError
    │
    ▼
return (None, "Agent response was not valid JSON: ...")
    │
    ▼
if err:
    print(f"Warning: {err}")
    await save_state(...)  ◄─ Still save accumulated requirements!
    continue               ◄─ Don't crash, retry
```

### Flow 2: Validation Error (JSON Doesn't Match Schema)

```
Agent Response Received (Valid JSON, Wrong Schema)
    │
    ▼
OutputSchema.model_validate_json(response_text)
    │
    ├─ ValidationError: field_x is required
    │
    ▼
return (None, "Agent response didn't match OutputSchema: field_x required")
    │
    ▼
if err:
    print(f"Warning: {err}")
    await save_state(...)  ◄─ Still save accumulated requirements!
    continue               ◄─ User can try again
```

### Flow 3: Database Error (Can't Save State)

```
await save_state(...)
    │
    ├─ DatabaseError: Cannot connect
    │
    ▼
Error is printed to console
But execution doesn't stop - user can continue
(State lost for this turn, but new input won't be lost)
```

---

## 7. Technology Stack in Workflow Context

```
User Input (Terminal)
    │
    ▼
[asyncio] - Async I/O handling
    │
    ├─────────────────────────────┐
    │                             │
    ▼                             ▼
[Google ADK]             [DatabaseSessionService]
Runner class            (Session persistence)
    │                             │
    ├─────────────────────────────┼────────────────┐
    │                             │                │
    ▼                             ▼                ▼
[Agent]              [SQLite]           [Pydantic]
Execution            Database           Schema
    │                             │     Validation
    ├─────────────────────────────┼────────────────┐
    │                             │                │
    ▼                             ▼                ▼
[LiteLLM]           [SQLAlchemy]        [JSON Parser]
Model Abstraction   ORM (if used)       Response Parse
    │
    ▼
[OpenRouter API]
    │
    ▼
[gpt-5-nano]
(or other models)
```

---

## Summary

Both workflows demonstrate the same core concepts:

1. **Schema-Driven I/O**: InputSchema → Agent → OutputSchema
2. **Pydantic Validation**: Every response validated before use
3. **State Persistence**: Session state accumulates across operations
4. **Error Resilience**: Parse errors don't crash the system
5. **Multi-Step Orchestration**: Complex workflows via simple sequencing

The interactive workflow (main.py) emphasizes user control and context preservation, while the automated workflow (product_workflow.py) emphasizes orchestration simplicity via instructions.
