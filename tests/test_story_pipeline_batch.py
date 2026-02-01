import pytest
from unittest.mock import MagicMock, patch, AsyncMock, ANY
from typing import Dict, Any, List

from orchestrator_agent.agent_tools.story_pipeline.batch import (
    process_story_batch,
    ProcessBatchInput,
)
from tools.story_query_tools import FeatureForStory
from google.adk.tools import ToolContext

# Mock data
MOCK_PRODUCT_ID = 123
MOCK_PRODUCT_NAME = "Test Product"

@pytest.fixture
def mock_db_session():
    with patch("orchestrator_agent.agent_tools.story_pipeline.batch.Session") as mock_session_cls:
        mock_session = MagicMock()
        mock_session_cls.return_value.__enter__.return_value = mock_session
        yield mock_session

@pytest.fixture
def mock_get_engine():
    with patch("orchestrator_agent.agent_tools.story_pipeline.batch.get_engine") as mock_engine:
        yield mock_engine

@pytest.fixture
def mock_ensure_authority():
    with patch("orchestrator_agent.agent_tools.story_pipeline.batch.ensure_accepted_spec_authority") as mock:
        yield mock

@pytest.fixture
def mock_load_compiled_authority():
    with patch("orchestrator_agent.agent_tools.story_pipeline.batch.load_compiled_authority") as mock:
        # Returns (spec_version, compiled_authority, technical_spec)
        mock.return_value = (MagicMock(), MagicMock(), "Mock Technical Spec")
        yield mock

@pytest.fixture
def mock_process_single_story():
    with patch("orchestrator_agent.agent_tools.story_pipeline.batch.process_single_story", new_callable=AsyncMock) as mock:
        yield mock

@pytest.fixture
def mock_tool_context():
    context = MagicMock(spec=ToolContext)
    context.state = {}
    return context

@pytest.mark.asyncio
async def test_spec_version_validation_fallback(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """If spec_version_id is provided but not found, fall back to auto-resolution."""
    # Setup
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[],
        spec_version_id=999
    )

    # Mock DB to return None for CompiledSpecAuthority lookup
    mock_db_session.exec.return_value.first.return_value = None

    # Mock ensure_accepted_spec_authority to return a valid ID
    mock_ensure_authority.return_value = 101

    # Execute
    result = await process_story_batch(input_data)

    # Verify
    assert result["success"] is True
    # ensure_accepted_spec_authority should be called because the provided ID was invalid
    mock_ensure_authority.assert_called_once()
    assert mock_load_compiled_authority.call_args[1]["spec_version_id"] == 101


@pytest.mark.asyncio
async def test_spec_auto_resolution_from_product_file_path(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """If spec missing, use Product.spec_file_path."""
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[]
    )

    # Mock DB product lookup
    mock_product = MagicMock()
    mock_product.spec_file_path = "specs/test.md"
    mock_product.technical_spec = None
    mock_db_session.exec.return_value.first.return_value = mock_product

    # Execute
    await process_story_batch(input_data)

    # Verify
    mock_ensure_authority.assert_called_once()
    assert mock_ensure_authority.call_args[1]["content_ref"] == "specs/test.md"
    assert mock_ensure_authority.call_args[1]["spec_content"] is None


@pytest.mark.asyncio
async def test_spec_auto_resolution_from_product_content(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """If spec missing and no file path, use Product.technical_spec."""
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[]
    )

    # Mock DB product lookup
    mock_product = MagicMock()
    mock_product.spec_file_path = None
    mock_product.technical_spec = "Raw Spec Content"
    mock_db_session.exec.return_value.first.return_value = mock_product

    # Execute
    await process_story_batch(input_data)

    # Verify
    mock_ensure_authority.assert_called_once()
    assert mock_ensure_authority.call_args[1]["content_ref"] is None
    assert mock_ensure_authority.call_args[1]["spec_content"] == "Raw Spec Content"

@pytest.mark.asyncio
async def test_tool_context_pending_spec_state(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story, mock_tool_context
):
    """Use pending spec from ToolContext state if available."""
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[]
    )

    mock_tool_context.state = {
        "pending_spec_content": "Pending Content",
        "pending_spec_path": "pending/path.md"
    }

    # Mock DB product lookup to return product with no spec, so we fall back to tool_context
    mock_product = MagicMock()
    mock_product.spec_file_path = None
    mock_product.technical_spec = None
    mock_db_session.exec.return_value.first.return_value = mock_product

    # Execute
    await process_story_batch(input_data, tool_context=mock_tool_context)

    mock_ensure_authority.assert_called_once()
    assert mock_ensure_authority.call_args[1]["content_ref"] == "pending/path.md"
    assert mock_ensure_authority.call_args[1]["spec_content"] is None

@pytest.mark.asyncio
async def test_authority_gate_input_rule(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """If both spec_content and content_ref provided, content_ref wins."""
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[],
        spec_content="Ignored Content",
        content_ref="valid/path.md"
    )

    # Execute
    await process_story_batch(input_data)

    # Verify
    mock_ensure_authority.assert_called_once()
    assert mock_ensure_authority.call_args[1]["content_ref"] == "valid/path.md"
    assert mock_ensure_authority.call_args[1]["spec_content"] is None

