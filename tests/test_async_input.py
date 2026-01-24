import asyncio
import unittest
from unittest.mock import MagicMock, patch
import sys
import os

# Add repo root to path so we can import main
sys.path.append(os.getcwd())

import main

class TestAsyncInput(unittest.TestCase):
    def test_get_user_input_calls_executor(self):
        """
        Verify that main.get_user_input uses run_in_executor to wrap console.input.
        """
        # Setup
        # We need to patch the console object in main.py
        with patch('main.console') as mock_console:
            mock_console.input.return_value = "user response"
            prompt = "TEST > "

            # We need to run the async function in an event loop
            async def run_test():
                # We patch the loop to verify run_in_executor is called
                with patch('asyncio.get_running_loop') as mock_get_loop:
                    mock_loop = MagicMock()
                    mock_get_loop.return_value = mock_loop

                    # Mock the future returned by run_in_executor so await works
                    future = asyncio.Future()
                    future.set_result("user response")
                    mock_loop.run_in_executor.return_value = future

                    # Execute
                    result = await main.get_user_input(prompt)

                    # Verify
                    self.assertEqual(result, "user response")
                    mock_loop.run_in_executor.assert_called_once_with(
                        None, mock_console.input, prompt
                    )

            # Run the async test
            asyncio.run(run_test())

if __name__ == "__main__":
    unittest.main()
