import os
import asyncio
from unittest.mock import MagicMock
from orchestrator_agent.agent_tools.story_pipeline.single_story import process_single_story
from orchestrator_agent.agent_tools.story_pipeline.models import ProcessStoryInput

# Patching dependencies manually since we aren't using pytest monkeypatch
import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod

# Mock dependencies
single_story_mod.resolve_spec_version_id = lambda story_input, *args: (story_input, None)
single_story_mod.setup_authority_and_alignment = lambda *args: (
    {"domain": "general"}, "spec", [], [], None
)
single_story_mod.build_initial_state = lambda *args: {}
mock_runner = MagicMock()
mock_runner.agent = MagicMock()
single_story_mod.create_pipeline_runner = lambda *args: (mock_runner, MagicMock())

mock_session_service = MagicMock()
async def async_create(*args, **kwargs):
    m = MagicMock()
    m.id = "sess"
    return m
mock_session_service.create_session = async_create
single_story_mod.InMemorySessionService = MagicMock(return_value=mock_session_service)

async def mock_execute(*args):
    return {}
single_story_mod.execute_pipeline = mock_execute
single_story_mod.process_pipeline_result = lambda *args: {"success": True}

async def run_verification():
    print("Verifying debug dump logic...")
    debug_file = "logs/debug_story_pipeline_input.txt"

    # CASE 1: Default (No Env Var)
    if os.path.exists(debug_file):
        os.remove(debug_file)
    if "STORY_PIPELINE_DEBUG_DUMP" in os.environ:
        del os.environ["STORY_PIPELINE_DEBUG_DUMP"]

    input_data = ProcessStoryInput(
        product_id=1, product_name="P", feature_id=1, feature_title="F",
        theme_id=1, epic_id=1, theme="T", epic="E", spec_version_id=1
    )

    await process_single_story(input_data)

    if os.path.exists(debug_file):
        print("FAIL: Debug file created when disabled.")
    else:
        print("PASS: Debug file NOT created by default.")

    # CASE 2: Enabled via Env Var
    os.environ["STORY_PIPELINE_DEBUG_DUMP"] = "1"
    await process_single_story(input_data)

    if os.path.exists(debug_file):
        print("PASS: Debug file created when enabled.")
    else:
        print("FAIL: Debug file NOT created when enabled.")

if __name__ == "__main__":
    asyncio.run(run_verification())
