"""Public lifecycle entrypoints for spec persistence workflows."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import hashlib

from google.adk.tools import ToolContext
from pydantic import BaseModel, Field
import re
from sqlmodel import Session

from models.core import Product
from models.db import get_engine
from models.specs import SpecRegistry

_DEFAULT_GET_ENGINE = get_engine


class LinkSpecToProductInput(BaseModel):
    """Input schema for linking an on-disk specification to a product."""

    product_id: int = Field(description="ID of the project to link the specification to")
    spec_path: str = Field(
        description="Path to on-disk specification file (.md, .txt)"
    )


class ReadProjectSpecificationInput(BaseModel):
    """Input schema for reading the active project's specification."""


class SaveProjectSpecificationInput(BaseModel):
    """Input schema for saving project specifications."""

    product_id: int = Field(description="ID of project to attach specification to")
    spec_source: str = Field(
        description='Source type: "file" (load from file path) or "text" (pasted content)'
    )
    content: str = Field(
        description="File path (if spec_source='file') or raw text content (if spec_source='text')"
    )


class RegisterSpecVersionInput(BaseModel):
    """Input schema for register_spec_version lifecycle entrypoint."""

    product_id: int = Field(description="Product ID to attach spec version to")
    content: str = Field(description="Full specification content (markdown or text)")
    content_ref: str | None = Field(
        default=None,
        description="Optional reference (file path, URL, or identifier)",
    )


class ApproveSpecVersionInput(BaseModel):
    """Input schema for approve_spec_version lifecycle entrypoint."""

    spec_version_id: int = Field(description="Spec version ID to approve")
    approved_by: str = Field(description="Approver identifier (username, email)")
    approval_notes: str | None = Field(
        default=None,
        description="Review notes or justification",
    )


def _resolve_engine():
    """Preserve the legacy spec_tools.engine monkeypatch seam for tests."""
    from services.specs._engine_resolution import resolve_spec_engine

    return resolve_spec_engine(
        service_get_engine=get_engine,
        default_service_get_engine=_DEFAULT_GET_ENGINE,
    )


def _compile_spec_authority_from_path(
    *,
    product_id: int,
    spec_path: str,
    tool_context: ToolContext | None,
) -> dict[str, Any]:
    from tools.spec_tools import (  # pylint: disable=import-outside-toplevel
        UpdateSpecAndCompileAuthorityInput,
        update_spec_and_compile_authority,
    )

    compile_input = UpdateSpecAndCompileAuthorityInput(
        product_id=product_id,
        content_ref=spec_path,
    )
    return update_spec_and_compile_authority(
        compile_input,
        tool_context=tool_context,
    )


def _compile_linked_spec_authority(
    *,
    product_id: int,
    spec_path: str,
    tool_context: ToolContext | None,
) -> dict[str, Any]:
    """Backwards-compatible compile seam for link-side tests and callers."""
    return _compile_spec_authority_from_path(
        product_id=product_id,
        spec_path=spec_path,
        tool_context=tool_context,
    )


def extract_markdown_sections(spec_text: str) -> list[str]:
    """Extract up to 20 markdown headings for navigation."""
    headings = re.findall(r"^#{1,3}\s+(.+)$", spec_text, re.MULTILINE)
    return headings[:20]


def resolve_spec_content(
    *,
    technical_spec: str | None,
    spec_file_path: str | None,
) -> tuple[str | None, str | None]:
    """Resolve spec content using the same precedence as session hydration."""
    if technical_spec:
        return technical_spec, spec_file_path

    if spec_file_path:
        spec_path_obj = Path(spec_file_path)
        if spec_path_obj.exists():
            try:
                return spec_path_obj.read_text(encoding="utf-8"), spec_file_path
            except (OSError, UnicodeDecodeError):
                return None, spec_file_path
        return None, spec_file_path

    return None, None


def hydrate_spec_state(
    state: dict[str, Any],
    *,
    technical_spec: str | None,
    spec_file_path: str | None,
) -> None:
    """Populate or clear pending spec fields from resolved spec content."""
    spec_content, resolved_path = resolve_spec_content(
        technical_spec=technical_spec,
        spec_file_path=spec_file_path,
    )

    if resolved_path is not None:
        state["pending_spec_path"] = resolved_path
    elif "pending_spec_path" in state:
        del state["pending_spec_path"]

    if spec_content is not None:
        state["pending_spec_content"] = spec_content
    elif "pending_spec_content" in state:
        del state["pending_spec_content"]


def _load_spec_text_from_file(path_str: str) -> tuple[str, float] | dict[str, Any]:
    path = Path(path_str)
    if not path.exists():
        return {
            "success": False,
            "error": f"Specification file not found: {path_str}",
        }

    file_size_kb = path.stat().st_size / 1024
    if file_size_kb > 100:
        return {
            "success": False,
            "error": f"File too large ({file_size_kb:.1f}KB). Maximum: 100KB",
        }

    try:
        spec_text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return {
            "success": False,
            "error": f"File encoding error. Ensure {path_str} is UTF-8",
        }

    return spec_text, file_size_kb


