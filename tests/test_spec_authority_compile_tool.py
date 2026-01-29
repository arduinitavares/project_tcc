"""
Tests for Spec Authority compile tool used by the orchestrator.
"""

import json
from pathlib import Path

import pytest
from sqlmodel import Session, select

from agile_sqlmodel import CompiledSpecAuthority, Product
import tools.spec_tools as spec_tools
from tools.spec_tools import (
    approve_spec_version,
    compile_spec_authority_for_version,
    register_spec_version,
)
from utils.schemes import (
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
    SourceMapEntry,
    Invariant,
    InvariantType,
    RequiredFieldParams,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    SPEC_AUTHORITY_COMPILER_VERSION,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_prompt_hash,
    compute_invariant_id,
)


@pytest.fixture
def sample_product(session: Session, engine) -> Product:
    """Create a product without spec."""
    spec_tools.engine = engine

    product = Product(
        name="Compile Tool Product",
        description="Product for compile tool tests",
        vision="Keep spec authority deterministic",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@pytest.fixture
def sample_spec_content() -> str:
    """Sample spec content for testing."""
    return """
# Technical Specification v1

## Scope
- Feature A: User authentication
- Feature B: Data export

## Invariants
- All API calls MUST require auth token.
- Export formats SHALL be CSV or JSON only.
"""


@pytest.fixture
def compiler_stub(monkeypatch):
    """Stub compiler agent to avoid real LLM calls."""
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


def test_compile_tool_blocks_unapproved_spec(
    session: Session, sample_product: Product, sample_spec_content: str
) -> None:
    """Compilation should fail for unapproved spec versions."""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": sample_spec_content},
        tool_context=None,
    )

    result = compile_spec_authority_for_version(
        {"spec_version_id": reg_result["spec_version_id"]},
        tool_context=None,
    )

    assert result["success"] is False
    assert "not approved" in result["error"].lower()


def test_compile_tool_compiles_and_returns_summary(
    session: Session,
    sample_product: Product,
    sample_spec_content: str,
    compiler_stub,
) -> None:
    """Compilation should create authority and return summary payload."""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": sample_spec_content},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    result = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True
    assert result["cached"] is False
    assert result["spec_version_id"] == spec_version_id
    assert result["compiler_version"] == SPEC_AUTHORITY_COMPILER_VERSION
    assert len(result["prompt_hash"]) == 64
    assert result["scope_themes_count"] >= 1
    assert result["invariants_count"] >= 1

    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()

    assert authority is not None


def test_compile_tool_returns_cached_when_already_compiled(
    session: Session,
    sample_product: Product,
    sample_spec_content: str,
    compiler_stub,
) -> None:
    """Compilation tool should be idempotent for existing authority."""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": sample_spec_content},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    first = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )
    assert first["success"] is True

    result = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True
    assert result["cached"] is True
    assert result["authority_id"] == first["authority_id"]


def test_compile_tool_uses_content_ref_when_content_empty(
    session: Session,
    sample_product: Product,
    tmp_path: Path,
    compiler_stub,
) -> None:
    """Compilation should load spec content from content_ref when needed."""
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(
        """
# Spec v1

## API
- Endpoint: /v1/data

## Invariants
- Requests MUST include a token.
""",
        encoding="utf-8",
    )

    reg_result = register_spec_version(
        {
            "product_id": sample_product.product_id,
            "content": "",
            "content_ref": str(spec_path),
        },
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    result = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True
    assert result["content_source"] == "content_ref"

    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()

    scope_themes = json.loads(authority.scope_themes)
    assert len(scope_themes) >= 1


def _build_raw_compiler_output(excerpt: str, field_name: str) -> str:
    """Build a raw compiler JSON output (pre-normalization)."""
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


def test_compile_persists_compiled_artifact_and_normalized_ids(
    session: Session, sample_product: Product, sample_spec_content: str, monkeypatch
) -> None:
    """Compilation should persist normalized artifact and deterministic IDs."""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": sample_spec_content},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    raw_json = _build_raw_compiler_output(
        excerpt="The payload must include user_id.",
        field_name="user_id",
    )
    monkeypatch.setattr(
        spec_tools,
        "_invoke_spec_authority_compiler",
        lambda **_: raw_json,
    )

    result = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )
    assert result["success"] is True

    session.expire_all()
    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()

    assert authority is not None
    assert authority.compiled_artifact_json

    parsed = SpecAuthorityCompilerOutput.model_validate_json(
        authority.compiled_artifact_json
    )
    assert isinstance(parsed.root, SpecAuthorityCompilationSuccess)

    expected_prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
    assert parsed.root.prompt_hash == expected_prompt_hash
    assert authority.prompt_hash == expected_prompt_hash

    for inv in parsed.root.invariants:
        entry = next(
            (e for e in parsed.root.source_map if e.invariant_id == inv.id), None
        )
        assert entry is not None
        expected_id = compute_invariant_id(entry.excerpt, inv.type)
        assert inv.id == expected_id
        assert entry.invariant_id == expected_id


def test_compile_cache_hit_does_not_change_compiled_artifact(
    session: Session, sample_product: Product, sample_spec_content: str, monkeypatch
) -> None:
    """Cache hit should not change artifact unless force_recompile=True."""
    reg_result = register_spec_version(
        {"product_id": sample_product.product_id, "content": sample_spec_content},
        tool_context=None,
    )
    spec_version_id = reg_result["spec_version_id"]

    approve_spec_version(
        {"spec_version_id": spec_version_id, "approved_by": "tester"},
        tool_context=None,
    )

    raw_json_1 = _build_raw_compiler_output(
        excerpt="The payload must include user_id.",
        field_name="user_id",
    )
    raw_json_2 = _build_raw_compiler_output(
        excerpt="The payload must include account_id.",
        field_name="account_id",
    )

    call_count = {"count": 0}

    def _fake_invoke(**_) -> str:
        call_count["count"] += 1
        return raw_json_1 if call_count["count"] == 1 else raw_json_2

    monkeypatch.setattr(spec_tools, "_invoke_spec_authority_compiler", _fake_invoke)

    first = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )
    assert first["success"] is True

    session.expire_all()
    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()
    assert authority is not None
    artifact_first = authority.compiled_artifact_json

    second = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id},
        tool_context=None,
    )
    assert second["success"] is True
    assert second["cached"] is True
    assert call_count["count"] == 1

    session.expire_all()
    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()
    assert authority is not None
    assert authority.compiled_artifact_json == artifact_first

    third = compile_spec_authority_for_version(
        {"spec_version_id": spec_version_id, "force_recompile": True},
        tool_context=None,
    )
    assert third["success"] is True
    assert call_count["count"] == 2

    session.expire_all()
    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()
    assert authority is not None
    assert authority.compiled_artifact_json != artifact_first
