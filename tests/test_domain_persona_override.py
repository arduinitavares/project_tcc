
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
import pytest
from orchestrator_agent.agent_tools.story_pipeline.single_story import process_single_story, ProcessStoryInput
from orchestrator_agent.agent_tools.story_pipeline import single_story as single_story_module

# Mock State
MOCK_STATE = {
    "story_draft": {
        "title": "Top-down people detection models",
        "description": "As an ML Ops Engineer, I want to train the model so that I can detect people in pickleball courts.",
        "acceptance_criteria": "- Model version 1.0 artifact exported\n- Config hash recorded",
    },
    "refined_story": {
        "title": "Top-down people detection models",
        "description": "As an ML Ops Engineer, I want to train the model so that I can detect people in pickleball courts.",
        "acceptance_criteria": "- Model version 1.0 artifact exported\n- Config hash recorded",
        "metadata": {"spec_version_id": 1}
    },
    "spec_validation_result": {
        "domain_compliance": {
            "matched_domain": "training",
            "critical_gaps": []
        }
    },
    "refinement_result": {
        "refined_story": {
            "title": "Top-down people detection models",
            "description": "As an ML Ops Engineer, I want to train the model so that I can detect people in pickleball courts.",
             "metadata": {"spec_version_id": 1}
        },
        "is_valid": True,
        "refinement_applied": True,
        "refinement_notes": "Added technical artifacts"
    },
    "current_feature": json.dumps({"feature_title": "Top-down people detection models"}),
    "iteration_count": 1
}

@pytest.mark.asyncio
async def test_persona_forced_overwrite_repro():
    """
    Reproduction test:
    Input requires 'gestor operacional'.
    Domain is 'training'.
    Refiner produced 'ML Ops Engineer'.
    
    EXPECTATION: Fail fast when a technical domain requires delivery_role but none is provided.
    """
    
    input_payload = ProcessStoryInput(
        product_id=1,
        product_name="Test Product", 
        feature_id=101,
        feature_title="Top-down people detection models",
        theme="AI Models",
        epic="Detection",
        theme_id=1, 
        epic_id=1,
        user_persona="gestor operacional",
        enable_spec_validator=True,
        pass_raw_spec_text=False
    )

    # Mock DB functions
    with patch("orchestrator_agent.agent_tools.story_pipeline.single_story.validate_persona_against_registry") as mock_db_check, \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.load_compiled_authority") as mock_load_auth, \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.validate_feature_alignment") as mock_align, \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.InMemorySessionService") as MockService, \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.Runner") as MockRunner, \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.ensure_accepted_spec_authority", return_value=1), \
         patch(
             "orchestrator_agent.agent_tools.story_pipeline.single_story.build_generation_context",
             return_value={"domain": "training"},
         ), \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.extract_invariants_from_authority", return_value=[]), \
         patch("orchestrator_agent.agent_tools.story_pipeline.single_story.derive_forbidden_capabilities_from_authority", return_value=[]):

        mock_db_check.return_value = (True, None) # Persona matches DB (assume 'gestor' is allowed)
        # Mocking load_compiled_authority result
        mock_spec_version = MagicMock()
        mock_spec_version.spec_hash = "hash"
        mock_load_auth.return_value = (mock_spec_version, MagicMock(), "raw spec")
        
        mock_align.return_value.is_aligned = True
        mock_align.return_value.is_aligned = True

        # Mock Session and Runner
        mock_session_instance = MagicMock()
        mock_session_instance.id = "test_session_id"
        mock_session_instance.state = MOCK_STATE

        mock_service_instance = MockService.return_value
        # Use AsyncMock for create_session and get_session
        mock_service_instance.create_session = AsyncMock(return_value=mock_session_instance)
        mock_service_instance.get_session = AsyncMock(return_value=mock_session_instance)
        # Runner simulation
        mock_runner_instance = MockRunner.return_value
        async def mock_run_generator(*args, **kwargs):
            yield "event"
        mock_runner_instance.run_async.side_effect = mock_run_generator

        # EXECUTE
        result = await process_single_story(input_payload)

        # ASSERT
        assert result["success"] is False
        assert "delivery_role" in result.get("error", "")

if __name__ == "__main__":
    asyncio.run(test_persona_forced_overwrite_repro())
