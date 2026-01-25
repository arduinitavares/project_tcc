import pytest
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput, process_single_story
from agile_sqlmodel import Product, ProductPersona
from sqlmodel import Session

# Helper to mock async iterator
class AsyncIterator:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        self._iter = iter(self.items)
        return self
    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration

@pytest.fixture
def review_first_product(session):
    """Create Review-First product with persona whitelist."""
    product = Product(
        name="Review-First P&ID Extraction",
        vision="AI-powered P&ID review tool for automation engineers"
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    # Add approved personas
    personas = [
        ProductPersona(product_id=product.product_id, persona_name="automation engineer", is_default=True, category="primary_user"),
        ProductPersona(product_id=product.product_id, persona_name="engineering qa reviewer", is_default=False, category="primary_user"),
    ]
    for p in personas:
        session.add(p)
    session.commit()

    return product

@pytest.mark.asyncio
async def test_persona_drift_prevented(review_first_product):
    """Ensure drift is corrected deterministically in the pipeline tool."""
    story_input = ProcessStoryInput(
        product_id=review_first_product.product_id,
        product_name=review_first_product.name,
        product_vision=review_first_product.vision,
        feature_id=1,
        feature_title="Interactive UI",
        theme="Core",
        epic="UI",
        user_persona="automation engineer",
        time_frame="Now",
    )

    # The pipeline (LLMs) returns a story with the WRONG persona ("frontend developer")
    drifted_story = {
        "title": "Interactive UI",
        "description": "As a frontend developer, I want to click buttons...",
        "acceptance_criteria": "- Click works",
        "story_points": 3
    }

    # We mock the internal components so we don't call real LLMs
    with patch("orchestrator_agent.agent_tools.story_pipeline.tools.Runner") as MockRunner, \
         patch("orchestrator_agent.agent_tools.story_pipeline.tools.InMemorySessionService") as MockService, \
         patch("orchestrator_agent.agent_tools.story_pipeline.tools.validate_feature_alignment") as mock_align:

        # 1. Bypass alignment check
        mock_align.return_value.is_aligned = True

        # 2. Mock Runner to return empty stream (we just want it to finish)
        instance = MockRunner.return_value
        instance.run_async.return_value = AsyncIterator([])

        # 3. Mock Session Service to return our drifted state at the end
        service_instance = MockService.return_value

        # create_session returns a mock with an id
        mock_session_obj = MagicMock()
        mock_session_obj.id = "test_session"
        service_instance.create_session = AsyncMock(return_value=mock_session_obj)

        # get_session returns the final state with the DRIFTED story
        mock_final_session = MagicMock()
        mock_final_session.state = {
            "refinement_result": json.dumps({
                "is_valid": True,
                "refined_story": drifted_story,
                "refinement_notes": "Validation passed (simulated)"
            }),
            "validation_result": json.dumps({"validation_score": 95})
        }
        service_instance.get_session = AsyncMock(return_value=mock_final_session)

        # Run the tool
        result = await process_single_story(story_input)

        # Verify SUCCESS but with CORRECTED persona
        assert result['success'] is True
        final_story = result['story']
        description = final_story['description']

        print(f"Final description: {description}")

        # It should have been auto-corrected
        assert "As an automation engineer" in description
        assert "frontend developer" not in description
