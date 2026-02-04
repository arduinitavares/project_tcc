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
from orchestrator_agent.agent_tools.product_roadmap_agent.tools import save_roadmap_tool
from orchestrator_agent.agent_tools.product_roadmap_agent.agent import root_agent as roadmap_agent
from orchestrator_agent.agent_tools.story_pipeline.tools import process_single_story, save_validated_stories
from orchestrator_agent.agent_tools.sprint_planning.tools import (
    get_backlog_for_planning,
    plan_sprint_tool,
    save_sprint_tool,
)
from orchestrator_agent.agent_tools.sprint_planning.sprint_query_tools import (
    get_sprint_details,
    list_sprints,
)
from orchestrator_agent.agent_tools.sprint_planning.sprint_execution_tools import (
    update_story_status,
    batch_update_story_status,
    modify_sprint_stories,
    complete_sprint,
    complete_story_with_notes,
    update_acceptance_criteria,
    create_follow_up_story,
)

# Wrappers for Agent Tools
product_vision_tool = AgentTool(agent=vision_agent)
product_roadmap_tool = AgentTool(agent=roadmap_agent)

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
You are the Orchestrator Agent.
Your role is to manage project workflow through strict state-driven logic.
You operate concisely, like an efficient Agile Coach.
You never add information, hallucinate, or invent requirements.
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
   - **Ask what to do:** "What would you like to do with this project? (create roadmap, modify vision, view details, create stories, plan sprint)"
   - **STOP and wait for user response**

2. **Explicit Vision Modification:** User says "modify vision", "change vision", "update vision" for the active project
   - Load vision from `state["active_project"]["vision"]`
   - Call: `product_vision_tool(user_raw_text=..., prior_vision_state=<JSON from state>)`

3. **New Project with Specification File:** User says "start new project" AND provides a file path
   - **Extract file path** from user message (look for patterns: `*.md`, `*.txt`, `docs/...`, `C:\...`)
   - **Load content:** Call `load_specification_from_file(file_path=<extracted_path>)` → spec_content
   - **Store in state:** Save to `tool_context.state["pending_spec_content"]` and `state["pending_spec_path"]`
   - **Pass to vision agent:** Call `product_vision_tool(user_raw_text=spec_content, prior_vision_state="NO_HISTORY")`
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
"""

VISION_INTERVIEW_INSTRUCTION = """
# STATE 1 — INTERVIEW MODE (Drafting)

**Behavior:**
1. **Output Lead-in:** *"I am handing this response to the Product Vision Agent…"*
2. **Construct Arguments:**
   - `user_raw_text`: The EXACT new string from the user.
   - `prior_vision_state`: **COPY** the entire JSON string from the *previous* `product_vision_tool` output found in the chat history.
3. **Execute Call:** `product_vision_tool(user_raw_text=..., prior_vision_state=...)`
4. **STOP.**
"""

VISION_REVIEW_INSTRUCTION = """
# STATE 2 — REVIEW MODE (Approval)

**Behavior:**
1. **Display:** Present the generated `product_vision_statement` clearly using Markdown blockquotes or bold text.
2. **Prompt:** Ask explicitly: *"The vision is complete. Would you like to save this to Project Memory, or do you want to make changes?"*
3. **STOP.** (Do NOT call the save tool yet).
"""

VISION_PERSISTENCE_INSTRUCTION = """
# STATE 3 — PERSISTENCE MODE (Saving)

**Behavior:**
1. **Action:** Call `save_vision_tool` with a `vision_input` object containing:
   - `project_name`: Extract from the **prior_vision_state** JSON in your history
   - `product_vision_statement`: Extract from the **prior_vision_state** JSON in your history

2. **Output:** *"Saving project to database..."*
3. **STOP.**

**Handling "Save Confirmation"**
- Once the user confirms, and `save_vision_tool` returns success:
- Ask: *"Project saved. Shall we generate the roadmap?"*
"""

ROADMAP_INTERVIEW_INSTRUCTION = """
# STATE 5 — ROADMAP INTERVIEW MODE