@pytest.mark.asyncio
async def test_classification_validated_story(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """Valid story goes to validated_stories."""
    feature = FeatureForStory(feature_id=1, feature_title="Feat 1", theme="T", epic="E", theme_id=10, epic_id=20)
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[feature],
        spec_version_id=101
    )

    # Mock DB for theme/epic lookup (return empty to skip lookup logic or mock it properly)
    mock_db_session.exec.return_value.all.return_value = []

    # Mock successful story processing
    mock_process_single_story.return_value = {
        "success": True,
        "is_valid": True,
        "rejected": False,
        "story": {"title": "Story 1", "description": "Desc", "acceptance_criteria": "- AC"},
        "iterations": 2
    }

    # Execute
    result = await process_story_batch(input_data)

    # Verify
    assert len(result["validated_stories"]) == 1
    assert len(result["failed_stories"]) == 0
    assert result["validated_stories"][0]["feature_id"] == 1
    assert result["validated_stories"][0]["story"]["title"] == "Story 1"
    assert result["average_iterations"] == 2.0

@pytest.mark.asyncio
async def test_classification_rejected_story(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """Rejected story goes to failed_stories."""
    feature = FeatureForStory(feature_id=1, feature_title="Feat 1", theme="T", epic="E", theme_id=10, epic_id=20)
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[feature],
        spec_version_id=101
    )

    # Mock rejected story
    mock_process_single_story.return_value = {
        "success": True,
        "is_valid": True, # Technically valid format but rejected by alignment
        "rejected": True,
        "alignment_issues": ["Forbidden capability"],
        "story": {"title": "Bad Story"}
    }

    # Execute
    result = await process_story_batch(input_data)

    # Verify
    assert len(result["validated_stories"]) == 0
    assert len(result["failed_stories"]) == 1
    assert "Forbidden capability" in result["failed_stories"][0]["error"]

@pytest.mark.asyncio
async def test_classification_exception(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """Exception during processing goes to failed_stories."""
    feature = FeatureForStory(feature_id=1, feature_title="Feat 1", theme="T", epic="E", theme_id=10, epic_id=20)
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[feature],
        spec_version_id=101
    )

    # Mock exception
    mock_process_single_story.side_effect = RuntimeError("Processing crashed")

    # Execute
    result = await process_story_batch(input_data)

    # Verify
    assert len(result["validated_stories"]) == 0
    assert len(result["failed_stories"]) == 1
    assert result["failed_stories"][0]["error"] == "Processing crashed"
    assert result["failed_stories"][0]["error_type"] == "RuntimeError"

@pytest.mark.asyncio
async def test_session_state_storage(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story, mock_tool_context
):
    """Validated stories and context are stored in tool_context state."""
    feature = FeatureForStory(feature_id=1, feature_title="Feat 1", theme="T", epic="E", theme_id=10, epic_id=20)
    input_data = ProcessBatchInput(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[feature],
        spec_version_id=101
    )

    mock_process_single_story.return_value = {
        "success": True,
        "is_valid": True,
        "rejected": False,
        "story": {"title": "Story 1", "description": "Desc", "story_points": 3},
    }

    # Execute
    await process_story_batch(input_data, tool_context=mock_tool_context)

    # Verify
    assert "pending_validated_stories" in mock_tool_context.state
    assert len(mock_tool_context.state["pending_validated_stories"]) == 1
    assert mock_tool_context.state["pending_product_id"] == MOCK_PRODUCT_ID
    assert mock_tool_context.state["pending_spec_version_id"] == 101

@pytest.mark.asyncio
async def test_robustness_missing_ids(
    mock_db_session, mock_ensure_authority, mock_load_compiled_authority, mock_process_single_story
):
    """Test that missing theme/epic IDs are resolved from DB lookup."""

    # 1. Setup DB to return Themes/Epics
    mock_theme = MagicMock()
    mock_theme.title = "Theme1"
    mock_theme.theme_id = 100

    mock_epic = MagicMock()
    mock_epic.title = "Epic1"
    mock_epic.epic_id = 200
    mock_epic.theme_id = 100

    # Mock DB queries: first for themes, second for epics
    # Note: earlier calls might happen if spec resolution is needed, but here we provide spec_version_id
    mock_db_session.exec.return_value.all.side_effect = [[mock_theme], [mock_epic]]

    # 2. Create feature with missing IDs (using model_construct to bypass validation)
    feature = FeatureForStory.model_construct(
        feature_id=1,
        feature_title="Feat 1",
        theme="Theme1",
        epic="Epic1",
        theme_id=None,
        epic_id=None,
        sibling_features=[]
    )

    input_data = ProcessBatchInput.model_construct(
        product_id=MOCK_PRODUCT_ID,
        product_name=MOCK_PRODUCT_NAME,
        features=[feature],
        spec_version_id=101,
        # Default other fields
        user_persona="user",
        include_story_points=True,
        recompile=False,
        enable_story_refiner=True,
        max_concurrency=1
    )

    # Mock successful processing
    mock_process_single_story.return_value = {
        "success": True,
        "is_valid": True,
        "story": {"title": "S"},
        "iterations": 1
    }

    # 3. Execute
    await process_story_batch(input_data)

    # 4. Verify process_single_story called with resolved IDs
    call_args = mock_process_single_story.call_args[0][0] # ProcessStoryInput
    assert call_args.theme_id == 100
    assert call_args.epic_id == 200
