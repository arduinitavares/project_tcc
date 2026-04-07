"""Tests for HTML snapshot export."""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

from sqlmodel import Session

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    Sprint,
    SprintStatus,
    SprintStory,
    SpecRegistry,
    TimeFrame,
    UserStory,
)
from scripts.export_snapshot import export_snapshot_command
from models.core import Epic, Feature, Team, Theme
from tools.export_snapshot import export_project_snapshot_html
from utils.spec_schemas import (
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


def _insert_story_structure(session: Session, product_id: int) -> UserStory:
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
        is_refined=True,
        story_origin="refined",
    )
    session.add(story)
    session.commit()
    session.refresh(story)
    return story


def _insert_current_sprint(
    session: Session,
    *,
    product_id: int,
    story_ids: list[int],
) -> Sprint:
    team = Team(name=f"Team-{product_id}")
    session.add(team)
    session.commit()
    session.refresh(team)

    sprint = Sprint(
        product_id=product_id,
        team_id=team.team_id,
        goal="Current Sprint Goal",
        start_date=date.today() - timedelta(days=3),
        end_date=date.today() + timedelta(days=7),
        status=SprintStatus.ACTIVE,
    )
    session.add(sprint)
    session.commit()
    session.refresh(sprint)

    for story_id in story_ids:
        session.add(SprintStory(sprint_id=sprint.sprint_id, story_id=story_id))
    session.commit()
    return sprint


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
        product_id = product.product_id  # Capture before session closes
        story = _insert_story_structure(session, product_id)
        _insert_current_sprint(session, product_id=product_id, story_ids=[story.story_id])
        _insert_approved_spec_with_authority(session, product_id)

    output_path = export_project_snapshot_html(
        product_id=product_id,
        output_dir=tmp_path,
        engine_override=engine,
    )

    html = output_path.read_text(encoding="utf-8")
    assert output_path.exists()
    assert "Test Product" in html
    assert "Product Vision" in html
    assert "Vision" in html
    # Spec content renders as markdown <h1> or falls back to <pre> with raw text
    assert "<h1>Spec</h1>" in html or "# Spec" in html
    assert "toc-level-2" in html
    assert "Current Sprint Refined Stories" in html
    assert "Project Backlog (All Stories)" in html
    assert "Payments" in html
    assert "INV-0123456789abcdef" in html


def test_export_snapshot_only_refined_current_sprint_stories(engine, tmp_path: Path) -> None:
    with Session(engine) as session:
        product = _insert_basic_project(session)
        product_id = product.product_id
        in_scope_story = _insert_story_structure(session, product_id)

        non_refined_in_sprint = UserStory(
            product_id=product_id,
            title="Seed backlog story",
            story_description="As a user, I want a seed story",
            acceptance_criteria="Placeholder",
            is_refined=False,
            story_origin="backlog_seed",
        )
        refined_not_in_sprint = UserStory(
            product_id=product_id,
            title="Refined outside sprint",
            story_description="As a user, I want a refined backlog story",
            acceptance_criteria="Done when approved",
            is_refined=True,
            story_origin="refined",
        )
        session.add(non_refined_in_sprint)
        session.add(refined_not_in_sprint)
        session.commit()
        session.refresh(non_refined_in_sprint)
        session.refresh(refined_not_in_sprint)

        _insert_current_sprint(
            session,
            product_id=product_id,
            story_ids=[in_scope_story.story_id, non_refined_in_sprint.story_id],
        )

    output_path = export_project_snapshot_html(
        product_id=product_id,
        output_dir=tmp_path,
        engine_override=engine,
    )
    html = output_path.read_text(encoding="utf-8")

    assert "Pay with card" in html
    assert "Seed backlog story" in html
    assert "Refined outside sprint" in html
    assert "Total 1" in html


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
