from typing import List, Any, Set
from pydantic import BaseModel, Field
from google.adk.tools import AgentTool
from .states import OrchestratorState, OrchestratorPhase

# --- Tool Imports ---
from tools.orchestrator_tools import (
    count_projects,
    list_projects,
    get_project_details,
    get_project_by_name,
    select_project,
    load_specification_from_file,
)
from tools.spec_tools import (
    save_project_specification,
    read_project_specification,
    compile_spec_authority_for_version,
    update_spec_and_compile_authority,
)
from tools.db_tools import get_story_details
from tools.story_query_tools import query_features_for_stories
from orchestrator_agent.agent_tools.product_vision_tool.tools import save_vision_tool
from orchestrator_agent.agent_tools.product_vision_tool.agent import root_agent as vision_agent
from orchestrator_agent.agent_tools.backlog_primer.agent import root_agent as backlog_agent
from orchestrator_agent.agent_tools.backlog_primer.tools import save_backlog_tool
from orchestrator_agent.agent_tools.roadmap_builder.agent import root_agent as roadmap_agent
from orchestrator_agent.agent_tools.roadmap_builder.tools import save_roadmap_tool

# Wrappers for Agent Tools
product_vision_tool = AgentTool(agent=vision_agent)
backlog_primer_tool = AgentTool(agent=backlog_agent)
roadmap_builder_tool = AgentTool(agent=roadmap_agent)

class StateDefinition(BaseModel):
    name: OrchestratorState
    phase: OrchestratorPhase
    instruction: str
    tools: List[Any] = Field(default_factory=list)
    allowed_transitions: Set[OrchestratorState] = Field(default_factory=set)

    class Config:
        arbitrary_types_allowed = True

# --- INSTRUCTIONS ---

COMMON_HEADER = """
You are the Orchestrator Agent — a ROUTER, not a GENERATOR.
Your role is to manage project workflow through strict state-driven logic.
You operate concisely, like an efficient Agile Coach.
You never add information, hallucinate, or invent requirements.

**DELEGATION RULE (ABSOLUTE):**
- You NEVER generate backlog items, user stories, roadmap milestones, or any
  deliverable content directly in your response text.
- ALL content creation MUST go through the designated sub-agent tool for
  the current phase: `backlog_primer_tool` for backlog work,
  `roadmap_builder_tool` for roadmap work, `product_vision_tool` for vision work.
- If the user asks for work that belongs to a DIFFERENT phase, redirect them:
  explain what phase they are in and what the next step is.
- If the user asks for work that has NO available sub-agent (e.g., story
  decomposition, sprint planning), say explicitly: "That capability is not
  yet available. The current workflow supports: Vision → Backlog → Roadmap."
- Your ONLY job is to: (a) route to the correct tool, (b) display tool output,
  (c) ask the user what to do next. NEVER improvise content.
- You MUST NOT offer to "manually draft", "outline", "begin writing", or
  produce ANY deliverable yourself. If no tool exists for the request, the
  answer is: "That capability is not yet available."

**WORKFLOW SEQUENCE (IMMUTABLE):**
Vision → Backlog → Roadmap. These are the ONLY phases. "User stories",
"story decomposition", "sprint planning", and "sprint-ready stories" are
NOT available capabilities — regardless of what the user requests.
"""