**Behavior:**
1. **Output Lead-in:** *"Working with the Product Roadmap Agent..."*
2. **Construct Arguments:**
   - `product_vision_statement`: The completed vision from active_project or database
   - `prior_roadmap_state`: **COPY** the entire JSON from the *previous* `product_roadmap_tool` output in chat history. If this is the FIRST call, use `"NO_HISTORY"`.
   - `user_input`: The EXACT new string from the user
3. **Execute Call:** `product_roadmap_tool(product_vision_statement=..., prior_roadmap_state=..., user_input=...)`
4. **Display Questions:** Show any `clarifying_questions` as bullet points
5. **STOP.**

**CRITICAL:** You MUST pass the previous roadmap_draft as `prior_roadmap_state` to maintain context across turns. Never lose previous work!
"""

ROADMAP_REVIEW_INSTRUCTION = """
# STATE 6 — ROADMAP REVIEW MODE

**Behavior:**
1. **Display:** Present the `roadmap_draft` clearly, formatted as themes with features and timeframes
2. **Prompt:** Ask: *"The roadmap is complete. Would you like to save this, or make changes?"*
3. **STOP.** (Do NOT call save_roadmap_tool yet)
"""

ROADMAP_PERSISTENCE_INSTRUCTION = """
# STATE 7 — ROADMAP PERSISTENCE MODE

**Behavior:**
1. **Format Roadmap:** Convert the `roadmap_draft` list into a readable text format
2. **Action:** Call `save_roadmap_tool` with a `roadmap_input` object containing:
   - `project_name`: The active project name
   - `roadmap_text`: The formatted readable text version
   - `roadmap_structure`: The RAW `roadmap_draft` array from the agent output (list of theme objects with theme_name, key_features, justification, time_frame)

   **CRITICAL:** You MUST include `roadmap_structure` so Theme/Epic/Feature records are created in the database. Without this, user stories cannot be linked to features later.

3. **Output:** *"Saving roadmap to database..."*
4. **After Success:**
   - Inform user: "Roadmap saved with [N] themes and [M] features created."
   - Suggest: "You can now create user stories for this project."
5. **STOP.**
"""

STORY_SETUP_INSTRUCTION = """
# STATE 8 — USER STORY SETUP MODE

**Pre-Condition Check:**
1. Ensure `active_project` is set. If not, ask user to select a project first.
2. Call `query_features_for_stories` with the product_id to get available features.
3. **CRITICAL:** Store the `features_flat` array in your working memory - you will need this for STATE 9
4. If no features exist, inform user: "No features found. Please create a roadmap hierarchy first."

**Behavior:**
1. **Display Features:** Show the available features grouped by theme/epic.
2. **Ask for Scope:**
   - "Which features should I create stories for? (e.g., 'Now slice', 'all features', specific theme name)"
   - "What user persona should I use? (e.g., 'junior frontend developer preparing for interviews')"
   - "Should I include story point estimates? (yes/no)"
3. **STOP.** Wait for user clarification.
"""

STORY_PIPELINE_INSTRUCTION = """
# STATE 9 — USER STORY PIPELINE MODE (NEW: INVEST-Validated)

**Behavior:**
1. **CRITICAL FIRST STEP - Query Features:**
   - ALWAYS call `query_features_for_stories` with product_id FIRST
   - Extract the `features_flat` array from the response
   - This array contains features WITH theme and epic metadata already attached

2. **Output Lead-in:** *"Starting INVEST-validated story pipeline..."*

