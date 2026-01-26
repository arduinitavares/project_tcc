import pytest
from unittest.mock import MagicMock
from pydantic import BaseModel, ValidationError
from google.adk.agents import BaseAgent
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent

# --- Mock Infrastructure ---
class MockOutput(BaseModel):
    plan: str
    confidence: int

class MockAgent(BaseAgent):
    name: str = "MockAgent"
    output_key: str = "result"

    async def run_async(self, parent_context):
        state = parent_context.state
        count = state.get("count", 0)
        state["count"] = count + 1

        # Behavior defined by state flags
        if state.get("fail_limit") and count < state.get("fail_limit"):
             raise ValidationError.from_exception_data("MockError", [])

        if state.get("fail_always"):
             raise ValidationError.from_exception_data("PersistentError", [])

        # Success
        state["result"] = MockOutput(plan="Success", confidence=10)
        yield "Event"

@pytest.mark.asyncio
async def test_self_healing_agent_retries_on_validation_error():
    """
    Scenario: The inner agent fails validation twice, then succeeds.
    Expected: The wrapper should catch the error, feed it back, and eventually return the valid object.
    """
    mock_inner_agent = MockAgent()
    resilient_agent = SelfHealingAgent(agent=mock_inner_agent, max_retries=3)

    # State configures the mock to fail 2 times
    valid_response = MockOutput(plan="Success", confidence=10)
    state = {
        "user_request": "Build a plan",
        "count": 0,
        "fail_limit": 2
    }

    context = MagicMock()
    context.state = state
    context.model_copy.return_value = context

    async for _ in resilient_agent.run_async(context):
        pass

    assert state["result"] == valid_response
    assert state["count"] == 3 # 0, 1 (fail), 2 (success) - wait, count starts at 0.
    # 1. run -> count=0 -> fail. count becomes 1.
    # 2. run -> count=1 -> fail. count becomes 2.
    # 3. run -> count=2 -> success (count<2 is false). count becomes 3.

    # Verify feedback injection
    assert "_validation_history" in state
    assert len(state["_validation_history"]) == 2

@pytest.mark.asyncio
async def test_self_healing_agent_fails_after_max_retries():
    """
    Scenario: The inner agent fails more times than allowed.
    Expected: The wrapper should raise the ValidationError.
    """
    mock_inner_agent = MockAgent()
    resilient_agent = SelfHealingAgent(agent=mock_inner_agent, max_retries=2)

    state = {
        "fail_always": True,
        "count": 0
    }
    context = MagicMock()
    context.state = state
    context.model_copy.return_value = context

    with pytest.raises(ValidationError):
        async for _ in resilient_agent.run_async(context):
            pass
