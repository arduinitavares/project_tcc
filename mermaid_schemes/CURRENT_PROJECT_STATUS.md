# Current Project Status - Mermaid Diagrams

## System Architecture Overview

```mermaid
graph TB
    subgraph "User Interface Layer"
        CLI[Interactive CLI<br/>main.py]
        AUTO[Automated Workflow<br/>product_workflow.py]
    end

    subgraph "Agent Layer"
        PVA[Product Vision Agent<br/>product_vision_agent/]
        PRA[Product Roadmap Agent<br/>product_roadmap_agent/]
        LOOP[LoopAgent Orchestrator<br/>Coordinates agent workflow]
    end

    subgraph "State Management Layer"
        DB[(SQLite Database<br/>my_agent_data.db)]
        SESSION[DatabaseSessionService<br/>Session Management]
        STATE{Session State<br/>- product_vision_statement<br/>- product_roadmap<br/>- unstructured_requirements<br/>- is_complete<br/>- clarifying_questions}
    end

    subgraph "Utilities Layer"
        AGENTIO[agent_io.py<br/>Event Processing & I/O]
        PARSER[response_parser.py<br/>JSON → Pydantic]
        PERSIST[persistence.py<br/>State Persistence]
        SCHEMES[schemes.py<br/>Pydantic Schemas]
        HELPER[helper.py<br/>Instruction Loader]
        COLORS[colors.py<br/>Terminal Formatting]
    end

    subgraph "External Services"
        LLM[LiteLLM<br/>Model Abstraction]
        OPENROUTER[OpenRouter API<br/>gpt-5-nano]
    end

    CLI -->|User Input| SESSION
    CLI -->|Call Agent| PVA
    CLI -->|Switch When Complete| PRA
    AUTO -->|Orchestrate| LOOP
    LOOP -->|Manage| PVA
    LOOP -->|Manage| PRA

    PVA -->|Stream Events| AGENTIO
    PRA -->|Stream Events| AGENTIO
    AGENTIO -->|Parse Response| PARSER
    PARSER -->|Validate| SCHEMES

    CLI -->|Load/Save| STATE
    STATE <-->|Persist| SESSION
    SESSION <-->|Store| DB
    STATE -->|Optional| PERSIST

    PVA -->|Instructions| HELPER
    PRA -->|Instructions| HELPER
    AGENTIO -->|Format Output| COLORS

    PVA -->|LLM Calls| LLM
    PRA -->|LLM Calls| LLM
    LLM -->|API Request| OPENROUTER

    style PVA fill:#fff9c4
    style PRA fill:#fff9c4
    style LOOP fill:#e1bee7
    style DB fill:#c8e6c9
    style SESSION fill:#c8e6c9
    style STATE fill:#c8e6c9
    style LLM fill:#ffccbc
    style OPENROUTER fill:#ffccbc
```

## Interactive Workflow (main.py)

```mermaid
sequenceDiagram
    actor User
    participant CLI as main.py
    participant DB as DatabaseSessionService
    participant State as Session State
    participant Vision as Vision Agent
    participant Roadmap as Roadmap Agent
    participant Parser as response_parser
    participant LLM as LiteLLM/OpenRouter

    User->>CLI: Enter requirements text
    CLI->>DB: load_or_create_session()
    DB-->>CLI: session_id
    CLI->>DB: get_session_state()
    DB-->>State: Current state

    CLI->>State: append_user_text_to_requirements()
    Note over State: Accumulates ALL user inputs

    CLI->>Vision: run_vision_agent(accumulated_requirements)
    Vision->>LLM: Process with full context
    LLM-->>Vision: JSON response
    Vision-->>CLI: Final response text

    CLI->>Parser: parse_agent_output(response)
    Parser-->>CLI: (structured_output, None) or (None, error)

    alt Parse Success
        CLI->>State: Mirror output fields
        Note over State: - product_vision_statement<br/>- is_complete<br/>- clarifying_questions
        CLI->>DB: save_state()

        alt Vision Complete
            CLI->>CLI: Switch runner to Roadmap Agent
            CLI->>User: Display vision + "Moving to roadmap..."
        else Vision Incomplete
            CLI->>User: Display draft vision + questions
        end
    else Parse Error
        CLI->>User: Display error details
        CLI->>DB: save_state() anyway
        Note over CLI: Preserves accumulated requirements
    end

    User->>CLI: Continue conversation...
```

## Automated Workflow (product_workflow.py)

