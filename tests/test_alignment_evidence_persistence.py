# tests/test_alignment_evidence_persistence.py
"""Tests for alignment findings persisted in ValidationEvidence."""

import json

import pytest
from sqlmodel import Session

import tools.spec_tools as spec_tools
from agile_sqlmodel import Product, Theme, Epic, Feature, UserStory, SpecRegistry
from tools.spec_tools import (
    register_spec_version,
    approve_spec_version,
    compile_spec_authority,
    validate_story_with_spec_authority,
)


@pytest.fixture
def product_with_spec(session: Session, engine) -> tuple[Product, int]:
    """Create product with pre-compiled spec authority containing FORBIDDEN_CAPABILITY."""
    from agile_sqlmodel import CompiledSpecAuthority
    from utils.schemes import (
        Invariant,
        InvariantType,
        ForbiddenCapabilityParams,
        SpecAuthorityCompilationSuccess,
        SpecAuthorityCompilerOutput,
        SourceMapEntry,
    )
    from datetime import datetime, timezone
    import hashlib

    spec_tools.engine = engine

    product = Product(name="Alignment Product", vision="Test")
    session.add(product)
    session.commit()
    session.refresh(product)

    spec_content = "# Spec\n\n## Invariants\n- Stories MUST NOT include web features."
    spec_hash = hashlib.sha256(spec_content.encode()).hexdigest()

    # Create spec registry entry
    spec_version = SpecRegistry(
        product_id=product.product_id,
        content=spec_content,
        spec_hash=spec_hash,
        version_number=1,
        status="approved",
        approved_by="tester",
    )
    session.add(spec_version)
    session.commit()
    session.refresh(spec_version)
    spec_version_id = spec_version.spec_version_id

    # Create pre-compiled authority with explicit FORBIDDEN_CAPABILITY
    invariants = [
        Invariant(
            id="INV-0000000000000001",
            type=InvariantType.FORBIDDEN_CAPABILITY,
            parameters=ForbiddenCapabilityParams(capability="web"),
        ),
    ]
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["core"],
        invariants=invariants,
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[
            SourceMapEntry(
                invariant_id="INV-0000000000000001",
                excerpt="Stories MUST NOT include web features.",
            ),
        ],
        compiler_version="1.0.0",
        prompt_hash="0" * 64,
    )
    authority = CompiledSpecAuthority(
        spec_version_id=spec_version_id,
        compiler_version="1.0.0",
        prompt_hash="test",
        scope_themes="[\"core\"]",
        invariants="[\"FORBIDDEN_CAPABILITY:web\"]",
        eligible_feature_ids="[]",
        rejected_features="[]",
        spec_gaps="[]",
        compiled_artifact_json=SpecAuthorityCompilerOutput(root=success).model_dump_json(),
        compiled_at=datetime.now(timezone.utc),
    )
    session.add(authority)
    session.commit()

    return product, spec_version_id


def _create_story(session: Session, product_id: int, title: str) -> UserStory:
    theme = Theme(product_id=product_id, title="Theme", description="")
    session.add(theme)
    session.commit()
    session.refresh(theme)

    epic = Epic(theme_id=theme.theme_id, title="Epic", description="")
    session.add(epic)
    session.commit()
    session.refresh(epic)

    feature = Feature(epic_id=epic.epic_id, title="Feature", description="")
    session.add(feature)
    session.commit()
    session.refresh(feature)

    story = UserStory(
        product_id=product_id,
        feature_id=feature.feature_id,
        title=title,
        story_description="As a user, I want a feature.",
        acceptance_criteria="- AC",
    )
    session.add(story)
    session.commit()
    session.refresh(story)
    return story


def test_alignment_failure_persisted(engine, session: Session, product_with_spec):
    """Alignment rejection persists alignment_failures in evidence."""
    spec_tools.engine = engine
    product, spec_version_id = product_with_spec

    story = _create_story(session, product.product_id, title="Web dashboard")
    result = validate_story_with_spec_authority(
        {"story_id": story.story_id, "spec_version_id": spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True
    assert result["passed"] is False

    session.refresh(story)
    evidence = json.loads(story.validation_evidence)
    assert evidence["alignment_failures"]
    assert any(f["code"] == "FORBIDDEN_CAPABILITY" for f in evidence["alignment_failures"])


def test_alignment_warning_persisted(engine, session: Session):
    """Alignment warning persists alignment_warnings in evidence."""
    spec_tools.engine = engine

    product = Product(name="Warn Product", vision="Test")
    session.add(product)
    session.commit()
    session.refresh(product)

    # Spec with no MUST statements -> mock extraction yields "No invariants extracted"
    spec_content = "# Spec\n\n## Notes\n- No requirements here"
    reg = register_spec_version(
        {"product_id": product.product_id, "content": spec_content},
        tool_context=None,
    )
    spec_version_id = reg["spec_version_id"]
    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )
    compile_spec_authority(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )

    story = _create_story(session, product.product_id, title="Normal story")
    result = validate_story_with_spec_authority(
        {"story_id": story.story_id, "spec_version_id": spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True

    session.refresh(story)
    evidence = json.loads(story.validation_evidence)
    assert evidence["alignment_warnings"]
    assert any(w["code"] == "NO_INVARIANTS" for w in evidence["alignment_warnings"])


def test_alignment_evidence_includes_spec_and_hash(engine, session: Session, product_with_spec):
    """Evidence includes spec_version_id and input_hash without vision access."""
    spec_tools.engine = engine
    product, spec_version_id = product_with_spec

    story = _create_story(session, product.product_id, title="Web dashboard")
    validate_story_with_spec_authority(
        {"story_id": story.story_id, "spec_version_id": spec_version_id},
        tool_context=None,
    )

    session.refresh(story)
    evidence = json.loads(story.validation_evidence)
    assert evidence["spec_version_id"] == spec_version_id
    assert evidence["input_hash"]