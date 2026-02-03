---

## Architecture Review Report

---

### ARCH-001
**Title:** Duplicate STATE 20 identifier creates ambiguous control-flow routing  
**Category:** Control Flow  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_lifecycle.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - Node `S20a["STATE 20: View Story Details\n(get_story_details)"]`
  - Node `S20b["STATE 20: Spec Compile Mode\n(compile_spec_authority_for_version)"]`
  - Node `AmbigNote["NOTE: STATE 20 defined twice\n(ambiguous id in instructions)"]`
- In scrum_agentic_system_lifecycle.mmd:
  - Node `Ambig{{Ambiguous STATE 20 in instructions}}`
  - Dashed edges from `Ambig` to both `StoryDetails` and `SpecAuthority`

**Why this is an issue:**  
The orchestrator agent's instruction-driven state machine uses state identifiers to determine routing. When the same identifier (`STATE 20`) is assigned to two semantically distinct behaviors (viewing story details vs. compiling spec authority), the LLM-based routing cannot deterministically distinguish which target behavior is intended. The resolution depends entirely on non-diagrammed heuristics or prompt context, making control-flow non-deterministic. Under ambiguous user input, the agent may invoke `get_story_details` when `compile_spec_authority_for_version` was expected, or vice versa.

**Impact:**  
- Non-deterministic execution path selection
- Potential invocation of unintended tool chains
- User confusion when system behavior does not match intent
- Inability to reason about system behavior from state identifier alone

**Confidence:** High

---

### ARCH-002
**Title:** System-trigger loop lacks explicit termination guard  
**Category:** Control Flow  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_turn_sequence.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - `SysTriggerLoop["evaluate_workflow_triggers() loop"]`
  - Transition: `TriggerDecision -->|Yes| RunSysTurn --> SysTriggerLoop`
- In scrum_agentic_system_turn_sequence.mmd:
  - `loop evaluate_workflow_triggers` with `alt system_instruction returned` → `Turn->>...` → loops back

**Why this is an issue:**  
The system-trigger loop re-evaluates triggers after each system-triggered turn and can invoke another system turn if a new trigger condition becomes true. If a system turn's tool execution produces state changes that satisfy another trigger (or the same trigger again due to incomplete state mutation), the loop may continue indefinitely. There is no explicit iteration counter, timeout, or "triggers already fired this cycle" guard visible in the diagrams.

**Impact:**  
- Potential infinite loop if trigger conditions oscillate or persist across turns
- Resource exhaustion (API calls, database writes)
- User-visible hang or timeout
- Difficulty debugging runaway system behavior

**Confidence:** Medium (the diagrams do not show an explicit guard; presence of one in code cannot be confirmed from diagrams alone)

---

### ARCH-003
**Title:** Session state vs. Business DB dual-write creates potential consistency gap  
**Category:** State  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_turn_sequence.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - `UpdateState["update_state_in_db()\n(vision_components / roadmap_draft / sprint_plan)"]` → `StateDB[("SQLite sessions state")]`
  - `SaveVisionTool --> BusinessDB`, `SaveRoadmapTool --> BusinessDB`, `SaveValidatedStories --> BusinessDB`, etc.
  - `StateDB -.-> SessionDB`
- In scrum_agentic_system_turn_sequence.mmd:
  - `alt PERSIST_LLM_OUTPUT enabled AND data_to_save has known keys` → `Turn->>StateDB: update_state_in_db(partial_update)`
  - Separate tool calls write to BusinessDB

**Why this is an issue:**  
State is persisted in two distinct stores: the `sessions.state` column (session-scoped, transient) and the Business DB (durable domain entities). The diagrams show that session state is updated via `update_state_in_db` based on the `PERSIST_LLM_OUTPUT` flag and recognized keys, while business data is persisted through explicit tool invocations (e.g., `save_vision_tool`, `save_roadmap_tool`). There is no diagrammed transactional boundary encompassing both writes. If a tool successfully writes to Business DB but the subsequent session-state update fails (or vice versa), the two stores diverge. On the next turn, the system may reason from stale or inconsistent session state while the business database reflects a different reality.

