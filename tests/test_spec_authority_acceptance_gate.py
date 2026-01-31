"""Tests for Spec Authority acceptance gate and load-time enforcement."""

import json
import hashlib
from datetime import datetime, timezone

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import (
    Product,
    SpecRegistry,
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
)
from orchestrator_agent.agent_tools.story_pipeline.common import load_compiled_authority
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    SPEC_AUTHORITY_COMPILER_VERSION,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_prompt_hash,
    compute_invariant_id,
)
from utils.schemes import (
    SpecAuthorityCompilationSuccess,
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SourceMapEntry,
)
import tools.spec_tools as spec_tools
from tools.spec_tools import ensure_spec_authority_accepted


@pytest.fixture
def sample_product(session: Session, engine) -> Product:
    spec_tools.engine = engine
    product = Product(
        name="Acceptance Gate Product",
        description="Product for acceptance gate tests",
        vision="Keep authority explicit",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _create_spec_and_compiled_authority(
    session: Session,
    product_id: int,
) -> tuple[SpecRegistry, CompiledSpecAuthority]:
    spec_content = "# Spec v1\n\n## Scope\n- Feature A\n\n## Invariants\n- The payload must include user_id."
    spec_hash = hashlib.sha256(spec_content.encode("utf-8")).hexdigest()

    spec_version = SpecRegistry(
        product_id=product_id,
        spec_hash=spec_hash,
        content=spec_content,
        content_ref=None,
        status="approved",
        approved_at=datetime.now(timezone.utc),
        approved_by="tester",
        approval_notes="approved",
    )
    session.add(spec_version)
    session.commit()
    session.refresh(spec_version)

    prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
    invariant_id = compute_invariant_id(
        "The payload must include user_id.",
        InvariantType.REQUIRED_FIELD,
    )
    invariant = Invariant(
        id=invariant_id,
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name="user_id"),
    )
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["Scope"],
        invariants=[invariant],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[
            SourceMapEntry(
                invariant_id=invariant_id,
                excerpt="The payload must include user_id.",
                location=None,
            )
        ],
        compiler_version=SPEC_AUTHORITY_COMPILER_VERSION,
        prompt_hash=prompt_hash,
    )

    compiled = CompiledSpecAuthority(
        spec_version_id=spec_version.spec_version_id,
        compiler_version=SPEC_AUTHORITY_COMPILER_VERSION,
        prompt_hash=prompt_hash,
        compiled_at=datetime.now(timezone.utc),
        compiled_artifact_json=success.model_dump_json(),
        scope_themes=json.dumps(["Scope"]),
        invariants=json.dumps(["REQUIRED_FIELD:user_id"]),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )
    session.add(compiled)
    session.commit()
    session.refresh(compiled)

    return spec_version, compiled


def test_compiled_but_not_accepted_is_blocked(
    session: Session, sample_product: Product
) -> None:
    spec_version, _compiled = _create_spec_and_compiled_authority(
        session, sample_product.product_id
    )

    with pytest.raises(ValueError) as exc:
        load_compiled_authority(
            session=session,
            product_id=sample_product.product_id,
            spec_version_id=spec_version.spec_version_id,
        )

    message = str(exc.value).lower()
    assert str(spec_version.spec_version_id) in message
    assert "not accepted" in message


def test_auto_accepted_spec_can_be_loaded(
    session: Session, sample_product: Product
) -> None:
    spec_version, _compiled = _create_spec_and_compiled_authority(
        session, sample_product.product_id
    )

    acceptance = ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
        policy="auto",
        decided_by="system",
        rationale="Auto-accepted on compile success",
    )

    assert acceptance.status == "accepted"

    loaded_spec, authority, _technical_spec = load_compiled_authority(
        session=session,
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
    )
    assert loaded_spec.spec_version_id == spec_version.spec_version_id
    assert authority.spec_version_id == spec_version.spec_version_id


def test_acceptance_append_only_and_idempotent(
    session: Session, sample_product: Product
) -> None:
    spec_version, _compiled = _create_spec_and_compiled_authority(
        session, sample_product.product_id
    )
    rejected = SpecAuthorityAcceptance(
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
        status="rejected",
        policy="human",
        decided_by="reviewer",
        decided_at=datetime.now(timezone.utc),
        rationale="Rejected for missing scope",
        compiler_version=SPEC_AUTHORITY_COMPILER_VERSION,
        prompt_hash=compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS),
        spec_hash=spec_version.spec_hash,
    )
    session.add(rejected)
    session.commit()

    accepted = ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
        policy="human",
        decided_by="reviewer",
        rationale="Approved after revision",
    )

    second = ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
        policy="human",
        decided_by="reviewer",
        rationale="Approved after revision",
    )

    assert accepted.id == second.id

    all_rows = session.exec(
        select(SpecAuthorityAcceptance).where(
            SpecAuthorityAcceptance.spec_version_id == spec_version.spec_version_id
        )
    ).all()
    assert len(all_rows) == 2
    assert accepted.status == "accepted"


def test_acceptance_captures_reproducibility_fields(
    session: Session, sample_product: Product
) -> None:
    spec_version, compiled = _create_spec_and_compiled_authority(
        session, sample_product.product_id
    )

    acceptance = ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_version.spec_version_id,
        policy="auto",
        decided_by="system",
        rationale="Auto-accepted on compile success",
    )

    assert acceptance.prompt_hash == compiled.prompt_hash
    assert acceptance.compiler_version == compiled.compiler_version
    assert acceptance.spec_hash == spec_version.spec_hash