ROUTING_INSTRUCTION = """
# ROUTING MODE (State 4)

**Trigger:** Start of conversation, or User changes topic.

**Routing Logic:**
1. **Existing Project Selection:** User references a specific project by ID or name (e.g., "continue with 3", "work on Tinder for Tennis", "let's go from X")
   - **Call:** `select_project(product_id=...)` to set it as the active project in volatile memory
   - **Display the returned project summary:**
     - Project name
     - Vision (if exists)
     - Roadmap status (if exists)
     - Story/theme/epic counts
   - **Ask what to do:** "What would you like to do with this project? (create backlog, modify vision, view details, create stories, plan sprint)"
   - **STOP and wait for user response**

2. **Explicit Vision Modification:** User says "modify vision", "change vision", "update vision" for the active project
   - Load vision from `state["active_project"]["vision"]`
   - Call: `product_vision_tool(user_raw_text=..., specification_content="", prior_vision_state=<JSON from state>)`

3. **New Project with Specification File:** User says "start new project" AND provides a file path
   - **Extract file path** from user message (look for patterns: `*.md`, `*.txt`, `docs/...`, `C:\\...`)
   - **Load content:** Call `load_specification_from_file(file_path=<extracted_path>)` → spec_content
   - **Store in state:** Save to `tool_context.state["pending_spec_content"]` and `state["pending_spec_path"]`
   - **Pass to vision agent:** Call `product_vision_tool(user_raw_text="Analyze this specification.", specification_content=spec_content, prior_vision_state="NO_HISTORY")`
   - When vision is approved and saved:
     a. Call `save_vision_tool(...)` → creates product, returns product_id
     b. Immediately call `save_project_specification(product_id=<new_id>, spec_source="file", content=<file_path>)`
     c. Confirm: "Project and specification saved successfully. Specification loaded from <the file path>."
   - **STOP** and ask what to do next

4. **New Project with Pasted Content:** `"start"`, `"new"`, `"create"`, `"vision"` with no file path mentioned
   - User provides pasted specification text directly in message
   - Call: `product_vision_tool(user_raw_text=<pasted_text>, prior_vision_state="NO_HISTORY")`
   - **Store pasted content:** Save to `tool_context.state["pending_spec_content"] = <pasted_text>`
   - When vision is approved:
     a. Call `save_vision_tool(...)`
     b. Call `save_project_specification(product_id=<new_id>, spec_source="text", content=<pasted_text>)`
     c. System will create backup file in specs/ folder with pattern: <project_name>_<id>_spec.md
     d. Confirm: "Project saved. Specification backed up to specs/ folder."

5. **Status/DB:** `"count"`, `"status"`, `"list"`
   - Call: `count_projects` or `list_projects`.
6. **Backlog Request (Preferred after Vision):** User says "backlog", "product backlog", "initial backlog"
   - If `active_project` exists and has a vision, proceed directly to `backlog_primer_tool`.
   - If vision is missing, ask the user to create or update the vision first.

7. **Roadmap Request (After Backlog):** User says "roadmap", "product roadmap", "milestones"
   - If `active_project` or its vision is missing: return to Vision flow (call `product_vision_tool`).
   - If `tool_context.state["approved_backlog"]` is missing: route to `backlog_primer_tool` first.
   - Otherwise: call `roadmap_builder_tool`.
"""

VISION_INTERVIEW_INSTRUCTION = """
# STATE 1 — INTERVIEW MODE (Drafting)

**Behavior:**
1. **Output Lead-in:** *"I am handing this response to the Product Vision Agent…"*
2. **Construct Arguments:**
   - `user_raw_text`: The EXACT new string from the user.
   - `specification_content`: Use `tool_context.state["pending_spec_content"]` if present; otherwise empty string.
   - `prior_vision_state`: **COPY** the entire JSON string from the *previous* `product_vision_tool` output found in the chat history.
3. **Execute Call:** `product_vision_tool(user_raw_text=..., specification_content=..., prior_vision_state=...)`
4. **STOP.**
"""

VISION_REVIEW_INSTRUCTION = """
# STATE 2 — REVIEW MODE (Approval)

**Behavior:**
1. **Display:** Present the generated `product_vision_statement` clearly using Markdown blockquotes or bold text.
2. **Prompt:** Ask explicitly: *"The vision is complete. Would you like to save this to Project Memory, or do you want to make changes?"*
3. **If the user confirms saving** (e.g., "save", "yes", "confirm"):
   - Call `save_vision_tool` with a `vision_input` object containing:
     - `project_name`: Extract from the latest `product_vision_tool` output in chat history: `updated_components.project_name`
     - `product_vision_statement`: Extract from the latest `product_vision_tool` output: `product_vision_statement`
     - `technical_spec`: If present, copy from `tool_context.state["pending_spec_content"]` (do not invent)
     - `spec_file_path`: If present, copy from `tool_context.state["pending_spec_path"]` (do not invent)
4. **If the user requests changes**: return to State 1 behavior and call `product_vision_tool` again with the updated user input.
5. **STOP.**
"""

VISION_PERSISTENCE_INSTRUCTION = """
# STATE 3 — PERSISTENCE MODE (After Save)

**Behavior:**
1. **Display:** Confirm the save result from `save_vision_tool` (success, project name, product_id).
2. **Prompt:** Ask: *"Project saved. Shall we generate the initial backlog?"*
3. **STOP.**
"""

