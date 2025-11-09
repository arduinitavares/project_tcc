# Multi-Agent System Architecture
## Autonomous Agile Management Platform

This document defines the complete architecture for the TCC project implementing a multi-agent system that simulates Scrum roles.

---

## 0. Current Implementation Status

### What Exists Now (Prototype Phase)

As of October 2025, the codebase is in an **early prototype phase** with a limited, exploratory implementation. This section documents the actual, as-built system that exists today.

#### Current Architecture Diagram

```mermaid
graph TB
    subgraph "User Interface Layer"
        INTERACTIVE["Interactive Chat Session<br/>(main.py)<br/>Multi-turn conversation"]
        AUTOMATED["Automated Workflow<br/>(product_workflow.py)<br/>Single-pass orchestration"]
    end

    subgraph "Session & Persistence Layer"
        SESSION["DatabaseSessionService<br/>(Google ADK)<br/>Session management"]
        SQLITE[(SQLite Database<br/>my_agent_data.db<br/>Persistent state store)]
    end

    subgraph "Agent Layer - CURRENT"
        VISION["Product Vision Agent<br/>Generates product vision<br/>Asks clarifying questions"]
        ROADMAP["Product Roadmap Agent<br/>Creates agile roadmap<br/>Organizes features into themes"]
    end

    subgraph "Orchestration & Processing"
        LOOP["LoopAgent<br/>(Automated workflow)<br/>Sequential orchestrator"]
        RUNNER["Runner<br/>(Interactive workflow)<br/>Agent execution wrapper"]
        PARSER["Response Parser<br/>JSON validation<br/>Pydantic models"]
        IO["Agent I/O Handler<br/>Event streaming<br/>Colored output"]
        PERSIST["State Persistence<br/>Utilities<br/>Session updates"]
    end

    subgraph "Technology Stack"
        LITELLM["LiteLLM<br/>Model abstraction"]
        OPENROUTER["OpenRouter API<br/>gpt-5-nano"]
        PYDANTIC["Pydantic<br/>Schema validation"]
    end

    INTERACTIVE --> |accumulates requirements| SESSION
    AUTOMATED --> LOOP

    LOOP --> VISION
    LOOP --> ROADMAP

    INTERACTIVE --> RUNNER
    RUNNER --> VISION
    VISION --> |streams events| IO
    IO --> PARSER
    PARSER --> PERSIST
    PERSIST --> SESSION

    VISION --> LITELLM
    ROADMAP --> LITELLM
    LITELLM --> OPENROUTER

    SESSION --> SQLITE
    PYDANTIC --> PARSER

    style VISION fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style ROADMAP fill:#e1f5ff,stroke:#01579b,stroke-width:2px
    style SESSION fill:#f3f3f3,stroke:#333
    style SQLITE fill:#e8f5e9,stroke:#1b5e20
    style LOOP fill:#fff4e1,stroke:#f57f17
    style PARSER fill:#f3e5f5,stroke:#4a148c
```

#### Two Workflow Patterns Currently Implemented

**1. Interactive Session-Based Workflow** (`main.py`)
- **User Experience**: Multi-turn conversational interface
- **Control Flow**:
  1. Load or create session (persisted to SQLite)
  2. User enters text
  3. Append text to accumulated `unstructured_requirements`
  4. Call Product Vision Agent with **full accumulated history** (not just latest message)
  5. Parse agent's JSON response (vision statement + is_complete flag + clarifying questions)
  6. Update in-memory session state
  7. Persist state to SQLite
  8. When vision is complete (is_complete=True), switch Runner to Roadmap Agent
  9. Repeat from step 2 with new agent

- **Key Functions**:
  - `load_or_create_session()`: Retrieves existing session or creates new one (user_id="user_123", app_name="ProductManager")
  - `append_user_text_to_requirements()`: Accumulates all user input into single string
  - `run_vision_agent()`: Calls agent with full accumulated requirements
  - `save_state()`: Persists session state to SQLite via DatabaseSessionService
  - `get_session_state()`: Fetches latest state from database

