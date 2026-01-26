# Implementation Task: Specification Persistence with TDD

## Context

You are working on an Autonomous Agile Management Platform built with Google ADK (Agent Development Kit). The system uses multiple AI agents to simulate Scrum roles and reduce cognitive load for small development teams.

**Current Problem:** Technical specifications are loaded once during project creation but are immediately discarded after the vision agent processes them. Downstream agents (roadmap, user stories) repeatedly ask questions that are already answered in the original specification, causing redundant conversations.

**Solution:** Implement a specification persistence layer that:
1. Stores specifications in the database (file path OR text content)
2. Provides tools for agents to read specifications on-demand
3. Creates backup files for pasted specifications
4. Uses Test-Driven Development (TDD) methodology

---

## Project Structure Reference

```
project_tcc/
├── agile_sqlmodel.py           # SQLModel schemas and DB initialization
├── orchestrator_agent/
│   ├── agent.py               # Root orchestrator with all tools
│   └── instructions.txt       # Orchestrator state machine logic
├── tools/
│   ├── orchestrator_tools.py  # Read-only project query tools
│   └── db_tools.py            # Database mutation tools
├── tests/
│   ├── conftest.py            # Pytest fixtures
│   └── test_*.py              # Existing test files
├── test_specs/                # Sample specification files
│   ├── test_quadra.md         # Arena camera system (10.7KB, ~2.7k tokens)
│   ├── genai_spec.md          # Extraction pipeline spec
│   └── ...
└── specs/                     # NEW: Backup files for pasted specs (you'll create this)
```

---

## Deliverables

You will implement the following with TDD approach (tests first, then implementation):

### 1. **Database Schema Changes**
File: `agile_sqlmodel.py`

Add fields to `Product` table:
- `technical_spec: Optional[str]` - Full text content (use SQLAlchemy `Text()` type)
- `spec_file_path: Optional[str]` - Original file path or generated path
- `spec_loaded_at: Optional[datetime]` - Timestamp when spec was saved

### 2. **New Tool Module**
File: `tools/spec_tools.py` (new file)

Implement two tools:
- `save_project_specification()` - Persist spec to database
- `read_project_specification()` - Retrieve spec for active project

### 3. **Test Suite**
File: `tests/test_spec_persistence.py` (new file)

Comprehensive test coverage with 15+ test cases (see detailed spec below)

### 4. **Integration Updates**
- Add tools to orchestrator agent (`orchestrator_agent/agent.py`)
- Update orchestrator instructions (`orchestrator_agent/instructions.txt`)
- Export tools from modules

### 5. **Directory Creation**
- Create `specs/` directory for backup files

---

## Part 1: Database Schema (agile_sqlmodel.py)

### Changes Required

Locate the `Product` class in `agile_sqlmodel.py` and add these fields:

```python
class Product(SQLModel, table=True):
    # ... existing fields (product_id, name, vision, roadmap, etc.)
    
    # NEW: Specification persistence fields
    technical_spec: Optional[str] = Field(
        default=None,
        sa_column_kwargs={"type_": Text()}  # Use Text for large content (>65KB)
    )
    spec_file_path: Optional[str] = Field(
        default=None,
        description="Path to original spec file or generated backup file"
    )
    spec_loaded_at: Optional[datetime] = Field(
        default=None,
        description="When the specification was saved to this product"
    )
```

**Important:** Import `Text` from SQLAlchemy:
```python
from sqlalchemy import Text
```

### Migration Script

After schema changes, create Alembic migration:

```bash
# If using Alembic (recommended):
alembic revision --autogenerate -m "Add specification fields to Product"
alembic upgrade head

# If using simple SQLModel approach (project's current method):
# The tables will auto-update on next app run (SQLModel creates missing columns)
```

---

## Part 2: Tool Implementation (tools/spec_tools.py)

Create new file `tools/spec_tools.py`:

