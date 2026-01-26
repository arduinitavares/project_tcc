import logging
import copy
from typing import Any, Dict, Optional, AsyncGenerator
from pydantic import ValidationError, Field
from google.adk.agents import BaseAgent
from google.adk.agents.invocation_context import InvocationContext

logger = logging.getLogger(__name__)

class SelfHealingAgent(BaseAgent):
    """
    A wrapper that catches Pydantic ValidationErrors from an inner agent
    and retries execution with error feedback injected into the state.
    """
    agent: BaseAgent = Field(description="The inner agent to wrap.")
    max_retries: int = Field(default=3, description="Number of retries on validation failure.")
    name: str = Field(default="SelfHealingAgent", description="Name of the agent")
    description: str = Field(default="Wrapper for resilience", description="Description of the agent")
    output_key: Optional[str] = Field(default=None, description="Output key for pipeline compatibility")
    output_schema: Optional[Any] = Field(default=None, description="Output schema for pipeline compatibility")

    def __init__(self, agent: BaseAgent, max_retries: int = 3):
        # Determine name and description from inner agent if possible
        name = f"SelfHealing_{agent.name}"
        sanitized_name = "".join(c if c.isalnum() or c == '_' else '_' for c in name)

        super().__init__(
            name=sanitized_name,
            description=getattr(agent, "description", "Wrapper for resilience"),
            sub_agents=[agent],
            agent=agent,
            max_retries=max_retries,
            output_key=getattr(agent, "output_key", None),
            output_schema=getattr(agent, "output_schema", None)
        )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Any, None]:
        """Override the ADK extension point for execution."""
        for attempt in range(self.max_retries + 1):
            try:
                async for event in self.agent.run_async(ctx):
                    yield event
                return

            except ValidationError as e:
                if attempt == self.max_retries:
                    logger.error(f"[{self.name}] Failed validation after {self.max_retries} retries.")
                    raise

                logger.warning(f"[{self.name}] Validation error (Attempt {attempt+1}/{self.max_retries}). Retrying...")

                # Inject feedback into state
                error_msg = f"Validation Error on attempt {attempt + 1}: {str(e)}"
                feedback_msg = (
                    f"\nSYSTEM_FEEDBACK: The previous output failed validation.\n"
                    f"ERROR: {error_msg}\n"
                    f"INSTRUCTION: Fix the JSON structure or logic based on the error above."
                )

                # Access session state directly via context
                if ctx.session and ctx.session.state is not None:
                     ctx.session.state["validation_feedback"] = feedback_msg
                     history = ctx.session.state.get("_validation_history", [])
                     ctx.session.state["_validation_history"] = list(history) + [error_msg]

                # ADK agents re-read state from session/context on next run

class ConditionalLoopAgent(BaseAgent):
    """
    Executes an inner agent in a loop until a condition is met or max_iterations reached.
    """
    agent: BaseAgent = Field(description="The agent to run in a loop.")
    max_iterations: int = Field(default=4, description="Maximum number of iterations.")
    exit_condition_key: str = Field(default="refinement_result.is_valid", description="State key path to check for True to exit loop.")
    name: str = Field(default="ConditionalLoopAgent", description="Name of the loop agent")
    description: str = Field(default="Loops until condition met", description="Description of the loop agent")

    def __init__(self, agent: BaseAgent, max_iterations: int = 4, exit_condition_key: str = "refinement_result.is_valid", **kwargs):
        super().__init__(
            name=kwargs.get("name", "ConditionalLoopAgent"),
            description=kwargs.get("description", "Loops until condition met"),
            sub_agents=[agent],
            agent=agent,
            max_iterations=max_iterations,
            exit_condition_key=exit_condition_key
        )

    async def _run_async_impl(self, ctx: InvocationContext) -> AsyncGenerator[Any, None]:
        for i in range(self.max_iterations):
            logger.debug(f"[{self.name}] Iteration {i}")
            async for event in self.agent.run_async(ctx):
                yield event

            if ctx.session and ctx.session.state and self._should_exit(ctx.session.state):
                logger.debug(f"[{self.name}] Exit condition met")
                break

    def _should_exit(self, state: Dict[str, Any]) -> bool:
        refinement = state.get("refinement_result")
        if not refinement:
            return False

        if hasattr(refinement, "is_valid"):
            return getattr(refinement, "is_valid")
        elif isinstance(refinement, dict):
            return refinement.get("is_valid", False)

        return False
