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

        # Story Setup
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROUTING_MODE,
            "query_features_for_stories",
            {},
            "create stories"
        )
        self.assertEqual(next_state, OrchestratorState.STORY_SETUP)

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

        # Persistence -> Roadmap Interview
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_PERSISTENCE,
            "product_roadmap_tool",
            {},
            "Yes generate roadmap"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_INTERVIEW)

        # Review -> Interview (Rejection)
        next_state = self.controller.determine_next_state(
            OrchestratorState.VISION_REVIEW,
            "product_vision_tool",
            {"is_complete": False},
            "Change vision"
        )
        self.assertEqual(next_state, OrchestratorState.VISION_INTERVIEW)

    def test_roadmap_phase_transitions(self):
        # Review -> Persistence
        next_state = self.controller.determine_next_state(
            OrchestratorState.ROADMAP_REVIEW,
            "save_roadmap_tool",
            {},
            "Save"
        )
        self.assertEqual(next_state, OrchestratorState.ROADMAP_PERSISTENCE)

    def test_story_pipeline_transitions(self):
        # Setup -> Pipeline
        next_state = self.controller.determine_next_state(
            OrchestratorState.STORY_SETUP,
            "process_single_story",
            {},
            "Go"
        )
        self.assertEqual(next_state, OrchestratorState.STORY_PIPELINE)

        # Pipeline -> Persistence
        next_state = self.controller.determine_next_state(
            OrchestratorState.STORY_PIPELINE,
            "save_validated_stories",
            {},
            "Save"
        )
        self.assertEqual(next_state, OrchestratorState.STORY_PERSISTENCE)

        # Persistence -> Sprint Setup (Next Action)
        next_state = self.controller.determine_next_state(
            OrchestratorState.STORY_PERSISTENCE,
            "get_backlog_for_planning",
            {},
            "Plan sprint"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_SETUP)

    def test_sprint_phase_transitions(self):
        # Setup -> Draft
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_SETUP,
            "plan_sprint_tool",
            {},
            "Plan it"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_DRAFT)

        # Draft -> Persistence
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_DRAFT,
            "save_sprint_tool",
            {},
            "Commit"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_PERSISTENCE)

        # Persistence -> View (Next Action)
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_PERSISTENCE,
            "get_sprint_details",
            {},
            "View sprint"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_VIEW)

    def test_sprint_hub_transitions(self):
        # View -> Update
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_VIEW,
            "update_story_status",
            {},
            "Update story 1"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_UPDATE_STORY)

        # Update -> View
        next_state = self.controller.determine_next_state(
            OrchestratorState.SPRINT_UPDATE_STORY,
            "get_sprint_details",
            {},
            "Show sprint"
        )
        self.assertEqual(next_state, OrchestratorState.SPRINT_VIEW)

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
