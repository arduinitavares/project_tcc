import sys
import os
import unittest

# Add repo root to path so we can import main
sys.path.append(os.getcwd())

import main
from orchestrator_agent.fsm.states import OrchestratorState


class TestMainWorkflowTriggers(unittest.TestCase):
    def test_backlog_trigger_suppressed_in_backlog_review(self):
        state = {
            "product_backlog": [{"priority": 1}],
            "sprint_plan": None,
            "fsm_state": OrchestratorState.BACKLOG_REVIEW.value,
        }
        result = main.evaluate_workflow_triggers(state)
        self.assertIsNone(result)

    def test_backlog_trigger_suppressed_in_vision_review(self):
        """Backlog trigger should NOT fire while still in VISION_REVIEW."""
        state = {
            "product_backlog": [{"priority": 1}],
            "sprint_plan": None,
            "fsm_state": OrchestratorState.VISION_REVIEW.value,
        }
        result = main.evaluate_workflow_triggers(state)
        self.assertIsNone(result)

    def test_backlog_trigger_fires_outside_backlog_phase(self):
        state = {
            "product_backlog": [{"priority": 1}],
            "sprint_plan": None,
            "fsm_state": OrchestratorState.ROUTING_MODE.value,
        }
        result = main.evaluate_workflow_triggers(state)
        self.assertEqual(result, "[SYSTEM TRIGGER]: The Product Backlog has been updated...")

    def test_sprint_trigger_suppressed_in_sprint_view(self):
        state = {
            "sprint_plan_confirmed": True,
            "dev_tasks_active": False,
            "fsm_state": OrchestratorState.SPRINT_VIEW.value,
        }
        result = main.evaluate_workflow_triggers(state)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
