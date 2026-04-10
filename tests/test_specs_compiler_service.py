import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlmodel import select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    SpecAuthorityAcceptance,
    SpecAuthorityStatus,
    SpecRegistry,
)
from utils import failure_artifacts
from utils.failure_artifacts import AgentInvocationError
from utils.spec_schemas import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SourceMapEntry,
    SpecAuthorityCompilationFailure,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)


def _compiled_success_json() -> str:
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
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


def _compiled_failure_json() -> str:
    failure = SpecAuthorityCompilationFailure(
        error="COMPILATION_FAILED",
        reason="Missing scope",
        blocking_gaps=["scope"],
    )
    return SpecAuthorityCompilerOutput(root=failure).model_dump_json()


def _raw_compiler_output_json() -> str:
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
        source_map=[
            SourceMapEntry(
                invariant_id="INV-0123456789abcdef",
                excerpt="The payload must include email.",
                location=None,
            )
        ],
        compiler_version="1.0.0",
        prompt_hash="a" * 64,
    )
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


def _raw_compiler_failure_json() -> str:
    failure = SpecAuthorityCompilationFailure(
        error="COMPILATION_FAILED",
        reason="Missing scope",
        blocking_gaps=["scope"],
    )
    return SpecAuthorityCompilerOutput(root=failure).model_dump_json()


def _create_spec_version(
    session,
    *,
    product_id: int,
    content: str = "Spec A",
) -> SpecRegistry:
    spec_row = SpecRegistry(
        product_id=product_id,
        spec_hash=f"{product_id:064d}"[-64:],
        content=content,
        content_ref=None,
        status="approved",
        approved_at=datetime.now(UTC),
        approved_by="tester",
        approval_notes="approved",
    )
    session.add(spec_row)
    session.commit()
    session.refresh(spec_row)
    return spec_row


def _create_compiled_authority(
    session,
    *,
    spec_version_id: int,
    artifact_json: str,
) -> CompiledSpecAuthority:
    authority = CompiledSpecAuthority(
        spec_version_id=spec_version_id,
        compiler_version="1.2.3",
        prompt_hash="e" * 64,
        compiled_at=datetime.now(UTC),
        compiled_artifact_json=artifact_json,
        scope_themes='["Payments"]',
        invariants='["REQUIRED_FIELD:email"]',
        eligible_feature_ids="[]",
        rejected_features="[]",
        spec_gaps="[]",
    )
    session.add(authority)
    session.commit()
    session.refresh(authority)
    return authority


def test_load_compiled_artifact_returns_success_payload():
    from services.specs.compiler_service import load_compiled_artifact

    authority = SimpleNamespace(compiled_artifact_json=_compiled_success_json())

    artifact = load_compiled_artifact(authority)

    assert artifact is not None
    assert artifact.scope_themes == ["Payments"]
    assert artifact.invariants[0].id == "INV-0123456789abcdef"


def test_load_compiled_artifact_returns_none_for_failure_or_invalid_json():
    from services.specs.compiler_service import load_compiled_artifact

    failure = SpecAuthorityCompilationFailure(
        error="COMPILATION_FAILED",
        reason="Missing scope",
        blocking_gaps=["scope"],
    )
    failure_json = SpecAuthorityCompilerOutput(root=failure).model_dump_json()

    assert (
        load_compiled_artifact(SimpleNamespace(compiled_artifact_json=failure_json))
        is None
    )
    assert (
        load_compiled_artifact(SimpleNamespace(compiled_artifact_json="not-json"))
        is None
    )


def test_services_package_exports_ensure_accepted_spec_authority():
    from services import specs
    from services.specs import compiler_service

    assert (
        specs.ensure_accepted_spec_authority
        is compiler_service.ensure_accepted_spec_authority
    )


def test_ensure_accepted_spec_authority_reuses_existing_accepted_version(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service
    from tools import spec_tools

    monkeypatch.setattr(spec_tools, "engine", session.get_bind(), raising=False)

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )
    acceptance = SpecAuthorityAcceptance(
        product_id=sample_product.product_id,
        spec_version_id=spec_row.spec_version_id,
        status="accepted",
        policy="auto",
        decided_by="system",
        decided_at=datetime.now(UTC),
        rationale="Auto-accepted for test",
        compiler_version=authority.compiler_version,
        prompt_hash=authority.prompt_hash,
        spec_hash=spec_row.spec_hash,
    )
    session.add(acceptance)
    session.commit()

    result = compiler_service.ensure_accepted_spec_authority(
        product_id=sample_product.product_id,
    )

    assert result == spec_row.spec_version_id


