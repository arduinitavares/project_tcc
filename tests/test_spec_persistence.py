"""
TDD Test Suite for Specification Persistence
Tests written BEFORE implementation (red-green-refactor cycle)

Test Structure:
- TestSaveProjectSpecification: Test save tool
- TestReadProjectSpecification: Test read tool
- TestSpecWorkflowIntegration: End-to-end workflows

Run with: pytest tests/test_spec_persistence.py -v
"""

import pytest
from pathlib import Path
from datetime import datetime, timezone
from sqlmodel import Session, select

from agile_sqlmodel import Product, engine
from unittest.mock import patch

# These imports will fail initially (Red phase)
try:
    from tools.spec_tools import (
        save_project_specification,
        read_project_specification,
    )
except ImportError as e:
    print(f"ImportError importing tools.spec_tools: {e}")
    # Allow tests to be collected even if module doesn't exist yet
    save_project_specification = None
    read_project_specification = None


@pytest.fixture()
def compile_stub(monkeypatch):
    """Stub authority compilation to avoid LLM calls and track invocations."""
    calls = {}

    def _stub(params, tool_context=None):
        calls["params"] = params
        return {
            "success": True,
            "spec_version_id": 1,
            "authority_id": 99,
        }

    monkeypatch.setattr(
        "tools.spec_tools.update_spec_and_compile_authority",
        _stub,
    )
    return calls


# ============================================================================
# Test Fixtures & Setup
# ============================================================================

@pytest.fixture(autouse=True)
def patch_engine(engine):
    """Patch the engine in spec_tools to use the test database engine"""
    with patch("tools.spec_tools.get_engine", return_value=engine):
        yield


# ============================================================================
# Test Class 1: Save Tool
# ============================================================================

