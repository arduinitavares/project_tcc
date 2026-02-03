import asyncio
import unittest
from unittest.mock import MagicMock, patch, AsyncMock
import sys
import os

# Add repo root to path so we can import main
sys.path.append(os.getcwd())

import main

class TestMainTriggerLoop(unittest.TestCase):
    def test_process_automated_workflows_terminates(self):
        """
        Verify that main.process_automated_workflows terminates after
        MAX_CONSECUTIVE_SYSTEM_TRIGGERS iterations when triggers keep firing.
        """
        # Ensure the constant and function exist (this will fail before refactor)
        self.assertTrue(hasattr(main, "MAX_CONSECUTIVE_SYSTEM_TRIGGERS"), "Constant missing")
        self.assertTrue(hasattr(main, "process_automated_workflows"), "Function missing")

        limit = main.MAX_CONSECUTIVE_SYSTEM_TRIGGERS

        # Mocks
        mock_runner = MagicMock()

        # We need to patch the functions called inside the loop
        with patch('main.get_current_state') as mock_get_state, \
             patch('main.evaluate_workflow_triggers') as mock_eval, \
             patch('main.run_agent_turn', new_callable=AsyncMock) as mock_run_turn, \
             patch('main.app_logger') as mock_logger, \
             patch('main.console') as mock_console:

            # Setup infinite triggers
            mock_get_state.return_value = {"some": "state"}
            mock_eval.return_value = "Trigger fired!" # Always returns a trigger

            # Execute
            asyncio.run(main.process_automated_workflows(mock_runner))

            # Verify
            # It should have called run_agent_turn exactly 'limit' times
            self.assertEqual(mock_run_turn.call_count, limit)

            # It should have logged a warning - note usage of lazy logging in main.py
            mock_logger.warning.assert_called_with(
                "System trigger loop limit reached (%d). Stopping to prevent infinite loop.",
                limit
            )

            # Verify console output too
            args, _ = mock_console.print.call_args
            self.assertIn("limit reached", str(args[0]))

if __name__ == "__main__":
    unittest.main()