def test_ensure_accepted_spec_authority_honors_legacy_tool_update_monkeypatch(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service
    from tools import spec_tools

    monkeypatch.setattr(spec_tools, "engine", session.get_bind(), raising=False)

    captured: dict[str, object] = {}

    def fake_update(params, tool_context=None):
        captured["params"] = params
        captured["tool_context"] = tool_context
        return {
            "success": True,
            "accepted": True,
            "spec_version_id": 777,
            "product_id": sample_product.product_id,
        }

    monkeypatch.setattr(
        spec_tools,
        "update_spec_and_compile_authority",
        fake_update,
        raising=False,
    )

    result = compiler_service.ensure_accepted_spec_authority(
        product_id=sample_product.product_id,
        spec_content="# Spec",
        recompile=True,
    )

    assert result == 777
    assert captured["params"] == {
        "product_id": sample_product.product_id,
        "recompile": True,
        "spec_content": "# Spec",
    }
    assert captured["tool_context"] is None


def test_ensure_spec_authority_accepted_inserts_new_acceptance(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )

    acceptance = compiler_service.ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_row.spec_version_id,
        policy="auto",
        decided_by="system",
        rationale="Auto-accepted on compile success",
    )

    assert acceptance.spec_version_id == spec_row.spec_version_id
    assert acceptance.product_id == sample_product.product_id
    assert acceptance.status == "accepted"
    assert acceptance.policy == "auto"
    assert acceptance.decided_by == "system"
    assert acceptance.compiler_version == authority.compiler_version
    assert acceptance.prompt_hash == authority.prompt_hash
    assert acceptance.spec_hash == spec_row.spec_hash


def test_ensure_spec_authority_accepted_returns_existing_acceptance(
    session, sample_product: Product, monkeypatch
):
    from agile_sqlmodel import SpecAuthorityAcceptance
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )
    existing = SpecAuthorityAcceptance(
        product_id=sample_product.product_id,
        spec_version_id=spec_row.spec_version_id,
        status="accepted",
        policy="human",
        decided_by="reviewer",
        decided_at=datetime.now(UTC),
        rationale="Manual approval",
        compiler_version=authority.compiler_version,
        prompt_hash=authority.prompt_hash,
        spec_hash=spec_row.spec_hash,
    )
    session.add(existing)
    session.commit()
    session.refresh(existing)

    acceptance = compiler_service.ensure_spec_authority_accepted(
        product_id=sample_product.product_id,
        spec_version_id=spec_row.spec_version_id,
        policy="auto",
        decided_by="system",
        rationale="Should be ignored",
    )

    assert acceptance.id == existing.id
    assert acceptance.policy == "human"
    assert acceptance.decided_by == "reviewer"


def test_ensure_spec_authority_accepted_rejects_failure_artifact(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_failure_json(),
    )

    with pytest.raises(
        ValueError,
        match="compiled artifact invalid",
    ):
        compiler_service.ensure_spec_authority_accepted(
            product_id=sample_product.product_id,
            spec_version_id=spec_row.spec_version_id,
            policy="auto",
            decided_by="system",
        )


def test_preview_spec_authority_returns_success_and_updates_cache(
    monkeypatch,
):
    from services.specs import compiler_service

    tool_context = SimpleNamespace(state={})
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    result = compiler_service.preview_spec_authority(
        {"content": "# Spec\n\n## Invariants\n- Auth required."},
        tool_context=tool_context,
    )

    assert result["success"] is True
    assert result["compiled_authority"] is not None
    assert (
        tool_context.state["compiled_authority_cached"] == result["compiled_authority"]
    )


def test_preview_spec_authority_returns_failure_envelope(monkeypatch):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_failure_json(),
    )

    result = compiler_service.preview_spec_authority(
        {"content": "# Spec\n\n## Invariants\n- Missing scope."},
        tool_context=SimpleNamespace(state={}),
    )

    assert result["success"] is False
    assert result["error"] == "Compilation failed"
    assert result["details"]["error"] == "COMPILATION_FAILED"
    assert result["details"]["reason"] == "Missing scope"