class TestSaveProjectSpecification:
    """Test suite for save_project_specification tool"""

    def test_save_spec_from_file_path_success(
        self, db_session, sample_product, compile_stub
    ):
        """
        GIVEN: A project exists and a valid spec file path
        WHEN: save_project_specification is called with spec_source="file"
        THEN:
            - Spec content is loaded from file and saved to DB
            - Original file path is preserved in DB
            - No new backup file is created
            - Returns success with metadata
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange
        # Create a dummy spec file for testing if it doesn't exist
        spec_dir = Path("test_specs")
        spec_dir.mkdir(exist_ok=True)
        spec_path = spec_dir / "test_quadra.md"
        if not spec_path.exists():
            spec_path.write_text("# Sistema Inteligente de Câmeras\n\nContent...", encoding="utf-8")

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "file",
            "content": str(spec_path),
        })

        # Assert - Return value
        assert result["success"] is True
        assert result["spec_saved"] is True
        assert result["spec_path"] == str(spec_path)
        assert result["file_created"] is False
        assert result["spec_size_kb"] > 0
        assert result["compile_success"] is True
        assert result["authority_id"] == 99
        assert "successfully" in result["message"].lower()

        assert "params" in compile_stub

        # Assert - Database persistence
        db_session.expire_all()  # Force fresh read
        product = db_session.get(Product, sample_product.product_id)
        assert product.technical_spec is not None
        assert product.spec_file_path == str(spec_path)
        assert len(product.technical_spec) > 0
        assert product.spec_loaded_at is not None
        assert isinstance(product.spec_loaded_at, datetime)

    def test_save_spec_from_pasted_text_success(
        self, db_session, sample_product, compile_stub
    ):
        """
        GIVEN: A project exists and user provides spec as pasted text
        WHEN: save_project_specification is called with spec_source="text"
        THEN:
            - Spec is saved to DB
            - Backup file is created in specs/ directory
            - File path points to created backup file
            - Backup file contains exact pasted content
            - Filename includes product_id
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange
        pasted_spec = """# My Product Specification
## Features
- Feature 1: User authentication
- Feature 2: Dashboard

## Technical Stack
- Python 3.11
- FastAPI
"""

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "text",
            "content": pasted_spec,
        })

        # Assert - Return value
        assert result["success"] is True
        assert result["file_created"] is True
        assert result["compile_success"] is True
        assert result["authority_id"] == 99
        # Check path contains specs dir (cross-platform: handles both / and \)
        assert "specs" in result["spec_path"]
        assert result["spec_path"].endswith(".md")

        assert "params" in compile_stub

        # Check filename pattern (should contain product_id)
        assert str(sample_product.product_id) in result["spec_path"]

        # Assert - Backup file was created
        created_file = Path(result["spec_path"])
        assert created_file.exists()
        assert created_file.read_text(encoding='utf-8') == pasted_spec

        # Assert - Database
        db_session.expire_all()
        product = db_session.get(Product, sample_product.product_id)
        assert product.technical_spec == pasted_spec
        assert product.spec_file_path == result["spec_path"]

        # Cleanup
        created_file.unlink()

    def test_save_spec_file_not_found_error(self, sample_product):
        """
        GIVEN: User provides invalid/nonexistent file path
        WHEN: save_project_specification is called
        THEN: Returns error with clear message, database not modified
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "file",
            "content": "nonexistent/path/spec.md",
        })

        # Assert
        assert result["success"] is False
        assert "not found" in result["error"].lower()
        assert "nonexistent/path/spec.md" in result["error"]

    def test_save_spec_file_too_large_error(self, tmp_path, sample_product):
        """
        GIVEN: Spec file exceeds size limit (100KB)
        WHEN: save_project_specification is called
        THEN: Returns error about file size, rejects operation
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Create 150KB file
        large_file = tmp_path / "large_spec.md"
        large_file.write_text("X" * 150_000, encoding='utf-8')

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "file",
            "content": str(large_file),
        })

        # Assert
        assert result["success"] is False
        assert "too large" in result["error"].lower()
        assert "100" in result["error"]  # Mentions limit

    def test_save_spec_pasted_text_too_large_error(self, sample_product):
        """
        GIVEN: Pasted text exceeds 100KB limit
        WHEN: save_project_specification is called with spec_source="text"
        THEN: Returns error, does not create file or save to DB
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Create 150KB text
        huge_text = "X" * 150_000

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "text",
            "content": huge_text,
        })

        # Assert
        assert result["success"] is False
        assert "too large" in result["error"].lower()

    def test_update_existing_spec_replaces_old_spec(self, db_session, sample_product):
        """
        GIVEN: Project already has a spec saved
        WHEN: save_project_specification is called with new spec
        THEN:
            - Old spec is completely replaced
            - Message indicates "updated" not "saved"
            - spec_loaded_at timestamp is updated
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Save initial spec
        initial_spec = "# Initial Spec\n## Version 1"
        save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "text",
            "content": initial_spec,
        })

        # Wait a moment to ensure timestamp difference
        import time
        time.sleep(0.1)

        # Act: Update with new spec
        new_spec = "# Updated Spec\n## Version 2\n\nCompletely new content"
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "text",
            "content": new_spec,
        })

        # Assert
        assert result["success"] is True
        assert "updated" in result["message"].lower()

        # Verify DB has new content (not old)
        db_session.expire_all()
        product = db_session.get(Product, sample_product.product_id)
        assert product.technical_spec == new_spec
        assert "Version 2" in product.technical_spec
        assert "Version 1" not in product.technical_spec

        # Cleanup
        Path(result["spec_path"]).unlink(missing_ok=True)

    def test_save_spec_invalid_product_id_error(self):
        """
        GIVEN: Invalid/nonexistent product_id
        WHEN: save_project_specification is called
        THEN: Returns error about product not found
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Act
        result = save_project_specification({
            "product_id": 99999,
            "spec_source": "text",
            "content": "# Some Spec",
        })

        # Assert
        assert result["success"] is False
        assert "not found" in result["error"].lower()
        assert "99999" in result["error"]

    def test_save_spec_missing_parameters_error(self):
        """
        GIVEN: Required parameters are missing
        WHEN: save_project_specification is called
        THEN: Returns error listing missing parameters
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Act - Missing content
        result1 = save_project_specification({
            "product_id": 1,
            "spec_source": "file",
        })

        # Act - Missing spec_source
        result2 = save_project_specification({
            "product_id": 1,
            "content": "# Spec",
        })

        # Assert
        assert result1["success"] is False
        assert "missing" in result1["error"].lower()

        assert result2["success"] is False
        assert "missing" in result2["error"].lower()

    def test_save_spec_invalid_spec_source_error(self, sample_product):
        """
        GIVEN: spec_source is neither "file" nor "text"
        WHEN: save_project_specification is called
        THEN: Returns error about invalid spec_source
        """
        if not save_project_specification:
            pytest.fail("Tool not implemented yet")

        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "invalid_value",
            "content": "# Spec",
        })

        # Assert
        assert result["success"] is False
        assert "invalid spec_source" in result["error"].lower()
        assert "must be 'file' or 'text'" in result["error"].lower()