3. **For EACH Feature:** Use `process_single_story`.

   **SPEC AUTHORITY GATE (Automatic):**
   - If `spec_version_id` is omitted, the pipeline runs the **Authority Gate** internally.
   - The gate checks for an existing accepted+compiled spec authority.
   - If no accepted authority exists, it uses `spec_content` or `content_ref` to compile one.
   - **Source of spec_content/content_ref:** Use values from `tool_context.state["pending_spec_content"]`
     (set in STATE 1 or STATE 1B) or `state["pending_spec_path"]` (file path from STATE 1).
   - If no accepted authority exists AND no spec_content/content_ref provided, the gate raises an error.

   **CRITICAL:** The `features_flat` array MUST come from `query_features_for_stories()["features_flat"]`.
   Each feature already contains:
   - `feature_id`, `feature_title`
   - `theme_id`, `epic_id` (REQUIRED database IDs - DO NOT OMIT)
   - `theme`, `epic` (REQUIRED - these fields must NEVER be "Unknown")
   - `time_frame`, `theme_justification`, `sibling_features`

   **DO NOT** manually construct feature objects - always use the query result.
   **COPY THE FEATURES EXACTLY** - including theme_id and epic_id fields.

4. **Loop over all selected features** and call `process_single_story` for each.

5. **Display Results:** Show each story with:
   - **Theme and Epic** (to verify metadata propagated correctly)
   - Title and description
   - Acceptance criteria
   - Validation score (0-100)
   - Number of refinement iterations needed
   - Story points (if requested)
   - **Any contract violations** (especially theme/epic metadata issues)

6. **Prompt:** *"Generated [N] INVEST-validated stories (avg validation score: [X]). Would you like to save these to the backlog?"*
7. **STOP.**
"""

STORY_PERSISTENCE_INSTRUCTION = """
# STATE 10 — USER STORY PERSISTENCE MODE

**Behavior:**
1. **IMPORTANT: Do NOT re-run the pipeline!** Use `save_validated_stories` to save the EXACT stories already shown to the user.

   Call `save_validated_stories` with minimal parameters (stories are auto-retrieved from session state).
   The `stories` field is **optional** - if omitted, the tool automatically retrieves them from session state.

2. **Output:** *"Saving [N] INVEST-validated user stories to the Product Backlog..."*
3. **After Success:**
   - List created stories with their IDs and validation scores
   - Show summary: "Average validation score: [X], Stories refined: [Y]"
   - Ask: *"Stories saved. Would you like to create more stories, or proceed to sprint planning?"*
4. **STOP.**
"""

STORY_DETAILS_INSTRUCTION = """
# STATE 20 — VIEW STORY DETAILS MODE

**Actions:**
1. **Parse User Request:**
   - Extract the story ID from user input

2. **Call `get_story_details`:**
   ```json
   {
     "story_id": <int>
   }
   ```

3. **Display Results:**
   - Story ID, title, description, acceptance criteria
   - Status, story points, rank
   - Feature ID, product ID
   - Created/updated timestamps

4. **Prompt:** *"Would you like to update this story, view related feature, or return to backlog?"*
5. **STOP.**
"""

SPRINT_SETUP_INSTRUCTION = """
# STATE 11 — SPRINT PLANNING SETUP MODE

**Pre-Condition Check:**
1. Ensure `active_project` is set. If not, ask user to select a project first.
2. Call `get_backlog_for_planning` with the product_id.
3. If no backlog-ready stories (status=TO_DO), inform user: "No backlog-ready stories. Create and validate stories first."

**Behavior:**
1. **Display Backlog Summary:**
   - Total stories available
   - Total story points
   - Stories grouped by theme/feature

2. **Ask for Sprint Parameters:**
   - "What is the Sprint Goal? (what will the team commit to delivering?)"
   - "Sprint duration? (default: 2 weeks / 14 days)"
   - "Team capacity? (story points or max stories)"
   - "Which stories should be included? (you can say 'top 5', 'all Now slice', or list specific IDs)"

3. **STOP.** Wait for user input.
"""

SPRINT_DRAFT_INSTRUCTION = """
# STATE 12 — SPRINT PLANNING DRAFT MODE

**Behavior:**
1. **Output Lead-in:** *"Drafting sprint plan..."*
2. **Call `plan_sprint_tool`** with sprint parameters.

