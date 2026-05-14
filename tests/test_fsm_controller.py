"""Tests for fsm controller."""

import sys
import unittest
from unittest.mock import patch

from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.definitions import STATE_REGISTRY
from orchestrator_agent.fsm.states import OrchestratorState
from utils.cli_output import emit


class TestFSMController(unittest.TestCase):
    """Test helper for test f s m controller."""

    def setUp(self) -> None:
        """Return set up."""
        self.controller = FSMController()

    def test_initial_state(self) -> None:
        """Verify initial state."""
        assert self.controller.get_initial_state() == OrchestratorState.SETUP_REQUIRED

    def test_registry_integrity(self) -> None:
        """Verify that all allowed transitions target valid states."""
        all_states = set(OrchestratorState)
        for state, definition in STATE_REGISTRY.items():
            for target in definition.allowed_transitions:
                assert target in all_states, f"State {state} has invalid transition target: {target}"  # noqa: E501

    def test_routing_mode_transitions(self) -> None:
        # Vision Interview
        """Verify routing mode transitions."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.SETUP_REQUIRED,
            "product_vision_tool",
            {"is_complete": False},
            "start project",
        )
        assert next_state == OrchestratorState.VISION_INTERVIEW

        # Vision Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.SETUP_REQUIRED,
            "product_vision_tool",
            {"is_complete": True},
            "start project",
        )
        assert next_state == OrchestratorState.VISION_REVIEW

    def test_vision_phase_transitions(self) -> None:
        # Interview -> Review
        """Verify vision phase transitions."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_INTERVIEW,
            "product_vision_tool",
            {"is_complete": True},
            "",
        )
        assert next_state == OrchestratorState.VISION_REVIEW

        # Review -> Persistence
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW, "save_vision_tool", {}, "Save"
        )
        assert next_state == OrchestratorState.VISION_PERSISTENCE

        # Review -> Interview (Rejection)
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "product_vision_tool",
            {"is_complete": False},
            "Change vision",
        )
        assert next_state == OrchestratorState.VISION_INTERVIEW

        # Vision Review -> stays in review until explicit save
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "backlog_primer_tool",
            {"is_complete": True},
            "create backlog",
        )
        assert next_state == OrchestratorState.VISION_REVIEW

    def test_roadmap_phase_transitions(self) -> None:
        # Routing -> Roadmap Interview
        """Verify roadmap phase transitions."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.SETUP_REQUIRED,
            "roadmap_builder_tool",
            {"is_complete": False},
            "create roadmap",
        )
        assert next_state == OrchestratorState.ROADMAP_INTERVIEW

        # Routing -> Roadmap Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.SETUP_REQUIRED,
            "roadmap_builder_tool",
            {"is_complete": True},
            "create roadmap",
        )
        assert next_state == OrchestratorState.ROADMAP_REVIEW

        # Interview -> Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_INTERVIEW,
            "roadmap_builder_tool",
            {"is_complete": True},
            "continue",
        )
        assert next_state == OrchestratorState.ROADMAP_REVIEW

        # Review -> Interview (needs changes)
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_REVIEW,
            "roadmap_builder_tool",
            {"is_complete": False},
            "adjust roadmap",
        )
        assert next_state == OrchestratorState.ROADMAP_INTERVIEW

        # Review -> Persistence (save)
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_REVIEW,
            "save_roadmap_tool",
            {"success": True},
            "save",
        )
        assert next_state == OrchestratorState.ROADMAP_PERSISTENCE

    def test_backlog_persistence_existing_transitions_unchanged(self) -> None:
        """Existing transitions from BACKLOG_PERSISTENCE remain intact."""
        # roadmap_builder_tool -> ROADMAP_INTERVIEW
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "roadmap_builder_tool",
            {},
            "create roadmap",
        )
        assert next_state == OrchestratorState.ROADMAP_INTERVIEW

        # backlog_primer_tool -> BACKLOG_INTERVIEW
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "backlog_primer_tool",
            {},
            "refine backlog",
        )
        assert next_state == OrchestratorState.BACKLOG_INTERVIEW

    def test_backlog_persistence_blocks_sprint_planner_transition(self) -> None:
        """BACKLOG_PERSISTENCE should not route directly to sprint planning."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "sprint_planner_tool",
            {},
            "plan sprint",
        )
        assert next_state == OrchestratorState.BACKLOG_PERSISTENCE

    def test_backlog_persistence_excludes_sprint_planner_tool(self) -> None:
        """BACKLOG_PERSISTENCE tools must not include sprint_planner_tool."""
        state_def = STATE_REGISTRY[OrchestratorState.BACKLOG_PERSISTENCE]
        tool_names = [
            getattr(t, "name", None) or getattr(t, "__name__", None)
            for t in state_def.tools
        ]
        assert "sprint_planner_tool" not in tool_names

    def test_backlog_persistence_disallows_sprint_draft_transition(self) -> None:
        """BACKLOG_PERSISTENCE allowed_transitions must not include SPRINT_DRAFT."""
        state_def = STATE_REGISTRY[OrchestratorState.BACKLOG_PERSISTENCE]
        assert OrchestratorState.SPRINT_DRAFT not in state_def.allowed_transitions

    def test_unknown_tool_stays_in_state(self) -> None:
        """Verify unknown tool stays in state."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_VIEW, "unknown_tool", {}, "blah"
        )
        assert next_state == OrchestratorState.SPRINT_VIEW

    def test_z_guard_blocks_invalid_transition(self) -> None:
        """
        Verify that a transition calculated by the controller is BLOCKED if it is not.

        in the current state's allowed_transitions set.
        """
        fake_def = STATE_REGISTRY[OrchestratorState.SETUP_REQUIRED].model_copy(
            deep=True
        )
        fake_def.allowed_transitions.remove(OrchestratorState.VISION_INTERVIEW)

        # Patch the class method instead of instance
        with patch.object(
            FSMController, "get_state_definition", return_value=fake_def
        ) as mock_method:
            next_state = self.controller.determine_next_state(
                OrchestratorState.SETUP_REQUIRED,
                "product_vision_tool",
                {"is_complete": False},
                "draft vision",
            )

            # Check call
            emit(f"DEBUG TEST: Mock called? {mock_method.called}", file=sys.stderr)

            assert next_state == OrchestratorState.SETUP_REQUIRED


if __name__ == "__main__":
    unittest.main()
