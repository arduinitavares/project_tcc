"""
Specification persistence and retrieval tools.
Handles both file-based and pasted text specifications.

Design:
- save_project_specification: Saves spec to DB, creates backup file if needed
- read_project_specification: Retrieves spec for active project

Specification Authority v1 (NEW):
- register_spec_version: Create versioned spec with hash
- approve_spec_version: Explicit approval gate
- compile_spec_authority: Extract and cache spec authority (LLM-based)
- check_spec_authority_status: Status check (CURRENT/STALE/NOT_COMPILED/PENDING_REVIEW)
- get_compiled_authority_by_version: Deterministic retrieval

Usage:
1. User provides spec via file path -> Load from file, save path reference
2. User pastes spec text -> Save text, create backup file in specs/
3. Agents read spec on-demand using read_project_specification
"""

from pathlib import Path
from typing import Any, Dict, Optional, List, Union, Literal
from datetime import datetime, timezone
import re
import hashlib
import json
import asyncio
import threading
import logging

from sqlmodel import Session, select
from google.adk.tools import ToolContext
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from agile_sqlmodel import (
    Product,
    SpecRegistry,
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecAuthorityStatus,
    UserStory,
    get_engine,
)

from utils.schemes import (
    ValidationEvidence,
    ValidationFailure,
    AlignmentFinding,
    SpecAuthorityCompilerInput,
    SpecAuthorityCompilerOutput,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilationFailure,
    Invariant,
    InvariantType,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.agent import (
    root_agent as spec_authority_compiler_agent,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
    normalize_compiler_output,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    SPEC_AUTHORITY_COMPILER_VERSION,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_prompt_hash,
)

logger = logging.getLogger(__name__)


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


class PreviewSpecAuthorityInput(BaseModel):
    """Input schema for preview_spec_authority tool."""
    
    content: str = Field(description="The raw specification text to compile.")


# pylint: disable=too-many-locals,too-many-return-statements
# Justification: Tool validation requires multiple early returns for error handling.
# Local variables are needed to handle both file and text spec sources.
def save_project_specification(
    params: Dict[str, Any],
    tool_context: Optional[ToolContext] = None,  # pylint: disable=unused-argument
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
            "compile_success": bool,
            "spec_version_id": int,
            "authority_id": int,
            "compile_error": str,     # Only present if compile_success=False
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
    except ValueError as e:
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

    # Initialize variables to avoid possibly-used-before-assignment
    spec_path = ""
    file_created = False
    spec_text = ""
    file_size_kb = 0.0

    # Verify product exists
    with Session(get_engine()) as session:
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
            except (OSError, IOError) as e:
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
        print(
            f"[save_project_specification] Spec {action} "
            f"for '{product.name}' ({file_size_kb:.1f}KB)"
        )

        if tool_context and tool_context.state is not None:
            tool_context.state["pending_spec_path"] = spec_path
            tool_context.state["pending_spec_content"] = spec_text

        compile_input = UpdateSpecAndCompileAuthorityInput(
            product_id=product_id,
            content_ref=spec_path,
        )
        compile_result = update_spec_and_compile_authority(
            compile_input,
            tool_context=tool_context,
        )

        if not compile_result.get("success"):
            return {
                "success": True,
                "product_id": product_id,
                "spec_saved": True,
                "spec_path": spec_path,
                "spec_size_kb": round(file_size_kb, 2),
                "file_created": file_created,
                "compile_success": False,
                "compile_error": compile_result.get("error"),
                "message": (
                    f"Specification {action} successfully ({file_size_kb:.1f}KB), "
                    "but authority compilation failed."
                ),
            }

        return {
            "success": True,
            "product_id": product_id,
            "spec_saved": True,
            "spec_path": spec_path,
            "spec_size_kb": round(file_size_kb, 2),
            "file_created": file_created,
            "compile_success": True,
            "spec_version_id": compile_result.get("spec_version_id"),
            "authority_id": compile_result.get("authority_id"),
            "message": (
                f"Specification {action} successfully ({file_size_kb:.1f}KB) "
                "and authority compiled."
            ),
        }


def read_project_specification(
    params: Optional[Dict[str, Any]] = None,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Read the technical specification for the active project.

    Agents should call this tool BEFORE asking questions to check if
    the answer is already in the specification.

    Args:
        params: Optional - Not used (for consistency with ADK tool signature)
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
    with Session(get_engine()) as session:
        product = session.get(Product, product_id)
        if not product or not product.technical_spec:
            project_name = active_project.get('name')
            return {
                "success": False,
                "error": f"Project '{project_name}' has no specification saved",
                "spec_content": None,
                "hint": (
                    "Spec may have been created without a specification file. "
                    "Ask user to provide one."
                ),
            }

        # Extract section headings for navigation (markdown ## headings)
        sections = _extract_markdown_sections(product.technical_spec)

        # Estimate tokens (rough: 1 token approx 4 characters)
        token_estimate = len(product.technical_spec) // 4

        print(
            f"[read_project_specification] Loaded spec for "
            f"'{product.name}' (~{token_estimate} tokens)"
        )

        if tool_context and tool_context.state is not None:
            tool_context.state["pending_spec_path"] = product.spec_file_path
            tool_context.state["pending_spec_content"] = product.technical_spec

        return {
            "success": True,
            "spec_content": product.technical_spec,
            "spec_path": product.spec_file_path,
            "token_estimate": token_estimate,
            "sections": sections,
            "message": (
                f"Loaded specification (~{token_estimate} tokens, "
                f"{len(sections)} sections)"
            ),
        }


def preview_spec_authority(
    params: PreviewSpecAuthorityInput,
    tool_context: Optional[ToolContext] = None,  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """
    Stateless 'Dry Run' of the Authority Compiler.
    Used during project initiation (before product_id exists) to make 
    constraints available to the Product Vision Agent.
    
    Args:
        params: {"content": "raw spec text"}
    
    Returns:
        JSON dict with "compiled_authority" (str) or "error"
    """
    try:
        parsed = PreviewSpecAuthorityInput.model_validate(params or {})
    except ValidationError as e:
        return {"success": False, "error": f"Invalid input: {e}"}

    print(f"[preview_spec_authority] Compiling {len(parsed.content)} chars...")
    
    try:
        # Invoke compiler directly (stateless)
        raw_json = _invoke_spec_authority_compiler(
            spec_content=parsed.content,
            content_ref=None,
            product_id=None,
            spec_version_id=None
        )
        
        # Normalize to ensure valid schema
        normalized = normalize_compiler_output(raw_json)
        
        if isinstance(normalized.root, SpecAuthorityCompilationFailure):
            return {
                "success": False,
                "error": "Compilation failed",
                "details": normalized.root.model_dump()
            }
            
        success_artifact = normalized.root
        return {
            "success": True,
            "compiled_authority": success_artifact.model_dump_json()
        }
        
    except Exception as e:
        logger.exception("preview_spec_authority failed")
        return {"success": False, "error": str(e)}


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


def _run_async_task(coro: Any) -> Any:
    """Run an async coroutine from sync code, even if a loop is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result: Dict[str, Any] = {}
    error: Dict[str, Exception] = {}

    def _runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except Exception as exc:  # pylint: disable=broad-except
            error["error"] = exc

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    thread.join()

    if "error" in error:
        raise error["error"]
    return result.get("value")


def _extract_compiler_response_text(events: List[Any]) -> str:
    """Extract the first text part from the final agent event."""
    final_event = events[-1] if events else None
    if not final_event or not getattr(final_event, "content", None):
        return ""
    for part in final_event.content.parts:
        text = getattr(part, "text", None)
        if text:
            return text
    return ""


async def _invoke_spec_authority_compiler_async(
    input_payload: SpecAuthorityCompilerInput,
) -> str:
    """Invoke the spec authority compiler agent and return raw JSON text."""
    print("[spec_authority_compiler] Input payload:")
    print(input_payload.model_dump_json())
    session_service = InMemorySessionService()
    runner = Runner(
        agent=spec_authority_compiler_agent,
        app_name="spec_authority_compiler",
        session_service=session_service,
    )

    session = await session_service.create_session(
        app_name="spec_authority_compiler",
        user_id="spec_compiler",
    )

    events: List[Any] = []
    new_message = types.Content(
        role="user",
        parts=[types.Part.from_text(text=input_payload.model_dump_json())],
    )

    async for event in runner.run_async(
        user_id="spec_compiler",
        session_id=session.id,
        new_message=new_message,
    ):
        events.append(event)

    response_text = _extract_compiler_response_text(events)
    if not response_text:
        raise ValueError("Compiler agent returned no text response")
    print("[spec_authority_compiler] Raw response text:")
    print(response_text)
    return response_text


def _invoke_spec_authority_compiler(
    spec_content: str,
    content_ref: Optional[str],
    product_id: Optional[int],
    spec_version_id: Optional[int],
) -> str:
    """Invoke the compiler agent from sync code and return raw JSON text.
    
    Note: We pass spec_source (the content) OR spec_content_ref (the path), not both.
    Since we've already loaded content, we always use spec_source and set spec_content_ref=None.
    """
    input_payload = SpecAuthorityCompilerInput(
        spec_source=spec_content,
        spec_content_ref=None,  # Content already loaded; don't pass ref
        domain_hint=None,
        product_id=product_id,
        spec_version_id=spec_version_id,
    )
    return _run_async_task(_invoke_spec_authority_compiler_async(input_payload))


def _render_invariant_summary(invariant: Invariant) -> str:
    """Render a structured invariant into a stable string for legacy consumers."""
    if invariant.type == InvariantType.FORBIDDEN_CAPABILITY:
        capability = getattr(invariant.parameters, "capability", "")
        return f"FORBIDDEN_CAPABILITY:{capability}"
    if invariant.type == InvariantType.REQUIRED_FIELD:
        field_name = getattr(invariant.parameters, "field_name", "")
        return f"REQUIRED_FIELD:{field_name}"
    if invariant.type == InvariantType.MAX_VALUE:
        field_name = getattr(invariant.parameters, "field_name", "")
        max_value = getattr(invariant.parameters, "max_value", "")
        return f"MAX_VALUE:{field_name}<= {max_value}"
    return f"INVARIANT:{invariant.type}"


def _load_compiled_artifact(
    authority: CompiledSpecAuthority,
) -> Optional[SpecAuthorityCompilationSuccess]:
    """Load normalized compiled artifact JSON if present and valid."""
    if not authority.compiled_artifact_json:
        return None
    try:
        parsed = SpecAuthorityCompilerOutput.model_validate_json(
            authority.compiled_artifact_json
        )
    except (ValidationError, ValueError):
        return None
    if isinstance(parsed.root, SpecAuthorityCompilationFailure):
        return None
    return parsed.root


def ensure_spec_authority_accepted(
    *,
    product_id: int,
    spec_version_id: int,
    policy: Literal["auto", "human"],
    decided_by: str,
    rationale: Optional[str] = None,
) -> SpecAuthorityAcceptance:
    """Ensure an accepted authority decision exists for a spec version.

    Returns existing accepted decision if present; otherwise inserts a new one.
    Raises on missing spec/compiled artifact or invalid artifact JSON.
    """
    with Session(get_engine()) as session:
        spec_version = session.get(SpecRegistry, spec_version_id)
        if not spec_version:
            raise ValueError(f"Spec version {spec_version_id} not found")
        if spec_version.product_id != product_id:
            raise ValueError(
                f"Spec version {spec_version_id} does not belong to product {product_id}"
            )

        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec_version_id
            )
        ).first()
        if not authority:
            raise ValueError(
                f"spec_version_id {spec_version_id} is not compiled"
            )

        artifact = _load_compiled_artifact(authority)
        if not artifact:
            raise ValueError(
                f"spec_version_id {spec_version_id} compiled artifact invalid"
            )

        existing = session.exec(
            select(SpecAuthorityAcceptance).where(
                SpecAuthorityAcceptance.spec_version_id == spec_version_id,
                SpecAuthorityAcceptance.status == "accepted",
            )
        ).first()
        if existing:
            return existing

        acceptance = SpecAuthorityAcceptance(
            product_id=product_id,
            spec_version_id=spec_version_id,
            status="accepted",
            policy=policy,
            decided_by=decided_by,
            decided_at=datetime.now(timezone.utc),
            rationale=rationale,
            compiler_version=authority.compiler_version,
            prompt_hash=authority.prompt_hash,
            spec_hash=spec_version.spec_hash,
        )
        session.add(acceptance)
        session.commit()
        session.refresh(acceptance)
        return acceptance


# =============================================================================
# SPECIFICATION AUTHORITY V1 — VERSIONING, APPROVAL, AND COMPILATION
# =============================================================================

# Compiler version constant (bump when extraction logic changes)
SPEC_COMPILER_VERSION = "1.0.0"


class RegisterSpecVersionInput(BaseModel):
    """Input schema for register_spec_version tool."""

    product_id: int = Field(description="Product ID to attach spec version to")
    content: str = Field(description="Full specification content (markdown or text)")
    content_ref: Optional[str] = Field(
        default=None,
        description="Optional reference (file path, URL, or identifier)"
    )


class ApproveSpecVersionInput(BaseModel):
    """Input schema for approve_spec_version tool."""

    spec_version_id: int = Field(description="Spec version ID to approve")
    approved_by: str = Field(description="Approver identifier (username, email)")
    approval_notes: Optional[str] = Field(
        default=None,
        description="Review notes or justification"
    )


class CompileSpecAuthorityInput(BaseModel):
    """Input schema for compile_spec_authority tool."""

    spec_version_id: int = Field(description="Approved spec version to compile")


class CompileSpecAuthorityForVersionInput(BaseModel):
    """Input schema for compile_spec_authority_for_version tool."""

    spec_version_id: int = Field(description="Approved spec version to compile")
    force_recompile: Optional[bool] = Field(
        default=False,
        description="If true, recompile even when cached authority exists",
    )


class UpdateSpecAndCompileAuthorityInput(BaseModel):
    """Input schema for update_spec_and_compile_authority tool."""

    product_id: int = Field(description="Product ID to update spec for")
    spec_content: Optional[str] = Field(
        default=None,
        description="Raw specification content (text or markdown)",
    )
    content_ref: Optional[str] = Field(
        default=None,
        description="Path or reference to specification content",
    )
    recompile: Optional[bool] = Field(
        default=False,
        description="Force recompile even if authority cache exists",
    )


class CheckSpecAuthorityStatusInput(BaseModel):
    """Input schema for check_spec_authority_status tool."""

    product_id: int = Field(description="Product ID to check status for")


class GetCompiledAuthorityInput(BaseModel):
    """Input schema for get_compiled_authority_by_version tool."""

    product_id: int = Field(description="Product ID")
    spec_version_id: int = Field(description="Spec version ID to retrieve")


def register_spec_version(
    params: RegisterSpecVersionInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """
    Register a new specification version with SHA-256 hash.

    Creates a DRAFT spec version entry in the registry. The spec is not
    approved or compiled automatically.

    Args:
        params: RegisterSpecVersionInput with product_id, content, content_ref
        tool_context: Optional ADK tool context

    Returns:
        Dict with success, spec_version_id, spec_hash, and message

    Examples:
        >>> register_spec_version({
        ...     "product_id": 1,
        ...     "content": "# Spec v1\\nFeature A",
        ...     "content_ref": "specs/v1.md"
        ... })
        {"success": True, "spec_version_id": 1, "spec_hash": "abc123...", ...}
    """
    parsed = RegisterSpecVersionInput.model_validate(params or {})

    # Compute SHA-256 hash of content
    spec_hash = hashlib.sha256(parsed.content.encode("utf-8")).hexdigest()

    with Session(get_engine()) as session:
        # Verify product exists
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product ID {parsed.product_id} not found"
            }

        # Create spec version
        spec_version = SpecRegistry(
            product_id=parsed.product_id,
            spec_hash=spec_hash,
            content=parsed.content,
            content_ref=parsed.content_ref,
            status="draft",
            created_at=datetime.now(timezone.utc)
        )
        session.add(spec_version)
        session.commit()
        session.refresh(spec_version)

        print(
            f"[register_spec_version] Created spec v{spec_version.spec_version_id} "
            f"for product '{product.name}' (hash: {spec_hash[:8]}...)"
        )

        return {
            "success": True,
            "spec_version_id": spec_version.spec_version_id,
            "spec_hash": spec_hash,
            "status": spec_version.status,
            "message": (
                f"Registered spec version {spec_version.spec_version_id} "
                f"(status: {spec_version.status})"
            )
        }


def approve_spec_version(
    params: ApproveSpecVersionInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """Approve a spec version, making it eligible for compilation.
    
    Approved specs become immutable. Records approver and timestamp.
    
    Args:
        params: ApproveSpecVersionInput or dict with spec_version_id, approved_by, approval_notes
        tool_context: Optional ADK ToolContext

    Returns:
        Dict with success, spec_version_id, and message

    Examples:
        >>> approve_spec_version({
        ...     "spec_version_id": 1,
        ...     "approved_by": "jane.doe@example.com",
        ...     "approval_notes": "LGTM after review"
        ... })
        {"success": True, "spec_version_id": 1, ...}
    """
    parsed = ApproveSpecVersionInput.model_validate(params or {})

    with Session(get_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found"
            }

        # Update to approved status
        spec_version.status = "approved"
        spec_version.approved_at = datetime.now(timezone.utc)
        spec_version.approved_by = parsed.approved_by
        spec_version.approval_notes = parsed.approval_notes

        session.add(spec_version)
        session.commit()

        print(
            f"[approve_spec_version] Approved spec v{parsed.spec_version_id} "
            f"by {parsed.approved_by}"
        )

        return {
            "success": True,
            "spec_version_id": parsed.spec_version_id,
            "approved_by": parsed.approved_by,
            "approved_at": spec_version.approved_at.isoformat(),
            "message": (
                f"Spec version {parsed.spec_version_id} approved "
                f"by {parsed.approved_by}"
            )
        }


def compile_spec_authority(
    params: CompileSpecAuthorityInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """
    Compile an approved spec version into cached authority.

    Extracts scope themes, invariants, and feature eligibility using LLM.
    Compilation is NEVER automatic — it must be explicitly invoked.

    Args:
        params: CompileSpecAuthorityInput with spec_version_id
        tool_context: Optional ADK tool context

    Returns:
        Dict with success, authority_id, and compilation metadata

    Examples:
        >>> compile_spec_authority({"spec_version_id": 1})
        {"success": True, "authority_id": 1, "compiler_version": "1.0.0", ...}
    """
    parsed = CompileSpecAuthorityInput.model_validate(params or {})

    with Session(get_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found"
            }

        # Guard: spec must be approved
        if spec_version.status != "approved":
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not approved "
                    f"(status: {spec_version.status}). "
                    "Only approved specs can be compiled."
                )
            }

        # Check if already compiled
        existing_authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if existing_authority:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is already compiled "
                    f"(authority_id: {existing_authority.authority_id})"
                )
            }

        # TODO: Replace with actual LLM extraction
        # For now, use minimal placeholder extraction
        scope_themes, invariants = _mock_extract_spec_authority(spec_version.content)

        # Compute prompt hash (for reproducibility tracking)
        extraction_prompt = _get_extraction_prompt_template()
        prompt_hash = hashlib.sha256(extraction_prompt.encode("utf-8")).hexdigest()

        # Create compiled authority
        authority = CompiledSpecAuthority(
            spec_version_id=parsed.spec_version_id,
            compiler_version=SPEC_COMPILER_VERSION,
            prompt_hash=prompt_hash,
            compiled_at=datetime.now(timezone.utc),
            scope_themes=json.dumps(scope_themes),
            invariants=json.dumps(invariants),
            eligible_feature_ids=json.dumps([]),  # Populated later by feature analysis
            rejected_features=json.dumps([]),
            spec_gaps=json.dumps([])
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)

        print(
            f"[compile_spec_authority] Compiled spec v{parsed.spec_version_id} "
            f"-> authority {authority.authority_id} "
            f"(compiler: {SPEC_COMPILER_VERSION})"
        )

        return {
            "success": True,
            "authority_id": authority.authority_id,
            "spec_version_id": parsed.spec_version_id,
            "compiler_version": SPEC_COMPILER_VERSION,
            "prompt_hash": prompt_hash[:8],
            "scope_themes_count": len(scope_themes),
            "invariants_count": len(invariants),
            "message": (
                f"Compiled spec version {parsed.spec_version_id} "
                f"(authority ID: {authority.authority_id})"
            )
        }


def compile_spec_authority_for_version(
    params: CompileSpecAuthorityForVersionInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Compile an approved spec version into cached authority (idempotent).

    - Returns cached authority if already compiled (unless force_recompile).
    - Loads content from content_ref if stored content is empty.

    Args:
        params: CompileSpecAuthorityForVersionInput with spec_version_id, force_recompile
        tool_context: Optional ADK tool context

    Returns:
        Dict with success, authority_id, cache status, and compilation metadata
    """
    parsed = CompileSpecAuthorityForVersionInput.model_validate(params or {})

    with Session(get_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
            }

        product = session.get(Product, spec_version.product_id)

        if spec_version.status != "approved":
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not approved "
                    f"(status: {spec_version.status}). "
                    "Only approved specs can be compiled."
                ),
            }

        existing_authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if (
            existing_authority
            and not parsed.force_recompile
            and existing_authority.compiled_artifact_json
        ):
            artifact = _load_compiled_artifact(existing_authority)
            if artifact:
                scope_themes = artifact.scope_themes
                invariants = [_render_invariant_summary(inv) for inv in artifact.invariants]
            else:
                scope_themes = json.loads(existing_authority.scope_themes)
                invariants = json.loads(existing_authority.invariants)

            if product:
                product.compiled_authority_json = (
                    existing_authority.compiled_artifact_json
                )
                session.add(product)
                session.commit()

            return {
                "success": True,
                "cached": True,
                "authority_id": existing_authority.authority_id,
                "spec_version_id": parsed.spec_version_id,
                "compiler_version": existing_authority.compiler_version,
                "prompt_hash": existing_authority.prompt_hash,
                "scope_themes_count": len(scope_themes),
                "invariants_count": len(invariants),
                "content_ref": spec_version.content_ref,
                "content_source": "content",
                "message": (
                    f"Spec version {parsed.spec_version_id} is already compiled "
                    f"(authority ID: {existing_authority.authority_id})."
                ),
            }

        spec_content = spec_version.content or ""
        content_source = "content"

        if not spec_content.strip() and spec_version.content_ref:
            content_path = Path(spec_version.content_ref)
            if not content_path.exists():
                return {
                    "success": False,
                    "error": (
                        "Spec content is empty and content_ref was not found: "
                        f"{spec_version.content_ref}"
                    ),
                }
            try:
                spec_content = content_path.read_text(encoding="utf-8")
                content_source = "content_ref"
            except (OSError, UnicodeDecodeError) as exc:
                return {
                    "success": False,
                    "error": f"Failed to read content_ref: {exc}",
                }

        if not spec_content.strip():
            return {
                "success": False,
                "error": "Spec content is empty; cannot compile authority.",
            }

        try:
            raw_json = _invoke_spec_authority_compiler(
                spec_content=spec_content,
                content_ref=spec_version.content_ref,
                product_id=spec_version.product_id,
                spec_version_id=spec_version.spec_version_id,
            )
        except Exception as exc:  # pylint: disable=broad-except
            return {
                "success": False,
                "error": "SPEC_COMPILER_INVOCATION_FAILED",
                "reason": str(exc),
            }

        print("[spec_authority_compiler] Normalizing output...")
        print(f"[spec_authority_compiler] Raw JSON length: {len(raw_json)}")

        normalized = normalize_compiler_output(raw_json)
        if isinstance(normalized.root, SpecAuthorityCompilationFailure):
            return {
                "success": False,
                "error": normalized.root.error,
                "reason": normalized.root.reason,
                "blocking_gaps": normalized.root.blocking_gaps,
            }

        success = normalized.root
        compiled_artifact_json = success.model_dump_json()
        prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
        compiler_version = SPEC_AUTHORITY_COMPILER_VERSION

        scope_themes = success.scope_themes
        invariants = [_render_invariant_summary(inv) for inv in success.invariants]
        spec_gaps = success.gaps

        if existing_authority and parsed.force_recompile:
            existing_authority.compiler_version = compiler_version
            existing_authority.prompt_hash = prompt_hash
            existing_authority.compiled_at = datetime.now(timezone.utc)
            existing_authority.compiled_artifact_json = compiled_artifact_json
            existing_authority.scope_themes = json.dumps(scope_themes)
            existing_authority.invariants = json.dumps(invariants)
            existing_authority.eligible_feature_ids = json.dumps([])
            existing_authority.rejected_features = json.dumps([])
            existing_authority.spec_gaps = json.dumps(spec_gaps)
            session.add(existing_authority)
            session.commit()
            session.refresh(existing_authority)

            if product:
                product.compiled_authority_json = compiled_artifact_json
                session.add(product)
                session.commit()

            authority_id = existing_authority.authority_id
            cached = False
            recompiled = True
        else:
            authority = CompiledSpecAuthority(
                spec_version_id=parsed.spec_version_id,
                compiler_version=compiler_version,
                prompt_hash=prompt_hash,
                compiled_at=datetime.now(timezone.utc),
                compiled_artifact_json=compiled_artifact_json,
                scope_themes=json.dumps(scope_themes),
                invariants=json.dumps(invariants),
                eligible_feature_ids=json.dumps([]),
                rejected_features=json.dumps([]),
                spec_gaps=json.dumps(spec_gaps),
            )
            session.add(authority)
            session.commit()
            session.refresh(authority)

            if product:
                product.compiled_authority_json = compiled_artifact_json
                session.add(product)
                session.commit()

            authority_id = authority.authority_id
            cached = False
            recompiled = False

        return {
            "success": True,
            "cached": cached,
            "recompiled": recompiled,
            "authority_id": authority_id,
            "spec_version_id": parsed.spec_version_id,
            "compiler_version": compiler_version,
            "prompt_hash": prompt_hash,
            "scope_themes_count": len(scope_themes),
            "invariants_count": len(invariants),
            "content_ref": spec_version.content_ref,
            "content_source": content_source,
            "message": (
                f"Compiled spec version {parsed.spec_version_id} "
                f"(authority ID: {authority_id})"
            ),
        }


def update_spec_and_compile_authority(
    params: UpdateSpecAndCompileAuthorityInput,
    tool_context: Optional[ToolContext] = None,
) -> Dict[str, Any]:
    """
    Update specification content with implicit approval and compile authority.

    Args:
        params: UpdateSpecAndCompileAuthorityInput with product_id and content
        tool_context: Optional ADK tool context

    Returns:
        Dict with spec_version_id and compilation summary

    Raises:
        ValueError: If both or neither spec_content/content_ref are provided.
    """
    parsed = UpdateSpecAndCompileAuthorityInput.model_validate(params or {})

    has_content = parsed.spec_content is not None
    has_ref = parsed.content_ref is not None
    if has_content == has_ref:
        raise ValueError("Provide exactly one of spec_content or content_ref")

    if parsed.content_ref:
        content_path = Path(parsed.content_ref)
        if not content_path.exists():
            return {
                "success": False,
                "error": f"Specification file not found: {parsed.content_ref}",
            }
        try:
            spec_content = content_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            return {
                "success": False,
                "error": f"Failed to read specification file: {exc}",
            }
    else:
        spec_content = parsed.spec_content or ""

    spec_hash = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()

    with Session(get_engine()) as session:
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product ID {parsed.product_id} not found",
            }

        latest_spec = session.exec(
            select(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(SpecRegistry.spec_version_id.desc())
        ).first()

        if latest_spec and latest_spec.spec_hash == spec_hash:
            spec_version_id = latest_spec.spec_version_id
        else:
            new_spec = SpecRegistry(
                product_id=parsed.product_id,
                spec_hash=spec_hash,
                content=spec_content,
                content_ref=parsed.content_ref,
                status="approved",
                approved_at=datetime.now(timezone.utc),
                approved_by="implicit",
                approval_notes="Implicit approval",
            )
            session.add(new_spec)
            session.commit()
            session.refresh(new_spec)
            spec_version_id = new_spec.spec_version_id

    compile_result = compile_spec_authority_for_version(
        {
            "spec_version_id": spec_version_id,
            "force_recompile": parsed.recompile,
        },
        tool_context=tool_context,
    )

    if not compile_result.get("success"):
        return compile_result

    with Session(get_engine()) as session:
        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec_version_id
            )
        ).first()

        if not authority:
            return {
                "success": False,
                "error": (
                    f"Compiled authority missing for spec version {spec_version_id}"
                ),
            }

    try:
        acceptance = ensure_spec_authority_accepted(
            product_id=parsed.product_id,
            spec_version_id=spec_version_id,
            policy="auto",
            decided_by="system",
            rationale="Auto-accepted on compile success",
        )
    except ValueError as exc:
        return {
            "success": False,
            "error": str(exc),
            "accepted": False,
        }

    artifact = _load_compiled_artifact(authority)
    if artifact:
        scope_themes = artifact.scope_themes
        invariants = [_render_invariant_summary(inv) for inv in artifact.invariants]
    else:
        scope_themes = json.loads(authority.scope_themes)
        invariants = json.loads(authority.invariants)
    eligible_feature_ids = json.loads(authority.eligible_feature_ids)

    return {
        "success": True,
        "product_id": parsed.product_id,
        "spec_version_id": spec_version_id,
        "authority_id": authority.authority_id,
        "spec_hash": spec_hash,
        "compiled_at": authority.compiled_at.isoformat(),
        "compiler_version": authority.compiler_version,
        "num_scope_themes": len(scope_themes),
        "num_invariants": len(invariants),
        "num_eligible_feature_ids": len(eligible_feature_ids),
        "cache_hit": bool(compile_result.get("cached")) and not parsed.recompile,
        "accepted": acceptance.status == "accepted",
        "acceptance_policy": acceptance.policy,
        "acceptance_decided_at": acceptance.decided_at.isoformat(),
        "acceptance_decided_by": acceptance.decided_by,
        "message": (
            f"Spec v{spec_version_id} ready. Use this spec_version_id for "
            "story validation and generation."
        ),
    }