```python
"""
Specification persistence and retrieval tools.
Handles both file-based and pasted text specifications.

Design:
- save_project_specification: Saves spec to DB, creates backup file if needed
- read_project_specification: Retrieves spec for active project

Usage:
1. User provides spec via file path → Load from file, save path reference
2. User pastes spec text → Save text, create backup file in specs/
3. Agents read spec on-demand using read_project_specification
"""

from pathlib import Path
from typing import Any, Dict, Optional
from datetime import datetime
import re

from sqlmodel import Session
from google.adk.core import ToolContext

from agile_sqlmodel import Product, engine


def save_project_specification(
    params: dict,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Save or update technical specification for a project.
    
    Args:
        params: {
            "product_id": int,        # Required - ID of project to attach spec to
            "spec_source": str,       # Required - "file" or "text"
            "content": str,           # Required - File path OR raw text content
        }
        tool_context: Optional ADK context (not used, for consistency)
    
    Returns:
        {
            "success": bool,
            "product_id": int,
            "spec_saved": bool,
            "spec_path": str,         # Path to file (original or created)
            "spec_size_kb": float,
            "file_created": bool,     # True if backup file was created
            "message": str,
            "error": str,             # Only present if success=False
        }
    
    Behavior:
        - spec_source="file": Load content from file path, save path as-is
        - spec_source="text": Save content to DB, create backup file in specs/
        - Updates existing spec if product already has one
        - Validates file existence and size (<100KB limit)
    
    Examples:
        # From file
        save_project_specification({
            "product_id": 1,
            "spec_source": "file",
            "content": "test_specs/test_quadra.md"
        })
        
        # From pasted text
        save_project_specification({
            "product_id": 1,
            "spec_source": "text",
            "content": "# My Spec\\n## Features\\n- Feature 1"
        })
    """
    # Validate inputs
    product_id = params.get("product_id")
    spec_source = params.get("spec_source")
    content = params.get("content")
    
    if not all([product_id, spec_source, content]):
        return {
            "success": False,
            "error": "Missing required parameters: product_id, spec_source, content"
        }
    
    if spec_source not in ["file", "text"]:
        return {
            "success": False,
            "error": f"Invalid spec_source: '{spec_source}'. Must be 'file' or 'text'"
        }
    
    # Verify product exists
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product {product_id} not found"
            }
        
        # Handle file path source
        if spec_source == "file":
            path = Path(content)
            if not path.exists():
                return {
                    "success": False,
                    "error": f"Specification file not found: {content}"
                }
            
            # Check file size (prevent loading huge files)
            file_size_kb = path.stat().st_size / 1024
            if file_size_kb > 100:
                return {
                    "success": False,
                    "error": f"File too large ({file_size_kb:.1f}KB). Maximum: 100KB"
                }
            
            # Load content
            try:
                spec_text = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                return {
                    "success": False,
                    "error": f"File encoding error. Ensure {content} is UTF-8"
                }
            
            spec_path = content
            file_created = False
        
        # Handle pasted text source
        elif spec_source == "text":
            spec_text = content
            file_size_kb = len(spec_text) / 1024
            
            if file_size_kb > 100:
                return {
                    "success": False,
                    "error": f"Specification too large ({file_size_kb:.1f}KB). Maximum: 100KB"
                }
            
            # Create backup file in specs/ directory
            specs_dir = Path("specs")
            specs_dir.mkdir(exist_ok=True)
            
            # Generate safe filename from product name
            safe_name = re.sub(r'[^\w\s-]', '', product.name.lower())
            safe_name = re.sub(r'[-\s]+', '_', safe_name)
            spec_filename = f"{safe_name}_spec.md"
            spec_path_obj = specs_dir / spec_filename
            
            # Write backup file
            try:
                spec_path_obj.write_text(spec_text, encoding='utf-8')
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to create backup file: {str(e)}"
                }
            
            spec_path = str(spec_path_obj)
            file_created = True
        
        # Check if updating existing spec
        is_update = product.technical_spec is not None
        
        # Save to database
        product.technical_spec = spec_text
        product.spec_file_path = spec_path
        product.spec_loaded_at = datetime.utcnow()
        
        session.add(product)
        session.commit()
        
        action = "updated" if is_update else "saved"
        print(f"[save_project_specification] Spec {action} for '{product.name}' ({file_size_kb:.1f}KB)")
        
        return {
            "success": True,
            "product_id": product_id,
            "spec_saved": True,
            "spec_path": spec_path,
            "spec_size_kb": round(file_size_kb, 2),
            "file_created": file_created,
            "message": f"Specification {action} successfully ({file_size_kb:.1f}KB)",
        }


def read_project_specification(
    params: Any = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Read the technical specification for the active project.
    
    Agents should call this tool BEFORE asking questions to check if
    the answer is already in the specification.
    
    Args:
        params: Not used (for consistency with ADK tool signature)
        tool_context: Required - Must contain active_project in state
    
    Returns:
        {
            "success": bool,
            "spec_content": str,      # Full specification text
            "spec_path": str,         # File path reference
            "token_estimate": int,    # Approximate token count (~chars/4)
            "sections": List[str],    # Extracted markdown headings
            "message": str,
            "error": str,             # Only present if success=False
            "hint": str,              # Optional helpful message
        }
    
    Usage in Agent Instructions:
        Before asking questions, call:
        result = read_project_specification()
        if result["success"]:
            # Search spec_content for relevant info
            # Only ask about missing information
    
    Examples:
        # In agent code (with active project selected)
        spec = read_project_specification(tool_context=context)
        if "authentication" in spec["spec_content"].lower():
            # Extract auth requirements from spec
        else:
            # Ask user about authentication
    """
    if not tool_context or not tool_context.state:
        return {
            "success": False,
            "error": "No context provided. Tool requires active project.",
            "spec_content": None,
        }
    
    state: Dict[str, Any] = tool_context.state
    
    # Check for active project
    active_project = state.get("active_project")
    if not active_project:
        return {
            "success": False,
            "error": "No active project selected. Use select_project first.",
            "spec_content": None,
        }
    
    # Get spec from database
    product_id = active_project.get("product_id")
    with Session(engine) as session:
        product = session.get(Product, product_id)
        if not product or not product.technical_spec:
            return {
                "success": False,
                "error": f"Project '{active_project.get('name')}' has no specification saved",
                "spec_content": None,
                "hint": "Spec may have been created without a specification file. Ask user to provide one.",
            }
        
        # Extract section headings for navigation (markdown ## headings)
        sections = _extract_markdown_sections(product.technical_spec)
        
        # Estimate tokens (rough: 1 token ≈ 4 characters)
        token_estimate = len(product.technical_spec) // 4
        
        print(f"[read_project_specification] Loaded spec for '{product.name}' (~{token_estimate} tokens)")
        
        return {
            "success": True,
            "spec_content": product.technical_spec,
            "spec_path": product.spec_file_path,
            "token_estimate": token_estimate,
            "sections": sections,
            "message": f"Loaded specification (~{token_estimate} tokens, {len(sections)} sections)",
        }


def _extract_markdown_sections(spec_text: str) -> list[str]:
    """
    Extract markdown headings from specification for navigation.
    
    Args:
        spec_text: Full specification text
    
    Returns:
        List of heading texts (without # markers), max 20 items
    
    Examples:
        "# Title\\n## Section 1\\n### Subsection" 
        -> ["Title", "Section 1", "Subsection"]
    """
    import re
    headings = re.findall(r'^#{1,3}\s+(.+)$', spec_text, re.MULTILINE)
    return headings[:20]  # Limit to top 20 for brevity
```