- **State Schema** (in-memory and persisted):
  ```python
  {
      "product_vision_statement": str,      # Agent output
      "product_roadmap": str,               # Agent output (future)
      "unstructured_requirements": str,     # All accumulated user input
      "is_complete": bool,                  # Vision completion flag
      "clarifying_questions": list[str]     # Questions from agent
  }
  ```

**2. Automated Orchestration Workflow** (`product_workflow.py`)
- **User Experience**: Non-interactive, single-pass execution with complete requirements
- **Orchestrator**: `LoopAgent` (Google ADK) as master controller
- **Control Flow**:
  1. Accept fully-formed requirements as input
  2. LoopAgent calls Product Vision Agent with requirements
  3. Checks if vision is complete (is_complete=True)
  4. If incomplete: stops and returns clarifying questions to user
  5. If complete: calls Product Roadmap Agent with vision + original requirements
  6. Returns final roadmap output

- **Key Feature**: Orchestration logic defined via agent instructions (ORCHESTRATOR_INSTRUCTIONS) rather than explicit graph construction

---

#### Agent Responsibilities (Current)

**Product Vision Agent** (`product_vision_agent/`)
- **Input**: Unstructured requirements text
- **Output**: JSON with `product_vision_statement`, `is_complete` bool, `clarifying_questions` list
- **Behavior**:
  - Analyzes requirements and generates a product vision statement
  - If information is missing: creates draft vision with placeholders, asks clarifying questions
  - If information is sufficient: marks vision as complete
- **Configuration**:
  - Uses `InputSchema` and `OutputSchema` from `utils/schemes.py`
  - Instructions loaded from `product_vision_agent/instructions.txt`
  - Disallows transfers to parent/peers

**Product Roadmap Agent** (`product_roadmap_agent/`)
- **Input**: Product vision statement + original user requirements
- **Output**: JSON with `roadmap_draft` (list of RoadmapTheme), `is_complete` bool, `clarifying_questions` list
- **Behavior**:
  - Takes a completed vision and unstructured requirements
  - Generates high-level roadmap organized by themes
  - Each theme includes: name, key features, justification, time frame (Now/Next/Later)
  - Can ask for clarification if roadmap needs more definition
- **Data Structures**:
  ```python
  class RoadmapTheme:
      theme_name: str              # e.g., "User Authentication"
      key_features: List[str]      # Major features under theme
      justification: str           # Why prioritized
      time_frame: str              # "Now", "Next", or "Later"
  ```

---

#### Technology Stack (Current Implementation)

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Agent Framework** | Google ADK | Agent orchestration, LoopAgent for sequencing |
| **LLM Access** | LiteLLM | Model abstraction layer |
| **LLM Provider** | OpenRouter API | Hosted model access |
| **LLM Model** | gpt-5-nano | Lightweight model for cost efficiency |
| **State Management** | SQLite | Persistent session storage |
| **Session Service** | DatabaseSessionService (ADK) | Session lifecycle management |
| **Schema Validation** | Pydantic | InputSchema/OutputSchema enforcement |
| **I/O Handling** | asyncio + Google ADK streaming | Async agent communication, event streaming |
| **Output Formatting** | Terminal colors (colors.py) | Colored console output |

---

#### Data Flow and State Management (Current)

```mermaid
graph LR
    subgraph "Session Lifecycle"
        direction TB
        CREATE["1. Create/Load Session"]
        FETCH["2. Fetch State from DB"]
        ACCUM["3. Accumulate User Input"]
        CREATE --> FETCH
        FETCH --> ACCUM
    end

    subgraph "Agent Execution"
        direction TB
        CALL["4. Call Agent with<br/>Full Accumulated Req"]
        STREAM["5. Stream Events<br/>to Handler"]
        CALL --> STREAM
    end

    subgraph "Response Processing"
        direction TB
        PARSE["6. Parse JSON<br/>to Pydantic Model"]
        VALIDATE["7. Validate Schema"]
        PARSE --> VALIDATE
    end

    subgraph "State Persistence"
        direction TB
        UPDATE["8. Update In-Memory<br/>Session State"]
        PERSIST["9. Write State<br/>to SQLite"]
        UPDATE --> PERSIST
    end

    subgraph "Loop Control"
        direction TB
        CHECK["10. Check is_complete<br/>Flag"]
        SWITCH["11. If complete:<br/>Switch Agent"]
        CHECK --> SWITCH
    end

    CREATE --> CALL
    STREAM --> PARSE
    VALIDATE --> UPDATE
    PERSIST --> CHECK
    SWITCH --> |next iteration| FETCH

    style CREATE fill:#e3f2fd
    style CALL fill:#fff3e0
    style PARSE fill:#f3e5f5
    style PERSIST fill:#e8f5e9
    style CHECK fill:#fce4ec
```