**Impact:**  
- Inconsistent state leading to incorrect routing or duplicate work
- "Lost" acknowledgment of completed actions
- Re-execution of tools on data already persisted
- Difficulty recovering correct state after partial failure

**Confidence:** High

---

### ARCH-004
**Title:** `PERSIST_LLM_OUTPUT` flag gates state persistence conditionally, creating hidden behavior variation  
**Category:** State  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_turn_sequence.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - `PersistDecision{"PERSIST_LLM_OUTPUT == 1?"}` with branches `Yes` → `UpdateState`, `No` → direct to `StateDB`
- In scrum_agentic_system_turn_sequence.mmd:
  - `alt PERSIST_LLM_OUTPUT enabled AND data_to_save has known keys` vs. `else persistence disabled or no recognized keys` → skip

**Why this is an issue:**  
The `PERSIST_LLM_OUTPUT` flag controls whether extracted data from the agent turn is written to session state. When disabled, the system continues operating but session state is not updated. This creates two fundamentally different runtime behaviors governed by a configuration flag not reflected in the instruction-driven state machine. Downstream logic (including system triggers that read from SessionDB) may behave differently depending on this flag, yet the orchestrator instructions and agent routing do not account for the persistence mode. The variation is hidden from the state-machine abstraction.

**Impact:**  
- Non-obvious behavioral divergence between environments with different flag values
- System triggers may never fire if dependent state keys are never persisted
- Difficult to reproduce issues across environments
- Testing coverage may miss the "persistence disabled" path

**Confidence:** High

---

### ARCH-005
**Title:** System triggers read session state written by prior turn without synchronization guarantee  
**Category:** State  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_turn_sequence.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - `SessionDB -.-> HasBacklog`, `SessionDB -.-> PlanConfirmed`
  - `TriggerBacklog --> RunSysTurn`, `TriggerPlan --> RunSysTurn`
- In scrum_agentic_system_turn_sequence.mmd:
  - `Main->>StateDB: get_current_state()` before `evaluate_workflow_triggers(state)`

**Why this is an issue:**  
System triggers are evaluated by reading from StateDB immediately after the user turn completes. The preceding turn may have updated session state via `update_state_in_db`. The diagrams do not show any transactional commit boundary or read-after-write consistency guarantee between the state update and the subsequent trigger read. In a scenario where the write is asynchronous, buffered, or fails silently, the trigger evaluation may operate on stale state. Additionally, if the agent turn produced an LLM response without tool calls (and thus no recognized keys), no state update occurs, yet triggers still evaluate against potentially outdated state.

**Impact:**  
- Triggers may fire prematurely or not at all based on stale reads
- Race conditions in high-throughput or concurrent scenarios (not shown but not precluded)
- Difficulty to reason about trigger timing guarantees

**Confidence:** Medium (synchronous SQLite access may mitigate, but diagrams do not confirm)

---

### ARCH-006
**Title:** Orchestrator agent owns both routing logic and tool invocation, creating overloaded responsibility  
**Category:** Orchestration  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `RootAgent["root_agent (Agent)\nmodel=LiteLlm"]`
- `RootAgent --> StateMachine` (all 21 states)
- `RootAgent --> VisionRoadmapAgents`, `RootAgent --> Tools`
- Transitions from states S1–S21 to various tools and sub-agents

**Why this is an issue:**  
The `root_agent` is responsible for interpreting user intent, determining the current macro phase, selecting the appropriate state, invoking sub-agents or tools, and returning results. This conflation of routing (state-machine transitions) and execution (tool/agent invocation) within a single LLM-based agent means that any misinterpretation of user intent can cascade into incorrect tool calls. There is no separation between a "router" that decides which workflow to enter and an "executor" that carries out the workflow. All decision-making is entangled in one prompt context.

**Impact:**  
- Single point of failure for all routing decisions
- Prompt complexity increases with each new state, raising misrouting probability
- Difficult to test routing logic independently of tool execution
- Changes to one workflow may inadvertently affect others via prompt drift

