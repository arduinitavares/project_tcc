from typing import Any, Dict, Optional
from .states import OrchestratorState
from .definitions import STATE_REGISTRY, StateDefinition

class FSMController:
    """
    Manages the state transitions of the Orchestrator Agent.
    Determines the next state based on the current state and the last tool executed.
    """

    def __init__(self):
        self.registry = STATE_REGISTRY

    def get_initial_state(self) -> OrchestratorState:
        """Default starting state."""
        return OrchestratorState.ROUTING_MODE

    def get_state_definition(self, state: OrchestratorState) -> StateDefinition:
        """Retrieve definition for a given state."""
        return self.registry.get(state, self.registry[OrchestratorState.ROUTING_MODE])

    def determine_next_state(
        self,
        current_state: OrchestratorState,
        tool_name: Optional[str],
        tool_output: Dict[str, Any],
        user_input: str
    ) -> OrchestratorState:
        """
        Calculates the next state based on the transition logic.
        """
        # Default: Stay in current state
        next_state = current_state

        # --- ROUTING MODE LOGIC (State 4) ---
        if current_state == OrchestratorState.ROUTING_MODE:
            if tool_name == "product_vision_tool":
                # Check completeness to decide Interview vs Review
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.VISION_REVIEW if is_complete else OrchestratorState.VISION_INTERVIEW

            elif tool_name == "backlog_primer_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.BACKLOG_REVIEW if is_complete else OrchestratorState.BACKLOG_INTERVIEW

            elif tool_name == "roadmap_builder_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.ROADMAP_REVIEW if is_complete else OrchestratorState.ROADMAP_INTERVIEW

            elif tool_name == "user_story_writer_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.STORY_REVIEW if is_complete else OrchestratorState.STORY_INTERVIEW

            elif tool_name == "sprint_planner_tool":
                next_state = OrchestratorState.SPRINT_DRAFT

            elif tool_name == "compile_spec_authority_for_version":
                next_state = OrchestratorState.SPEC_COMPILE

            elif tool_name == "update_spec_and_compile_authority":
                next_state = OrchestratorState.SPEC_UPDATE

            elif tool_name is None and "sprint" in user_input.lower():
                next_state = OrchestratorState.SPRINT_SETUP

            # select_project keeps us in ROUTING_MODE (context update)

            pass

        # --- VISION PHASE ---
        if current_state == OrchestratorState.VISION_INTERVIEW:
            if tool_name == "product_vision_tool":
                is_complete = tool_output.get("is_complete", False)
                if is_complete:
                    next_state = OrchestratorState.VISION_REVIEW

        elif current_state == OrchestratorState.VISION_REVIEW:
            if tool_name == "save_vision_tool":
                next_state = OrchestratorState.VISION_PERSISTENCE
            elif tool_name == "product_vision_tool":
                is_complete = tool_output.get("is_complete", False)
                if not is_complete:
                    next_state = OrchestratorState.VISION_INTERVIEW
            elif tool_name == "backlog_primer_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = (
                    OrchestratorState.BACKLOG_REVIEW
                    if is_complete
                    else OrchestratorState.BACKLOG_INTERVIEW
                )

        elif current_state == OrchestratorState.VISION_PERSISTENCE:
            if tool_name == "backlog_primer_tool":
                next_state = OrchestratorState.BACKLOG_INTERVIEW
            elif tool_name == "save_vision_tool":
                 # Stay in Persistence to show success and ask next question
                pass

        # --- BACKLOG PHASE ---
        if current_state == OrchestratorState.BACKLOG_INTERVIEW:
            if tool_name == "backlog_primer_tool":
                is_complete = tool_output.get("is_complete", False)
                if is_complete:
                    next_state = OrchestratorState.BACKLOG_REVIEW

        elif current_state == OrchestratorState.BACKLOG_REVIEW:
            if tool_name == "backlog_primer_tool":
                is_complete = tool_output.get("is_complete", False)
                if not is_complete:
                    next_state = OrchestratorState.BACKLOG_INTERVIEW
            elif tool_name == "save_backlog_tool":
                if tool_output.get("success", False):
                    next_state = OrchestratorState.BACKLOG_PERSISTENCE

        elif current_state == OrchestratorState.BACKLOG_PERSISTENCE:
            if tool_name == "roadmap_builder_tool":
                next_state = OrchestratorState.ROADMAP_INTERVIEW
            elif tool_name == "backlog_primer_tool":
                next_state = OrchestratorState.BACKLOG_INTERVIEW

        # --- ROADMAP PHASE ---
        if current_state == OrchestratorState.ROADMAP_INTERVIEW:
            if tool_name == "roadmap_builder_tool":
                is_complete = tool_output.get("is_complete", False)
                if is_complete:
                    next_state = OrchestratorState.ROADMAP_REVIEW
            elif tool_name == "save_roadmap_tool":
                if tool_output.get("success", False):
                    next_state = OrchestratorState.ROADMAP_PERSISTENCE

        elif current_state == OrchestratorState.ROADMAP_REVIEW:
            if tool_name == "roadmap_builder_tool":
                is_complete = tool_output.get("is_complete", False)
                if not is_complete:
                    next_state = OrchestratorState.ROADMAP_INTERVIEW
            elif tool_name == "save_roadmap_tool":
                if tool_output.get("success", False):
                    next_state = OrchestratorState.ROADMAP_PERSISTENCE

        elif current_state == OrchestratorState.ROADMAP_PERSISTENCE:
            # After roadmap save, user can proceed to story decomposition
            if tool_name == "user_story_writer_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.STORY_REVIEW if is_complete else OrchestratorState.STORY_INTERVIEW

        # --- STORY PHASE ---
        if current_state == OrchestratorState.STORY_INTERVIEW:
            if tool_name == "user_story_writer_tool":
                is_complete = tool_output.get("is_complete", False)
                if is_complete:
                    next_state = OrchestratorState.STORY_REVIEW

        elif current_state == OrchestratorState.STORY_REVIEW:
            if tool_name == "user_story_writer_tool":
                is_complete = tool_output.get("is_complete", False)
                if not is_complete:
                    next_state = OrchestratorState.STORY_INTERVIEW
            elif tool_name == "save_stories_tool":
                if tool_output.get("success", False):
                    next_state = OrchestratorState.STORY_PERSISTENCE

        elif current_state == OrchestratorState.STORY_PERSISTENCE:
            if tool_name == "user_story_writer_tool":
                # Proceed to next requirement decomposition
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.STORY_REVIEW if is_complete else OrchestratorState.STORY_INTERVIEW

        # --- SPRINT PHASE ---
        if current_state == OrchestratorState.SPRINT_SETUP:
            if tool_name == "sprint_planner_tool":
                next_state = OrchestratorState.SPRINT_DRAFT

        elif current_state == OrchestratorState.SPRINT_DRAFT:
            if tool_name == "save_sprint_plan_tool" and tool_output.get("success", False):
                next_state = OrchestratorState.SPRINT_PERSISTENCE
            elif tool_name == "sprint_planner_tool":
                next_state = OrchestratorState.SPRINT_DRAFT

        elif current_state == OrchestratorState.SPRINT_PERSISTENCE:
            if tool_name == "sprint_planner_tool":
                next_state = OrchestratorState.SPRINT_DRAFT

        # Validate transition (Security/Stability Check)
        if next_state != current_state:
            current_def = self.get_state_definition(current_state)
            # We allow transition to self implicitly, but if next_state != current_state, check allowed.
            if next_state not in current_def.allowed_transitions:
                # If invalid transition, fallback to current state (safe default)
                print(f"[FSM] Blocked invalid transition: {current_state} -> {next_state}")
                return current_state

        return next_state