def ensure_accepted_spec_authority(
    product_id: int,
    *,
    spec_content: Optional[str] = None,
    content_ref: Optional[str] = None,
    recompile: bool = False,
    tool_context: Optional[ToolContext] = None,
) -> int:
    """
    Ensure an accepted spec authority exists for the product.

    This is the orchestrator-level gate that ensures story generation has a valid,
    accepted spec authority to validate against.

    Behavior:
    1. If an accepted spec authority already exists for the product, return its spec_version_id.
    2. Otherwise, call update_spec_and_compile_authority() to create and auto-accept one.
    3. Require success==True and accepted==True; otherwise raise RuntimeError.

    Args:
        product_id: The product ID to check/create authority for.
        spec_content: Raw specification content (text or markdown).
        content_ref: Path or reference to specification content.
        recompile: Force recompile even if authority cache exists.
        tool_context: Optional ADK ToolContext to pass through to tool execution.

    Returns:
        The spec_version_id of the accepted authority.

    Raises:
        RuntimeError: If no accepted authority exists and no spec content is provided,
                      or if update_spec_and_compile_authority fails or returns not accepted.
    """
    # Determine spec_input_provided and input_source for logging
    spec_input_provided = spec_content is not None or content_ref is not None
    
    # Extract session_id if available from tool_context
    session_id: Optional[str] = None
    if tool_context and hasattr(tool_context, "session_id"):
        session_id = getattr(tool_context, "session_id", None)
    
    logger.info(
        "authority_gate.check",
        extra={
            "product_id": product_id,
            "session_id": session_id,
            "recompile": recompile,
            "spec_input_provided": spec_input_provided,
            "has_spec_content": spec_content is not None,
            "has_content_ref": content_ref is not None,
            "tool_context_present": tool_context is not None,
        },
    )
    # Ensure runtime schema is current (idempotent and safe to call repeatedly).
    # This protects Authority Gate reads from stale DB schemas.
    from db.migrations import ensure_schema_current

    ensure_schema_current(get_engine())
    # Step 1: Check if an accepted authority already exists for this product
    compile_reason = "no_accepted_authority"
    existing_spec_version_id: Optional[int] = None
    accepted_decision_found = False
    compiled_row_found = False
    compiled_artifact_success = False
    
    with Session(get_engine()) as session:
        # Query for the most recent accepted authority for this product
        existing_acceptance = session.exec(
            select(SpecAuthorityAcceptance)
            .where(
                SpecAuthorityAcceptance.product_id == product_id,
                SpecAuthorityAcceptance.status == "accepted",
            )
            .order_by(SpecAuthorityAcceptance.decided_at.desc())
        ).first()

        if existing_acceptance:
            accepted_decision_found = True
            existing_spec_version_id = existing_acceptance.spec_version_id
            # Verify the compiled authority still exists and has a valid success artifact
            compiled = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == existing_acceptance.spec_version_id
                )
            ).first()
            if compiled:
                compiled_row_found = True
                if compiled.compiled_artifact_json:
                    # Validate artifact is a success, not a failure envelope
                    artifact = _load_compiled_artifact(compiled)
                    if artifact is not None:
                        compiled_artifact_success = True
                        logger.info(
                            "authority_gate.pass",
                            extra={
                                "product_id": product_id,
                                "session_id": session_id,
                                "spec_version_id": existing_acceptance.spec_version_id,
                                "path_used": "existing_authority",
                                "accepted_decision_found": True,
                                "compiled_row_found": True,
                                "compiled_artifact_success": True,
                                "spec_input_provided": spec_input_provided,
                            },
                        )
                        return existing_acceptance.spec_version_id
            compile_reason = "compiled_unusable_or_missing"

    # Step 2: No accepted authority exists - need to create one
    # Check if we have spec content to work with
    if spec_content is None and content_ref is None:
        logger.error(
            "authority_gate.fail_no_source",
            extra={
                "product_id": product_id,
                "session_id": session_id,
                "path_used": "fail_no_source",
                "accepted_decision_found": accepted_decision_found,
                "compiled_row_found": compiled_row_found,
                "compiled_artifact_success": compiled_artifact_success,
                "spec_input_provided": False,
                "reason": "missing_inputs",
            },
        )
        raise RuntimeError(
            f"No accepted spec authority exists for product {product_id}, and no "
            "spec_content or content_ref was provided. Please provide the specification "
            "content or a file path to create an authority."
        )

    # Determine path_used based on source
    path_used = "explicit_args"
    if tool_context and tool_context.state:
        if (tool_context.state.get("pending_spec_content") == spec_content or 
            tool_context.state.get("pending_spec_path") == content_ref):
            path_used = "proposal_from_state"

    # Step 3: Call update_spec_and_compile_authority to create and auto-accept
    params = {
        "product_id": product_id,
        "recompile": recompile,
    }
    if spec_content is not None:
        params["spec_content"] = spec_content
    if content_ref is not None:
        params["content_ref"] = content_ref
    input_source = "spec_content" if spec_content is not None else "content_ref"
    logger.info(
        "authority_gate.compile_start",
        extra={
            "product_id": product_id,
            "session_id": session_id,
            "path_used": path_used,
            "input_source": input_source,
            "recompile": recompile,
            "reason": compile_reason,
            "accepted_decision_found": accepted_decision_found,
            "compiled_row_found": compiled_row_found,
            "compiled_artifact_success": compiled_artifact_success,
            "spec_input_provided": True,
        },
    )

    try:
        result = update_spec_and_compile_authority(params, tool_context=tool_context)
    except Exception as exc:
        logger.error(
            "authority_gate.compile_result",
            extra={
                "product_id": product_id,
                "session_id": session_id,
                "path_used": path_used,
                "reason": "update_failed",
                "success": False,
                "accepted": False,
                "spec_version_id": None,
                "error_type": type(exc).__name__,
                "error_message": str(exc),
            },
        )
        raise

    # Step 4: Validate the result
    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "update_failed",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Failed to create accepted spec authority for product {product_id}: {error_msg}"
        )

    if not result.get("accepted"):
        logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "not_accepted",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Spec authority for product {product_id} was compiled but not accepted. "
            "Authority acceptance is required before story generation can proceed."
        )

    spec_version_id = result.get("spec_version_id")
    if spec_version_id is None:
        logger.error(
            "authority_gate.fail",
            extra={
                "product_id": product_id,
                "reason": "missing_spec_version_id",
                "success": result.get("success"),
                "accepted": result.get("accepted"),
                "spec_version_id": result.get("spec_version_id"),
            },
        )
        raise RuntimeError(
            f"Spec authority creation succeeded but no spec_version_id was returned "
            f"for product {product_id}."
        )

    logger.info(
        "authority_gate.updated",
        extra={
            "product_id": product_id,
            "spec_version_id": spec_version_id,
            "accepted": result.get("accepted"),
            "success": result.get("success"),
            "compiler_version": result.get("compiler_version"),
        },
    )

    return spec_version_id


