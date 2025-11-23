"""
Orchestrator workflow tests - demonstrates the decision flow.
"""

import pytest

from orchestrator import Orchestrator, OrchestratorState


@pytest.mark.asyncio
async def test_orchestrator_init_no_projects(engine):
    """Test orchestrator initialization with empty database."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    orchestrator = Orchestrator()
    intro_message = await orchestrator.initialize()

    assert "don't see any projects" in intro_message.lower()
    assert orchestrator.state.phase == "new_project_intro"
    assert len(orchestrator.state.available_projects) == 0


@pytest.mark.asyncio
async def test_orchestrator_init_with_projects(engine):
    """Test orchestrator initialization with existing projects."""
    import tools.orchestrator_tools as orch_tools

    orch_tools.engine = engine

    import tools.db_tools as db_tools
    from tools.db_tools import create_or_get_product

    db_tools.engine = engine

    # Create some projects
    create_or_get_product(product_name="Project A", vision="Vision A")
    create_or_get_product(product_name="Project B", vision="Vision B")

    orchestrator = Orchestrator()
    intro_message = await orchestrator.initialize()

    assert "2" in intro_message or "found 2" in intro_message.lower()
    assert orchestrator.state.phase == "selection"
    assert len(orchestrator.state.available_projects) == 2


def test_orchestrator_state_serialization():
    """Test that orchestrator state can be saved/loaded."""
    state = OrchestratorState(
        phase="phase_1",
        selected_project_id=1,
        selected_phase="1",
        available_projects=[
            {"product_id": 1, "name": "Project A", "user_stories_count": 5}
        ],
        conversation_history=[
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ],
    )

    # Should be serializable to JSON (useful for DatabaseSessionService)
    state_dict = state.model_dump()

    assert state_dict["phase"] == "phase_1"
    assert state_dict["selected_project_id"] == 1
    assert len(state_dict["conversation_history"]) == 2

    # Should be deserializable
    restored_state = OrchestratorState(**state_dict)
    assert restored_state.phase == "phase_1"
    assert restored_state.selected_project_id == 1
