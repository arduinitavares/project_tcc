import unittest
from orchestrator_agent.fsm.controller import FSMController
from orchestrator_agent.fsm.states import OrchestratorState

class TestFSMController(unittest.TestCase):
    def setUp(self):
        self.controller = FSMController()

    def test_initial_state(self):
        self.assertEqual(self.controller.get_initial_state(), OrchestratorState.ROUTING_MODE)

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

if __name__ == "__main__":
    unittest.main()