**Confidence:** High

---

### ARCH-007
**Title:** Story pipeline loop termination depends on LLM-generated `refinement_result.is_valid` without hard iteration cap enforcement at sequence level  
**Category:** Orchestration  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `LoopAgent["ConditionalLoopAgent\nmax_iterations=4\nexit when refinement_result.is_valid"]`
- `LoopAgent --> SeqPipeline` → `StoryDraftAgent` → `SpecValidatorAgent` → `StoryRefinerAgent`

**Why this is an issue:**  
The `ConditionalLoopAgent` has a `max_iterations=4` parameter and an exit condition `refinement_result.is_valid`. However, the exit condition is evaluated based on LLM-generated output from `StoryRefinerAgent`. If the refiner agent consistently produces malformed or unparseable output (e.g., failing schema validation), the loop may not recognize `is_valid=True` and will iterate until `max_iterations` is reached. This is acceptable if schema validation reliably rejects bad output, but the diagram also shows `SelfHeal["SelfHealingAgent\n(retry on ValidationError or ZDR)"]` which implies retries occur within each iteration. The interaction between inner retries and outer loop iterations is not clearly bounded in the diagram.

**Impact:**  
- Potentially excessive LLM calls if inner retries compound with outer iterations
- Unpredictable latency for story pipeline execution
- Cost amplification under adversarial or edge-case inputs

**Confidence:** Medium (max_iterations provides a hard cap, but retry interaction is unclear)

---

### ARCH-008
**Title:** Vision and Roadmap agents produce outputs consumed by save tools without intermediate validation gate  
**Category:** Control Flow  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `S1 --> VisionAgent`, `S2 --> VisionAgent`, `S3 --> SaveVisionTool`
- `S5 --> RoadmapAgent`, `S6 --> RoadmapAgent`, `S7 --> SaveRoadmapTool`
- `VisionAgent --> SaveVisionTool`, `RoadmapAgent --> SaveRoadmapTool`

**Why this is an issue:**  
The flow from `VisionAgent` to `SaveVisionTool` and from `RoadmapAgent` to `SaveRoadmapTool` does not show an explicit validation or review gate enforced by deterministic logic. States S2 ("Vision Review") and S6 ("Roadmap Review") are instruction-driven, meaning the LLM decides whether the user has confirmed. If the LLM misinterprets user intent or hallucinates confirmation, the save tool may be invoked on unreviewed or incorrect data. There is no deterministic guard (analogous to `AuthorityGate` in the story pipeline) between the draft and save steps.

**Impact:**  
- Premature persistence of incorrect vision or roadmap data
- User may not realize data was saved without explicit confirmation
- Recovery requires manual database correction

**Confidence:** Medium (review states exist but are LLM-interpreted, not deterministically enforced)

---

### ARCH-009
**Title:** `ensure_accepted_spec_authority` invoked conditionally in story pipeline but also invoked unconditionally in spec update flow  
**Category:** Consistency  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- In Story Pipeline:
  - `AuthorityGate["ensure_accepted_spec_authority\n(if spec_version_id missing)"]`
  - `AuthorityGate --> AuthoritySetup`
  - `AuthorityGate --> SpecAuthority`
- In Spec Authority Compilation:
  - `EnsureAccepted["ensure_spec_authority_accepted (auto)"]`
  - `UpdateSpec --> EnsureAccepted`

**Why this is an issue:**  
The `ensure_accepted_spec_authority` function appears in two contexts with different invocation semantics. In the story pipeline, it is conditionally invoked ("if spec_version_id missing"), acting as a fallback. In the spec update flow, it is invoked unconditionally after `UpdateSpec`. This asymmetry means that the story pipeline may proceed without an accepted authority if one was previously resolved, while the spec update flow always ensures acceptance. If the spec update flow's acceptance overwrites or modifies the authority state, subsequent story pipeline runs may operate against a different authority than expected without re-validation.