def test_preview_spec_authority_returns_invalid_input_envelope():
    from services.specs import compiler_service

    result = compiler_service.preview_spec_authority({}, tool_context=None)

    assert result["success"] is False
    assert result["error"].startswith("Invalid input: ")


def test_preview_spec_authority_returns_unexpected_exception_error(monkeypatch, caplog):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: (_ for _ in ()).throw(RuntimeError("preview boom")),
    )

    with caplog.at_level("ERROR"):
        result = compiler_service.preview_spec_authority(
            {"content": "# Spec"},
            tool_context=SimpleNamespace(state={}),
        )

    assert result == {"success": False, "error": "preview boom"}
    assert any(
        record.levelname == "ERROR"
        and "preview_spec_authority failed" in record.getMessage()
        for record in caplog.records
    )


def test_preview_spec_authority_honors_legacy_tool_compiler_monkeypatch(
    monkeypatch,
):
    from services.specs import compiler_service
    from tools import spec_tools

    tool_context = SimpleNamespace(state={})
    monkeypatch.setattr(
        spec_tools,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    result = compiler_service.preview_spec_authority(
        {"content": "# Spec\n\n## Invariants\n- Auth required."},
        tool_context=tool_context,
    )

    assert result["success"] is True
    assert (
        tool_context.state["compiled_authority_cached"] == result["compiled_authority"]
    )


def test_resolve_engine_honors_legacy_spec_tools_engine(monkeypatch):
    from services.specs import compiler_service
    from tools import spec_tools

    sentinel_engine = object()
    monkeypatch.setattr(spec_tools, "engine", sentinel_engine, raising=False)
    monkeypatch.setattr(
        spec_tools,
        "get_engine",
        compiler_service.get_engine,
    )

    resolved = compiler_service._resolve_engine()

    assert resolved is sentinel_engine


def test_resolve_engine_prefers_patched_spec_tools_get_engine_over_stale_engine(
    monkeypatch,
):
    from services.specs import compiler_service
    from tools import spec_tools

    stale_engine = object()
    preferred_engine = object()
    monkeypatch.setattr(spec_tools, "engine", stale_engine, raising=False)
    monkeypatch.setattr(spec_tools, "get_engine", lambda: preferred_engine)

    resolved = compiler_service._resolve_engine()

    assert resolved is preferred_engine


def test_compile_spec_authority_for_version_persists_authority(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    tool_context = SimpleNamespace(state={})

    result = compiler_service.compile_spec_authority_for_version(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=tool_context,
    )

    assert result["success"] is True
    assert result["cached"] is False
    assert result["recompiled"] is False
    assert result["spec_version_id"] == spec_row.spec_version_id
    assert result["content_source"] == "content"
    assert result["compiler_version"] is not None
    assert sample_product.compiled_authority_json is not None
    assert tool_context.state["compiled_authority_cached"] is not None

    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_row.spec_version_id
        )
    ).first()
    assert authority is not None
    assert authority.compiled_artifact_json == sample_product.compiled_authority_json


def test_compile_spec_authority_persists_authority_with_legacy_envelope(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    tool_context = SimpleNamespace(state={})

    result = compiler_service.compile_spec_authority(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=tool_context,
    )

    assert result["success"] is True
    assert set(result.keys()) == {
        "success",
        "authority_id",
        "spec_version_id",
        "compiler_version",
        "prompt_hash",
        "scope_themes_count",
        "invariants_count",
        "message",
    }
    assert result["spec_version_id"] == spec_row.spec_version_id
    assert len(result["prompt_hash"]) == 8
    assert "compiled_authority_cached" not in tool_context.state

    authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_row.spec_version_id
        )
    ).first()
    assert authority is not None


def test_compile_spec_authority_returns_error_when_already_compiled(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("compiler should not run for already-compiled specs")
        ),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )

    result = compiler_service.compile_spec_authority(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=SimpleNamespace(state={}),
    )

    assert result["success"] is False
    assert result["error"] == (
        f"Spec version {spec_row.spec_version_id} is already compiled "
        f"(authority_id: {authority.authority_id})"
    )


def test_compile_spec_authority_for_version_returns_cached_authority(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: (_ for _ in ()).throw(AssertionError("compiler should not run")),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    existing = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )
    tool_context = SimpleNamespace(state={})

    result = compiler_service.compile_spec_authority_for_version(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=tool_context,
    )

    assert result["success"] is True
    assert result["cached"] is True
    assert "recompiled" not in result
    assert result["authority_id"] == existing.authority_id
    assert result["content_source"] == "content"
    assert (
        tool_context.state["compiled_authority_cached"]
        == existing.compiled_artifact_json
    )
    session.refresh(sample_product)
    assert sample_product.compiled_authority_json == existing.compiled_artifact_json