# ============================================================================
# Test Class 2: Read Tool
# ============================================================================

class TestReadProjectSpecification:
    """Test suite for read_project_specification tool"""

    def test_read_existing_spec_success(self, db_session, sample_product_with_spec):
        """
        GIVEN: Project has spec saved in DB
        WHEN: read_project_specification is called with active project in context
        THEN:
            - Returns spec content with metadata
            - Extracts section headings from markdown
            - Calculates token estimate
        """
        if not read_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Create mock context with active project
        context = MockToolContext(state={
            "active_project": {
                "product_id": sample_product_with_spec.product_id,
                "name": sample_product_with_spec.name,
            }
        })

        # Act
        result = read_project_specification({}, context)

        # Assert
        assert result["success"] is True
        assert result["spec_content"] is not None
        assert len(result["spec_content"]) > 0
        assert result["token_estimate"] > 0
        assert result["token_estimate"] == len(result["spec_content"]) // 4  # Approx formula
        assert len(result["sections"]) > 0  # Has extracted headings
        assert result["spec_path"] is not None
        assert "loaded" in result["message"].lower()

    def test_read_spec_no_active_project_error(self):
        """
        GIVEN: No active project is selected in context
        WHEN: read_project_specification is called
        THEN: Returns error with helpful message about selecting project
        """
        if not read_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Empty context
        context = MockToolContext(state={})

        # Act
        result = read_project_specification({}, context)

        # Assert
        assert result["success"] is False
        # If state is empty, it might fail "No context provided" check or "No active project" check
        # Both are valid failure modes for this test case
        error_msg = result["error"].lower()
        assert "no active project" in error_msg or "no context provided" in error_msg

    def test_read_spec_project_has_no_spec_error(self, sample_product):
        """
        GIVEN: Project exists but has no specification saved
        WHEN: read_project_specification is called
        THEN: Returns error with hint about providing spec
        """
        if not read_project_specification:
            pytest.fail("Tool not implemented yet")

        # Arrange: Product exists but technical_spec is None
        context = MockToolContext(state={
            "active_project": {
                "product_id": sample_product.product_id,
                "name": sample_product.name,
            }
        })

        # Act
        result = read_project_specification({}, context)

        # Assert
        assert result["success"] is False
        assert "no specification saved" in result["error"].lower()
        assert "hint" in result
        assert "ask user" in result["hint"].lower()


# ============================================================================
# Test Class 3: Integration Workflows
# ============================================================================

