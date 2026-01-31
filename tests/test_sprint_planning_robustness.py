
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

        # Verify the warning is in the output message (optional but good)
        # The tool currently prints to stdout/stderr, verifying print output is harder
        # unless captured, but we can verify the behavior via the result.
        # The prompt asked to log a warning (print) which we can't easily assert here
        # without capsys, but the functional result is what matters most.
