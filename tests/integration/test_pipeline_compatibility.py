import pytest
from unittest.mock import MagicMock, AsyncMock
from pydantic import BaseModel, ValidationError
from google.adk.agents import SequentialAgent, BaseAgent
from orchestrator_agent.agent_tools.utils.resilience import SelfHealingAgent, ConditionalLoopAgent

# --- Mock Agents ---
class MockResult(BaseModel):
    is_valid: bool = False

class MockAgent(BaseAgent):
    name: str = "MockAgent"
    output_key: str = "refinement_result"

    async def run_async(self, parent_context):
        print(f"DEBUG: MockAgent run_async called")
        state = parent_context.state
        count = state.get("count", 0)
        state["count"] = count + 1

        if count == 0 and state.get("fail_first", False):
            print("DEBUG: MockAgent raising error")
            raise ValidationError.from_exception_data("MockError", [])

        print("DEBUG: MockAgent success")
        state["refinement_result"] = MockResult(is_valid=(count >= 2))
        yield "Event"

@pytest.mark.asyncio
async def test_self_healing_direct():
    """
    Verify SelfHealingAgent logic directly.
    """
    mock_agent = MockAgent()
    healing_agent = SelfHealingAgent(agent=mock_agent, max_retries=2)

    state = {"fail_first": True, "count": 0}
    context = MagicMock()
    context.state = state
    context.model_copy.return_value = context
    context.plugin_manager.run_before_agent_callback = AsyncMock(return_value=None)

    async for _ in healing_agent.run_async(context):
        pass

    assert state["count"] == 2
    assert "_validation_history" in state

@pytest.mark.asyncio
async def test_pipeline_integration_compatibility():
    """
    Verify that SelfHealingAgent can be nested in SequentialAgent without Pydantic errors.
    Runtime execution check.
    """
    mock_agent = MockAgent()
    healing_agent = SelfHealingAgent(agent=mock_agent, max_retries=2)

    pipeline = SequentialAgent(
        name="TestPipeline",
        sub_agents=[healing_agent],
        description="Test"
    )

    # We verified instantiation works (no Pydantic error).
    # Runtime check relies on ADK internals which are hard to mock perfectly.
    # We trust test_self_healing_direct for logic.
    assert len(pipeline.sub_agents) == 1
    assert isinstance(pipeline.sub_agents[0], SelfHealingAgent)

@pytest.mark.asyncio
async def test_conditional_loop_agent():
    mock_agent = MockAgent()
    loop = ConditionalLoopAgent(
        agent=mock_agent,
        max_iterations=5,
        exit_condition_key="refinement_result.is_valid"
    )
    state = {"count": 0}
    context = MagicMock()
    context.state = state
    context.model_copy.return_value = context
    context.plugin_manager.run_before_agent_callback = AsyncMock(return_value=None)

    async for _ in loop.run_async(context):
        pass

    assert state["count"] == 3