**Export from module:**

Update `tools/__init__.py`:
```python
from tools.spec_tools import (
    save_project_specification,
    read_project_specification,
)

__all__ = [
    # ... existing exports
    "save_project_specification",
    "read_project_specification",
]
```

---

## Part 3: Test Suite (tests/test_spec_persistence.py)

Create comprehensive test file following TDD methodology:

```python
"""
TDD Test Suite for Specification Persistence
Tests written BEFORE implementation (red-green-refactor cycle)

Test Structure:
- TestSaveProjectSpecification: Test save tool (9 tests)
- TestReadProjectSpecification: Test read tool (3 tests)
- TestSpecWorkflowIntegration: End-to-end workflows (2 tests)

Run with: pytest tests/test_spec_persistence.py -v
"""

import pytest
from pathlib import Path
from datetime import datetime
from sqlmodel import Session, select

from agile_sqlmodel import Product, engine
from tools.spec_tools import (
    save_project_specification,
    read_project_specification,
)


# ============================================================================
# Test Class 1: Save Tool
# ============================================================================

class TestSaveProjectSpecification:
    """Test suite for save_project_specification tool"""
    
    def test_save_spec_from_file_path_success(self, db_session, sample_product):
        """
        GIVEN: A project exists and a valid spec file path
        WHEN: save_project_specification is called with spec_source="file"
        THEN: 
            - Spec content is loaded from file and saved to DB
            - Original file path is preserved in DB
            - No new backup file is created
            - Returns success with metadata
        """
        # Arrange
        spec_path = "test_specs/test_quadra.md"
        
        # Act
        result = save_project_specification({
            "product_id": sample_product.product_id,
            "spec_source": "file",
            "content": spec_path,
        })
        
        # Assert - Return value
        assert result["success"] is True
        assert result["spec_saved"] is True
        assert result["spec_path"] == spec_path
        assert result["file_created"] is False
        assert result["spec_size_kb"] > 0
        assert "successfully" in result["message"].lower()
        
        # Assert - Database persistence
        db_session.expire_all()  # Force fresh read
        product = db_session.get(Product, sample_product.product_id)
        assert product.technical_spec is not None
        assert product.spec_file_path == spec_path
        assert len(product.technical_spec) > 1000  # test_quadra.md is ~10KB
        assert product.spec_loaded_at is not None
        assert isinstance(product.spec_loaded_at, datetime)
    
    def test_save_spec_from_pasted_text_success(self, db_session, sample_product):
        """
        GIVEN: A project exists and user provides spec as pasted text
        WHEN: save_project_specification is called with spec_source="text"
        THEN:
            - Spec is saved to DB
            - Backup file is created in specs/ directory
            - File path points to created backup file
            - Backup file contains exact pasted content
        """
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
        assert "specs/" in result["spec_path"]
        assert result["spec_path"].endswith(".md")
        
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
        # Arrange: Create mock context with active project
        context = MockToolContext(state={
            "active_project": {
                "product_id": sample_product_with_spec.product_id,
                "name": sample_product_with_spec.name,
            }
        })
        
        # Act
        result = read_project_specification(tool_context=context)
        
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
        # Arrange: Empty context
        context = MockToolContext(state={})
        
        # Act
        result = read_project_specification(tool_context=context)
        
        # Assert
        assert result["success"] is False
        assert "no active project" in result["error"].lower()
        assert "select_project" in result["error"].lower()
    
    def test_read_spec_project_has_no_spec_error(self, sample_product):
        """
        GIVEN: Project exists but has no specification saved
        WHEN: read_project_specification is called
        THEN: Returns error with hint about providing spec
        """
        # Arrange: Product exists but technical_spec is None
        context = MockToolContext(state={
            "active_project": {
                "product_id": sample_product.product_id,
                "name": sample_product.name,
            }
        })
        
        # Act
        result = read_project_specification(tool_context=context)
        
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
        # Step 1: Create product
        product = Product(name="Arena System", vision="Camera-based compliance system")
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        
        # Step 2: Save spec from file
        save_result = save_project_specification({
            "product_id": product.product_id,
            "spec_source": "file",
            "content": "test_specs/test_quadra.md",
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
        read_result = read_project_specification(tool_context=context)
        
        # Assert: Consistency
        assert read_result["success"] is True
        assert "Sistema Inteligente de Câmeras" in read_result["spec_content"]
        assert read_result["spec_path"] == "test_specs/test_quadra.md"
        assert read_result["token_estimate"] > 2000  # test_quadra.md is ~2.7k tokens
    
    def test_full_workflow_pasted_text_save_and_read(self, db_session):
        """
        GIVEN: User pastes spec instead of providing file path
        WHEN: Full workflow executed (save pasted → read back)
        THEN:
            - Backup file is created in specs/
            - Spec is readable with exact content
            - File cleanup works
        """
        # Step 1: Create product
        product = Product(name="Pasted Project", vision="Test vision")
        db_session.add(product)
        db_session.commit()
        db_session.refresh(product)
        
        # Step 2: Save pasted spec
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
        read_result = read_project_specification(tool_context=context)
        
        # Assert: Content matches exactly
        assert read_result["success"] is True
        assert read_result["spec_content"] == pasted_text
        assert "Pasted Specification" in read_result["spec_content"]
        assert len(read_result["sections"]) == 2  # Two headings
        
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
        spec_loaded_at=datetime.utcnow(),
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    return product


@pytest.fixture
def db_session():
    """Create a fresh database session for each test"""
    with Session(engine) as session:
        yield session
        session.rollback()  # Rollback any uncommitted changes


class MockToolContext:
    """Mock Google ADK ToolContext for testing without full ADK runtime"""
    def __init__(self, state: dict):
        self.state = state
```

