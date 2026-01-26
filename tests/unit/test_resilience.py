import pytest
from unittest.mock import MagicMock, ANY
from pydantic import BaseModel, ValidationError, Field
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent

# --- Mock Infrastructure ---
class MockOutput(BaseModel):
    plan: str
    confidence: int

def test_self_healing_agent_retries_on_validation_error():
    """
    Scenario: The inner agent fails validation twice, then succeeds.
    Expected: The wrapper should catch the error, feed it back, and eventually return the valid object.
    """
    # 1. Setup Mock Inner Agent
    mock_inner_agent = MagicMock()

    # Define side effects for .run(state):
    # Attempt 1: Raises ValidationError (Simulating bad JSON)
    # Attempt 2: Raises ValidationError again
    # Attempt 3: Returns success
    valid_response = MockOutput(plan="Success", confidence=10)
    validation_error = ValidationError.from_exception_data("MockError", [])

    mock_inner_agent.run.side_effect = [
        validation_error,
        validation_error,
        valid_response
    ]

    # 2. Initialize Wrapper
    # We assume the wrapper takes the inner agent and retry count
    resilient_agent = SelfHealingAgent(agent=mock_inner_agent, max_retries=3)

    # 3. Execution
    initial_state = {"user_request": "Build a plan"}
    result = resilient_agent.run(initial_state)

    # 4. Assertions
    assert result == valid_response
    assert mock_inner_agent.run.call_count == 3

    # Verify that subsequent calls included error feedback in the state or prompt
    # The first call uses initial_state
    mock_inner_agent.run.assert_any_call(initial_state)

    # We verify that subsequent calls received a modified state containing the error
    # Note: The implementation of SelfHealingAgent determines HOW it passes feedback.
    # For this test, we check that it was passed *somehow* (e.g., appended to history).
    args, _ = mock_inner_agent.run.call_args
    final_state_passed = args[0]

    # Adjust this assertion based on how you implement the feedback injection
    # But fundamentally, the inputs MUST differ to provide feedback
    assert final_state_passed != initial_state

def test_self_healing_agent_fails_after_max_retries():
    """
    Scenario: The inner agent fails more times than allowed.
    Expected: The wrapper should raise the ValidationError.
    """
    mock_inner_agent = MagicMock()
    mock_inner_agent.run.side_effect = ValidationError.from_exception_data("PersistentError", [])

    resilient_agent = SelfHealingAgent(agent=mock_inner_agent, max_retries=2)

    with pytest.raises(ValidationError):
        resilient_agent.run({})

    assert mock_inner_agent.run.call_count == 3 # Initial + 2 Retries