---

#### Key Implementation Patterns

**1. Multi-Turn Context Accumulation**
```
Turn 1: User input = "Need a task manager"
        Accumulated = "Need a task manager"

Turn 2: User input = "For mobile users"
        Accumulated = "Need a task manager For mobile users"

Turn 3: User input = "With AI prioritization"
        Accumulated = "Need a task manager For mobile users With AI prioritization"
```
The agent receives the FULL accumulated history, not just the latest message. This preserves context across clarifying question exchanges.

**2. Runner Switching Pattern** (Interactive workflow)
```python
# Start with Vision Agent
runner = Runner(agent=product_vision_agent, ...)

# When vision is complete:
if structured.is_complete and runner.agent is not product_roadmap_agent:
    runner = Runner(agent=product_roadmap_agent, ...)  # Switch
```

**3. Schema-Driven Validation**
- Agent outputs MUST be valid JSON matching OutputSchema
- Pydantic validates structure before state update
- Parse failures don't crash the system (error is displayed, user continues)

---

#### Current Limitations and Gaps

| Gap | Why It Matters | Future Solution |
|-----|----------------|-----------------|
| **No Scrum Master Agent** | Cannot facilitate sprint events or detect impediments | Implement SM agent (Phase 3) |
| **No Developer Support Agent** | Cannot break down stories into tasks or track progress | Implement Dev agent (Phase 2) |
| **No Sprint Orchestration** | No state machine for Scrum event flow | State machine + Sprint Facilitator (Phase 3) |
| **No Artifact Persistence** | Vision/Roadmap not linked to formal Product Backlog structure | Implement artifact schemas + INVEST validation (Phase 4) |
| **No Evaluation Framework** | Cannot measure cognitive load or artifact quality | NASA-TLX + INVEST validator agents (Phase 5) |
| **No Multi-Agent Collaboration** | Agents work in series, no peer-to-peer communication | Event bus / Blackboard pattern (Phase 3) |

---

### What Will Be Built (Target Architecture)

The sections below (1-10) describe the **complete target system** as specified in the TCC proposal. The current prototype (Section 0 above) is an early exploration that will evolve into this architecture.

Key differences between current and target:
- **Current**: 2 exploratory agents (Vision, Roadmap)
- **Target**: 8+ specialized agents (PO domain + SM domain + Dev domain)
- **Current**: Simple linear workflows
- **Target**: State machine orchestration with 5 Scrum events
- **Current**: Session-level state management
- **Target**: Full Scrum artifacts (Product Backlog, Sprint Backlog, DoD, Impediments)
- **Current**: No evaluation
- **Target**: NASA-TLX, INVEST, cycle time measurement

---

## 1. High-Level System Architecture