class TestSpecWorkflowIntegration:
    """Integration tests for complete spec workflows"""

    def test_full_workflow_file_save_and_read(self, db_session):
        """
        GIVEN: New project creation workflow
        WHEN: User loads spec from file, saves project, then reads spec back
        THEN: Entire workflow succeeds with data consistency
        """
        if not save_project_specification or not read_project_specification:
            pytest.fail("Tools not implemented yet")

        # Step 1: Create product
        product = Product(name="Arena System", vision="Camera-based compliance system")
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)

        # Ensure dummy file exists
        spec_dir = Path("test_specs")
        spec_dir.mkdir(exist_ok=True)
        spec_path = spec_dir / "test_quadra.md"
        if not spec_path.exists():
             spec_path.write_text("# Sistema Inteligente de Câmeras\n\nContent...", encoding="utf-8")

        # Step 2: Save spec from file
        save_result = save_project_specification({
            "product_id": product.product_id,
            "spec_source": "file",
            "content": str(spec_path),
        })
        assert save_result["success"] is True
        assert save_result["file_created"] is False  # Using original file

        # Step 3: Read spec back
        context = MockToolContext(state={
            "active_project": {
                "product_id": product.product_id,
                "name": product.name,
            }
        })
        read_result = read_project_specification({}, context)

        # Assert: Consistency
        assert read_result["success"] is True
        assert "Sistema Inteligente de Câmeras" in read_result["spec_content"]
        assert read_result["spec_path"] == str(spec_path)
        assert read_result["token_estimate"] > 0

    def test_full_workflow_pasted_text_save_and_read(self, db_session):
        """
        GIVEN: User pastes spec instead of providing file path
        WHEN: Full workflow executed (save pasted -> read back)
        THEN:
            - Backup file is created in specs/
            - Spec is readable with exact content
            - File cleanup works
        """
        if not save_project_specification or not read_project_specification:
            pytest.fail("Tools not implemented yet")

        # Step 1: Create product
        product = Product(name="Pasted Project", vision="Test vision")
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)

        # Step 2: Save pasted spec

    def test_save_project_specification_sets_pending_state(self, db_session, tmp_path):
        """save_project_specification should persist pending spec state for downstream tools."""
        product = Product(name="Spec Pending Project", vision="Pending spec")
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)

        spec_path = tmp_path / "pending_spec.md"
        spec_path.write_text("# Pending Spec\n\nContent", encoding="utf-8")

        context = MockToolContext(state={})

        result = save_project_specification(
            {
                "product_id": product.product_id,
                "spec_source": "file",
                "content": str(spec_path),
            },
            tool_context=context,
        )

        assert result["success"] is True
        assert context.state["pending_spec_path"] == str(spec_path)
        assert "Pending Spec" in context.state["pending_spec_content"]
        pasted_text = """# Pasted Specification
## Section 1: Overview
This is a test specification pasted by the user.

## Section 2: Features
- Feature A
- Feature B
"""
        save_result = save_project_specification({
            "product_id": product.product_id,
            "spec_source": "text",
            "content": pasted_text,
        })
        assert save_result["success"] is True
        assert save_result["file_created"] is True

        # Step 3: Verify backup file exists
        backup_path = Path(save_result["spec_path"])
        assert backup_path.exists()
        assert backup_path.read_text(encoding='utf-8') == pasted_text

        # Step 4: Read back from DB
        context = MockToolContext(state={
            "active_project": {
                "product_id": product.product_id,
                "name": "Pasted Project",
            }
        })
        read_result = read_project_specification({}, context)

        # Assert: Content matches exactly
        assert read_result["success"] is True
        assert read_result["spec_content"] == pasted_text
        assert "Pasted Specification" in read_result["spec_content"]
        assert len(read_result["sections"]) == 3  # H1 + two H2s

        # Cleanup
        backup_path.unlink()


# ============================================================================
# Fixtures
# ============================================================================

@pytest.fixture
def sample_product(db_session):
    """Create a test product WITHOUT specification"""
    product = Product(
        name="Test Product",
        vision="A test product for unit testing"
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def sample_product_with_spec(db_session):
    """Create a test product WITH specification already saved"""
    product = Product(
        name="Product With Spec",
        vision="Test vision for product with spec",
        technical_spec="""# Test Specification
## Section 1: Introduction
This is a test specification.

## Section 2: Features
- Feature A
- Feature B

## Section 3: Technical Details
Stack: Python, FastAPI
""",
        spec_file_path="specs/test_spec.md",
        spec_loaded_at=datetime.now(timezone.utc),
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def db_session(session):  # Re-use session fixture from conftest.py
    """Use the session provided by conftest.py"""
    yield session
    # No rollback needed as conftest handles it or we're using in-memory db


class MockToolContext:
    """Mock Google ADK ToolContext for testing without full ADK runtime"""
    def __init__(self, state: dict):
        self.state = state