**Impact:**  
- Stories generated before and after a spec update may reference different authority versions without explicit versioning
- Potential for subtle inconsistencies in alignment validation
- Difficulty auditing which authority version governed each story

**Confidence:** Medium (behavior depends on implementation details not fully visible in diagrams)

---

### ARCH-010
**Title:** Lifecycle diagram shows linear phase transitions, but full diagram reveals re-entrant paths  
**Category:** Lifecycle  
**Diagrams involved:** scrum_agentic_system_lifecycle.mmd, scrum_agentic_system_full.mmd  
**Evidence:**
- In scrum_agentic_system_lifecycle.mmd:
  - `Vision --> Routing`, `Roadmap --> Routing`, `Stories --> Routing`, `Sprint --> Routing`, etc.
  - Appears as a hub-and-spoke model with `Routing` as central dispatcher
- In scrum_agentic_system_full.mmd:
  - `S4 --> LoadSpecFile --> SessionDB`
  - `S4 --> SaveSpec --> BusinessDB`
  - `S4 --> SelectProject --> BusinessDB`
  - Routing state S4 can invoke multiple tools that mutate state

**Why this is an issue:**  
The lifecycle diagram presents routing as a simple dispatch point that directs flow into macro phases (Vision, Roadmap, Stories, Sprint, SpecAuthority). However, the full diagram reveals that the Routing state (S4) can invoke stateful tools (`LoadSpecFile`, `SaveSpec`, `SelectProject`) that read from and write to both session and business databases. This means that the "Routing" phase is not merely a dispatcher but can itself mutate system state before delegating to a macro phase. The lifecycle abstraction hides this complexity, making it difficult to reason about what state changes may occur during "routing."

**Impact:**  
- Lifecycle diagram provides false simplicity
- Architects reasoning from lifecycle diagram may miss state mutations in routing
- Increased risk of unintended side effects during project selection

**Confidence:** High

---

### ARCH-011
**Title:** ZDR retry loop wraps entire turn but tool side effects may have already occurred  
**Category:** Control Flow  
**Diagrams involved:** scrum_agentic_system_full.mmd, scrum_agentic_system_turn_sequence.mmd  
**Evidence:**
- In scrum_agentic_system_full.mmd:
  - `ZdrRetry{"OpenRouter privacy routing error?"}` → `Backoff["Retry w/ backoff (ZDR_MAX_RETRIES)"]` → `RunTurn`
- In scrum_agentic_system_turn_sequence.mmd:
  - `loop ZDR retry (max ZDR_MAX_RETRIES)` containing `Main->>Turn: run_agent_turn(user_input)` and all downstream steps

**Why this is an issue:**  
The ZDR retry logic retries the entire `run_agent_turn` invocation. However, before the ZDR error is raised (presumably during LLM inference via `Runner.run_async`), tool calls may have already executed and committed to the database. The diagrams show `Agent->>Tools: tool call(s)` occurring before `Runner-->>Turn: events stream`. If a tool writes to BusinessDB and then the LLM inference fails with a ZDR error during response generation, the retry will re-execute the turn from the beginning. This can result in duplicate tool invocations or inconsistent state if tools are not idempotent.

**Impact:**  
- Duplicate writes to database on retry
- Potential for corrupted or duplicated business entities
- Non-idempotent tools may cause data integrity issues

**Confidence:** High (unless all tools are confirmed idempotent, which diagrams do not show)

---

### ARCH-012
**Title:** `SelfHealingAgent` retry scope overlaps with `ConditionalLoopAgent` iteration scope  
**Category:** Orchestration  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `LoopAgent["ConditionalLoopAgent\nmax_iterations=4\nexit when refinement_result.is_valid"]`
- `SeqPipeline -.-> SelfHeal`
- `SelfHeal["SelfHealingAgent\n(retry on ValidationError or ZDR)"]`