```mermaid
graph TB
    subgraph "Human Interface Layer"
        USER[Developer/User<br/>Small Team 1-4 people]
        CLI[CLI/Chat Interface]
    end

    subgraph "Orchestration Layer"
        ORCH[Sprint Facilitator Agent<br/>Event orchestrator]
        STATE[State Machine<br/>Scrum cycle controller]
    end

    subgraph "Product Owner Domain"
        REQ[Requirements Analyst<br/>NLU + Domain modeling]
        BACK[Backlog Curator<br/>User story generation]
        PRIOR[Prioritization Advisor<br/>Value-based ranking]
    end

    subgraph "Scrum Master Domain"
        COACH[Process Coach<br/>Scrum adherence]
        IMPED[Impediment Detective<br/>Blocker identification]
        METRICS[Metrics Collector<br/>Evaluation data]
    end

    subgraph "Developer Support Domain"
        TASK[Task Decomposer<br/>Technical breakdown]
        TRACK[Progress Monitor<br/>Sprint tracking]
        QA[Quality Validator<br/>DoD enforcement]
    end

    subgraph "Persistence Layer"
        DB[(SQLite Database)]
        MEM[Session Service<br/>ADK DatabaseSessionService]
    end

    subgraph "Evaluation Layer"
        EVAL[Evaluation Framework]
        NASA[NASA-TLX]
        INVEST[INVEST Validator]
        CYCLE[Cycle Time Tracker]
    end

    USER <--> CLI
    CLI <--> ORCH
    ORCH <--> STATE

    STATE --> REQ
    STATE --> BACK
    STATE --> PRIOR
    STATE --> COACH
    STATE --> IMPED
    STATE --> TASK
    STATE --> TRACK
    STATE --> QA
    STATE --> METRICS

    REQ <--> BACK
    BACK <--> PRIOR
    TASK <--> TRACK
    TRACK <--> QA
    COACH <--> IMPED

    REQ --> MEM
    BACK --> MEM
    PRIOR --> MEM
    COACH --> MEM
    IMPED --> MEM
    TASK --> MEM
    TRACK --> MEM
    QA --> MEM
    METRICS --> MEM

    MEM <--> DB

    METRICS --> EVAL
    EVAL --> NASA
    EVAL --> INVEST
    EVAL --> CYCLE

    style USER fill:#e1f5ff
    style ORCH fill:#fff4e1
    style DB fill:#e8f5e9
    style EVAL fill:#f3e5f5
```

---

## 2. Agent Catalog and Responsibilities

```mermaid
mindmap
  root((Multi-Agent<br/>Scrum System))
    Product Owner Domain
      Requirements Analyst
        Parse natural language
        Extract user needs
        Ask clarifying questions
        Build domain model
      Backlog Curator
        Generate user stories
        Apply INVEST criteria
        Write acceptance criteria
        Maintain Product Backlog
      Prioritization Advisor
        Rank by business value
        Assess technical risk
        Consider dependencies
        Optimize sprint goals
    Scrum Master Domain
      Sprint Facilitator
        Orchestrate events
        Enforce timeboxes
        Manage state machine
        Facilitate discussions
      Process Coach
        Monitor adherence
        Suggest improvements
        Coach best practices
        Maintain DoD
      Impediment Detective
        Detect blockers
        Analyze patterns
        Suggest resolutions
        Track resolution
    Developer Support
      Task Decomposer
        Break down stories
        Estimate effort
        Identify subtasks
        Create Sprint Backlog
      Progress Monitor
        Track task status
        Calculate velocity
        Detect risks
        Generate burndown
      Quality Validator
        Verify DoD compliance
        Check completeness
        Ensure quality gates
        Validate increment
    Cross-Cutting
      Metrics Collector
        Gather NASA-TLX
        Measure cycle time
        Validate INVEST
        Aggregate KPIs
```

---

## 3. Scrum Event State Machine

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> BacklogRefinement: User initiates project

    BacklogRefinement --> SprintPlanning: Backlog ready
    SprintPlanning --> SprintExecution: Sprint goal defined

    SprintExecution --> DailyStandup: Each working day
    DailyStandup --> SprintExecution: Continue work

    SprintExecution --> SprintReview: Sprint timebox ends
    SprintReview --> SprintRetrospective: Increment reviewed
    SprintRetrospective --> BacklogRefinement: Insights captured

    BacklogRefinement --> Idle: Project paused/completed

    note right of BacklogRefinement
        Active Agents:
        - Requirements Analyst
        - Backlog Curator
        - Prioritization Advisor

        Duration: Continuous/On-demand
        Output: Product Backlog
    end note

    note right of SprintPlanning
        Active Agents:
        - Sprint Facilitator
        - Backlog Curator
        - Prioritization Advisor
        - Task Decomposer

        Duration: 8h (1-month sprint)
        Output: Sprint Backlog, Sprint Goal
    end note

    note right of DailyStandup
        Active Agents:
        - Sprint Facilitator
        - Progress Monitor
        - Impediment Detective

        Duration: 15 min
        Output: Updated Sprint Backlog, Impediments
    end note

    note right of SprintReview
        Active Agents:
        - Sprint Facilitator
        - Quality Validator
        - Progress Monitor

        Duration: 4h (1-month sprint)
        Output: Accepted Increment, Backlog Updates
    end note

    note right of SprintRetrospective
        Active Agents:
        - Sprint Facilitator
        - Process Coach
        - Metrics Collector

        Duration: 3h (1-month sprint)
        Output: Improvement Actions, Updated DoD
    end note