3. **Display Draft for Review:**
   - Sprint Goal (bold)
   - Date range (start → end)
   - Selected stories with points
   - Total points vs capacity (if provided)
   - Capacity utilization percentage
   - Any warnings (e.g., stories excluded due to wrong status)

4. **Prompt:** *"Sprint draft ready. Review the plan above. Would you like to:*
   - *'Save' - Commit this sprint*
   - *'Change goal' - Modify the sprint goal*
   - *'Add/remove stories' - Adjust story selection*
   - *'Change capacity' - Update capacity estimate"*

5. **STOP.** Wait for user decision.
"""

SPRINT_PERSISTENCE_INSTRUCTION = """
# STATE 13 — SPRINT PERSISTENCE MODE

**Behavior:**
1. **Output Lead-in:** *"Saving sprint to database..."*
2. **Call `save_sprint_tool`** with the finalized parameters.

3. **After Success:**
   - Display: "Sprint created! ID: [X]"
   - Show: Stories linked, total points, tasks created
   - Show: Planning duration (for TCC metrics)
   - Display TLX prompt: "🎯 Consider completing the NASA-TLX questionnaire to measure cognitive load."

4. **Next Steps Prompt:**
   - *"Sprint [ID] is planned. What would you like to do next?*
   - *View sprint details*
   - *Start daily standups*
   - *Create another sprint*
   - *Return to backlog"*

5. **STOP.**
"""

SPRINT_VIEW_INSTRUCTION = """
# STATE 14 — SPRINT VIEW MODE

**Actions:**
1. **Determine Sprint to View:**
   - If user specifies sprint ID: Use that
   - Otherwise: Use most recent active sprint for current project

2. **Call `get_sprint_details`.**

3. **Display Results:**
   - **Sprint Header:** Sprint #[ID] - [Team Name]
   - **Goal:** [sprint goal]
   - **Duration:** [start_date] → [end_date] ([status])
   - **Stories ([count]):**
     - List each story with: ID, title, status, points
     - Show status breakdown: TO_DO (X), IN_PROGRESS (Y), DONE (Z)
   - **Tasks ([count]):** If any tasks exist, show summary
   - **Progress:** [completion_pct]% complete ([completed_points]/[total_points] points)

4. **Next Steps Prompt:**
   - *"What would you like to do?*
   - *Update story status*
   - *Add/remove stories*
   - *View all sprints*
   - *Return to backlog"*

5. **STOP.**
"""

SPRINT_LIST_INSTRUCTION = """
# STATE 15 — SPRINT LIST MODE

**Actions:**
1. **Call `list_sprints`.**

2. **Display Results:**
   - For each sprint, show:
     - Sprint #[ID]: [goal] ([status])
     - Duration: [start_date] → [end_date]
     - Team: [team_name]
     - Stories: [count]

3. **Prompt:** *"Select a sprint ID to view details, or say 'plan sprint' to create a new one."*

4. **STOP.**
"""

SPRINT_UPDATE_STORY_INSTRUCTION = """
# STATE 16 — UPDATE STORY STATUS MODE

**Actions:**
1. **Parse User Request:**
   - Extract story ID(s) and target status
   - Valid statuses: TO_DO, IN_PROGRESS, DONE

2. **For Single Story - Call `update_story_status`.**
3. **For Multiple Stories - Call `batch_update_story_status`.**

4. **Display Result:**
   - Show: "✅ Story #[ID] updated: [old_status] → [new_status]"
   - If batch: Show summary of successes/failures

5. **Prompt:** *"Story updated. Would you like to view sprint progress or update another story?"*
6. **STOP.**
"""

SPRINT_MODIFY_INSTRUCTION = """
# STATE 17 — MODIFY SPRINT STORIES MODE

**Actions:**
1. **Parse User Request:**
   - Determine if adding or removing
   - Extract story ID(s)
   - Identify target sprint (use current active sprint if not specified)