def test_compile_spec_authority_for_version_uses_content_ref_when_content_empty(
    session, sample_product: Product, tmp_path: Path, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: _raw_compiler_output_json(),
    )

    spec_path = tmp_path / "spec.md"
    spec_path.write_text("Spec from file", encoding="utf-8")
    spec_row = _create_spec_version(
        session,
        product_id=sample_product.product_id,
        content="",
    )
    spec_row.content_ref = str(spec_path)
    session.add(spec_row)
    session.commit()
    session.refresh(spec_row)

    result = compiler_service.compile_spec_authority_for_version(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=SimpleNamespace(state={}),
    )

    assert result["success"] is True
    assert result["content_source"] == "content_ref"


def test_compile_spec_authority_for_version_persists_invocation_failure_artifact(
    session, sample_product: Product, tmp_path: Path, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(failure_artifacts, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(
        failure_artifacts,
        "FAILURES_DIR",
        tmp_path / "logs" / "failures",
    )
    monkeypatch.setattr(
        compiler_service,
        "_invoke_spec_authority_compiler",
        lambda **_: (_ for _ in ()).throw(
            AgentInvocationError(
                "provider timeout",
                partial_output='{"partial": true}',
                event_count=2,
            )
        ),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)

    result = compiler_service.compile_spec_authority_for_version(
        {"spec_version_id": spec_row.spec_version_id},
        tool_context=SimpleNamespace(state={}),
    )

    assert result["success"] is False
    assert result["error"] == "SPEC_COMPILER_INVOCATION_FAILED"
    assert result["failure_artifact_id"] is not None
    artifact = failure_artifacts.read_failure_artifact(result["failure_artifact_id"])
    assert artifact is not None
    assert artifact["phase"] == "spec_authority"
    assert artifact["raw_output"] == '{"partial": true}'


def test_check_spec_authority_status_returns_not_compiled_when_no_spec_versions(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    result = compiler_service.check_spec_authority_status(
        {"product_id": sample_product.product_id},
        tool_context=None,
    )

    assert result == {
        "success": True,
        "status": SpecAuthorityStatus.NOT_COMPILED.value,
        "status_details": "No spec versions exist for this product",
        "message": "Status: NOT_COMPILED (no specs)",
    }


def test_check_spec_authority_status_prefers_pending_review_over_stale(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    approved_spec = _create_spec_version(
        session,
        product_id=sample_product.product_id,
        content="Approved Spec",
    )
    _create_compiled_authority(
        session,
        spec_version_id=approved_spec.spec_version_id,
        artifact_json=_compiled_success_json(),
    )

    draft_spec = SpecRegistry(
        product_id=sample_product.product_id,
        spec_hash="d" * 64,
        content="Draft Spec",
        content_ref=None,
        status="draft",
        approved_at=None,
        approved_by=None,
        approval_notes=None,
    )
    session.add(draft_spec)
    session.commit()
    session.refresh(draft_spec)

    result = compiler_service.check_spec_authority_status(
        {"product_id": sample_product.product_id},
        tool_context=None,
    )

    assert result == {
        "success": True,
        "status": SpecAuthorityStatus.PENDING_REVIEW.value,
        "status_details": (
            f"Latest spec version {draft_spec.spec_version_id} is {draft_spec.status}"
        ),
        "latest_spec_version_id": draft_spec.spec_version_id,
        "message": "Status: PENDING_REVIEW (latest spec not approved)",
    }


def test_get_compiled_authority_by_version_returns_expected_envelope(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = _create_compiled_authority(
        session,
        spec_version_id=spec_row.spec_version_id,
        artifact_json=_compiled_success_json(),
    )

    result = compiler_service.get_compiled_authority_by_version(
        {
            "product_id": sample_product.product_id,
            "spec_version_id": spec_row.spec_version_id,
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert result["spec_version_id"] == spec_row.spec_version_id
    assert result["authority_id"] == authority.authority_id
    assert result["compiler_version"] == authority.compiler_version
    assert result["compiled_at"] == authority.compiled_at.isoformat()
    assert result["scope_themes"] == ["Payments"]
    assert result["invariants"] == ["REQUIRED_FIELD:email"]
    assert result["eligible_feature_ids"] == []
    assert result["rejected_features"] == []
    assert result["spec_gaps"] == []
    assert result["compiled_artifact_json"] == authority.compiled_artifact_json
    assert (
        result["message"]
        == f"Retrieved compiled authority for spec version {spec_row.spec_version_id}"
    )


def test_get_compiled_authority_by_version_falls_back_to_legacy_columns(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    authority = CompiledSpecAuthority(
        spec_version_id=spec_row.spec_version_id,
        compiler_version="9.9.9",
        prompt_hash="f" * 64,
        compiled_at=datetime.now(UTC),
        compiled_artifact_json="not-json",
        scope_themes=json.dumps(["Legacy Theme"]),
        invariants=json.dumps(["FORBIDDEN_CAPABILITY:upload"]),
        eligible_feature_ids=json.dumps([10, 11]),
        rejected_features=json.dumps(["Feature X"]),
        spec_gaps=json.dumps(["gap one"]),
    )
    session.add(authority)
    session.commit()
    session.refresh(authority)

    result = compiler_service.get_compiled_authority_by_version(
        {
            "product_id": sample_product.product_id,
            "spec_version_id": spec_row.spec_version_id,
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert result["scope_themes"] == ["Legacy Theme"]
    assert result["invariants"] == ["FORBIDDEN_CAPABILITY:upload"]
    assert result["eligible_feature_ids"] == [10, 11]
    assert result["rejected_features"] == ["Feature X"]
    assert result["spec_gaps"] == ["gap one"]


def test_get_compiled_authority_by_version_returns_existing_error_messages(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    not_found = compiler_service.get_compiled_authority_by_version(
        {"product_id": sample_product.product_id, "spec_version_id": 999999},
        tool_context=None,
    )
    assert not_found == {"success": False, "error": "Spec version 999999 not found"}

    spec_row = _create_spec_version(session, product_id=sample_product.product_id)
    other_product = Product(
        name="Other Product",
        description="Other",
        vision="Other vision",
    )
    session.add(other_product)
    session.commit()
    session.refresh(other_product)

    mismatch = compiler_service.get_compiled_authority_by_version(
        {
            "product_id": other_product.product_id,
            "spec_version_id": spec_row.spec_version_id,
        },
        tool_context=None,
    )
    assert mismatch == {
        "success": False,
        "error": (
            f"Spec version {spec_row.spec_version_id} does not belong to "
            f"product {other_product.product_id} (mismatch)"
        ),
    }

    not_compiled = compiler_service.get_compiled_authority_by_version(
        {
            "product_id": sample_product.product_id,
            "spec_version_id": spec_row.spec_version_id,
        },
        tool_context=None,
    )
    assert not_compiled == {
        "success": False,
        "error": (
            f"Spec version {spec_row.spec_version_id} is not compiled. "
            "Use compile_spec_authority to compile it."
        ),
    }


@pytest.fixture
def sample_product(session) -> Product:
    product = Product(
        name="Compiler Service Product",
        description="Product for compiler service tests",
        vision="Keep compiler orchestration outside tool modules",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def test_update_spec_and_compile_authority_creates_spec_and_delegates_compile(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    compile_calls: dict[str, object] = {}
    acceptance_calls: dict[str, object] = {}

    def fake_compile(*, spec_version_id: int, force_recompile: bool, tool_context):
        compile_calls["spec_version_id"] = spec_version_id
        compile_calls["force_recompile"] = force_recompile
        compile_calls["tool_context"] = tool_context

        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="1.2.3",
            prompt_hash="b" * 64,
            compiled_at=datetime.now(UTC),
            compiled_artifact_json=_compiled_success_json(),
            scope_themes='["Payments"]',
            invariants='["REQUIRED_FIELD:email"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)

        return {
            "success": True,
            "cached": False,
            "authority_id": authority.authority_id,
        }

    def fake_accept(
        *,
        product_id: int,
        spec_version_id: int,
        policy: str,
        decided_by: str,
        rationale: str | None = None,
    ):
        acceptance_calls["product_id"] = product_id
        acceptance_calls["spec_version_id"] = spec_version_id
        acceptance_calls["policy"] = policy
        acceptance_calls["decided_by"] = decided_by
        acceptance_calls["rationale"] = rationale
        return SimpleNamespace(
            status="accepted",
            policy=policy,
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by=decided_by,
        )

    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(
        compiler_service,
        "_ensure_spec_authority_accepted",
        fake_accept,
        raising=False,
    )

    result = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert result["product_id"] == sample_product.product_id
    assert result["cache_hit"] is False
    assert result["accepted"] is True
    assert compile_calls["force_recompile"] is False
    assert acceptance_calls["product_id"] == sample_product.product_id

    spec_row = session.get(SpecRegistry, result["spec_version_id"])
    assert spec_row is not None
    assert spec_row.content == "Spec A"
    assert spec_row.status == "approved"
    assert spec_row.approved_by == "implicit"


def test_update_spec_and_compile_authority_honors_tool_compile_override(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service
    from tools import spec_tools

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("service compile path should be bypassed")
        ),
    )

    compile_calls: dict[str, object] = {}

    def fake_tool_compile(params, tool_context=None):
        compile_calls["params"] = params
        compile_calls["tool_context"] = tool_context
        spec_version_id = params["spec_version_id"]
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="1.2.3",
            prompt_hash="f" * 64,
            compiled_at=datetime.now(UTC),
            compiled_artifact_json=_compiled_success_json(),
            scope_themes='["Payments"]',
            invariants='["REQUIRED_FIELD:email"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)
        return {
            "success": True,
            "cached": False,
            "authority_id": authority.authority_id,
        }

    monkeypatch.setattr(
        spec_tools,
        "compile_spec_authority_for_version",
        fake_tool_compile,
    )
    monkeypatch.setattr(
        compiler_service,
        "_ensure_spec_authority_accepted",
        lambda **_: SimpleNamespace(
            status="accepted",
            policy="auto",
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by="system",
        ),
        raising=False,
    )

    result = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert compile_calls["params"]["spec_version_id"] == result["spec_version_id"]
    assert compile_calls["params"]["force_recompile"] is False


def test_update_spec_and_compile_authority_honors_tool_acceptance_override(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service
    from tools import spec_tools

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )
    monkeypatch.setattr(
        compiler_service,
        "ensure_spec_authority_accepted",
        lambda **_: (_ for _ in ()).throw(
            AssertionError("service acceptance path should be bypassed")
        ),
    )

    def fake_compile(*, spec_version_id: int, force_recompile: bool, tool_context):
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="1.2.3",
            prompt_hash="a" * 64,
            compiled_at=datetime.now(UTC),
            compiled_artifact_json=_compiled_success_json(),
            scope_themes='["Payments"]',
            invariants='["REQUIRED_FIELD:email"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)
        return {
            "success": True,
            "cached": False,
            "authority_id": authority.authority_id,
        }

    acceptance_calls: dict[str, object] = {}

    def fake_tool_ensure(
        *,
        product_id: int,
        spec_version_id: int,
        policy: str,
        decided_by: str,
        rationale: str | None = None,
    ):
        acceptance_calls["product_id"] = product_id
        acceptance_calls["spec_version_id"] = spec_version_id
        acceptance_calls["policy"] = policy
        acceptance_calls["decided_by"] = decided_by
        acceptance_calls["rationale"] = rationale
        return SimpleNamespace(
            status="accepted",
            policy=policy,
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by=decided_by,
        )

    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        fake_compile,
    )
    monkeypatch.setattr(
        spec_tools,
        "ensure_spec_authority_accepted",
        fake_tool_ensure,
    )

    result = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert acceptance_calls["product_id"] == sample_product.product_id
    assert acceptance_calls["spec_version_id"] == result["spec_version_id"]
    assert acceptance_calls["policy"] == "auto"


def test_update_spec_and_compile_authority_loads_content_ref(
    session, sample_product: Product, tmp_path: Path, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    spec_path = tmp_path / "service_spec.md"
    spec_path.write_text("Spec from file", encoding="utf-8")

    def fake_compile(*, spec_version_id: int, force_recompile: bool, tool_context):
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="1.2.3",
            prompt_hash="c" * 64,
            compiled_at=datetime.now(UTC),
            compiled_artifact_json=_compiled_success_json(),
            scope_themes='["Payments"]',
            invariants='["REQUIRED_FIELD:email"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)
        return {
            "success": True,
            "cached": False,
            "authority_id": authority.authority_id,
        }

    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(
        compiler_service,
        "_ensure_spec_authority_accepted",
        lambda **_: SimpleNamespace(
            status="accepted",
            policy="auto",
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by="system",
        ),
        raising=False,
    )

    result = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "content_ref": str(spec_path),
        },
        tool_context=None,
    )

    assert result["success"] is True

    spec_row = session.get(SpecRegistry, result["spec_version_id"])
    assert spec_row is not None
    assert spec_row.content == "Spec from file"
    assert spec_row.content_ref == str(spec_path)


def test_update_spec_and_compile_authority_reuses_existing_version_for_same_hash(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    compile_calls: list[dict[str, object]] = []
    authority_counter = {"value": 0}

    def fake_compile(*, spec_version_id: int, force_recompile: bool, tool_context):
        compile_calls.append(
            {
                "spec_version_id": spec_version_id,
                "force_recompile": force_recompile,
            }
        )
        existing = session.exec(
            select(CompiledSpecAuthority).where(
                CompiledSpecAuthority.spec_version_id == spec_version_id
            )
        ).first()
        if existing is None:
            authority_counter["value"] += 1
            authority = CompiledSpecAuthority(
                spec_version_id=spec_version_id,
                compiler_version="1.2.3",
                prompt_hash=f"{authority_counter['value']:064d}"[-64:],
                compiled_at=datetime.now(UTC),
                compiled_artifact_json=_compiled_success_json(),
                scope_themes='["Payments"]',
                invariants='["REQUIRED_FIELD:email"]',
                eligible_feature_ids="[]",
                rejected_features="[]",
                spec_gaps="[]",
            )
            session.add(authority)
            session.commit()
            session.refresh(authority)
            authority_id = authority.authority_id
        else:
            authority_id = existing.authority_id
        return {
            "success": True,
            "cached": True,
            "authority_id": authority_id,
        }

    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(
        compiler_service,
        "_ensure_spec_authority_accepted",
        lambda **_: SimpleNamespace(
            status="accepted",
            policy="auto",
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by="system",
        ),
        raising=False,
    )

    first = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
        },
        tool_context=None,
    )
    second = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
        },
        tool_context=None,
    )

    assert first["success"] is True
    assert second["success"] is True
    assert first["spec_version_id"] == second["spec_version_id"]
    assert second["cache_hit"] is True
    assert len(compile_calls) == 2
    assert (
        len(
            session.exec(
                select(SpecRegistry).where(
                    SpecRegistry.product_id == sample_product.product_id
                )
            ).all()
        )
        == 1
    )


def test_update_spec_and_compile_authority_treats_recompile_none_as_false(
    session, sample_product: Product, monkeypatch
):
    from services.specs import compiler_service

    monkeypatch.setattr(
        compiler_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    compile_calls: dict[str, object] = {}

    def fake_compile(*, spec_version_id: int, force_recompile: bool, tool_context):
        compile_calls["force_recompile"] = force_recompile
        authority = CompiledSpecAuthority(
            spec_version_id=spec_version_id,
            compiler_version="1.2.3",
            prompt_hash="d" * 64,
            compiled_at=datetime.now(UTC),
            compiled_artifact_json=_compiled_success_json(),
            scope_themes='["Payments"]',
            invariants='["REQUIRED_FIELD:email"]',
            eligible_feature_ids="[]",
            rejected_features="[]",
            spec_gaps="[]",
        )
        session.add(authority)
        session.commit()
        session.refresh(authority)
        return {
            "success": True,
            "cached": False,
            "authority_id": authority.authority_id,
        }

    monkeypatch.setattr(
        compiler_service,
        "compile_spec_authority_for_version",
        fake_compile,
        raising=False,
    )
    monkeypatch.setattr(
        compiler_service,
        "_ensure_spec_authority_accepted",
        lambda **_: SimpleNamespace(
            status="accepted",
            policy="auto",
            decided_at=SimpleNamespace(isoformat=lambda: "2026-04-05T00:00:00+00:00"),
            decided_by="system",
        ),
        raising=False,
    )

    result = compiler_service.update_spec_and_compile_authority(
        {
            "product_id": sample_product.product_id,
            "spec_content": "Spec A",
            "recompile": None,
        },
        tool_context=None,
    )

    assert result["success"] is True
    assert compile_calls["force_recompile"] is False
    assert result["cache_hit"] is False
