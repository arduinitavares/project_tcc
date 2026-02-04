from typing import Any, Dict, Optional, Tuple, List
import json
from .states import OrchestratorState, OrchestratorPhase
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

            elif tool_name == "product_roadmap_tool":
                is_complete = tool_output.get("is_complete", False)
                next_state = OrchestratorState.ROADMAP_REVIEW if is_complete else OrchestratorState.ROADMAP_INTERVIEW

            elif tool_name == "query_features_for_stories":
                next_state = OrchestratorState.STORY_SETUP

            elif tool_name == "get_backlog_for_planning":
                next_state = OrchestratorState.SPRINT_SETUP

            elif tool_name == "get_story_details":
                next_state = OrchestratorState.STORY_DETAILS

            elif tool_name == "get_sprint_details":
                next_state = OrchestratorState.SPRINT_VIEW

            elif tool_name == "list_sprints":
                next_state = OrchestratorState.SPRINT_LIST

            elif tool_name == "complete_sprint":
                next_state = OrchestratorState.SPRINT_COMPLETE

            elif tool_name in ["complete_story_with_notes", "create_follow_up_story"]:
                next_state = OrchestratorState.STORY_COMPLETE_DOC

            elif tool_name in ["update_story_status", "batch_update_story_status"]:
                next_state = OrchestratorState.SPRINT_UPDATE_STORY

            elif tool_name == "compile_spec_authority_for_version":
                next_state = OrchestratorState.SPEC_COMPILE

            elif tool_name == "update_spec_and_compile_authority":
                next_state = OrchestratorState.SPEC_UPDATE

            # select_project keeps us in ROUTING_MODE (context update)
            # save_vision_tool, etc should ideally not happen in ROUTING_MODE unless completing a "one-shot"

            return next_state

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

        elif current_state == OrchestratorState.VISION_PERSISTENCE:
            if tool_name == "product_roadmap_tool":
                next_state = OrchestratorState.ROADMAP_INTERVIEW
            elif tool_name == "save_vision_tool":
                 # Stay in Persistence to show success and ask next question
                pass

        # --- ROADMAP PHASE ---
        if current_state == OrchestratorState.ROADMAP_INTERVIEW:
            if tool_name == "product_roadmap_tool":
                is_complete = tool_output.get("is_complete", False)
                if is_complete:
                    next_state = OrchestratorState.ROADMAP_REVIEW

        elif current_state == OrchestratorState.ROADMAP_REVIEW:
            if tool_name == "save_roadmap_tool":
                next_state = OrchestratorState.ROADMAP_PERSISTENCE
            elif tool_name == "product_roadmap_tool":
                is_complete = tool_output.get("is_complete", False)
                if not is_complete:
                    next_state = OrchestratorState.ROADMAP_INTERVIEW

        elif current_state == OrchestratorState.ROADMAP_PERSISTENCE:
            if tool_name == "query_features_for_stories":
                next_state = OrchestratorState.STORY_SETUP

        # --- STORY PHASE ---
        if current_state == OrchestratorState.STORY_SETUP:
            if tool_name == "process_single_story":
                next_state = OrchestratorState.STORY_PIPELINE

        elif current_state == OrchestratorState.STORY_PIPELINE:
            if tool_name == "save_validated_stories":
                next_state = OrchestratorState.ROUTING_MODE

        elif current_state == OrchestratorState.STORY_DETAILS:
            # Usually return to routing after viewing? Or stay?
            # Instructions say "Prompt: Return to backlog?".
            # If user says "backlog" (Text), we might need to route.
            # But based on tools:
            pass

        # --- SPRINT PHASE ---
        if current_state == OrchestratorState.SPRINT_SETUP:
            if tool_name == "plan_sprint_tool":
                next_state = OrchestratorState.SPRINT_DRAFT

        elif current_state == OrchestratorState.SPRINT_DRAFT:
            if tool_name == "save_sprint_tool":
                next_state = OrchestratorState.ROUTING_MODE

        # --- SPRINT MANAGEMENT HUB ---
        elif current_state == OrchestratorState.SPRINT_VIEW:
            if tool_name in ["update_story_status", "batch_update_story_status"]:
                next_state = OrchestratorState.SPRINT_UPDATE_STORY
            elif tool_name == "modify_sprint_stories":
                next_state = OrchestratorState.SPRINT_MODIFY
            elif tool_name == "list_sprints":
                next_state = OrchestratorState.SPRINT_LIST
            elif tool_name == "complete_sprint":
                next_state = OrchestratorState.SPRINT_COMPLETE

        elif current_state == OrchestratorState.SPRINT_LIST:
            if tool_name == "get_sprint_details":
                next_state = OrchestratorState.SPRINT_VIEW
            elif tool_name == "get_backlog_for_planning":
                next_state = OrchestratorState.SPRINT_SETUP

        # For other Sprint execution states (UPDATE, MODIFY), we might want to return to VIEW
        # after an action, or stay.
        # If get_sprint_details is called, we go to VIEW.
        elif current_state in [OrchestratorState.SPRINT_UPDATE_STORY, OrchestratorState.SPRINT_MODIFY, OrchestratorState.SPRINT_COMPLETE]:
            if tool_name == "get_sprint_details":
                next_state = OrchestratorState.SPRINT_VIEW

        # Validate transition (Security/Stability Check)
        if next_state != current_state:
            current_def = self.get_state_definition(current_state)
            # We allow transition to self implicitly, but if next_state != current_state, check allowed.
            if next_state not in current_def.allowed_transitions:
                # If invalid transition, fallback to current state (safe default)
                print(f"[FSM] Blocked invalid transition: {current_state} -> {next_state}")
                return current_state

        return next_state