2. **Call `modify_sprint_stories`.**

3. **Display Result:**
   - **Added:** List stories that were added with titles
   - **Removed:** List stories that were removed
   - **Errors:** Show any stories that couldn't be added/removed and why
   - **New Totals:** "[X] stories, [Y] points"

4. **Prompt:** *"Sprint updated. Would you like to view sprint details or make more changes?"*
5. **STOP.**
"""

SPRINT_COMPLETE_INSTRUCTION = """
# STATE 18 — COMPLETE SPRINT MODE

**Actions:**
1. **Confirm Intent:**
   - Show current sprint summary (stories completed vs remaining)
   - Ask: *"Are you sure you want to complete this sprint? [Y stories are not done]"*

2. **If Confirmed - Call `complete_sprint`.**

3. **Display Results:**
   - 🏁 Sprint #[ID] completed!
   - **Metrics:**
     - Stories: [completed]/[total] ([completion_rate]%)
     - Velocity: [completed_points] points
   - **Incomplete Stories:** List any stories not marked DONE (they remain IN_PROGRESS)

4. **Prompt:**
   - *"Sprint complete! Velocity: [X] points.*
   - *Would you like to:*
   - *Plan next sprint*
   - *View incomplete stories*
   - *Return to backlog"*

5. **STOP.**
"""

STORY_COMPLETE_DOC_INSTRUCTION = """
# STATE 19 — COMPLETE STORY WITH DOCUMENTATION MODE

**Actions:**
1. **If completion details not provided, ask:**
   - "Before marking Story #[ID] as done, please provide:"
   - "- What was delivered?"
   - "- Evidence/links (optional)?"
   - "- Any known gaps or follow-ups needed?"

2. **Determine Resolution:**
   - COMPLETED: All original AC met
   - COMPLETED_WITH_CHANGES: AC were updated before completion
   - PARTIAL: Some work descoped, follow-up created
   - WONT_DO: Story cancelled

3. **If user mentions AC changed:**
   - Set ac_was_updated=true
   - Ask for ac_update_reason if not provided

4. **If scope was reduced (PARTIAL):**
   - Ask: "Would you like to create a follow-up story for the descoped work?"
   - If yes, call `create_follow_up_story` first, capture the new story ID

5. **Call `complete_story_with_notes`.**

6. **Display Completion Summary:**
   ✅ Story #[ID] Completed
   📋 Resolution: [resolution]
   📝 Delivered: [summary]
   🔗 Evidence: [links]
   ⚠️ Known Gaps: [gaps]
   ➡️ Follow-ups: [story IDs]