```mermaid
flowchart TD
    START([Start with Complete Requirements])

    ORCH[LoopAgent Orchestrator<br/>Analyzes workflow instructions]

    CALL_VISION[Call Vision Agent<br/>with unstructured_requirements]
    VISION_RESULT{Check is_complete}

    QUESTIONS[Return clarifying questions<br/>STOP workflow]

    CALL_ROADMAP[Call Roadmap Agent<br/>with vision + requirements]
    ROADMAP_RESULT[Receive roadmap output]

    FINAL[Return final_roadmap<br/>END workflow]

    START --> ORCH
    ORCH --> CALL_VISION
    CALL_VISION --> VISION_RESULT

    VISION_RESULT -->|False| QUESTIONS
    VISION_RESULT -->|True| CALL_ROADMAP

    CALL_ROADMAP --> ROADMAP_RESULT
    ROADMAP_RESULT --> FINAL

    style START fill:#e1f5ff
    style ORCH fill:#e1bee7
    style CALL_VISION fill:#fff9c4
    style CALL_ROADMAP fill:#fff9c4
    style FINAL fill:#c8e6c9
    style QUESTIONS fill:#ffccbc
```

## Agent Architecture Details

```mermaid
graph LR
    subgraph "Product Vision Agent"
        PVA_INST[instructions.txt<br/>Vision template instructions]
        PVA_AGENT[agent.py<br/>Agent configuration]
        PVA_TOOLS[tools.py<br/>Custom tools<br/>Currently unused]
        PVA_INPUT[InputSchema<br/>- unstructured_requirements]
        PVA_OUTPUT[OutputSchema<br/>- product_vision_statement<br/>- is_complete<br/>- clarifying_questions]

        PVA_AGENT -->|Loads| PVA_INST
        PVA_AGENT -->|Defines| PVA_TOOLS
        PVA_AGENT -->|Uses| PVA_INPUT
        PVA_AGENT -->|Returns| PVA_OUTPUT
    end

    subgraph "Product Roadmap Agent"
        PRA_INST[instructions.txt<br/>4-step roadmap process]
        PRA_AGENT[agent.py<br/>Agent + embedded schemas]
        PRA_INPUT[InputSchema<br/>- product_vision_statement<br/>- user_input]
        PRA_OUTPUT[OutputSchema<br/>- roadmap_draft<br/>- is_complete<br/>- clarifying_questions]
        PRA_THEMES[RoadmapTheme Model<br/>- theme_name<br/>- key_features<br/>- justification<br/>- time_frame]

        PRA_AGENT -->|Loads| PRA_INST
        PRA_AGENT -->|Uses| PRA_INPUT
        PRA_AGENT -->|Returns| PRA_OUTPUT
        PRA_OUTPUT -->|Contains list of| PRA_THEMES
    end

    PVA_OUTPUT -.->|Feeds into| PRA_INPUT

    style PVA_AGENT fill:#fff9c4
    style PRA_AGENT fill:#fff9c4
```

## State Management Flow

```mermaid
stateDiagram-v2
    [*] --> LoadSession: User starts app

    LoadSession --> CheckExisting: DatabaseSessionService
    CheckExisting --> LoadState: Session exists
    CheckExisting --> CreateNew: No session found
    CreateNew --> EmptyState: Initialize empty state
    LoadState --> SessionActive: Retrieve from DB
    EmptyState --> SessionActive

    SessionActive --> AccumulateInput: User provides text
    AccumulateInput --> CallAgent: unstructured_requirements += new_text
    CallAgent --> ParseResponse: Agent returns JSON

    ParseResponse --> MirrorToState: Success
    ParseResponse --> HandleError: Parse failure

    MirrorToState --> SaveState: Update state fields
    HandleError --> SaveState: Still save requirements

    SaveState --> CheckComplete: Persist to DB
    CheckComplete --> SwitchAgent: is_complete = True
    CheckComplete --> SessionActive: is_complete = False

    SwitchAgent --> SessionActive: Now using Roadmap Agent

    SessionActive --> [*]: User exits (quit/exit)

    note right of AccumulateInput
        Critical: ALL previous inputs
        are concatenated, not replaced
    end note

    note right of MirrorToState
        State fields updated:
        - product_vision_statement
        - is_complete
        - clarifying_questions
    end note
```

## Dependencies Graph

