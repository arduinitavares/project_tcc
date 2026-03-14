# Enterprise Architecture Analysis Report

> **Repository:** `project_tcc` — Autonomous Agile Management Platform  
> **Analysis date:** 2026-02-09  
> **Analyst scope:** Static code analysis, repository structure, dependency signals, documentation  

> **Legacy note:** This report analyzes the pre-FastAPI CLI architecture. The current supported runtime entrypoint is [api.py](api.py), and references to `main.py` below are historical.

---

## Repository & Context Summary

### Purpose of the System

This system is a **multi-agent AI platform** that simulates Scrum roles (Product Owner, Scrum Master, Architect) to reduce cognitive load for small development teams (1–4 developers). It orchestrates the full Agile planning pipeline—from product vision through sprint execution—using LLM-powered agents coordinated by a central orchestrator and governed by a finite state machine (FSM).

**[Fact]** The system is a TCC (Trabalho de Conclusão de Curso / capstone research project) exploring how AI agents can autonomously manage Agile workflows via a **Spec-Driven Architecture** ([README.md](README.md), [chapter-04](docs/tcc/chapter-04-desenvolvimento-do-artefato.md)).

### Key Technologies

| Technology | Role | Signal |
|---|---|---|
| **Python 3.12+** | Core language | [pyproject.toml](pyproject.toml) `requires-python = ">=3.12"` |
| **Google ADK ≥1.16** | Agent orchestration framework | [pyproject.toml](pyproject.toml), all agent definitions |
| **LiteLLM ≥1.78** | LLM abstraction (OpenRouter) | [pyproject.toml](pyproject.toml), [model_config.py](utils/model_config.py) |
| **SQLModel ≥0.27** | ORM with Pydantic integration | [pyproject.toml](pyproject.toml), [agile_sqlmodel.py](agile_sqlmodel.py) |
| **SQLite** | Embedded relational database | [agile_sqlmodel.py](agile_sqlmodel.py#L795), `.db` files in root |
| **Pydantic v2** | Schema validation & serialization | [utils/schemes.py](utils/schemes.py), all `*Input`/`*Output` models |
| **Pytest ≥9.0** | Testing framework | [pyproject.toml](pyproject.toml), [tests/conftest.py](tests/conftest.py) |
| **Rich** | CLI presentation layer | [main.py](main.py#L32) |

### Architectural Signals Observed (Evidence-Based)

1. **Hub-and-spoke agent topology:** Single `orchestrator_agent` delegates to 6 specialist sub-agents via `AgentTool` wrappers ([orchestrator_agent/agent.py](orchestrator_agent/agent.py#L87-L112)).
2. **Explicit FSM governance:** 7 phases, 24+ states with tool restrictions per state ([orchestrator_agent/fsm/states.py](orchestrator_agent/fsm/states.py), [orchestrator_agent/fsm/definitions.py](orchestrator_agent/fsm/definitions.py), [orchestrator_agent/fsm/controller.py](orchestrator_agent/fsm/controller.py)).
3. **Spec-Driven Authority chain:** `SpecRegistry → CompiledSpecAuthority → SpecAuthorityAcceptance → UserStory.accepted_spec_version_id` ([agile_sqlmodel.py](agile_sqlmodel.py#L185-L300), [chapter-04 §4.3.2](docs/tcc/chapter-04-desenvolvimento-do-artefato.md)).
4. **Stateless agents / Bucket Brigade:** Sub-agents receive structured JSON input, produce structured JSON output, maintain no internal state ([README.md](README.md#L43-L44), agent `disallow_transfer_to_parent=True`).
5. **Draft → Review → Commit pattern:** Each artifact phase follows Interview → Review → Persistence states in the FSM ([orchestrator_agent/fsm/states.py](orchestrator_agent/fsm/states.py#L15-L45)).
6. **Dual-store state management:** Volatile session state (ADK `DatabaseSessionService`) + durable business DB (SQLite via SQLModel) ([main.py](main.py#L103-L137), [architecture_review_issues.md](architecture_review_issues.md) ARCH-003).
7. **Schema-driven I/O contracts:** All agents use Pydantic `input_schema` / `output_schema` enforced by ADK ([all agent.py files](orchestrator_agent/agent_tools/)).
8. **Resilience wrapper:** `SelfHealingAgent` handles ZDR, 429, 5xx, and `ValidationError` retries with orthogonal counters ([orchestrator_agent/agent_tools/utils/resilience.py](orchestrator_agent/agent_tools/utils/resilience.py)).
9. **Deterministic compilation contract:** Spec authority compiler uses SHA-256 hashes for prompt and spec content reproducibility ([orchestrator_agent/agent_tools/spec_authority_compiler_agent/compiler_contract.py](orchestrator_agent/agent_tools/spec_authority_compiler_agent/compiler_contract.py)).
10. **Test isolation:** In-memory SQLite with `StaticPool`, automatic `get_engine()` guard against accidental production DB access during tests ([tests/conftest.py](tests/conftest.py), [agile_sqlmodel.py](agile_sqlmodel.py#L761-L790)).

---

## Architecture Decisions

### 1) Architecture Style

#### Observed

**[Fact]** The system is a **single-process monolith** with internal modular boundaries. All agents, tools, the FSM, and the persistence layer run in a single Python process initiated by [main.py](main.py).

**[Fact]** The internal organization follows a **hub-and-spoke (centralized orchestration)** pattern documented explicitly in [chapter-04 §4.2](docs/tcc/chapter-04-desenvolvimento-do-artefato.md):

> *"A arquitetura segue o padrão de orquestração centralizada (hub-and-spoke): um agente orquestrador conduz a interação com o usuário e delega a geração de artefatos para agentes especializados."*

**[Fact]** Three explicit layers are documented ([chapter-04 §4.2.1](docs/tcc/chapter-04-desenvolvimento-do-artefato.md)):
1. **Orchestration layer** (conversation + FSM)
2. **Specialist layer** (agents/tools)
3. **Persistence layer** (state + audit)

Signals supporting **Modular Monolith**:
- Each agent lives in its own directory with `agent.py`, `tools.py`, `schemes.py`, `instructions.txt` ([orchestrator_agent/agent_tools/](orchestrator_agent/agent_tools/))
- Tools are grouped by domain: `orchestrator_tools.py`, `db_tools.py`, `spec_tools.py`, `story_query_tools.py` ([tools/](tools/))
- Clear boundary enforcement: FSM restricts tool visibility per state; agents use `disallow_transfer_to_parent=True` and `disallow_transfer_to_peers=True`

Signals of **emerging Pipe-and-Filter** characteristics:
- The story pipeline (`StoryDraftAgent → SpecValidatorAgent → StoryRefinerAgent → ConditionalLoopAgent`) operates as a sequential processing pipeline ([architecture_review_issues.md](architecture_review_issues.md) ARCH-007, ARCH-012)
- "Bucket Brigade" pattern: agents are explicitly described as "stateless processors that receive state, apply a diff, and pass it forward" ([README.md](README.md#L43))

#### Recommended

**Modular Monolith with Centralized Orchestration and Pipeline Sub-patterns**

This is the architecture that the codebase already implements. The recommendation is to **formalize and strengthen** the existing boundaries rather than migrate to a different style.

#### Why it fits

- **Team size (1–4 developers):** A monolith is appropriate; microservices would impose disproportionate infrastructure overhead.
- **Research context (TCC):** Reproducibility and local execution are explicit requirements ([chapter-04 §4.5.1](docs/tcc/chapter-04-desenvolvimento-do-artefato.md)). A single-process design with SQLite satisfies this.
- **Deployment model:** `python main.py` is the only entry point. No container orchestration needed.
- **Module boundaries are already enforced** by the FSM's per-state tool restrictions and agent isolation flags.

#### Rejected Alternatives

| Alternative | Rejection Reason |
|---|---|
| **Microservices** | Team of 1–4 cannot maintain distributed infrastructure. No concurrent users. SQLite cannot serve network clients. Overhead vastly exceeds benefit for a research prototype. |
| **Clean Architecture / Hexagonal** | Would require explicit port/adapter interfaces for the LLM provider and persistence layers. Current codebase directly couples tools to `get_engine()` and `LiteLlm`. The refactoring cost is not justified for a prototype, but hexagonal principles could be adopted incrementally (see Evolution section). |
| **Event-Driven Architecture** | No message broker, no event bus, no async event consumers. The FSM + tool-call model is synchronous and sequential by design. Not appropriate for the current scale. |
| **SOA** | As a single-process CLI application, service orientation adds complexity without benefit. |

#### Trade-offs

| Dimension | Assessment |
|---|---|
| Complexity | **Low** — single process, no deployment orchestration |
| Scalability | **Limited** — SQLite, single-user, single-process; adequate for research scope |
| Performance | **Adequate** — LLM latency dominates; internal architecture is not the bottleneck |
| Coupling | **Moderate** — agents are well-isolated; tools directly import `agile_sqlmodel` and `get_engine()` |
| Cohesion | **High** within agent modules; moderate across tools directory |
| Cognitive load | **Moderate** — FSM adds structural clarity but has 24+ states |

---

### 2) Business Logic Modeling

#### Observed

**[Fact]** Business logic is distributed across two categories:

1. **Transaction Script pattern** in tool functions: Each tool (`save_vision_tool`, `save_backlog_tool`, `save_stories_tool`, `save_sprint_plan_tool`) is a standalone function that opens a `Session`, performs CRUD operations, commits, and returns a result dict ([orchestrator_agent/agent_tools/product_vision_tool/tools.py](orchestrator_agent/agent_tools/product_vision_tool/tools.py), [backlog_primer/tools.py](orchestrator_agent/agent_tools/backlog_primer/tools.py), [sprint_planner_tool/tools.py](orchestrator_agent/agent_tools/sprint_planner_tool/tools.py)).

2. **Compiler / Pipeline pattern** for spec authority: The `spec_authority_compiler_agent` + `normalizer.py` + `compiler_contract.py` form a deterministic compilation pipeline that transforms spec text into structured invariants ([orchestrator_agent/agent_tools/spec_authority_compiler_agent/](orchestrator_agent/agent_tools/spec_authority_compiler_agent/)).

**[Fact]** Domain models (`Product`, `UserStory`, `Sprint`, etc.) are **anemic data classes** — they carry data but no behavior. All business logic lives in tool functions and agent instructions.

**[Inference]** The combination of Transaction Script tools + anemic SQLModel entities aligns with the **Transaction Script** pattern. This is consistent with the CRUD-centric nature of the persistence operations and the fact that complex business reasoning is delegated to LLM agents rather than encoded in domain objects.

#### Recommended

**Transaction Script** (current) with **Pipeline** sub-pattern for the story generation and spec compilation flows.

#### Why it fits

- Business logic is procedural and tool-driven. Each tool corresponds to a well-defined Scrum ceremony outcome (save vision, save backlog, etc.).
- The LLM agents handle the "intelligent" business reasoning (decomposing requirements, applying INVEST criteria, validating against spec authority). Encoding this in a Rich Domain Model would be redundant.
- Transaction Scripts are easy to test in isolation (each tool is a function with clear inputs/outputs).
- The Pipeline sub-pattern is appropriate for the multi-step story generation flow where data passes through draft → validate → refine stages.

#### Rejected Alternatives

| Alternative | Rejection Reason |
|---|---|
| **Rich Domain Model** | Domain logic is delegated to LLM agents, not encoded in code. SQLModel entities are data carriers. Adding behavior to them would create two sources of truth (model methods vs. LLM instructions). |
| **Domain Model (DDD)** | Overkill for CRUD operations. No complex invariants that justify aggregates, value objects, or domain events in code — the invariants live in compiled spec authority (managed by the LLM compiler). |
| **Event Sourcing** | No requirement for temporal queries beyond audit logs. `WorkflowEvent` and `StoryCompletionLog` already provide append-only audit. Full event sourcing would add complexity without clear research benefit. |
| **Table Module** | Would be appropriate if tool logic were organized by table. Instead, tools are organized by Scrum ceremony/agent responsibility, which better matches the domain. |

#### Trade-offs

| Dimension | Assessment |
|---|---|
| Complexity | **Low** — procedural, easy to follow |
| Testability | **High** — each tool function is unit-testable |
| Duplication risk | **Moderate** — similar session open/query/commit patterns across tools |
| Evolution risk | **Low** — Transaction Script is sufficient unless the system needs complex cross-entity invariants enforced in code |

---

### 3) Data Source & Persistence

#### Observed

**[Fact]** The persistence layer uses **SQLModel (SQLAlchemy ORM) with SQLite** in **Active Record-adjacent** style:

- Models inherit from `SQLModel` with `table=True` and include relationship definitions ([agile_sqlmodel.py](agile_sqlmodel.py)).
- Tool functions open `Session` objects, use `select()` queries, and call `session.add()` / `session.commit()` directly ([tools/db_tools.py](tools/db_tools.py), [tools/orchestrator_tools.py](tools/orchestrator_tools.py)).
- There is **no explicit Repository abstraction** — tools directly import models and `get_engine()`.

**[Fact]** Two distinct data stores coexist:
1. **Business DB** (configured by `PROJECT_TCC_DB_URL`, for example `db/spec_authority_dev.db`): Product, spec, story, sprint data via SQLModel. Created by `agile_sqlmodel.create_db_and_tables()`.
2. **Session/Volatile State DB** (configured by `PROJECT_TCC_SESSION_DB_URL`, for example `db/spec_authority_session_dev.db`): ADK's `DatabaseSessionService` stores transient agent session state.

**[Fact]** Schema evolution uses **hand-written idempotent migrations** in [db/migrations.py](db/migrations.py) — `ALTER TABLE ADD COLUMN` only, no `DROP`, no data destructive operations.

**[Fact]** The `get_engine()` function includes a **test safety guard** that raises `RuntimeError` if called during pytest without explicit override ([agile_sqlmodel.py](agile_sqlmodel.py#L761-L790)).

**[Inference]** The pattern is best classified as **ORM with inline Unit of Work** (SQLAlchemy's `Session` provides implicit UoW semantics, but there is no explicit UoW abstraction in the codebase).

#### Recommended

**ORM (SQLModel/SQLAlchemy) with Transaction Script consumers** — the current approach.

For medium-term evolution: introduce a **thin Repository layer** to decouple tool functions from direct `get_engine()` / `Session` usage, improving testability and enabling future database backend swaps.

#### Why it fits

- SQLite is explicitly chosen for reproducibility and zero-infrastructure deployment ([chapter-04 §4.5.1](docs/tcc/chapter-04-desenvolvimento-do-artefato.md)).
- SQLModel provides Pydantic integration, aligning with the schema-driven validation philosophy.
- The schema is relational with FK constraints enforced via `PRAGMA foreign_keys=ON` ([agile_sqlmodel.py](agile_sqlmodel.py#L808-L812)).
- 12+ tables with many-to-many link models and versioned specs indicate genuine relational complexity.

#### Rejected Alternatives

| Alternative | Rejection Reason |
|---|---|
| **Pure Active Record** | SQLModel models don't contain persistence methods (no `.save()`, `.delete()`). Logic lives in tool functions. |
| **Data Mapper** | Would require separating domain models from persistence models. Current SQLModel models serve both roles. Over-engineering for prototype scope. |
| **Event Store** | Workflow events are persisted, but the system is not event-sourced. Adding event store semantics would require replay infrastructure not justified by requirements. |
| **Polyglot Persistence** | Single SQLite DB is sufficient. Adding Redis/Mongo/etc. would violate the zero-infrastructure constraint. |
| **Repository Pattern (full)** | Not currently implemented. The direct `get_engine()` + `Session` pattern is simpler and adequate. Recommended as an incremental evolution. |

#### Trade-offs

| Dimension | Assessment |
|---|---|
| Simplicity | **High** — direct ORM usage, no abstraction layers |
| Testability | **Good** — in-memory SQLite with test fixtures; but tools import `get_engine()` directly, requiring monkeypatch |
| Portability | **Low** — SQLite-specific (PRAGMA, file-based); migration to PostgreSQL would require adapter changes |
| Concurrent access | **Not supported** — SQLite + `check_same_thread=False` is single-user; documented as a limitation |
| Schema evolution | **Manual** — idempotent `ALTER TABLE` migrations; no Alembic or formal migration framework |

#### Risks

- **Dual-store consistency gap** (ARCH-003 in [architecture_review_issues.md](architecture_review_issues.md)): Session state and business DB lack transactional boundaries.
- **No formal migration framework:** Hand-written migrations are simple but fragile for complex schema changes.

---

### 4) Presentation & Interface Architecture

#### Observed

**[Fact]** The system is a **CLI (Command Line Interface) application** with Rich Console output:

- User interaction via `console.input()` in an async loop ([main.py](main.py#L543-L560))
- Agent responses streamed to terminal with `console.print()` ([main.py](main.py#L350-L370))
- Tool calls and responses displayed as Rich `Panel` widgets ([main.py](main.py#L188-L228))
- HTML export for read-only snapshots ([tools/export_snapshot.py](tools/export_snapshot.py))

**[Fact]** There is **no web frontend, no REST API, no GraphQL endpoint**. The ADK `Runner` operates in a conversational loop, not as a server.

**[Inference]** The presentation pattern is **Conversational UI / REPL** — user input is natural language, output is agent-generated text and structured tool results.

#### Recommended

**Conversational CLI (REPL) with Rich formatting** — the current approach.

This is the correct presentation architecture for the system's context:

- Single-user research prototype
- LLM-driven conversation is the primary interaction mode
- Rich provides sufficient formatting for tool output, state transitions, and panels

#### Rejected Alternatives

| Alternative | Rejection Reason |
|---|---|
| **Web SPA (React/Vue)** | No web server exists. Adding one would increase deployment complexity without research benefit. |
| **MVC / MVVM** | These patterns assume a GUI with views, controllers, and view-models. The CLI conversational model doesn't fit this paradigm. |
| **BFF (Backend for Frontend)** | No frontend exists. BFF is irrelevant. |
| **Micro-frontends** | Single-user CLI. |
| **ADK Web UI** | ADK provides an optional web UI, but the system uses a custom REPL loop. This is a deliberate choice for full control over FSM state injection. |

#### Trade-offs

| Dimension | Assessment |
|---|---|
| User experience | **Adequate for research** — power-user friendly; not suitable for non-technical users |
| Accessibility | **Low** — CLI only |
| Extensibility | **Medium** — adding a web layer would require extracting agent interaction into a service layer |
| Observability | **Good** — Rich panels + structured logging to file ([main.py](main.py#L48-L71)) |

---

### 5) Supporting & Cross-Cutting Patterns

#### 5a) Finite State Machine (FSM) as Control Flow Governor

**[Fact]** The FSM is explicitly documented and implemented:
- States defined in [orchestrator_agent/fsm/states.py](orchestrator_agent/fsm/states.py) (24+ states across 7 phases)
- State definitions with instructions and tool sets in [orchestrator_agent/fsm/definitions.py](orchestrator_agent/fsm/definitions.py) (698 lines)
- Transition logic in [orchestrator_agent/fsm/controller.py](orchestrator_agent/fsm/controller.py) (202 lines)
- Per-state tool restriction: each `StateDefinition` declares its `tools` list, and the orchestrator injects only those tools into the agent at runtime ([main.py](main.py#L316-L321))

**[Recommendation]** This is a **well-chosen** pattern for controlling LLM behavior. It separates control flow (deterministic FSM) from reasoning (probabilistic LLM), reducing prompt drift and ensuring workflow compliance.

#### 5b) Spec Authority / Compilation Pattern

**[Fact]** The system implements a **custom Compilation pattern** for specification governance:
- `SpecRegistry` stores versioned specs with SHA-256 hashes
- `CompiledSpecAuthority` caches extracted invariants with compiler version and prompt hash
- `SpecAuthorityAcceptance` records explicit accept/reject decisions
- Downstream stories are "pinned" to accepted spec versions via `accepted_spec_version_id`

**[Recommendation]** This is an **innovative and appropriate** pattern for ensuring LLM-generated artifacts maintain traceability to source specifications. It acts as an **Anti-Corruption Layer** between the probabilistic LLM world and the deterministic validation world.

#### 5c) Resilience / Self-Healing Pattern

**[Fact]** `SelfHealingAgent` wraps the orchestrator with orthogonal retry counters:
- `ValidationError`: Pydantic schema failures
- ZDR routing: Privacy-compliant provider unavailable
- Rate Limit (429): Service at capacity (resets provider error counter as "alive" signal)
- Provider Error (5xx): Service unhealthy

**[Recommendation]** Appropriate for unreliable LLM API providers. The orthogonal counter design (a 429 proves service is alive and resets 5xx counter) is well-reasoned.

**[Risk]** As noted in ARCH-011 and ARCH-012, retry scope overlaps with `ConditionalLoopAgent` iterations, creating multiplicative call counts. **Mitigation:** Document and enforce a global call budget.

#### 5d) Schema-Driven Validation (Contract-First)

**[Fact]** All agent communication uses Pydantic v2 `BaseModel` with `Annotated` + `Field(description=...)`:
- `input_schema` and `output_schema` on every specialist agent
- `ConfigDict(extra="forbid")` on critical output models
- `model_validator` decorators for cross-field constraints
- Deterministic hash computation for compiler reproducibility

**[Recommendation]** This is a **best practice** that converts LLM output from free-form text into validated structured data. It acts as the system's **type system boundary** between the LLM and the persistence layer.

#### 5e) Tool-Context Caching

**[Fact]** Read-only orchestrator tools use a transparent TTL cache via `ToolContext.state`:
- `projects_last_refreshed_utc` timestamp checked against `CACHE_TTL_MINUTES = 5`
- Cache stores project summaries to reduce DB queries
- `force_refresh` parameter available for manual invalidation

**[Recommendation]** Appropriate for reducing latency in conversational turns. The TTL approach is simple and effective.

#### 5f) Audit Trail / Observability

**[Fact]** Multiple audit mechanisms exist:
- `WorkflowEvent` table for TCC metrics (cycle time, lead time, planning effort)
- `StoryCompletionLog` for story status change audit
- `validation_evidence` JSON field on `UserStory` for spec validation audit
- Structured logging to timestamped files in `logs/`

**[Recommendation]** Adequate for research evaluation. For production, would need centralized log aggregation.

#### Rejected Cross-Cutting Alternatives

| Alternative | Rejection Reason |
|---|---|
| **CQRS** | Read and write models are the same SQLModel entities. No benefit from separation at current scale. Could be adopted if read-heavy dashboards are added. |
| **Saga Pattern** | No distributed transactions. The dual-store issue (ARCH-003) is real but mitigated by synchronous SQLite access. Saga would over-engineer the solution. |
| **Outbox Pattern** | No event publishing to external systems. |
| **Identity Map** | SQLAlchemy `Session` provides identity map internally. No need for explicit implementation. |

---

## Architectural Tensions & Risks

### Critical Tensions (Highest Risk First)

#### T1 — Dual-Store Consistency Gap (ARCH-003)

**Intent:** Session state and business DB should reflect the same reality.  
**Implementation:** Two independent SQLite stores with no transactional boundary.  
**Evidence:** [main.py](main.py#L420-L460) writes to session state; [tools/*.py](tools/) write to business DB. A failed session update after a successful tool commit creates divergence.  
**Risk level:** **High** — can cause duplicate tool invocations or lost acknowledgments.  
**Mitigation:** The FSM state is now persisted with `force=True` ([main.py](main.py#L406)), reducing the most critical case. Full mitigation requires either a single-store consolidation or a reconciliation mechanism.

#### T2 — Retry Scope Overlap (ARCH-011, ARCH-012)

**Intent:** Resilient LLM interactions.  
**Implementation:** `SelfHealingAgent` retries + `ConditionalLoopAgent` iterations = multiplicative calls.  
**Evidence:** Up to `3 retries × 4 iterations × 3 agents = 36+ LLM calls` for a single story in worst case.  
**Risk level:** **High** — cost and latency amplification.  
**Mitigation:** Implement a global call budget counter that caps total LLM invocations per user turn.

#### T3 — Non-Idempotent Tool Retries (ARCH-011)

**Intent:** ZDR/rate-limit retries should be transparent.  
**Implementation:** `SelfHealingAgent` retries the entire agent turn. If tools have already committed side effects before the LLM call fails, retried turns may produce duplicate writes.  
**Evidence:** `save_backlog_tool` checks for duplicates by title ([backlog_primer/tools.py](orchestrator_agent/agent_tools/backlog_primer/tools.py#L89-L94)), but other save tools may not.  
**Risk level:** **Medium** — partially mitigated by duplicate checks in some tools.  
**Mitigation:** Ensure all save tools implement idempotency guards.

#### T4 — FSM State Explosion

**Intent:** Each Scrum artifact gets Interview → Review → Persistence states.  
**Implementation:** 24+ states in the FSM, with 698 lines of state definitions.  
**Evidence:** [orchestrator_agent/fsm/states.py](orchestrator_agent/fsm/states.py), [orchestrator_agent/fsm/definitions.py](orchestrator_agent/fsm/definitions.py).  
**Risk level:** **Medium** — cognitive load for developers maintaining the FSM grows with each new artifact type.  
**Mitigation:** Consider extracting the Interview → Review → Persistence pattern into a reusable template that generates state definitions programmatically.

#### T5 — Validation Gap in Vision/Roadmap Save (ARCH-008)

**Intent:** Draft → Review → Commit should ensure human confirmation.  
**Implementation:** The "review" state relies on LLM interpretation of user confirmation, not a deterministic gate.  
**Evidence:** Unlike the story pipeline (which has `AuthorityGate`), vision and roadmap saves are protected only by FSM state + LLM instruction.  
**Risk level:** **Low-Medium** — the FSM state restriction prevents wrong-phase saves, but within the review state, premature persistence is possible.

### Accidental Architecture

1. **Legacy `engine` module-level variable:** A non-guarded `engine = create_engine(...)` exists at module level alongside the safer `get_engine()` function ([agile_sqlmodel.py](agile_sqlmodel.py#L799-L804)). The `export_snapshot.py` imports this legacy variable directly.
2. **Configuration sprawl risk:** database locations must remain env-driven (`PROJECT_TCC_DB_URL`, `PROJECT_TCC_SESSION_DB_URL`) to avoid reintroducing confusing legacy filenames or split-brain local setups.
3. **`PERSIST_LLM_OUTPUT` flag** (ARCH-004) creates two fundamentally different runtime behaviors controlled by a hidden environment variable.

---

## Evolution & Refactoring Paths

### Short-Term Improvements (1–4 weeks)

| # | Action | Justification | Signal to Act |
|---|---|---|---|
| S1 | **Enforce idempotency in all save tools** | Prevent duplicate writes on retry (ARCH-011) | Any duplicate record in production DB |
| S2 | **Remove legacy module-level `engine`** | Consolidate to `get_engine()` for test safety | Any test accidentally hitting production DB |
| S3 | **Standardize DB file naming** | `business.db` and `session.db` instead of current names | Developer confusion |
| S4 | **Add global LLM call budget** | Cap total calls per user turn to prevent cost runaway (T2) | Any unexpected API bill spike |
| S5 | **Extract FSM Interview→Review→Persist template** | Reduce duplication in state definitions | Adding a new artifact type to the pipeline |

### Medium-Term Restructuring (1–3 months)

| # | Action | Justification | Signal to Act |
|---|---|---|---|
| M1 | **Introduce thin Repository layer** for persistence | Decouple tools from `get_engine()` / `Session` direct usage; improve testability | Need to support multiple DB backends or mock persistence in unit tests without monkeypatch |
| M2 | **Consolidate dual-store into single-store** | Eliminate session/business DB consistency gap (T1) | Recurring "state divergence" bugs |
| M3 | **Add Alembic for schema migrations** | Replace hand-written migrations with proper versioned migrations | Schema changes becoming more frequent or complex |
| M4 | **Implement deterministic review gate for Vision/Roadmap** | Match the spec authority's `AuthorityGate` pattern for all artifact saves | Users report premature saves |
| M5 | **Add structured observability** | OpenTelemetry traces for agent calls, tool durations, LLM token usage | Need to optimize costs or debug latency |

### Long-Term Architectural Evolution (3–12+ months)

| # | Action | Justification | Signal to Act |
|---|---|---|---|
| L1 | **Extract agent orchestration as a service** | Enable web UI or API access without rewriting business logic | Multiple access channels needed (web, API, CLI) |
| L2 | **Adopt Hexagonal Architecture boundaries** | Formalize ports (LLM provider, persistence, UI) and adapters; enable provider swaps | OpenRouter becomes unreliable; need to swap to direct API |
| L3 | **Consider PostgreSQL migration** | Multi-user support, concurrent access, better tooling | Team size exceeds 4; deployment moves to shared server |
| L4 | **Evaluate CQRS for read-heavy analytics** | If dashboards or reporting are added, separate read models from write models | Analytics dashboard requirement |
| L5 | **Consider event-driven extensions** | If real-time notifications or async processing needed | Cross-team collaboration features |

---

## Final Consistency Check

### Cross-Layer Alignment

| Layer | Pattern | Aligned? |
|---|---|---|
| **Architecture Style** | Modular Monolith + Hub-and-Spoke Orchestration | ✅ Documented intent matches implementation |
| **Business Logic** | Transaction Script + Pipeline | ✅ Tool functions are procedural; pipeline agents are sequential |
| **Persistence** | ORM (SQLModel) with direct Session usage | ✅ Matches Transaction Script consumers |
| **Presentation** | Conversational CLI (Rich REPL) | ✅ Single-user research prototype |
| **Cross-cutting** | FSM governance + Schema validation + Resilience wrapper | ✅ Well-integrated; FSM drives tool injection at runtime |

**Overall alignment: High.** The system's architectural intent (documented in chapter-04 and README) closely matches its implementation. The primary tensions are operational (dual-store, retry scoping) rather than structural.

### Known Architectural Debt

| ID | Debt | Impact | Priority |
|---|---|---|---|
| D1 | Dual-store consistency gap | State divergence risk | **High** |
| D2 | Retry scope multiplication | Cost/latency risk | **High** |
| D3 | Non-idempotent saves | Data duplication risk | **Medium** |
| D4 | Legacy module-level engine | Test safety bypass | **Medium** |
| D5 | Hand-written migrations | Schema evolution fragility | **Low** |
| D6 | `PERSIST_LLM_OUTPUT` behavioral bifurcation | Hidden runtime variation | **Low** |
| D7 | No formal API layer | Cannot add UI without refactor | **Low** (research scope) |

### Non-Negotiable Boundaries to Enforce Going Forward

1. **FSM Tool Restriction:** Every state MUST define its complete tool set. No base-tool merge. This is the system's primary safety mechanism against uncontrolled agent behavior.

2. **Schema-Driven I/O:** Every new agent MUST use `input_schema` / `output_schema` with Pydantic v2 `BaseModel`. No free-form string exchange between agents.

3. **Spec Authority Chain:** Every persisted story MUST be traceable to an accepted spec version via `accepted_spec_version_id`. Stories without this link are audit-incomplete.

4. **Test Safety Guard:** `get_engine()` MUST raise during pytest unless explicitly overridden. No new code should use the legacy module-level `engine` variable.

5. **Deterministic Compilation Contract:** The `compute_prompt_hash()` and `compute_spec_hash()` functions MUST be used for all spec authority operations. Prompt changes MUST produce different hashes.

6. **Single Responsibility for Agents:** The orchestrator MUST NOT generate content. All content creation MUST flow through specialist sub-agents. This boundary is the system's most important architectural invariant.

---

*Report generated by static analysis of the `project_tcc` repository. All citations refer to files and documentation present in the codebase as of the analysis date.*