BACKLOG_INTERVIEW_INSTRUCTION = """
# STATE 23 — BACKLOG INTERVIEW MODE

**Behavior:**
1. **Output Lead-in:** *"Working with the Backlog Primer..."*
2. **Construct Arguments:**
   - `product_vision_statement`: The completed vision from active_project or database
   - `technical_spec`: Use `tool_context.state["pending_spec_content"]` if present; otherwise empty string
   - `compiled_authority`: Use `tool_context.state["compiled_authority_cached"]` if present; otherwise empty string
   - `prior_backlog_state`: **COPY** the entire JSON from the *previous* `backlog_primer_tool` output in chat history. If this is the FIRST call, use "NO_HISTORY".
   - `user_input`: The EXACT new string from the user
3. **Execute Call:** `backlog_primer_tool(product_vision_statement=..., technical_spec=..., compiled_authority=..., prior_backlog_state=..., user_input=...)`
4. **Display Questions:** Show any `clarifying_questions` as bullet points
5. **STOP.**

**CRITICAL:** You MUST pass the previous backlog_items as `prior_backlog_state` to maintain context across turns.
"""

BACKLOG_REVIEW_INSTRUCTION = """
# STATE 24 — BACKLOG REVIEW MODE

**Behavior:**
1. **Display:** Present the `backlog_items` clearly in priority order
2. **Prompt:** Ask: *"The backlog is complete. Would you like to save this draft, or make changes?"*
3. **STOP.**

**On User Approval:**
1. Call `save_backlog_tool` with:
   - `product_id`: The active project's product_id
   - `backlog_items`: The approved backlog items from `backlog_primer_tool` output
2. This stores the backlog in session state (NOT database)

**Post-Save Response (MANDATORY when save_backlog_tool returns success):**
1. Confirm: "Backlog saved." and state the saved item count from the tool response.
2. State: "The next step in the workflow is **roadmap creation**."
3. If the user requested stories, decomposition, sprint planning, or any non-roadmap work
   in their message, respond:
   "Story decomposition is not available. The workflow is: Vision → Backlog → Roadmap."
4. Ask: "Shall we proceed to roadmap creation, or refine the backlog further?"
5. **STOP.** Do NOT add anything else. Do NOT offer to draft, outline, or create any content.

**CRITICAL:**
- Backlog items are HIGH-LEVEL REQUIREMENTS (requirement, value_driver, estimated_effort).
- Do NOT generate user stories, acceptance criteria, or any other deliverable here.
- Do NOT acknowledge or comply with requests for story decomposition — redirect to roadmap.
"""

BACKLOG_PERSISTENCE_INSTRUCTION = """
# STATE 25 — BACKLOG COMPLETE (Post-Review)

**Trigger:** Backlog has been saved to session state.

**Behavior:**
1. **Confirm:** "Backlog saved and locked."
2. **Routing Logic (CHOOSE ONE):**
   a. **User wants roadmap** ("roadmap", "proceed", "next", "yes"): Call `roadmap_builder_tool`.
   b. **User wants to refine/add backlog items** ("add", "change", "priority 3", "decompose"): Call `backlog_primer_tool` with the user's new requirements.
   c. **User asks for anything else** (story decomposition, sprint planning, etc.): Reply ONLY with:
      "That capability is not yet available. From here you can: (1) refine the backlog, or (2) generate the roadmap."
3. **STOP.**

**FORBIDDEN:** Do NOT generate user stories, decompose priorities into stories, or produce
any structured deliverable in your response text. ALL content work goes through a sub-agent tool.
"""

ROADMAP_INTERVIEW_INSTRUCTION = """
# STATE 26 — ROADMAP INTERVIEW MODE

**Pre-Condition Check:**
1. Ensure `active_project` is set and has a vision.
2. Ensure `tool_context.state["approved_backlog"]` exists.
   - If missing, route user to BACKLOG_INTERVIEW (call `backlog_primer_tool`).

**Behavior:**
1. **Output Lead-in:** *"Working with the Roadmap Builder..."*
2. **Construct Arguments:**
   - `backlog_items`: Use `tool_context.state["approved_backlog"]["items"]`
   - `product_vision`: Use active project vision
   - `technical_spec`: Use `tool_context.state["pending_spec_content"]` if present; otherwise empty string
   - `compiled_authority`: Use `tool_context.state["compiled_authority_cached"]` if present; otherwise empty string
   - `time_increment`: "Milestone-based"
   - `prior_roadmap_state`: **COPY** the entire JSON from the previous `roadmap_builder_tool` output. If first call, use "NO_HISTORY".
   - `user_input`: The EXACT new string from the user
3. **Execute Call:** `roadmap_builder_tool(...)`
4. **Display Questions:** Show any `clarifying_questions` as bullet points
5. **STOP.**

**On User Approval (user says "save", "approve", "lock", "baseline" or similar):**
1. If `roadmap_builder_tool` has already produced a complete roadmap in this session,
   call `save_roadmap_tool` with:
   - `product_id`: The active project's product_id
   - `roadmap_data`: The approved output from the latest `roadmap_builder_tool`
2. Confirm the save and state the pipeline is complete.
3. **STOP.**
"""

