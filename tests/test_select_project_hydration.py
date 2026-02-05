"""Tests for select_project hydration of session state."""

from datetime import datetime, timezone

import pytest
from sqlmodel import Session

from agile_sqlmodel import Product, SpecRegistry
from tools.orchestrator_tools import get_project_details, select_project


class MockToolContext:
    """Minimal ToolContext stub with state dict."""

    def __init__(self, state):
        self.state = state


def _create_product(session: Session, **kwargs) -> Product:
    product = Product(
        name=kwargs.get("name", "Hydration Project"),
        vision=kwargs.get("vision", "Vision"),
        description=kwargs.get("description"),
        roadmap=kwargs.get("roadmap"),
        technical_spec=kwargs.get("technical_spec"),
        compiled_authority_json=kwargs.get("compiled_authority_json"),
        spec_file_path=kwargs.get("spec_file_path"),
        spec_loaded_at=kwargs.get("spec_loaded_at"),
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _create_approved_spec(session: Session, product_id: int) -> SpecRegistry:
    spec = SpecRegistry(
        product_id=product_id,
        spec_hash="hash",
        content="# Spec content",
        content_ref="specs/spec.md",
        status="approved",
        approved_at=datetime.now(timezone.utc),
        approved_by="tester",
    )
    session.add(spec)
    session.commit()
    session.refresh(spec)
    return spec


def test_select_project_hydrates_spec_and_authority(session: Session) -> None:
    spec_loaded_at = datetime.now(timezone.utc)
    product = _create_product(
        session,
        technical_spec="Spec body",
        compiled_authority_json="{\"compiled\":true}",
        spec_file_path="specs/spec.md",
        spec_loaded_at=spec_loaded_at,
        description="Desc",
    )
    spec = _create_approved_spec(session, product.product_id)

    state = {
        "pending_spec_content": "OLD",
        "pending_spec_path": "OLD",
        "compiled_authority_cached": "OLD",
        "latest_spec_version_id": 999,
    }
    context = MockToolContext(state)

    result = select_project(product.product_id, context)

    assert result["success"] is True
    assert context.state["pending_spec_content"] == "Spec body"
    assert context.state["pending_spec_path"] == "specs/spec.md"
    assert context.state["compiled_authority_cached"] == "{\"compiled\":true}"
    assert context.state["latest_spec_version_id"] == spec.spec_version_id
    assert context.state["current_project_name"] == product.name

    active_project = context.state["active_project"]
    assert active_project["description"] == "Desc"
    assert active_project["technical_spec"] == "Spec body"
    assert active_project["compiled_authority_json"] == "{\"compiled\":true}"
    assert active_project["spec_file_path"] == "specs/spec.md"
    expected_loaded_at = spec_loaded_at.replace(tzinfo=None).isoformat()
    assert active_project["spec_loaded_at"] == expected_loaded_at


def test_select_project_clears_missing_spec_state(session: Session) -> None:
    product = _create_product(session)

    state = {
        "pending_spec_content": "OLD",
        "pending_spec_path": "OLD",
        "compiled_authority_cached": "OLD",
        "latest_spec_version_id": 999,
    }
    context = MockToolContext(state)

    result = select_project(product.product_id, context)

    assert result["success"] is True
    assert "pending_spec_content" not in context.state
    assert "pending_spec_path" not in context.state
    assert "compiled_authority_cached" not in context.state
    assert "latest_spec_version_id" not in context.state


def test_get_project_details_includes_spec_fields(session: Session) -> None:
    spec_loaded_at = datetime.now(timezone.utc)
    product = _create_product(
        session,
        technical_spec="Spec body",
        compiled_authority_json="{\"compiled\":true}",
        spec_file_path="specs/spec.md",
        spec_loaded_at=spec_loaded_at,
        description="Desc",
    )
    spec = _create_approved_spec(session, product.product_id)

    result = get_project_details(product.product_id)

    assert result["success"] is True
    details = result["product"]
    assert details["technical_spec"] == "Spec body"
    assert details["compiled_authority_json"] == "{\"compiled\":true}"
    assert details["spec_file_path"] == "specs/spec.md"
    expected_loaded_at = spec_loaded_at.replace(tzinfo=None).isoformat()
    assert details["spec_loaded_at"] == expected_loaded_at
    assert details["latest_spec_version_id"] == spec.spec_version_id
