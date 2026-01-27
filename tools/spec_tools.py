"""
Specification persistence and retrieval tools.
Handles both file-based and pasted text specifications.

Design:
- save_project_specification: Saves spec to DB, creates backup file if needed
- read_project_specification: Retrieves spec for active project

Usage:
1. User provides spec via file path -> Load from file, save path reference
2. User pastes spec text -> Save text, create backup file in specs/
3. Agents read spec on-demand using read_project_specification
"""

from pathlib import Path
from typing import Any, Dict, Optional, List
from datetime import datetime, timezone
import re

from sqlmodel import Session
from google.adk.tools import ToolContext
from pydantic import BaseModel, Field

from agile_sqlmodel import Product, engine


# --- Input Schemas ---


class SaveProjectSpecificationInput(BaseModel):
    """Input schema for save_project_specification tool."""

    product_id: int = Field(description="ID of project to attach specification to")
    spec_source: str = Field(
        description='Source type: "file" (load from file path) or "text" (pasted content)'
    )
    content: str = Field(
        description="File path (if spec_source='file') or raw text content (if spec_source='text')"
    )


class ReadProjectSpecificationInput(BaseModel):
    """Input schema for read_project_specification tool.
    
    This tool requires no parameters - it reads the spec for the active project
    from tool_context.state['active_project'].
    """


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
        tool_context: Optional ADK context (not used internally, for signature consistency)

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
    try:
        parsed = SaveProjectSpecificationInput.model_validate(params or {})
    except Exception as e:
        return {
            "success": False,
            "error": f"Invalid parameters: {str(e)}"
        }
    
    product_id = parsed.product_id
    spec_source = parsed.spec_source
    content = parsed.content

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

            # Generate safe filename from product name + product_id (guarantee unique)
            safe_name = re.sub(r'[^\w\s-]', '', product.name.lower())
            safe_name = re.sub(r'[-\s]+', '_', safe_name)
            spec_filename = f"{safe_name}_{product_id}_spec.md"
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
        product.spec_loaded_at = datetime.now(timezone.utc)

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
    params: Any,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Read the technical specification for the active project.

    Agents should call this tool BEFORE asking questions to check if
    the answer is already in the specification.

    Args:
        params: Not used (for consistency with ADK tool signature)
        tool_context: Optional - Must contain active_project in state (when called by agent)

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
        spec = read_project_specification({}, tool_context=context)
        if "authentication" in spec["spec_content"].lower():
            # Extract auth requirements from spec
        else:
            # Ask user about authentication
    """
    # Validate inputs (no params needed, but validate for consistency)
    ReadProjectSpecificationInput.model_validate(params or {})
    
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

        # Estimate tokens (rough: 1 token approx 4 characters)
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


def _extract_markdown_sections(spec_text: str) -> List[str]:
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
    headings = re.findall(r'^#{1,3}\s+(.+)$', spec_text, re.MULTILINE)
    return headings[:20]  # Limit to top 20 for brevity