---

## Part 4: Integration with Orchestrator

### 4.1 Add Tools to Orchestrator Agent

File: `orchestrator_agent/agent.py`

```python
# Add imports at top of file
from tools.spec_tools import (
    save_project_specification,
    read_project_specification,
)

# In root_agent definition, add to tools list:
root_agent = Agent(
    name="orchestrator_agent",
    model=model,
    tools=[
        # ... existing tools
        count_projects,
        list_projects,
        
        # NEW: Specification tools
        save_project_specification,
        read_project_specification,
        
        # ... rest of tools
    ],
    # ... rest of config
)
```

### 4.2 Update Orchestrator Instructions

File: `orchestrator_agent/instructions.txt`

Find **STATE 4 — ROUTING MODE** section and update the "New Project with Specification File" subsection:

```markdown
## STATE 4 — ROUTING MODE (New/Other)

**Trigger:** Start of conversation, or User changes topic.

**Routing Logic:**

3. **New Project with Specification File:** User says "start new project" AND provides a file path
   - **Extract file path** from user message (look for patterns: `*.md`, `*.txt`, `docs/...`, `C:\...`)
   - **Load content:** Call `load_specification_from_file(file_path=<extracted_path>)` → spec_content
   - **Store in state:** Save to `tool_context.state["pending_spec_content"]` and `state["pending_spec_path"]`
   - **Pass to vision agent:** Call `product_vision_tool(user_raw_text=spec_content, prior_vision_state="NO_HISTORY")`
   - When vision is approved and saved:
     a. Call `save_vision_tool(...)` → creates product, returns product_id
     b. Immediately call `save_project_specification(product_id=<new_id>, spec_source="file", content=<file_path>)`
     c. Confirm: "Project and specification saved successfully. Specification loaded from {file_path}"
   - **STOP** and ask what to do next

4. **New Project with Pasted Content:** `"start"`, `"new"`, `"create"`, `"vision"` with no file path mentioned
   - User provides pasted specification text directly in message
   - Call: `product_vision_tool(user_raw_text=<pasted_text>, prior_vision_state="NO_HISTORY")`
   - **Store pasted content:** Save to `tool_context.state["pending_spec_content"] = <pasted_text>`
   - When vision is approved:
     a. Call `save_vision_tool(...)`
     b. Call `save_project_specification(product_id=<new_id>, spec_source="text", content=<pasted_text>)`
     c. System will create backup file: `specs/{project_name}_spec.md`
     d. Confirm: "Project saved. Specification backed up to {backup_path}"
```