ROADMAP_REVIEW_INSTRUCTION = """
# STATE 27 — ROADMAP REVIEW MODE

**Behavior:**
1. **Display:** Present `roadmap_releases` in order and show `roadmap_summary`.
2. **Prompt:** Ask: *"The roadmap is complete. Would you like to save it, or make changes?"*
3. **STOP.**

**On User Approval:**
1. Call `save_roadmap_tool` with:
   - `product_id`: The active project's product_id
   - `roadmap_data`: The approved output from the latest `roadmap_builder_tool`
2. Transition to ROADMAP_PERSISTENCE
"""

ROADMAP_PERSISTENCE_INSTRUCTION = """
# STATE 28 — ROADMAP COMPLETE (Post-Save)

**Trigger:** Roadmap saved.

**Behavior:**
1. **Confirm:** "Roadmap saved. The Vision → Backlog → Roadmap pipeline is complete for this project."
2. **Prompt:** "You can now: (1) start a new project, (2) refine this project's vision or backlog, or (3) exit."
3. **STOP.**
"""

SPEC_UPDATE_INSTRUCTION = """
# STATE 21 — IMPLICIT SPEC UPDATE MODE

**Actions:**
1. **Gather Input:**
    - If user provided file path, use as `content_ref`.
    - If user pasted content, use as `spec_content`.
    - If neither provided, ask for file path or pasted content.

2. **Call `update_spec_and_compile_authority`.**

3. **Display Result:**
   - "Spec vN ready. Use this spec_version_id explicitly for story generation/validation."
   - Show summary: compiler version, invariant count, scope themes count.

4. **STOP.**
"""

SPEC_COMPILE_INSTRUCTION = """
# STATE 22 — SPEC COMPILE MODE

**Actions:**
1. **Parse User Request:**
   - Extract `spec_version_id` from the user's message (look for "vN" or "version N")
   - If no version is provided, ask: "Which spec version should I compile?"

2. **Call `compile_spec_authority_for_version`.**

3. **Display Result:**
   - If `cached=true`: "Spec vN already compiled. Using cached authority (ID: X)."
   - If compiled: "Spec vN compiled. Extracted [themes] themes and [invariants] invariants."

4. **STOP.**
"""

# --- REGISTRY ---