```mermaid
graph TD
    subgraph "Application Layer"
        MAIN[main.py]
        WORKFLOW[product_workflow.py]
    end

    subgraph "Google ADK Framework"
        AGENT[google.adk.agents<br/>Agent, LoopAgent]
        RUNNER[google.adk.runners<br/>Runner]
        SESSION_SVC[google.adk.sessions<br/>DatabaseSessionService]
        LITELLM[google.adk.models.lite_llm<br/>LiteLlm]
    end

    subgraph "Project Agents"
        PVAGENT[product_vision_agent]
        PRAGENT[product_roadmap_agent]
    end

    subgraph "Utilities"
        UTIL_IO[utils/agent_io.py]
        UTIL_PARSER[utils/response_parser.py]
        UTIL_SCHEMES[utils/schemes.py]
        UTIL_PERSIST[utils/persistence.py]
        UTIL_STATE[utils/state.py]
        UTIL_COLORS[utils/colors.py]
        UTIL_HELPER[utils/helper.py]
    end

    subgraph "External Validation"
        PYDANTIC[pydantic<br/>Schema validation]
    end

    subgraph "External Services"
        OPENROUTER_API[OpenRouter API<br/>gpt-5-nano]
    end

    MAIN --> SESSION_SVC
    MAIN --> RUNNER
    MAIN --> PVAGENT
    MAIN --> PRAGENT
    MAIN --> UTIL_IO
    MAIN --> UTIL_PARSER
    MAIN --> UTIL_SCHEMES
    MAIN --> UTIL_STATE

    WORKFLOW --> AGENT
    WORKFLOW --> RUNNER
    WORKFLOW --> SESSION_SVC
    WORKFLOW --> PVAGENT
    WORKFLOW --> PRAGENT

    PVAGENT --> AGENT
    PVAGENT --> LITELLM
    PVAGENT --> UTIL_HELPER
    PVAGENT --> UTIL_SCHEMES

    PRAGENT --> AGENT
    PRAGENT --> LITELLM
    PRAGENT --> UTIL_HELPER

    UTIL_IO --> UTIL_COLORS
    UTIL_PARSER --> PYDANTIC
    UTIL_PARSER --> UTIL_SCHEMES
    UTIL_SCHEMES --> PYDANTIC
    UTIL_PERSIST --> SESSION_SVC

    LITELLM --> OPENROUTER_API

    style PVAGENT fill:#fff9c4
    style PRAGENT fill:#fff9c4
    style AGENT fill:#e1bee7
    style OPENROUTER_API fill:#ffccbc
```

## File Structure

```mermaid
graph TD
    ROOT[project_tcc/]

    ROOT --> MAIN[main.py<br/>275 lines<br/>Interactive workflow]
    ROOT --> WORKFLOW[product_workflow.py<br/>170 lines<br/>Automated orchestration]
    ROOT --> DB[(my_agent_data.db<br/>SQLite database)]
    ROOT --> ENV[.env<br/>OPEN_ROUTER_API_KEY]
    ROOT --> PYPROJECT[pyproject.toml<br/>Dependencies]

    ROOT --> PV_DIR[product_vision_agent/]
    PV_DIR --> PV_AGENT[agent.py]
    PV_DIR --> PV_INST[instructions.txt]
    PV_DIR --> PV_TOOLS[tools.py]

    ROOT --> PR_DIR[product_roadmap_agent/]
    PR_DIR --> PR_AGENT[agent.py]
    PR_DIR --> PR_INST[instructions.txt]

    ROOT --> UTILS[utils/]
    UTILS --> U_AGENTIO[agent_io.py<br/>135 lines<br/>Event processing]
    UTILS --> U_PARSER[response_parser.py<br/>50 lines<br/>JSON parsing]
    UTILS --> U_SCHEMES[schemes.py<br/>60 lines<br/>Pydantic schemas]
    UTILS --> U_PERSIST[persistence.py<br/>42 lines<br/>State persistence]
    UTILS --> U_STATE[state.py<br/>34 lines<br/>State display]
    UTILS --> U_COLORS[colors.py<br/>32 lines<br/>ANSI colors]
    UTILS --> U_HELPER[helper.py<br/>10 lines<br/>Instruction loader]

    ROOT --> NOTEBOOKS[notebooks/<br/>Jupyter notebooks]

    style MAIN fill:#e1f5ff
    style WORKFLOW fill:#e1f5ff
    style PV_DIR fill:#fff9c4
    style PR_DIR fill:#fff9c4
    style DB fill:#c8e6c9
```

## Key Metrics

| Metric | Value |
|--------|-------|
| **Agents Implemented** | 2 (Vision, Roadmap) |
| **Workflow Patterns** | 2 (Interactive, Automated) |
| **Utility Modules** | 7 modules in utils/ |
| **Total Python Files** | ~15 core files |
| **State Fields** | 5 tracked fields |
| **Database Tables** | 4 (sessions, events, app_states, user_states) |
| **Main Entry Point Lines** | 275 (main.py) |
| **LLM Model** | openrouter/openai/gpt-5-nano |
| **Session Persistence** | SQLite via Google ADK |
| **Agent Transfer Restrictions** | Disabled (no autonomous transfers) |

## Legend

- 🟡 **Yellow** - Agent components
- 🟣 **Purple** - Orchestration layer
- 🟢 **Green** - State/Database layer
- 🟠 **Orange** - External services
- 🔵 **Blue** - User interface layer