---

## Part 5: Agent Instructions Update (For Future Use)

Create template for agents to use `read_project_specification`:

File: `docs/SPEC_FIRST_AGENT_TEMPLATE.md` (for reference)

```markdown
# SPECIFICATION ACCESS PROTOCOL

You have access to `read_project_specification` tool to read the project's technical specification.

## MANDATORY: Check Spec First

BEFORE asking ANY clarifying question:
1. Call `read_project_specification()`
2. Search the returned `spec_content` for relevant information
3. Quote relevant sections in your response
4. ONLY ask about information that is:
   - Completely missing from spec
   - Ambiguous in spec (provide 2-3 interpretations and ask which is correct)
   - Contradictory in spec (quote conflicting sections and ask for resolution)

## Example Decision Flow

❌ BAD (blind questioning):
```
User: "Create roadmap"
Agent: "What features do you want to build?"
```

✅ GOOD (spec-first):
```
User: "Create roadmap"
Agent: [calls read_project_specification()]
Agent: "I reviewed the specification (10.7KB, 2,694 tokens) and found:

📋 EXTRACTED FROM SPEC:
- Section 2: 5 core system objectives defined
- Section 7: Compliance rules fully specified (3 operational modes)
- Section 9: Computer vision approach detailed

PROPOSED THEMES:
1. Real-time Occupancy Monitoring (Spec: Section 9)
2. Compliance Detection (Spec: Section 7)
3. Integration Layer (Spec: Sections 3.2, 3.3)

❓ CLARIFICATIONS NEEDED:
- Priority order? (All seem equally critical in Section 13)
- Enrollment sync frequency? (Spec says 'quase estática' but no interval)

Would you like to confirm this roadmap structure?"
```

## When to Skip Reading Spec

- User explicitly says "ignore spec" or "different approach"
- You already read it earlier in conversation (check history)
- Project has no spec (tool returns success=false)
- Question is about user preferences, not technical requirements

## Output Traceability

When creating artifacts, include spec references:

```json
{
  "theme_name": "Compliance Detection",
  "spec_references": [
    "Section 7: Regras de Conformidade",
    "Section 4: Classificação de Modo"
  ],
  "spec_derived": true,
  "assumptions": []
}
```

If you make assumptions NOT in spec:
```json
{
  "assumptions": [
    {
      "assumption": "Cooldown applies per-court, not globally",
      "reason": "Spec says 'cooldown_minutes=5' but doesn't specify scope",
      "confidence": "medium"
    }
  ]
}
```
```