STATE_REGISTRY = {
    OrchestratorState.ROUTING_MODE: StateDefinition(
        name=OrchestratorState.ROUTING_MODE,
        phase=OrchestratorPhase.ROUTING,
        instruction=COMMON_HEADER + ROUTING_INSTRUCTION,
        tools=[
            count_projects,
            list_projects,
            select_project,
            get_project_details,
            get_project_by_name,
            load_specification_from_file,
            save_vision_tool,
            save_project_specification,
            read_project_specification,
            compile_spec_authority_for_version,
            update_spec_and_compile_authority,
            product_vision_tool,
            backlog_primer_tool,
            roadmap_builder_tool,
            query_features_for_stories,
            get_story_details,
        ],
        allowed_transitions={
            OrchestratorState.VISION_INTERVIEW,
            OrchestratorState.VISION_REVIEW,
            OrchestratorState.BACKLOG_INTERVIEW,
            OrchestratorState.BACKLOG_REVIEW,
            OrchestratorState.ROADMAP_INTERVIEW,
            OrchestratorState.ROADMAP_REVIEW,
            OrchestratorState.SPEC_COMPILE,
            OrchestratorState.SPEC_UPDATE,
        }
    ),
    OrchestratorState.VISION_INTERVIEW: StateDefinition(
        name=OrchestratorState.VISION_INTERVIEW,
        phase=OrchestratorPhase.VISION,
        instruction=COMMON_HEADER + VISION_INTERVIEW_INSTRUCTION,
        tools=[product_vision_tool],
        allowed_transitions={OrchestratorState.VISION_INTERVIEW, OrchestratorState.VISION_REVIEW}
    ),
    OrchestratorState.VISION_REVIEW: StateDefinition(
        name=OrchestratorState.VISION_REVIEW,
        phase=OrchestratorPhase.VISION,
        instruction=COMMON_HEADER + VISION_REVIEW_INSTRUCTION,
        tools=[product_vision_tool, save_vision_tool], # Allow save or revision
      allowed_transitions={
         OrchestratorState.VISION_INTERVIEW,
         OrchestratorState.VISION_PERSISTENCE,
         OrchestratorState.BACKLOG_INTERVIEW,
         OrchestratorState.BACKLOG_REVIEW,
      }
    ),
    OrchestratorState.VISION_PERSISTENCE: StateDefinition(
        name=OrchestratorState.VISION_PERSISTENCE,
        phase=OrchestratorPhase.VISION,
        instruction=COMMON_HEADER + """
# STATE 3 — VISION COMPLETE (Post-Save)

**Trigger:** Vision has been saved to database.

**Behavior:**
1. **Confirm:** "Vision saved successfully."
2. **Prompt:** "Would you like to generate the backlog now?"
3. **STOP.**
""",
      tools=[backlog_primer_tool],
      allowed_transitions={OrchestratorState.BACKLOG_INTERVIEW, OrchestratorState.ROUTING_MODE}
    ),
   OrchestratorState.BACKLOG_INTERVIEW: StateDefinition(
      name=OrchestratorState.BACKLOG_INTERVIEW,
      phase=OrchestratorPhase.BACKLOG,
      instruction=COMMON_HEADER + BACKLOG_INTERVIEW_INSTRUCTION,
      tools=[backlog_primer_tool],
      allowed_transitions={OrchestratorState.BACKLOG_INTERVIEW, OrchestratorState.BACKLOG_REVIEW}
   ),
   OrchestratorState.BACKLOG_REVIEW: StateDefinition(
      name=OrchestratorState.BACKLOG_REVIEW,
      phase=OrchestratorPhase.BACKLOG,
      instruction=COMMON_HEADER + BACKLOG_REVIEW_INSTRUCTION,
      tools=[backlog_primer_tool, save_backlog_tool],
      allowed_transitions={
         OrchestratorState.BACKLOG_INTERVIEW,
         OrchestratorState.BACKLOG_PERSISTENCE,
      }
   ),
   OrchestratorState.BACKLOG_PERSISTENCE: StateDefinition(
      name=OrchestratorState.BACKLOG_PERSISTENCE,
      phase=OrchestratorPhase.BACKLOG,
      instruction=COMMON_HEADER + BACKLOG_PERSISTENCE_INSTRUCTION,
      tools=[roadmap_builder_tool, backlog_primer_tool],
      allowed_transitions={OrchestratorState.ROADMAP_INTERVIEW, OrchestratorState.ROUTING_MODE, OrchestratorState.BACKLOG_INTERVIEW}
   ),
   OrchestratorState.ROADMAP_INTERVIEW: StateDefinition(
      name=OrchestratorState.ROADMAP_INTERVIEW,
      phase=OrchestratorPhase.ROADMAP,
      instruction=COMMON_HEADER + ROADMAP_INTERVIEW_INSTRUCTION,
      tools=[roadmap_builder_tool, save_roadmap_tool],
      allowed_transitions={OrchestratorState.ROADMAP_INTERVIEW, OrchestratorState.ROADMAP_REVIEW, OrchestratorState.ROADMAP_PERSISTENCE}
   ),
   OrchestratorState.ROADMAP_REVIEW: StateDefinition(
      name=OrchestratorState.ROADMAP_REVIEW,
      phase=OrchestratorPhase.ROADMAP,
      instruction=COMMON_HEADER + ROADMAP_REVIEW_INSTRUCTION,
      tools=[roadmap_builder_tool, save_roadmap_tool],
      allowed_transitions={
         OrchestratorState.ROADMAP_INTERVIEW,
         OrchestratorState.ROADMAP_PERSISTENCE,
      }
   ),
   OrchestratorState.ROADMAP_PERSISTENCE: StateDefinition(
      name=OrchestratorState.ROADMAP_PERSISTENCE,
      phase=OrchestratorPhase.ROADMAP,
      instruction=COMMON_HEADER + ROADMAP_PERSISTENCE_INSTRUCTION,
      tools=[],
      allowed_transitions={OrchestratorState.ROUTING_MODE}
   ),
    OrchestratorState.SPEC_UPDATE: StateDefinition(
        name=OrchestratorState.SPEC_UPDATE,
        phase=OrchestratorPhase.SPEC,
        instruction=COMMON_HEADER + SPEC_UPDATE_INSTRUCTION,
        tools=[update_spec_and_compile_authority],
        allowed_transitions={OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPEC_COMPILE: StateDefinition(
        name=OrchestratorState.SPEC_COMPILE,
        phase=OrchestratorPhase.SPEC,
        instruction=COMMON_HEADER + SPEC_COMPILE_INSTRUCTION,
        tools=[compile_spec_authority_for_version],
        allowed_transitions={OrchestratorState.ROUTING_MODE}
    )
}
