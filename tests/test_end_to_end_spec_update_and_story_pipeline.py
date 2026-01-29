"""End-to-end smoke tests for implicit spec update and story pipeline pinning."""

import asyncio

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import CompiledSpecAuthority, Product, SpecRegistry
import tools.spec_tools as spec_tools
from tools.spec_tools import update_spec_and_compile_authority
import orchestrator_agent.agent_tools.story_pipeline.tools as story_tools
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessBatchInput, process_story_batch
from utils.schemes import (
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
    SourceMapEntry,
    Invariant,
    InvariantType,
    RequiredFieldParams,
)


@pytest.fixture
def sample_product(session: Session, engine) -> Product:
    """Create a product for smoke tests."""
    spec_tools.engine = engine
    story_tools.engine = engine

    product = Product(
        name="Spec Update E2E",
        description="Smoke test product",
        vision="Make spec updates explicit",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _build_raw_compiler_output(excerpt: str, field_name: str) -> str:
    invariant = Invariant(
        id="INV-0000000000000000",
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name=field_name),
    )
    success = SpecAuthorityCompilationSuccess(
        scope_themes=["Scope"],
        invariants=[invariant],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[
            SourceMapEntry(
                invariant_id=invariant.id,
                excerpt=excerpt,
                location=None,
            )
        ],
        compiler_version="0.0.0",
        prompt_hash="0" * 64,
    )
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


@pytest.fixture
def compiler_stub(monkeypatch):
    raw_json = _build_raw_compiler_output(
        excerpt="The payload must include user_id.",
        field_name="user_id",
    )
    monkeypatch.setattr(
        spec_tools,
        "_invoke_spec_authority_compiler",
        lambda **_: raw_json,
    )
    return raw_json


@pytest.mark.asyncio
async def test_story_pipeline_requires_spec_input_when_no_authority(
    sample_product: Product,
) -> None:
    """Pipeline should fail fast if no authority exists and no spec content is provided."""
    batch_input = ProcessBatchInput(
        product_id=sample_product.product_id,
        product_name=sample_product.name,
        product_vision=sample_product.vision,
        features=[],
        spec_version_id=None,
    )

    with pytest.raises(RuntimeError) as exc:
        await process_story_batch(batch_input)

    assert "spec" in str(exc.value).lower()


def test_update_spec_and_compile_returns_pinned_version_and_pipeline_accepts_it(
    session: Session,
    sample_product: Product,
    compiler_stub,
) -> None:
    """Pipeline should accept explicit spec_version_id without latest fallback."""
    update_result = update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec v1 content",
        },
        tool_context=None,
    )

    assert update_result["success"] is True
    assert update_result["product_id"] == sample_product.product_id
    assert update_result["spec_version_id"]
    assert update_result["spec_hash"]
    assert update_result["compiled_at"]
    assert update_result["compiler_version"]
    assert update_result["cache_hit"] in (True, False)

    batch_input = ProcessBatchInput(
        product_id=sample_product.product_id,
        product_name=sample_product.name,
        product_vision=sample_product.vision,
        features=[],
        spec_version_id=update_result["spec_version_id"],
    )

    result = asyncio.run(process_story_batch(batch_input))

    assert result["success"] is True
    assert result["total_features"] == 0

    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == update_result["spec_version_id"]
        )
    ).first()
    assert authority is not None


def test_update_same_spec_is_cache_hit_or_reuses_version(
    session: Session,
    sample_product: Product,
    compiler_stub,
) -> None:
    """Identical content should reuse spec version and compiled authority."""
    first = update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec v1 content",
        },
        tool_context=None,
    )

    second = update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec v1 content",
        },
        tool_context=None,
    )

    assert first["spec_hash"] == second["spec_hash"]
    assert first["spec_version_id"] == second["spec_version_id"]
    assert second["cache_hit"] is True

    authorities = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == first["spec_version_id"]
        )
    ).all()
    assert len(authorities) == 1


def test_update_changed_spec_creates_new_version_append_only(
    session: Session,
    sample_product: Product,
    compiler_stub,
) -> None:
    """Changed content should create a new spec version without overwriting."""
    first = update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec v1 content",
        },
        tool_context=None,
    )

    first_spec = session.get(SpecRegistry, first["spec_version_id"])
    assert first_spec is not None
    first_hash = first["spec_hash"]
    first_content = first_spec.content

    second = update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec v2 content - changed",
        },
        tool_context=None,
    )

    assert second["spec_hash"] != first_hash
    assert second["spec_version_id"] != first["spec_version_id"]

    unchanged = session.get(SpecRegistry, first["spec_version_id"])
    assert unchanged is not None
    assert unchanged.spec_hash == first_hash
    assert unchanged.content == first_content

    versions = session.exec(
        select(SpecRegistry).where(SpecRegistry.product_id == sample_product.product_id)
    ).all()
    assert len(versions) == 2