def check_spec_authority_status(
    params: CheckSpecAuthorityStatusInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """
    Check the spec authority status for a product.

    Returns one of:
    - NOT_COMPILED: No spec version exists or no compiled authority
    - PENDING_REVIEW: Latest spec version is draft (not approved)
    - STALE: Compiled authority exists but for older spec version
    - CURRENT: Compiled authority matches latest approved spec

    Args:
        params: CheckSpecAuthorityStatusInput with product_id
        tool_context: Optional ADK tool context

    Returns:
        Dict with success, status, and status_details

    Examples:
        >>> check_spec_authority_status({"product_id": 1})
        {"success": True, "status": "current", ...}
    """
    parsed = CheckSpecAuthorityStatusInput.model_validate(params or {})

    with Session(get_engine()) as session:
        # Get all spec versions for product, ordered by ID (newest first)
        spec_versions = session.exec(
            select(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(SpecRegistry.spec_version_id.desc())
        ).all()

        if not spec_versions:
            return {
                "success": True,
                "status": SpecAuthorityStatus.NOT_COMPILED.value,
                "status_details": "No spec versions exist for this product",
                "message": "Status: NOT_COMPILED (no specs)"
            }

        latest_spec = spec_versions[0]

        # Case 1: Latest spec is not approved
        if latest_spec.status != "approved":
            return {
                "success": True,
                "status": SpecAuthorityStatus.PENDING_REVIEW.value,
                "status_details": (
                    f"Latest spec version {latest_spec.spec_version_id} "
                    f"is {latest_spec.status}"
                ),
                "latest_spec_version_id": latest_spec.spec_version_id,
                "message": "Status: PENDING_REVIEW (latest spec not approved)"
            }

        # Latest approved spec is the latest spec (approved)
        latest_approved = latest_spec

        # Get most recent compiled authority for this product
        latest_authority = session.exec(
            select(CompiledSpecAuthority)
            .join(SpecRegistry)
            .where(SpecRegistry.product_id == parsed.product_id)
            .order_by(CompiledSpecAuthority.spec_version_id.desc())
        ).first()

        if not latest_authority:
            return {
                "success": True,
                "status": SpecAuthorityStatus.NOT_COMPILED.value,
                "status_details": (
                    f"Latest approved spec version {latest_approved.spec_version_id} "
                    "is not compiled"
                ),
                "latest_approved_spec_version_id": latest_approved.spec_version_id,
                "message": "Status: NOT_COMPILED (approved but not compiled)"
            }

        # If compiled authority is for older spec, status is STALE
        if latest_authority.spec_version_id < latest_approved.spec_version_id:
            return {
                "success": True,
                "status": SpecAuthorityStatus.STALE.value,
                "status_details": (
                    "Compiled authority is stale (newer approved spec exists)"
                ),
                "compiled_spec_version_id": latest_authority.spec_version_id,
                "latest_approved_spec_version_id": latest_approved.spec_version_id,
                "message": "Status: STALE (compiled for older spec)"
            }

        # Authority exists for latest approved spec
        return {
            "success": True,
            "status": SpecAuthorityStatus.CURRENT.value,
            "status_details": (
                f"Compiled authority exists for latest approved spec "
                f"version {latest_approved.spec_version_id}"
            ),
            "latest_approved_spec_version_id": latest_approved.spec_version_id,
            "authority_id": latest_authority.authority_id,
            "compiled_at": latest_authority.compiled_at.isoformat(),
            "message": f"Status: CURRENT (authority ID: {latest_authority.authority_id})"
        }


def get_compiled_authority_by_version(
    params: GetCompiledAuthorityInput,
    tool_context: Optional[ToolContext] = None
) -> Dict[str, Any]:
    """
    Retrieve compiled spec authority for a specific version.

    Returns clear error if:
    - Spec version doesn't exist
    - Spec version doesn't belong to product
    - Spec version is not compiled

    Args:
        params: GetCompiledAuthorityInput with product_id, spec_version_id
        tool_context: Optional ADK tool context

    Returns:
        Dict with success, authority data, or error

    Examples:
        >>> get_compiled_authority_by_version({
        ...     "product_id": 1,
        ...     "spec_version_id": 2
        ... })
        {"success": True, "scope_themes": [...], "invariants": [...], ...}
    """
    parsed = GetCompiledAuthorityInput.model_validate(params or {})

    with Session(get_engine()) as session:
        # Verify spec version exists and belongs to product
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found"
            }

        if spec_version.product_id != parsed.product_id:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} does not belong to "
                    f"product {parsed.product_id} (mismatch)"
                )
            }

        # Get compiled authority
        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if not authority:
            return {
                "success": False,
                "error": (
                    f"Spec version {parsed.spec_version_id} is not compiled. "
                    "Use compile_spec_authority to compile it."
                )
            }

        artifact = _load_compiled_artifact(authority)
        if artifact:
            scope_themes = artifact.scope_themes
            invariants = [_render_invariant_summary(inv) for inv in artifact.invariants]
            spec_gaps = artifact.gaps
        else:
            scope_themes = json.loads(authority.scope_themes)
            invariants = json.loads(authority.invariants)
            spec_gaps = (
                json.loads(authority.spec_gaps)
                if authority.spec_gaps
                else []
            )
        eligible_feature_ids = json.loads(authority.eligible_feature_ids)
        rejected_features = (
            json.loads(authority.rejected_features)
            if authority.rejected_features
            else []
        )

        print(
            f"[get_compiled_authority_by_version] Retrieved authority "
            f"{authority.authority_id} for spec v{parsed.spec_version_id}"
        )

        return {
            "success": True,
            "spec_version_id": parsed.spec_version_id,
            "authority_id": authority.authority_id,
            "compiler_version": authority.compiler_version,
            "compiled_at": authority.compiled_at.isoformat(),
            "scope_themes": scope_themes,
            "invariants": invariants,
            "eligible_feature_ids": eligible_feature_ids,
            "rejected_features": rejected_features,
            "spec_gaps": spec_gaps,
            "compiled_artifact_json": authority.compiled_artifact_json,
            "message": (
                f"Retrieved compiled authority for spec version "
                f"{parsed.spec_version_id}"
            )
        }


