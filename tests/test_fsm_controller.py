import unittest
import sys
from unittest.mock import patch
from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.states import OrchestratorState
from orchestrator_agent.fsm.definitions import STATE_REGISTRY

class TestFSMController(unittest.TestCase):
    def setUp(self):
        self.controller = FSMController()

    def test_initial_state(self):
        self.assertEqual(self.controller.get_initial_state(), OrchestratorState.ROUTING_MODE)

    def test_registry_integrity(self):
        """Verify that all allowed transitions target valid states."""
        all_states = set(OrchestratorState)
        for state, definition in STATE_REGISTRY.items():
            for target in definition.allowed_transitions:
                self.assertIn(target, all_states, f"State {state} has invalid transition target: {target}")

    def test_routing_mode_transitions(self):
        # Vision Interview
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "product_vision_tool",
            {"is_complete": False},
            "start project"
        )
        self.assertEqual(next_state, OrchestratorState.VISION_INTERVIEW)

        # Vision Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "product_vision_tool",
            {"is_complete": True},
            "start project"
        )
        self.assertEqual(next_state, OrchestratorState.VISION_REVIEW)

    def test_vision_phase_transitions(self):
        # Interview -> Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_INTERVIEW,
            "product_vision_tool",
            {"is_complete": True},
            ""
        )
        self.assertEqual(next_state, OrchestratorState.VISION_REVIEW)

        # Review -> Persistence
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "save_vision_tool",
            {},
            "Save"
        )
        self.assertEqual(next_state, OrchestratorState.VISION_PERSISTENCE)

        # Review -> Interview (Rejection)
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "product_vision_tool",
            {"is_complete": False},
            "Change vision"
        )
        self.assertEqual(next_state, OrchestratorState.VISION_INTERVIEW)

        # Vision Review -> Backlog Review (User requests backlog)
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "backlog_primer_tool",
            {"is_complete": True},
            "create backlog"
        )
        self.assertEqual(next_state, OrchestratorState.BACKLOG_REVIEW)

    def test_roadmap_phase_transitions(self):
        # Routing -> Roadmap Interview
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "roadmap_builder_tool",
            {"is_complete": False},
            "create roadmap"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_INTERVIEW)

        # Routing -> Roadmap Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "roadmap_builder_tool",
            {"is_complete": True},
            "create roadmap"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_REVIEW)

        # Interview -> Review
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_INTERVIEW,
            "roadmap_builder_tool",
            {"is_complete": True},
            "continue"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_REVIEW)

        # Review -> Interview (needs changes)
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_REVIEW,
            "roadmap_builder_tool",
            {"is_complete": False},
            "adjust roadmap"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_INTERVIEW)

        # Review -> Persistence (save)
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_REVIEW,
            "save_roadmap_tool",
            {"success": True},
            "save"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_PERSISTENCE)

    def test_backlog_persistence_sprint_planner_transition(self):
        """BACKLOG_PERSISTENCE + sprint_planner_tool → SPRINT_DRAFT."""
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "sprint_planner_tool",
            {},
            "plan sprint"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_DRAFT)

    def test_backlog_persistence_existing_transitions_unchanged(self):
        """Existing transitions from BACKLOG_PERSISTENCE remain intact."""
        # roadmap_builder_tool → ROADMAP_INTERVIEW
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "roadmap_builder_tool",
            {},
            "create roadmap"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_INTERVIEW)

        # backlog_primer_tool → BACKLOG_INTERVIEW
        next_state = self.controller.determine_next_state(
            OrchestratorState.BACKLOG_PERSISTENCE,
            "backlog_primer_tool",
            {},
            "refine backlog"
        )
        self.assertEqual(next_state, OrchestratorState.BACKLOG_INTERVIEW)

    def test_backlog_persistence_has_sprint_planner_tool(self):
        """BACKLOG_PERSISTENCE state definition must include sprint_planner_tool."""
        state_def = STATE_REGISTRY[OrchestratorState.BACKLOG_PERSISTENCE]
        tool_names = [
            getattr(t, "name", None) or getattr(t, "__name__", None)
            for t in state_def.tools
        ]
        self.assertIn("sprint_planner_tool", tool_names)

    def test_backlog_persistence_allows_sprint_draft_transition(self):
        """BACKLOG_PERSISTENCE allowed_transitions must include SPRINT_DRAFT."""
        state_def = STATE_REGISTRY[OrchestratorState.BACKLOG_PERSISTENCE]
        self.assertIn(
            OrchestratorState.SPRINT_DRAFT,
            state_def.allowed_transitions,
        )

    def test_unknown_tool_stays_in_state(self):
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_VIEW,
            "unknown_tool",
            {},
            "blah"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_VIEW)

    def test_z_guard_blocks_invalid_transition(self):
        """
        Verify that a transition calculated by the controller is BLOCKED if it is not
        in the current state's allowed_transitions set.
        """
        fake_def = STATE_REGISTRY[OrchestratorState.ROUTING_MODE].model_copy(deep=True)
        fake_def.allowed_transitions.remove(OrchestratorState.VISION_INTERVIEW)

        # Patch the class method instead of instance
        with patch.object(FSMController, 'get_state_definition', return_value=fake_def) as mock_method:
            next_state = self.controller.determine_next_state(
                OrchestratorState.ROUTING_MODE,
                "product_vision_tool",
                {"is_complete": False},
                "draft vision"
            )

            # Check call
            print(f"DEBUG TEST: Mock called? {mock_method.called}", file=sys.stderr)

            self.assertEqual(next_state, OrchestratorState.ROUTING_MODE)

if __name__ == "__main__":
    unittest.main()
