
import sys
from pathlib import Path
import pytest
from sqlmodel import Session, select

# Adjust path to include project root
sys.path.insert(0, str(Path(__file__).parent.parent))

from agile_sqlmodel import Product, Team
from orchestrator_agent.agent_tools.sprint_planning.tools import PlanSprintInput

def test_plan_sprint_recovers_from_invalid_team_id(engine):
    """
    Test that plan_sprint_tool handles a non-existent team_id by falling back
    to auto-discovery instead of failing.
    """
    # Patch the module's engine to use the test database
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    # Setup: Create a product in the test database
    with Session(engine) as session:
        product = Product(name="Test Product", description="A test product")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.product_id

        # Verify Team 999 does not exist
        team = session.get(Team, 999)
        assert team is None

    # Action: Call plan_sprint_tool with invalid team_id=999
    from orchestrator_agent.agent_tools.sprint_planning.tools import plan_sprint_tool

    input_data = PlanSprintInput(
        product_id=product_id,
        team_id=999, # INVALID ID
        sprint_goal="Survive the error",
        selected_story_ids=[]
    )

    # Run the tool
    result = plan_sprint_tool(input_data)

    # Assertions
    # 1. The tool should succeed (it previously failed)
    assert result["success"] is True, f"Tool failed with error: {result.get('error')}"

    # 2. It should have a draft
    draft = result.get("draft")
    assert draft is not None

    # 3. The used team_id should NOT be 999
    assert draft["team_id"] != 999

    # 4. Verify the team that WAS used exists and is correct (auto-created default)
    with Session(engine) as session:
        used_team = session.get(Team, draft["team_id"])
        assert used_team is not None
        assert used_team.name == "Team Test Product"


def test_plan_sprint_defaults_duration(engine):
    """
    Test that plan_sprint_tool defaults to 14 days when duration_days is None,
    and correctly reports this in the draft and message.
    """
    # Patch the module's engine to use the test database
    import orchestrator_agent.agent_tools.sprint_planning.tools as sprint_tools
    sprint_tools.engine = engine

    # Setup: Create a product in the test database
    with Session(engine) as session:
        product = Product(name="Duration Test Product", description="Testing duration defaults")
        session.add(product)
        session.commit()
        session.refresh(product)
        product_id = product.product_id

    # Action: Call plan_sprint_tool with duration_days=None
    from orchestrator_agent.agent_tools.sprint_planning.tools import plan_sprint_tool

    input_data = PlanSprintInput(
        product_id=product_id,
        team_id=None,  # Let it auto-create team
        sprint_goal="Test Duration Default",
        selected_story_ids=[],
        duration_days=None
    )

    # Run the tool
    result = plan_sprint_tool(input_data)

    # Assertions
    assert result["success"] is True
    draft = result.get("draft")
    assert draft is not None

    # 1. Check draft contains resolved duration
    assert draft["duration_days"] == 14, f"Expected 14 days in draft, got {draft.get('duration_days')}"

    # 2. Check message contains resolved duration string
    message = result.get("message", "")
    assert "(14 days)" in message, f"Message should contain '(14 days)', got: {message}"
    assert "(None days)" not in message
