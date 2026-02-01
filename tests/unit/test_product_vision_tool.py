from unittest.mock import MagicMock, patch
from sqlmodel import Session, select
from agile_sqlmodel import Product
from orchestrator_agent.agent_tools.product_vision_tool.tools import save_vision_tool, SaveVisionInput
from google.adk.tools import ToolContext

def test_save_vision_tool_creates_project_and_returns_dict(engine):
    """Test that save_vision_tool creates a project and returns the correct dictionary structure."""
    
    # Mock ToolContext
    tool_context = MagicMock(spec=ToolContext)
    tool_context.state = {}

    # Input data
    vision_input = SaveVisionInput(
        project_name="New Test Project",
        product_vision_statement="A vision for the future."
    )

    # Patch get_engine to use our test fixture engine
    with patch("orchestrator_agent.agent_tools.product_vision_tool.tools.get_engine", return_value=engine):
        result = save_vision_tool(vision_input, tool_context)

    # Verify result structure
    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["project_name"] == "New Test Project"
    assert "product_id" in result
    assert isinstance(result["product_id"], int)
    assert "SUCCESS: Created project" in result["message"]

    # Verify DB state
    with Session(engine) as session:
        product = session.exec(select(Product).where(Product.name == "New Test Project")).first()
        assert product is not None
        assert product.product_id == result["product_id"]
        assert product.vision == "A vision for the future."

    # Verify context update
    assert tool_context.state["current_project_name"] == "New Test Project"

def test_save_vision_tool_updates_existing_project(engine):
    """Test that save_vision_tool updates an existing project and returns the ID."""
    
    # Pre-populate DB
    with Session(engine) as session:
        existing_project = Product(name="Existing Project", vision="Old vision")
        session.add(existing_project)
        session.commit()
        original_id = existing_project.product_id

    # Mock ToolContext
    tool_context = MagicMock(spec=ToolContext)
    tool_context.state = {}

    # Input data
    vision_input = SaveVisionInput(
        project_name="Existing Project",
        product_vision_statement="New Updated Vision"
    )

    # Patch get_engine
    with patch("orchestrator_agent.agent_tools.product_vision_tool.tools.get_engine", return_value=engine):
        result = save_vision_tool(vision_input, tool_context)

    # Verify result
    assert result["success"] is True
    assert result["product_id"] == original_id
    assert "SUCCESS: Updated project" in result["message"]

    # Verify DB update
    with Session(engine) as session:
        product = session.exec(select(Product).where(Product.name == "Existing Project")).first()
        assert product.vision == "New Updated Vision"