# =============================================================================
# STORY VALIDATION PINNING V2 — SPEC VERSION REQUIRED + EVIDENCE PERSISTENCE
# =============================================================================

# Validator version constant (bump when validation logic changes)
VALIDATOR_VERSION = "1.0.0"


class ValidateStoryInput(BaseModel):
    """Input schema for validate_story_with_spec_authority tool."""

    story_id: int = Field(description="Story ID to validate")
    spec_version_id: int = Field(
        description="Spec version ID to validate against (REQUIRED)"
    )


def _compute_story_input_hash(story: UserStory) -> str:
    """Compute deterministic SHA-256 hash of story content."""
    content = json.dumps(
        {
            "title": story.title or "",
            "description": story.story_description or "",
            "acceptance_criteria": story.acceptance_criteria or "",
        },
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(content.encode()).hexdigest()


def _persist_validation_evidence(
    session: Session,
    story: UserStory,
    evidence: ValidationEvidence,
    passed: bool,
) -> None:
    """Persist validation evidence and update accepted spec version on pass."""
    story.validation_evidence = evidence.model_dump_json()
    if passed:
        story.accepted_spec_version_id = evidence.spec_version_id
    session.add(story)
    session.commit()


def validate_story_with_spec_authority(
    params: ValidateStoryInput,
    tool_context: Optional[ToolContext] = None  # pylint: disable=unused-argument
) -> Dict[str, Any]:
    """
    Canonical validation entry point: validates story against explicit spec version.

    Requirements:
    - spec_version_id is REQUIRED (no defaults)
    - CompiledSpecAuthority must exist for (product_id, spec_version_id)
    - Evidence is persisted on every validation (pass or fail)
    - accepted_spec_version_id is only set on pass
    """
    parsed = ValidateStoryInput.model_validate(params or {})

    with Session(get_engine()) as session:
        story = session.get(UserStory, parsed.story_id)
        if not story:
            return {
                "success": False,
                "error": f"Story {parsed.story_id} not found",
            }

        input_hash = _compute_story_input_hash(story)

        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_VERSION_EXISTS"],
                invariants_checked=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_VERSION_EXISTS",
                        expected="Spec version exists",
                        actual="Not found",
                        message=f"Spec version {parsed.spec_version_id} not found",
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=VALIDATOR_VERSION,
                input_hash=input_hash,
            )
            _persist_validation_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
                "passed": False,
                "input_hash": input_hash,
            }

        if spec_version.product_id != story.product_id:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_PRODUCT_MATCH"],
                invariants_checked=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_PRODUCT_MATCH",
                        expected=f"Product {story.product_id}",
                        actual=f"Product {spec_version.product_id}",
                        message=(
                            "Spec version belongs to a different product "
                            f"(expected {story.product_id}, got {spec_version.product_id})"
                        ),
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=VALIDATOR_VERSION,
                input_hash=input_hash,
            )
            _persist_validation_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": (
                    f"Product mismatch: story belongs to product {story.product_id}, "
                    f"but spec version {parsed.spec_version_id} belongs to product "
                    f"{spec_version.product_id}"
                ),
                "passed": False,
                "input_hash": input_hash,
            }

        authority = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == parsed.spec_version_id
            )
        ).first()

        if not authority:
            evidence = ValidationEvidence(
                spec_version_id=parsed.spec_version_id,
                validated_at=datetime.now(timezone.utc),
                passed=False,
                rules_checked=["SPEC_VERSION_COMPILED"],
                invariants_checked=[],
                failures=[
                    ValidationFailure(
                        rule="SPEC_VERSION_COMPILED",
                        expected="Compiled authority exists",
                        actual="Not compiled",
                        message=(
                            f"spec_version_id {parsed.spec_version_id} is not compiled"
                        ),
                    )
                ],
                warnings=[],
                alignment_warnings=[],
                alignment_failures=[],
                validator_version=VALIDATOR_VERSION,
                input_hash=input_hash,
            )
            _persist_validation_evidence(session, story, evidence, passed=False)
            return {
                "success": False,
                "error": f"spec_version_id {parsed.spec_version_id} is not compiled",
                "passed": False,
                "input_hash": input_hash,
            }

        artifact = _load_compiled_artifact(authority)
        if artifact:
            invariants_checked = [_render_invariant_summary(inv) for inv in artifact.invariants]
        else:
            invariants_checked = (
                json.loads(authority.invariants) if authority.invariants else []
            )
        rules_checked: List[str] = []
        failures: List[ValidationFailure] = []
        warnings: List[str] = []

        # Alignment check (pinned authority only)
        from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
            validate_feature_alignment,
        )

        alignment_result = validate_feature_alignment(
            feature_title=f"{story.title or ''} {story.story_description or ''}".strip(),
            compiled_authority=authority,
        )

        alignment_failures = [
            AlignmentFinding(
                code=finding.code,
                invariant=finding.invariant,
                capability=finding.capability,
                message=finding.message,
                severity=finding.severity,  # type: ignore[arg-type]
                created_at=finding.created_at,
            )
            for finding in alignment_result.findings
            if finding.severity == "failure"
        ]
        alignment_warnings = [
            AlignmentFinding(
                code=finding.code,
                invariant=finding.invariant,
                capability=finding.capability,
                message=finding.message,
                severity=finding.severity,  # type: ignore[arg-type]
                created_at=finding.created_at,
            )
            for finding in alignment_result.findings
            if finding.severity == "warning"
        ]

        rules_checked.append("RULE_TITLE_REQUIRED")
        if not story.title or not story.title.strip():
            failures.append(
                ValidationFailure(
                    rule="RULE_TITLE_REQUIRED",
                    expected="Non-empty title",
                    actual="Empty or missing",
                    message="Story must have a title",
                )
            )

        rules_checked.append("RULE_ACCEPTANCE_CRITERIA_REQUIRED")
        if not story.acceptance_criteria or not story.acceptance_criteria.strip():
            failures.append(
                ValidationFailure(
                    rule="RULE_ACCEPTANCE_CRITERIA_REQUIRED",
                    expected="Non-empty acceptance criteria",
                    actual="Empty or missing",
                    message="Story must have acceptance criteria",
                )
            )

        rules_checked.append("RULE_PERSONA_FORMAT")
        title_lower = (story.title or "").lower()
        desc_lower = (story.story_description or "").lower()
        if not (
            "as a " in title_lower
            or "as a " in desc_lower
            or "as an " in title_lower
            or "as an " in desc_lower
        ):
            warnings.append("Story does not follow 'As a [persona], I want...' format")

        passed = len(failures) == 0 and len(alignment_failures) == 0

        evidence = ValidationEvidence(
            spec_version_id=parsed.spec_version_id,
            validated_at=datetime.now(timezone.utc),
            passed=passed,
            rules_checked=rules_checked,
            invariants_checked=invariants_checked,
            failures=failures,
            warnings=warnings,
            alignment_warnings=alignment_warnings,
            alignment_failures=alignment_failures,
            validator_version=VALIDATOR_VERSION,
            input_hash=input_hash,
        )
        _persist_validation_evidence(session, story, evidence, passed=passed)

        return {
            "success": True,
            "passed": passed,
            "story_id": parsed.story_id,
            "spec_version_id": parsed.spec_version_id,
            "failures": [failure.model_dump() for failure in failures],
            "warnings": warnings,
            "input_hash": input_hash,
            "message": (
                "Validation passed" if passed else f"Validation failed with {len(failures)} issue(s)"
            ),
        }