```

---

## 4. Memory and State Architecture

```mermaid
graph TB
    subgraph "Agent Working Memory"
        direction LR
        A1[Agent 1<br/>Context Buffer]
        A2[Agent 2<br/>Context Buffer]
        A3[Agent N<br/>Context Buffer]
    end

    subgraph "Shared Session State (In-Memory)"
        CURRENT[Current Event State]
        CONV[Conversation History]
        TEMP[Temporary Decisions]
    end

    subgraph "SQLite Persistent Storage"
        direction TB

        subgraph "Scrum Artifacts Tables"
            PB_TABLE[(product_backlog)]
            SB_TABLE[(sprint_backlog)]
            DOD_TABLE[(definition_of_done)]
            IMP_TABLE[(impediments)]
        end

        subgraph "Session Tables"
            SESSION[(sessions)]
            SPRINT[(sprints)]
            EVENTS[(event_history)]
        end

        subgraph "Metrics Tables"
            NASA_TABLE[(nasa_tlx_responses)]
            INVEST_TABLE[(invest_scores)]
            CYCLE_TABLE[(cycle_times)]
            VELOCITY[(velocity_history)]
        end

        subgraph "Knowledge Base"
            DOMAIN[(domain_knowledge)]
            PROCESS[(process_definitions)]
        end
    end

    A1 --> CURRENT
    A2 --> CURRENT
    A3 --> CURRENT

    CURRENT --> SESSION
    CONV --> EVENTS
    TEMP --> SESSION

    SESSION --> SPRINT
    SPRINT --> PB_TABLE
    SPRINT --> SB_TABLE
    SPRINT --> DOD_TABLE
    SPRINT --> IMP_TABLE

    EVENTS --> NASA_TABLE
    EVENTS --> INVEST_TABLE
    EVENTS --> CYCLE_TABLE
    EVENTS --> VELOCITY

    A1 -.Read Only.-> DOMAIN
    A2 -.Read Only.-> DOMAIN
    A3 -.Read Only.-> DOMAIN
    A1 -.Read Only.-> PROCESS
    A2 -.Read Only.-> PROCESS
    A3 -.Read Only.-> PROCESS

    style CURRENT fill:#fff9c4
    style SESSION fill:#e1f5fe
    style DOMAIN fill:#f1f8e9
```

---

## 5. Communication Patterns

```mermaid
graph TB
    subgraph "Pattern 1: Hierarchical (Event Orchestration)"
        FACIL1[Sprint Facilitator] --> |Delegates| REQ1[Requirements Analyst]
        FACIL1 --> |Delegates| BACK1[Backlog Curator]
        FACIL1 --> |Delegates| TASK1[Task Decomposer]
        REQ1 --> |Reports back| FACIL1
        BACK1 --> |Reports back| FACIL1
        TASK1 --> |Reports back| FACIL1
    end

    subgraph "Pattern 2: Peer-to-Peer (Collaboration)"
        REQ2[Requirements Analyst] <--> |Negotiates| BACK2[Backlog Curator]
        BACK2 <--> |Consults| PRIOR2[Prioritization Advisor]
        TASK2[Task Decomposer] <--> |Coordinates| TRACK2[Progress Monitor]
    end

    subgraph "Pattern 3: Blackboard (Async Updates)"
        direction TB
        BB[(Shared Artifacts<br/>Blackboard)]

        REQ3[Requirements Analyst] --> BB
        BACK3[Backlog Curator] --> BB
        PRIOR3[Prioritization Advisor] --> BB
        TASK3[Task Decomposer] --> BB
        TRACK3[Progress Monitor] --> BB
        QA3[Quality Validator] --> BB

        BB --> REQ3
        BB --> BACK3
        BB --> PRIOR3
        BB --> TASK3
        BB --> TRACK3
        BB --> QA3
    end

    subgraph "Pattern 4: Human-in-the-Loop (Validation)"
        AGENT[Any Agent] --> |Proposes| HUMAN[Developer/User]
        HUMAN --> |Approves/Rejects/Modifies| AGENT
    end

    style BB fill:#e8eaf6
    style HUMAN fill:#e1f5ff