**Why this is an issue:**  
The `SelfHealingAgent` retries individual agent executions on `ValidationError` or ZDR errors. The `ConditionalLoopAgent` iterates the entire sequential pipeline up to 4 times. If a `ValidationError` triggers `SelfHealingAgent` retries within a single loop iteration, and those retries exhaust without success, the outer loop increments and retries the entire sequence again. The total number of LLM calls is multiplicative (inner retries × outer iterations), but the diagrams do not specify the `SelfHealingAgent`'s retry limit. This creates an unclear upper bound on execution cost and latency.

**Impact:**  
- Unpredictable and potentially excessive LLM call count
- Cost and latency amplification under persistent validation failures
- Difficulty setting appropriate timeouts or budgets

**Confidence:** Medium (depends on `SelfHealingAgent` configuration not shown in diagrams)

---

### ARCH-013
**Title:** Alignment rejection terminates early but no explicit state cleanup is shown  
**Category:** State  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `AlignCheck{"feature aligned to forbidden capabilities?"}` → `|No| RejectFeature["Return rejection response"]`
- `AlignCheck --> |Yes| InitState --> RunnerSetup`

**Why this is an issue:**  
When a feature fails alignment validation (i.e., it aligns to forbidden capabilities), the pipeline returns a rejection response. However, the diagrams do not show any state cleanup or recording of the rejection. If the story pipeline was invoked via a system trigger or as part of a batch operation, the rejection may not be persisted, and subsequent trigger evaluations may attempt to re-process the same feature. Without explicit rejection tracking, the system may repeatedly attempt to generate stories for a forbidden feature.

**Impact:**  
- Potential infinite retry of rejected features
- Wasted LLM calls on features that will always fail
- No audit trail of alignment rejections

**Confidence:** Medium (diagram shows return but not persistence or flag-setting)

---

### ARCH-014
**Title:** Multiple entry points into story pipeline without unified precondition validation  
**Category:** Control Flow  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `S8 --> QueryFeatures`, `S9 --> ProcessSingleStory`, `S10 --> SaveValidatedStories`
- `ProcessSingleStory --> StoryPipeline`
- `AuthorityGate["ensure_accepted_spec_authority\n(if spec_version_id missing)"]`

**Why this is an issue:**  
The story pipeline can be entered via State 9 (`ProcessSingleStory`) after State 8 (`query_features_for_stories`). However, the diagrams also show direct transitions from the orchestrator to various states. If a user or system trigger invokes `ProcessSingleStory` directly (bypassing State 8), the feature data may not have been queried or validated for completeness. The `AuthorityGate` handles missing `spec_version_id`, but there is no diagrammed guard for other preconditions (e.g., feature existence, product context). Multiple entry points without unified precondition validation create risk of partial or invalid inputs reaching the pipeline.

**Impact:**  
- Runtime errors or malformed story output if preconditions are not met
- Difficulty enforcing consistent pipeline entry semantics
- Increased defensive coding burden in pipeline implementation

**Confidence:** Medium (diagram shows one entry path clearly but does not preclude others)

---

### ARCH-015
**Title:** `pending_validated_stories` state key creates implicit coupling between pipeline and save tool  
**Category:** State  
**Diagrams involved:** scrum_agentic_system_full.mmd  
**Evidence:**
- `PendingState["pending_validated_stories\n(from tool_context.state)"]`
- `PendingState --> SaveLoop`

**Why this is an issue:**  
The `save_validated_stories` tool reads `pending_validated_stories` from `tool_context.state`. This state key must have been set by a prior tool or pipeline step (implied by the story pipeline's `PostProcess`). This creates an implicit contract: the save tool assumes the key exists and contains valid data. If the key is absent, stale, or corrupted (e.g., due to a prior failure or manual state manipulation), the save tool may fail or persist incorrect data. The coupling is implicit because the diagrams do not show an explicit write to `pending_validated_stories`; it is inferred from the read.

**Impact:**  
- Silent failure or incorrect behavior if state key is missing
- Difficulty tracing data flow from pipeline to save tool
- Fragile coupling that may break under refactoring

**Confidence:** Medium (write side not explicitly shown; read side is explicit)

---
