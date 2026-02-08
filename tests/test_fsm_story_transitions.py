"""TDD tests for FSM Story phase transitions."""

from __future__ import annotations

from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.states import OrchestratorState


class TestFSMStoryTransitions:
    """Tests for story-phase state transitions in the FSM controller."""

    def setup_method(self) -> None:
        self.ctrl = FSMController()

    # --- ROUTING → STORY ---

    def test_routing_to_story_interview_on_incomplete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.ROUTING_MODE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": False},
            user_input="decompose stories",
        )
        assert next_state == OrchestratorState.STORY_INTERVIEW

    def test_routing_to_story_review_on_complete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.ROUTING_MODE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": True},
            user_input="decompose stories",
        )
        assert next_state == OrchestratorState.STORY_REVIEW

    # --- ROADMAP_PERSISTENCE → STORY ---

    def test_roadmap_persistence_to_story_interview(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.ROADMAP_PERSISTENCE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": False},
            user_input="yes, decompose",
        )
        assert next_state == OrchestratorState.STORY_INTERVIEW

    def test_roadmap_persistence_to_story_review(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.ROADMAP_PERSISTENCE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": True},
            user_input="yes, decompose",
        )
        assert next_state == OrchestratorState.STORY_REVIEW

    # --- STORY_INTERVIEW ---

    def test_story_interview_stays_on_incomplete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_INTERVIEW,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": False},
            user_input="more details",
        )
        assert next_state == OrchestratorState.STORY_INTERVIEW

    def test_story_interview_to_review_on_complete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_INTERVIEW,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": True},
            user_input="looks good",
        )
        assert next_state == OrchestratorState.STORY_REVIEW

    # --- STORY_REVIEW ---

    def test_story_review_back_to_interview_on_incomplete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_REVIEW,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": False},
            user_input="change the first story",
        )
        assert next_state == OrchestratorState.STORY_INTERVIEW

    def test_story_review_to_persistence_on_save(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_REVIEW,
            tool_name="save_stories_tool",
            tool_output={"success": True, "saved_count": 5},
            user_input="save",
        )
        assert next_state == OrchestratorState.STORY_PERSISTENCE

    def test_story_review_stays_on_failed_save(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_REVIEW,
            tool_name="save_stories_tool",
            tool_output={"success": False, "error": "Validation failed"},
            user_input="save",
        )
        assert next_state == OrchestratorState.STORY_REVIEW

    # --- STORY_PERSISTENCE ---

    def test_story_persistence_to_interview_for_next_requirement(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_PERSISTENCE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": False},
            user_input="next requirement",
        )
        assert next_state == OrchestratorState.STORY_INTERVIEW

    def test_story_persistence_to_review_for_next_complete(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_PERSISTENCE,
            tool_name="user_story_writer_tool",
            tool_output={"is_complete": True},
            user_input="next requirement",
        )
        assert next_state == OrchestratorState.STORY_REVIEW

    def test_story_persistence_stays_without_tool(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_PERSISTENCE,
            tool_name=None,
            tool_output={},
            user_input="what now?",
        )
        assert next_state == OrchestratorState.STORY_PERSISTENCE

    def test_story_persistence_to_sprint_draft(self) -> None:
        next_state = self.ctrl.determine_next_state(
            current_state=OrchestratorState.STORY_PERSISTENCE,
            tool_name="sprint_planner_tool",
            tool_output={},
            user_input="plan sprint",
        )
        assert next_state == OrchestratorState.SPRINT_DRAFT


class TestFSMStoryStateDefinitions:
    """Validate that story states exist in the registry with correct properties."""

    def setup_method(self) -> None:
        self.ctrl = FSMController()

    def test_story_interview_in_registry(self) -> None:
        defn = self.ctrl.get_state_definition(OrchestratorState.STORY_INTERVIEW)
        assert defn.name == OrchestratorState.STORY_INTERVIEW
        assert OrchestratorState.STORY_REVIEW in defn.allowed_transitions

    def test_story_review_in_registry(self) -> None:
        defn = self.ctrl.get_state_definition(OrchestratorState.STORY_REVIEW)
        assert defn.name == OrchestratorState.STORY_REVIEW
        assert OrchestratorState.STORY_PERSISTENCE in defn.allowed_transitions
        assert OrchestratorState.STORY_INTERVIEW in defn.allowed_transitions

    def test_story_persistence_in_registry(self) -> None:
        defn = self.ctrl.get_state_definition(OrchestratorState.STORY_PERSISTENCE)
        assert defn.name == OrchestratorState.STORY_PERSISTENCE
        assert OrchestratorState.STORY_INTERVIEW in defn.allowed_transitions
        assert OrchestratorState.SPRINT_DRAFT in defn.allowed_transitions

    def test_roadmap_persistence_allows_story_interview(self) -> None:
        defn = self.ctrl.get_state_definition(OrchestratorState.ROADMAP_PERSISTENCE)
        assert OrchestratorState.STORY_INTERVIEW in defn.allowed_transitions

    def test_routing_allows_story_transitions(self) -> None:
        defn = self.ctrl.get_state_definition(OrchestratorState.ROUTING_MODE)
        assert OrchestratorState.STORY_INTERVIEW in defn.allowed_transitions
        assert OrchestratorState.STORY_REVIEW in defn.allowed_transitions