---

## TDD Workflow Instructions

Follow strict TDD (red-green-refactor) methodology:

### Step 1: Run Tests First (RED)
```bash
# All tests should FAIL initially (code doesn't exist yet)
pytest tests/test_spec_persistence.py -v

# Expected: ImportError or function not found errors
```

### Step 2: Implement Minimum Code to Pass (GREEN)

Implement in order:
1. Database schema changes (run app to create columns)
2. `save_project_specification` - implement minimal version
3. Run save tests: `pytest tests/test_spec_persistence.py::TestSaveProjectSpecification -v`
4. Fix failures one by one until all green
5. Implement `read_project_specification`
6. Run read tests: `pytest tests/test_spec_persistence.py::TestReadProjectSpecification -v`
7. Fix until green
8. Run integration tests: `pytest tests/test_spec_persistence.py::TestSpecWorkflowIntegration -v`

### Step 3: Refactor (REFACTOR)
- Clean up code
- Add docstrings
- Extract helper functions
- Re-run tests to ensure still passing

### Step 4: Full Test Suite
```bash
# Run ALL tests to ensure no regressions
pytest tests/test_spec_persistence.py -v

# Expected output:
# ===== 14 passed in X.XXs =====
```

---

## Acceptance Criteria

Before marking this task complete, verify:

- ✅ All 14+ tests pass
- ✅ Database migration successful (3 new columns in Product table)
- ✅ `specs/` directory created
- ✅ Manual test: Save spec from file (`test_specs/test_quadra.md`)
- ✅ Manual test: Save spec from pasted text
- ✅ Manual test: Read spec back with active project
- ✅ Tools appear in orchestrator agent tools list
- ✅ Orchestrator instructions updated for new workflow
- ✅ No breaking changes to existing tests

---

## Manual Testing Script

After implementation, test manually:

```python
# In Python REPL or notebook

from sqlmodel import Session, select
from agile_sqlmodel import Product, engine
from tools.spec_tools import save_project_specification, read_project_specification

# 1. Create test product
with Session(engine) as session:
    product = Product(name="Manual Test", vision="Test vision")
    session.add(product)
    session.commit()
    session.refresh(product)
    print(f"Created product ID: {product.product_id}")

# 2. Test save from file
result = save_project_specification({
    "product_id": product.product_id,
    "spec_source": "file",
    "content": "test_specs/test_quadra.md"
})
print("Save from file:", result)
assert result["success"] is True

# 3. Test read
class MockContext:
    def __init__(self):
        self.state = {
            "active_project": {
                "product_id": product.product_id,
                "name": "Manual Test"
            }
        }

context = MockContext()
result = read_project_specification(tool_context=context)
print("Read result:", {
    "success": result["success"],
    "token_estimate": result.get("token_estimate"),
    "sections_count": len(result.get("sections", []))
})
assert result["success"] is True
assert "Câmeras" in result["spec_content"]  # Portuguese content check

print("\n✅ All manual tests passed!")
```

---

## Edge Cases to Handle

1. **Unicode/Special Characters:** Ensure UTF-8 encoding everywhere
2. **Long Product Names:** Filename generation must handle spaces, special chars
3. **Concurrent Updates:** Last write wins (acceptable for MVP)
4. **Missing specs/ Directory:** Create automatically with `mkdir(exist_ok=True)`
5. **Existing Backup File:** Overwrite silently (update scenario)

---

## Questions to Ask if Unclear

- Should we version specifications (keep history)?
- Should we validate spec content (e.g., must be markdown)?
- Should we extract metadata (keywords, entities) during save?
- Should agents auto-read spec or require explicit instruction?

**For MVP, answers are:**
- No versioning (simple replacement)
- No content validation (accept any text)
- No metadata extraction (raw storage only)
- Agents must explicitly call read tool (per instructions)

---

## Success Metrics

Implementation is successful when:
1. All tests pass (100% green)
2. Zero regressions in existing tests
3. Manual workflow works end-to-end
4. Code follows existing patterns in codebase
5. Documentation is clear and complete

---

## Final Notes

- This is a foundational feature for the TCC research project
- Quality matters more than speed - follow TDD strictly
- Ask questions if spec is ambiguous
- Test edge cases thoroughly
- Keep it simple - no premature optimization

Good luck! 🚀