```

---

## 6. Data Schema (Scrum Artifacts)

```mermaid
erDiagram
    SESSION ||--o{ SPRINT : contains
    SPRINT ||--o{ PRODUCT_BACKLOG_ITEM : has
    SPRINT ||--o{ SPRINT_BACKLOG_ITEM : has
    SPRINT ||--|| DEFINITION_OF_DONE : uses
    SPRINT ||--o{ IMPEDIMENT : tracks
    SPRINT ||--o{ EVENT_HISTORY : records

    SESSION {
        string session_id PK
        string app_name
        string user_id
        datetime created_at
        datetime updated_at
        json state
    }

    SPRINT {
        int sprint_id PK
        string session_id FK
        int sprint_number
        string sprint_goal
        date start_date
        date end_date
        int duration_weeks
        string status
        float planned_velocity
        float actual_velocity
    }

    PRODUCT_BACKLOG_ITEM {
        int pbi_id PK
        string session_id FK
        string title
        string description
        string user_story
        json acceptance_criteria
        string priority
        int business_value
        int effort_estimate
        json invest_score
        string status
        int rank_order
        datetime created_at
    }

    SPRINT_BACKLOG_ITEM {
        int sbi_id PK
        int sprint_id FK
        int pbi_id FK
        string task_title
        string task_description
        int effort_hours
        string status
        string assigned_to
        datetime started_at
        datetime completed_at
    }

    DEFINITION_OF_DONE {
        int dod_id PK
        int sprint_id FK
        json quality_criteria
        json acceptance_rules
        json technical_standards
        datetime defined_at
        datetime updated_at
    }

    IMPEDIMENT {
        int impediment_id PK
        int sprint_id FK
        string description
        string severity
        string detected_by_agent
        datetime detected_at
        string resolution_status
        string resolution_notes
        datetime resolved_at
    }

    EVENT_HISTORY {
        int event_id PK
        int sprint_id FK
        string event_type
        datetime event_start
        datetime event_end
        int duration_minutes
        json participants
        json decisions
        json artifacts_produced
    }

    NASA_TLX_RESPONSE {
        int response_id PK
        string session_id FK
        int sprint_id FK
        string measurement_point
        int mental_demand
        int physical_demand
        int temporal_demand
        int performance
        int effort
        int frustration
        float overall_score
        datetime collected_at
    }

    INVEST_SCORE {
        int score_id PK
        int pbi_id FK
        string evaluated_by_agent
        boolean independent
        boolean negotiable
        boolean valuable
        boolean estimable
        boolean small
        boolean testable
        float overall_score
        json feedback
        datetime evaluated_at
    }

    CYCLE_TIME_METRIC {
        int metric_id PK
        int sbi_id FK
        datetime entered_backlog
        datetime started_work
        datetime completed
        int lead_time_hours
        int cycle_time_hours
        string stage_breakdown
    }

    PRODUCT_BACKLOG_ITEM ||--o{ INVEST_SCORE : evaluated_by
    SPRINT_BACKLOG_ITEM ||--o{ CYCLE_TIME_METRIC : measures
    SPRINT ||--o{ NASA_TLX_RESPONSE : collects
```

---

## 7. Agent Interaction Sequence (Sprint Planning Example)

```mermaid
sequenceDiagram
    actor User as Developer/User
    participant Facil as Sprint Facilitator
    participant Back as Backlog Curator
    participant Prior as Prioritization Advisor
    participant Task as Task Decomposer
    participant DB as Session State

    User->>Facil: "Start sprint planning"
    Facil->>DB: Load Product Backlog
    DB-->>Facil: Backlog items

    Facil->>User: "Review top priority items?"
    User-->>Facil: "Yes, show them"

    Facil->>Prior: "Get top N items for sprint capacity"
    Prior->>DB: Query priorities & velocity
    DB-->>Prior: Ranked items + team velocity
    Prior-->>Facil: Recommended items [PBI-1, PBI-2, PBI-3]

    Facil->>User: "Proposed: PBI-1, PBI-2, PBI-3 (13 points). Agree?"
    User-->>Facil: "Yes, let's define sprint goal"

    Facil->>User: "What is the sprint goal?"
    User-->>Facil: "Implement user authentication"

    Facil->>Task: "Decompose PBI-1, PBI-2, PBI-3 into tasks"

    loop For each PBI
        Task->>Back: "Get acceptance criteria for PBI-X"
        Back-->>Task: Acceptance criteria details
        Task->>Task: Analyze & decompose
        Task->>DB: Save sprint backlog items
    end

    Task-->>Facil: Sprint Backlog created (18 tasks)

    Facil->>DB: Create Sprint record
    Facil->>DB: Save event history (Planning completed)

    Facil->>User: "Sprint Planning complete! 18 tasks, Goal: 'Implement user authentication'"

    Note over User,DB: Planning took 2.5h (within 4h timebox for 2-week sprint)
```

---

## 8. Evaluation Framework Integration

```mermaid
graph TB
    subgraph "Runtime Data Collection"
        AGENTS[All Agents] --> |Operational data| METRICS[Metrics Collector Agent]
        USER_INT[User Interactions] --> |Behavioral data| METRICS
        EVENTS[Scrum Events] --> |Temporal data| METRICS
    end

    subgraph "Evaluation Metrics (TCC Validation)"
        direction TB

        subgraph "Cognitive Load (NASA-TLX)"
            NASA_PRE[Pre-Sprint Survey]
            NASA_POST[Post-Sprint Survey]
            NASA_SCORE[TLX Score<br/>Target: <50/100]
        end

        subgraph "Artifact Quality (INVEST)"
            INVEST_AUTO[Automated Validation]
            INVEST_HUMAN[Expert Review]
            INVEST_SCORE[INVEST Score<br/>Target: >4/6]
        end

        subgraph "Workflow Efficiency"
            LEAD[Lead Time]
            CYCLE[Cycle Time]
            VELOCITY[Sprint Velocity]
            EFFICIENCY[Efficiency Score<br/>Target: >Baseline]
        end

        subgraph "System Performance"
            LATENCY[Agent Response Time]
            COST[LLM API Cost]
            COMPLETE[Task Completion Rate]
        end
    end

    subgraph "Baseline Comparison"
        BASELINE[Solo Developer<br/>Traditional Tools]
        EXPERIMENTAL[Developer + MAS<br/>This System]
        COMPARISON[Statistical Analysis<br/>T-test, Effect Size]
    end

    METRICS --> NASA_PRE
    METRICS --> NASA_POST
    NASA_PRE --> NASA_SCORE
    NASA_POST --> NASA_SCORE

    METRICS --> INVEST_AUTO
    METRICS --> INVEST_HUMAN
    INVEST_AUTO --> INVEST_SCORE
    INVEST_HUMAN --> INVEST_SCORE

    METRICS --> LEAD
    METRICS --> CYCLE
    METRICS --> VELOCITY
    LEAD --> EFFICIENCY
    CYCLE --> EFFICIENCY
    VELOCITY --> EFFICIENCY

    METRICS --> LATENCY
    METRICS --> COST
    METRICS --> COMPLETE

    NASA_SCORE --> EXPERIMENTAL
    INVEST_SCORE --> EXPERIMENTAL
    EFFICIENCY --> EXPERIMENTAL
    LATENCY --> EXPERIMENTAL
    COST --> EXPERIMENTAL
    COMPLETE --> EXPERIMENTAL

    BASELINE --> COMPARISON
    EXPERIMENTAL --> COMPARISON

    style NASA_SCORE fill:#ffcdd2
    style INVEST_SCORE fill:#c8e6c9
    style EFFICIENCY fill:#bbdefb
    style COMPARISON fill:#f3e5f5
```

---

## 9. Technology Stack Mapping

```mermaid
graph LR
    subgraph "Application Layer"
        CLI[CLI Interface<br/>Python argparse/rich]
        CHAT[Chat Interface<br/>Asyncio loop]
    end

    subgraph "Agent Framework"
        ADK[Google ADK]
        LOOP[LoopAgent<br/>Orchestrator]
        AGENTS[Individual Agents<br/>Agent class]
        TOOLS[Agent Tools<br/>Function calling]
    end

    subgraph "LLM Layer"
        LITELLM[LiteLLM]
        OPENROUTER[OpenRouter API]
        GPT[GPT-5-nano]
    end

    subgraph "State Management"
        SESSION[DatabaseSessionService]
        SQLITE[(SQLite DB)]
        SCHEMA[SQLAlchemy ORM]
    end

    subgraph "Validation & Metrics"
        PYDANTIC[Pydantic Models]
        INVEST_VAL[INVEST Validator]
        NASA_VAL[NASA-TLX Calculator]
        STATS[Statistics Module<br/>scipy/numpy]
    end

    CLI --> CHAT
    CHAT --> LOOP
    LOOP --> ADK
    ADK --> AGENTS
    AGENTS --> TOOLS

    AGENTS --> LITELLM
    LITELLM --> OPENROUTER
    OPENROUTER --> GPT

    AGENTS --> SESSION
    SESSION --> SQLITE
    SCHEMA --> SQLITE

    AGENTS --> PYDANTIC
    TOOLS --> INVEST_VAL
    TOOLS --> NASA_VAL
    METRICS[Metrics Collector] --> STATS

    style ADK fill:#4285f4,color:#fff
    style SQLITE fill:#003b57,color:#fff
    style PYDANTIC fill:#e92063,color:#fff
```

---

## 10. Implementation Phases

```mermaid
gantt
    title TCC Implementation Roadmap
    dateFormat YYYY-MM-DD
    section Phase 1: Foundation
    Define data schemas (SQLite)           :p1_1, 2025-01-01, 1w
    Implement Session Service wrapper      :p1_2, after p1_1, 1w
    Create Scrum artifact models           :p1_3, after p1_2, 1w

    section Phase 2: Core Agents
    Requirements Analyst agent             :p2_1, after p1_3, 1w
    Backlog Curator agent                  :p2_2, after p2_1, 1w
    Task Decomposer agent                  :p2_3, after p2_2, 1w
    Progress Monitor agent                 :p2_4, after p2_3, 1w

    section Phase 3: Orchestration
    Sprint Facilitator agent               :p3_1, after p2_4, 1w
    State machine implementation           :p3_2, after p3_1, 1w
    Event orchestration logic              :p3_3, after p3_2, 1w

    section Phase 4: Support Agents
    Prioritization Advisor                 :p4_1, after p3_3, 1w
    Process Coach agent                    :p4_2, after p4_1, 1w
    Impediment Detective                   :p4_3, after p4_2, 1w
    Quality Validator                      :p4_4, after p4_3, 1w

    section Phase 5: Evaluation
    Metrics Collector agent                :p5_1, after p4_4, 1w
    INVEST validator tool                  :p5_2, after p5_1, 1w
    NASA-TLX integration                   :p5_3, after p5_2, 1w
    Cycle time tracker                     :p5_4, after p5_3, 1w

    section Phase 6: Validation
    Baseline study execution               :p6_1, after p5_4, 2w
    Experimental study execution           :p6_2, after p6_1, 2w
    Statistical analysis                   :p6_3, after p6_2, 1w

    section Phase 7: Documentation
    Write TCC monograph                    :p7_1, after p6_3, 4w
    Prepare defense presentation           :p7_2, after p7_1, 1w
    Final revisions                        :p7_3, after p7_2, 1w
```

---

## Next Steps

1. **Review and refine** this architecture with your advisor
2. **Validate** that all TCC requirements are covered
3. **Prioritize** which agents to implement first (suggestion: start with Product Owner domain)
4. **Define** the first sprint's scope for implementation
5. **Begin** with data schema implementation (foundation for everything)

## Questions to Resolve

- [ ] Sprint duration for PoC: 1 week or 2 weeks?
- [ ] Number of test participants for evaluation study?
- [ ] Baseline tool selection (Trello? Jira? GitHub Projects?)
- [ ] LLM model selection (cost vs. capability tradeoff)
- [ ] Human approval checkpoints: synchronous or asynchronous?