7. **STOP.**
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
            product_vision_tool,
            # Also allow entry to other workflows via triggers
            get_backlog_for_planning, # for sprint check
            list_sprints, # for sprint check
            query_features_for_stories, # for story check
        ],
        allowed_transitions={
            OrchestratorState.VISION_INTERVIEW,
            OrchestratorState.VISION_REVIEW,  # If tool returns complete immediately
            OrchestratorState.ROADMAP_INTERVIEW,
            OrchestratorState.ROADMAP_REVIEW, # If tool returns complete immediately
            OrchestratorState.STORY_SETUP,
            OrchestratorState.SPRINT_SETUP,
            OrchestratorState.SPRINT_VIEW,
            OrchestratorState.SPRINT_LIST,
            OrchestratorState.SPRINT_UPDATE_STORY, # If entering via update tool
            OrchestratorState.SPRINT_COMPLETE, # If entering via complete tool
            OrchestratorState.STORY_DETAILS,
            OrchestratorState.STORY_COMPLETE_DOC, # If entering via complete tool
            OrchestratorState.SPEC_COMPILE,
            OrchestratorState.SPEC_UPDATE
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
        allowed_transitions={OrchestratorState.VISION_INTERVIEW, OrchestratorState.VISION_PERSISTENCE}
    ),
    OrchestratorState.VISION_PERSISTENCE: StateDefinition(
        name=OrchestratorState.VISION_PERSISTENCE,
        phase=OrchestratorPhase.VISION,
        instruction=COMMON_HEADER + """
# STATE 3 — VISION COMPLETE (Post-Save)

**Trigger:** Vision has been saved to database.

**Behavior:**
1. **Confirm:** "Vision saved successfully."
2. **Prompt:** "Would you like to generate the roadmap now?"
3. **STOP.**
""",
        tools=[product_roadmap_tool],
        allowed_transitions={OrchestratorState.ROADMAP_INTERVIEW, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.ROADMAP_INTERVIEW: StateDefinition(
        name=OrchestratorState.ROADMAP_INTERVIEW,
        phase=OrchestratorPhase.ROADMAP,
        instruction=COMMON_HEADER + ROADMAP_INTERVIEW_INSTRUCTION,
        tools=[product_roadmap_tool],
        allowed_transitions={OrchestratorState.ROADMAP_INTERVIEW, OrchestratorState.ROADMAP_REVIEW}
    ),
    OrchestratorState.ROADMAP_REVIEW: StateDefinition(
        name=OrchestratorState.ROADMAP_REVIEW,
        phase=OrchestratorPhase.ROADMAP,
        instruction=COMMON_HEADER + ROADMAP_REVIEW_INSTRUCTION,
        tools=[product_roadmap_tool, save_roadmap_tool], # Allow save or revision
        allowed_transitions={OrchestratorState.ROADMAP_INTERVIEW, OrchestratorState.ROADMAP_PERSISTENCE}
    ),
    OrchestratorState.ROADMAP_PERSISTENCE: StateDefinition(
        name=OrchestratorState.ROADMAP_PERSISTENCE,
        phase=OrchestratorPhase.ROADMAP,
        instruction=COMMON_HEADER + """
# STATE 7 — ROADMAP COMPLETE (Post-Save)

**Trigger:** Roadmap has been saved.

**Behavior:**
1. **Confirm:** "Roadmap saved. Themes and Epics created."
2. **Prompt:** "Would you like to generate user stories for a specific theme?"
3. **STOP.**
""",
        tools=[query_features_for_stories],
        allowed_transitions={OrchestratorState.STORY_SETUP, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.STORY_SETUP: StateDefinition(
        name=OrchestratorState.STORY_SETUP,
        phase=OrchestratorPhase.STORY,
        instruction=COMMON_HEADER + STORY_SETUP_INSTRUCTION,
        tools=[query_features_for_stories, process_single_story], # Allow starting pipeline
        allowed_transitions={OrchestratorState.STORY_PIPELINE, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.STORY_PIPELINE: StateDefinition(
        name=OrchestratorState.STORY_PIPELINE,
        phase=OrchestratorPhase.STORY,
        instruction=COMMON_HEADER + STORY_PIPELINE_INSTRUCTION,
        tools=[query_features_for_stories, process_single_story, save_validated_stories], # Allow saving results
        allowed_transitions={OrchestratorState.STORY_PERSISTENCE, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.STORY_PERSISTENCE: StateDefinition(
        name=OrchestratorState.STORY_PERSISTENCE,
        phase=OrchestratorPhase.STORY,
        instruction=COMMON_HEADER + """
# STATE 10 — STORY COMPLETE (Post-Save)

**Trigger:** Stories saved to backlog.

**Behavior:**
1. **Confirm:** "Stories saved."
2. **Prompt:** "Would you like to plan a sprint or create more stories?"
3. **STOP.**
""",
        tools=[get_backlog_for_planning, query_features_for_stories],
        allowed_transitions={OrchestratorState.SPRINT_SETUP, OrchestratorState.STORY_SETUP, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.STORY_DETAILS: StateDefinition(
        name=OrchestratorState.STORY_DETAILS,
        phase=OrchestratorPhase.STORY,
        instruction=COMMON_HEADER + STORY_DETAILS_INSTRUCTION,
        tools=[get_story_details],
        allowed_transitions={OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_SETUP: StateDefinition(
        name=OrchestratorState.SPRINT_SETUP,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_SETUP_INSTRUCTION,
        tools=[get_backlog_for_planning],
        allowed_transitions={OrchestratorState.SPRINT_DRAFT, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_DRAFT: StateDefinition(
        name=OrchestratorState.SPRINT_DRAFT,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_DRAFT_INSTRUCTION,
        tools=[plan_sprint_tool, save_sprint_tool], # Allow commit
        allowed_transitions={OrchestratorState.SPRINT_PERSISTENCE, OrchestratorState.SPRINT_DRAFT}
    ),
    OrchestratorState.SPRINT_PERSISTENCE: StateDefinition(
        name=OrchestratorState.SPRINT_PERSISTENCE,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + """
# STATE 13 — SPRINT COMPLETE (Post-Save)

**Trigger:** Sprint created.

**Behavior:**
1. **Confirm:** "Sprint #[ID] created."
2. **Prompt:** "Would you like to view the sprint board?"
3. **STOP.**
""",
        tools=[get_sprint_details],
        allowed_transitions={OrchestratorState.SPRINT_VIEW, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_VIEW: StateDefinition(
        name=OrchestratorState.SPRINT_VIEW,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_VIEW_INSTRUCTION,
        # SPRINT_VIEW acts as a hub for sprint management
        tools=[
            get_sprint_details,
            update_story_status,
            batch_update_story_status,
            modify_sprint_stories,
            list_sprints,
            complete_sprint
        ],
        allowed_transitions={
            OrchestratorState.SPRINT_UPDATE_STORY,
            OrchestratorState.SPRINT_MODIFY,
            OrchestratorState.SPRINT_LIST,
            OrchestratorState.SPRINT_COMPLETE,
            OrchestratorState.ROUTING_MODE
        }
    ),
    OrchestratorState.SPRINT_LIST: StateDefinition(
        name=OrchestratorState.SPRINT_LIST,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_LIST_INSTRUCTION,
        tools=[list_sprints, get_sprint_details, get_backlog_for_planning],
        allowed_transitions={OrchestratorState.SPRINT_VIEW, OrchestratorState.SPRINT_SETUP, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_UPDATE_STORY: StateDefinition(
        name=OrchestratorState.SPRINT_UPDATE_STORY,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_UPDATE_STORY_INSTRUCTION,
        tools=[update_story_status, batch_update_story_status, get_sprint_details],
        allowed_transitions={OrchestratorState.SPRINT_VIEW, OrchestratorState.SPRINT_UPDATE_STORY, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_MODIFY: StateDefinition(
        name=OrchestratorState.SPRINT_MODIFY,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_MODIFY_INSTRUCTION,
        tools=[modify_sprint_stories, get_sprint_details],
        allowed_transitions={OrchestratorState.SPRINT_VIEW, OrchestratorState.SPRINT_MODIFY, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.SPRINT_COMPLETE: StateDefinition(
        name=OrchestratorState.SPRINT_COMPLETE,
        phase=OrchestratorPhase.SPRINT,
        instruction=COMMON_HEADER + SPRINT_COMPLETE_INSTRUCTION,
        tools=[complete_sprint],
        allowed_transitions={OrchestratorState.SPRINT_SETUP, OrchestratorState.SPRINT_VIEW, OrchestratorState.ROUTING_MODE}
    ),
    OrchestratorState.STORY_COMPLETE_DOC: StateDefinition(
        name=OrchestratorState.STORY_COMPLETE_DOC,
        phase=OrchestratorPhase.STORY,
        instruction=COMMON_HEADER + STORY_COMPLETE_DOC_INSTRUCTION,
        tools=[complete_story_with_notes, create_follow_up_story, update_acceptance_criteria],
        allowed_transitions={OrchestratorState.SPRINT_VIEW, OrchestratorState.ROUTING_MODE}
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
