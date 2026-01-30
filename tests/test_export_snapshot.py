"""Tests for HTML snapshot export."""

from __future__ import annotations

import json
from pathlib import Path

from sqlmodel import Session

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Epic,
    Feature,
    Product,
    SpecRegistry,
    Theme,
    TimeFrame,
    UserStory,
)
from scripts.export_snapshot import export_snapshot_command
from tools.export_snapshot import export_project_snapshot_html
from utils.schemes import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)


def _insert_basic_project(session: Session) -> Product:
    product = Product(
        name="Test Product",
        description="Demo",
        vision="Vision **bold**",
        roadmap="Roadmap text",
        technical_spec="Fallback spec",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _insert_story_structure(session: Session, product_id: int) -> None:
    theme = Theme(
        product_id=product_id,
        title="Payments",
        description="Payment flows",
        time_frame=TimeFrame.NOW,
    )
    session.add(theme)
    session.commit()
    session.refresh(theme)

    epic = Epic(
        theme_id=theme.theme_id,
        title="Checkout",
        summary="Checkout flow",
    )
    session.add(epic)
    session.commit()
    session.refresh(epic)

    feature = Feature(
        epic_id=epic.epic_id,
        title="Card payments",
        description="Support card payments",
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)

    story = UserStory(
        product_id=product_id,
        feature_id=feature.feature_id,
        title="Pay with card",
        story_description="As a buyer, I want to pay with card",
        acceptance_criteria="Given a valid card, when I pay, then it succeeds",
        story_points=3,
    )
    session.add(story)
    session.commit()


def _insert_approved_spec_with_authority(session: Session, product_id: int) -> SpecRegistry:
    spec = SpecRegistry(
        product_id=product_id,
        spec_hash="hash123",
        content="# Spec\n## Section",
        content_ref="specs/test.md",
        status="approved",
        approved_by="reviewer@example.com",
        approval_notes="Looks good",
    )
    session.add(spec)
    session.commit()
    session.refresh(spec)

    success = SpecAuthorityCompilationSuccess(
        scope_themes=["Payments"],
        invariants=[
            Invariant(
                id="INV-0123456789abcdef",
                type=InvariantType.REQUIRED_FIELD,
                parameters=RequiredFieldParams(field_name="email"),
            )
        ],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[],
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
    )
    compiled_json = SpecAuthorityCompilerOutput(success).model_dump_json()

    authority = CompiledSpecAuthority(
        spec_version_id=spec.spec_version_id,
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
        scope_themes=json.dumps(["Payments"]),
        invariants=json.dumps([
            {
                "id": "INV-0123456789abcdef",
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "email"},
            }
        ]),
        eligible_feature_ids=json.dumps([]),
        compiled_artifact_json=compiled_json,
    )
    session.add(authority)
    session.commit()

    return spec


def test_export_snapshot_html_basic(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        product = _insert_basic_project(session)
        _insert_story_structure(session, product.product_id)
        _insert_approved_spec_with_authority(session, product.product_id)

    output_path = export_project_snapshot_html(
        product_id=product.product_id,
        output_dir=tmp_path,
        engine_override=engine,
    )

    html = output_path.read_text(encoding="utf-8")
    assert output_path.exists()
    assert "Test Product" in html
    assert "Product Vision" in html
    assert "Vision" in html
    assert "<h1>Spec</h1>" in html
    assert "User Stories" in html
    assert "Payments" in html
    assert "INV-0123456789abcdef" in html


def test_export_snapshot_falls_back_to_product_spec(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        product = _insert_basic_project(session)

    output_path = export_project_snapshot_html(
        product_id=product.product_id,
        output_dir=tmp_path,
        engine_override=engine,
    )

    html = output_path.read_text(encoding="utf-8")
    assert "Fallback spec" in html


def test_export_snapshot_command_writes_file(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        product = _insert_basic_project(session)

    output_path = export_snapshot_command(
        product_id=product.product_id,
        output_dir=tmp_path,
        engine_override=engine,
    )

    assert output_path.exists()