# --- Mock LLM Extraction (Placeholder for v1) ---


def _mock_extract_spec_authority(spec_content: str) -> tuple[List[str], List[str]]:
    """
    Mock extraction of scope themes and invariants from spec.

    TODO: Replace with actual LLM-based extraction in v1.1+

    Args:
        spec_content: Full specification text

    Returns:
        Tuple of (scope_themes, invariants)
    """
    # Extract markdown headings as themes (simple heuristic)
    themes = re.findall(r'^##\s+(.+)$', spec_content, re.MULTILINE)[:5]

    # Extract "MUST" statements as invariants (simple heuristic)
    invariants = re.findall(
        r'(?:^|\s)((?:MUST|SHALL|REQUIRED)[^.!?]+[.!?])',
        spec_content,
        re.MULTILINE
    )[:5]

    return (
        themes if themes else ["Default scope theme"],
        invariants if invariants else ["No invariants extracted"]
    )


def _get_extraction_prompt_template() -> str:
    """
    Return the LLM prompt template for spec extraction.

    Used for prompt_hash computation to track reproducibility.

    Returns:
        Prompt template string
    """
    return """
Extract the following from the technical specification:
1. Scope themes (high-level features/domains)
2. Invariants (MUST/SHALL requirements, business rules)
3. Eligible feature IDs (features that align with spec)
4. Rejected features (out-of-scope features)
5. Spec gaps (ambiguities, missing requirements)

Return as JSON.
""".strip()