def _write_backup_spec_file(
    *, product_name: str, product_id: int, spec_text: str
) -> tuple[str, float] | dict[str, Any]:
    file_size_kb = len(spec_text) / 1024
    if file_size_kb > 100:
        return {
            "success": False,
            "error": f"Specification too large ({file_size_kb:.1f}KB). Maximum: 100KB",
        }

    specs_dir = Path("specs")
    specs_dir.mkdir(exist_ok=True)

    safe_name = re.sub(r"[^\w\s-]", "", product_name.lower())
    safe_name = re.sub(r"[-\s]+", "_", safe_name)
    spec_filename = f"{safe_name}_{product_id}_spec.md"
    spec_path_obj = specs_dir / spec_filename

    try:
        spec_path_obj.write_text(spec_text, encoding="utf-8")
    except (OSError, IOError) as exc:
        return {
            "success": False,
            "error": f"Failed to create backup file: {str(exc)}",
        }

    return str(spec_path_obj), file_size_kb


def register_spec_version(
    params: RegisterSpecVersionInput,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Register a new spec version with DRAFT status and SHA-256 hash."""
    del tool_context
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    parsed = RegisterSpecVersionInput.model_validate(params or {})

    spec_hash = hashlib.sha256(parsed.content.encode("utf-8")).hexdigest()

    with Session(_resolve_engine()) as session:
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product ID {parsed.product_id} not found",
            }

        spec_version = SpecRegistry(
            product_id=parsed.product_id,
            spec_hash=spec_hash,
            content=parsed.content,
            content_ref=parsed.content_ref,
            status="draft",
            created_at=datetime.now(timezone.utc),
        )
        session.add(spec_version)
        session.commit()
        session.refresh(spec_version)

        return {
            "success": True,
            "spec_version_id": spec_version.spec_version_id,
            "spec_hash": spec_hash,
            "status": spec_version.status,
            "message": (
                f"Registered spec version {spec_version.spec_version_id} "
                f"(status: {spec_version.status})"
            ),
        }


def approve_spec_version(
    params: ApproveSpecVersionInput,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Approve a spec version so it becomes eligible for compilation."""
    del tool_context
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    parsed = ApproveSpecVersionInput.model_validate(params or {})

    with Session(_resolve_engine()) as session:
        spec_version = session.get(SpecRegistry, parsed.spec_version_id)
        if not spec_version:
            return {
                "success": False,
                "error": f"Spec version {parsed.spec_version_id} not found",
            }

        spec_version.status = "approved"
        spec_version.approved_at = datetime.now(timezone.utc)
        spec_version.approved_by = parsed.approved_by
        spec_version.approval_notes = parsed.approval_notes

        session.add(spec_version)
        session.commit()

        return {
            "success": True,
            "spec_version_id": parsed.spec_version_id,
            "approved_by": parsed.approved_by,
            "approved_at": spec_version.approved_at.isoformat(),
            "message": (
                f"Spec version {parsed.spec_version_id} approved "
                f"by {parsed.approved_by}"
            ),
        }


def link_spec_to_product(
    params: dict[str, Any],
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Link an on-disk specification file to a product and compile authority."""
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    try:
        parsed = LinkSpecToProductInput.model_validate(params or {})
    except ValueError as exc:
        return {"success": False, "error": f"Invalid parameters: {exc}"}

    path = Path(parsed.spec_path)

    if not path.exists():
        return {
            "success": False,
            "error": f"Specification file not found: {parsed.spec_path}",
        }

    file_size_kb = path.stat().st_size / 1024
    if file_size_kb > 100:
        return {
            "success": False,
            "error": f"File too large ({file_size_kb:.1f}KB). Maximum: 100KB",
        }

    with Session(_resolve_engine()) as session:
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product {parsed.product_id} not found",
            }

        is_update = product.spec_file_path is not None
        product.spec_file_path = parsed.spec_path
        product.spec_loaded_at = datetime.now(timezone.utc)
        # NOTE: product.technical_spec is intentionally NOT written.
        # The file on disk + SpecRegistry are the sources of truth.

        session.add(product)
        session.commit()

        product_name = product.name

    action = "updated" if is_update else "linked"
    print(
        f"[link_spec_to_product] Spec {action} "
        f"for '{product_name}' -> {parsed.spec_path} ({file_size_kb:.1f}KB)"
    )

    if tool_context and tool_context.state is not None:
        tool_context.state["spec_persisted"] = True

    compile_result = _compile_linked_spec_authority(
        product_id=parsed.product_id,
        spec_path=parsed.spec_path,
        tool_context=tool_context,
    )

    if not compile_result.get("success"):
        return {
            "success": True,
            "product_id": parsed.product_id,
            "spec_path": parsed.spec_path,
            "file_created": False,
            "spec_size_kb": round(file_size_kb, 2),
            "compile_success": False,
            "compile_error": compile_result.get("error"),
            "message": (
                f"Specification {action} ({file_size_kb:.1f}KB) "
                "but authority compilation failed."
            ),
            "failure_artifact_id": compile_result.get("failure_artifact_id"),
            "failure_stage": compile_result.get("failure_stage"),
            "failure_summary": compile_result.get("failure_summary"),
            "raw_output_preview": compile_result.get("raw_output_preview"),
            "has_full_artifact": compile_result.get("has_full_artifact", False),
        }

    return {
        "success": True,
        "product_id": parsed.product_id,
        "spec_path": parsed.spec_path,
        "file_created": False,
        "spec_size_kb": round(file_size_kb, 2),
        "compile_success": True,
        "spec_version_id": compile_result.get("spec_version_id"),
        "authority_id": compile_result.get("authority_id"),
        "message": (
            f"Specification {action} ({file_size_kb:.1f}KB) "
            "and authority compiled."
        ),
    }


def save_project_specification(
    params: dict[str, Any],
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Save or update a project's specification and compile authority."""
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    try:
        parsed = SaveProjectSpecificationInput.model_validate(params or {})
    except ValueError as exc:
        return {
            "success": False,
            "error": f"Invalid parameters: {str(exc)}",
        }

    if parsed.spec_source not in ["file", "text"]:
        return {
            "success": False,
            "error": (
                f"Invalid spec_source: '{parsed.spec_source}'. Must be 'file' or 'text'"
            ),
        }

    with Session(_resolve_engine()) as session:
        product = session.get(Product, parsed.product_id)
        if not product:
            return {
                "success": False,
                "error": f"Product {parsed.product_id} not found",
            }

        if parsed.spec_source == "file":
            loaded = _load_spec_text_from_file(parsed.content)
            if isinstance(loaded, dict):
                return loaded
            spec_text, file_size_kb = loaded
            spec_path = parsed.content
            file_created = False
        else:
            saved = _write_backup_spec_file(
                product_name=product.name,
                product_id=parsed.product_id,
                spec_text=parsed.content,
            )
            if isinstance(saved, dict):
                return saved
            spec_path, file_size_kb = saved
            spec_text = parsed.content
            file_created = True

        is_update = product.technical_spec is not None
        product.technical_spec = spec_text
        product.spec_file_path = spec_path
        product.spec_loaded_at = datetime.now(timezone.utc)

        session.add(product)
        session.commit()

        action = "updated" if is_update else "saved"

    if tool_context and tool_context.state is not None:
        tool_context.state["spec_persisted"] = True

    compile_result = _compile_spec_authority_from_path(
        product_id=parsed.product_id,
        spec_path=spec_path,
        tool_context=tool_context,
    )

    if not compile_result.get("success"):
        return {
            "success": True,
            "product_id": parsed.product_id,
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
        "product_id": parsed.product_id,
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
    params: dict[str, Any] | None = None,
    tool_context: ToolContext | None = None,
) -> dict[str, Any]:
    """Read the active project's specification through the lifecycle boundary."""
    if hasattr(params, "model_dump"):
        params = params.model_dump()
    ReadProjectSpecificationInput.model_validate(params or {})

    if not tool_context or not tool_context.state:
        return {
            "success": False,
            "error": "No context provided. Tool requires active project.",
            "spec_content": None,
        }

    state: dict[str, Any] = tool_context.state
    active_project = state.get("active_project")
    if not active_project:
        return {
            "success": False,
            "error": "No active project selected. Use select_project first.",
            "spec_content": None,
        }

    product_id = active_project.get("product_id")
    with Session(_resolve_engine()) as session:
        product = session.get(Product, product_id)
        if not product:
            project_name = active_project.get("name")
            return {
                "success": False,
                "error": f"Project '{project_name}' has no specification saved",
                "spec_content": None,
                "hint": (
                    "Spec may have been created without a specification file. "
                    "Ask user to provide one."
                ),
            }

        spec_content, spec_path = resolve_spec_content(
            technical_spec=product.technical_spec,
            spec_file_path=product.spec_file_path,
        )
        if not spec_content:
            project_name = active_project.get("name")
            return {
                "success": False,
                "error": f"Project '{project_name}' has no specification saved",
                "spec_content": None,
                "hint": (
                    "Spec may have been created without a specification file. "
                    "Ask user to provide one."
                ),
            }

        hydrate_spec_state(
            state,
            technical_spec=product.technical_spec,
            spec_file_path=product.spec_file_path,
        )

        sections = extract_markdown_sections(spec_content)
        token_estimate = len(spec_content) // 4

        print(
            f"[read_project_specification] Loaded spec for "
            f"'{product.name}' (~{token_estimate} tokens)"
        )

        return {
            "success": True,
            "spec_content": spec_content,
            "spec_path": spec_path,
            "token_estimate": token_estimate,
            "sections": sections,
            "message": (
                f"Loaded specification (~{token_estimate} tokens, "
                f"{len(sections)} sections)"
            ),
        }


__all__ = [
    "ApproveSpecVersionInput",
    "LinkSpecToProductInput",
    "ReadProjectSpecificationInput",
    "RegisterSpecVersionInput",
    "SaveProjectSpecificationInput",
    "approve_spec_version",
    "extract_markdown_sections",
    "hydrate_spec_state",
    "link_spec_to_product",
    "read_project_specification",
    "register_spec_version",
    "resolve_spec_content",
    "save_project_specification",
]
