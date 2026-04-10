from datetime import UTC, datetime
from types import SimpleNamespace

from agile_sqlmodel import CompiledSpecAuthority, Product, SpecRegistry, UserStory
from utils.spec_schemas import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SourceMapEntry,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
    ValidationEvidence,
)


def test_services_package_exports_validate_story_with_spec_authority():
    from services import specs
    from services.specs import story_validation_service

    assert (
        specs.validate_story_with_spec_authority
        is story_validation_service.validate_story_with_spec_authority
    )
    assert (
        specs.compute_story_input_hash
        is story_validation_service.compute_story_input_hash
    )


def test_validate_story_with_spec_authority_returns_missing_story_error(
    session, monkeypatch
):
    from services.specs import story_validation_service

    monkeypatch.setattr(
        story_validation_service,
        "get_engine",
        lambda: session.get_bind(),
    )

    result = story_validation_service.validate_story_with_spec_authority(
        {"story_id": 999999, "spec_version_id": 123},
        tool_context=None,
    )

    assert result == {
        "success": False,
        "error": "Story 999999 not found",
    }


def test_resolve_engine_honors_legacy_spec_tools_engine(monkeypatch):
    from services.specs import story_validation_service
    from tools import spec_tools

    sentinel_engine = object()
    monkeypatch.setattr(spec_tools, "engine", sentinel_engine, raising=False)
    monkeypatch.setattr(
        spec_tools,
        "get_engine",
        story_validation_service.get_engine,
    )

    resolved = story_validation_service._resolve_engine()

    assert resolved is sentinel_engine


def test_compute_story_input_hash_is_stable_for_same_story_content():
    from services.specs.story_validation_service import (
        compute_story_input_hash,
    )

    story_a = SimpleNamespace(
        title="Story",
        story_description="Description",
        acceptance_criteria="Criteria",
    )
    story_b = SimpleNamespace(
        title="Story",
        story_description="Description",
        acceptance_criteria="Criteria",
    )

    assert compute_story_input_hash(story_a) == compute_story_input_hash(story_b)


def test_compute_story_input_hash_changes_when_story_content_changes():
    from services.specs.story_validation_service import (
        compute_story_input_hash,
    )

    story_a = SimpleNamespace(
        title="Story",
        story_description="Description",
        acceptance_criteria="Criteria",
    )
    story_b = SimpleNamespace(
        title="Story",
        story_description="Changed",
        acceptance_criteria="Criteria",
    )

    assert compute_story_input_hash(story_a) != compute_story_input_hash(story_b)


def test_render_invariant_summary_formats_required_field():
    from services.specs.story_validation_service import render_invariant_summary

    invariant = Invariant(
        id="INV-0000000000000001",
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name="user_id"),
    )

    assert render_invariant_summary(invariant) == "REQUIRED_FIELD:user_id"


def test_parse_llm_validator_response_parses_compliant_payload():
    from services.specs.story_validation_service import parse_llm_validator_response

    result = parse_llm_validator_response(
        """
        {"is_compliant": true, "issues": [], "suggestions": [],
         "verdict": "Compliant", "domain_compliance": null}
        """
    )

    assert result == {
        "passed": True,
        "issues": [],
        "suggestions": [],
        "verdict": "Compliant",
        "critical_gaps": [],
    }


def test_run_llm_spec_validation_uses_injected_helpers():
    from services.specs.story_validation_service import run_llm_spec_validation

    captured = {}

    async def fake_invoke(payload_text: str) -> str:
        captured["payload"] = payload_text
        return '{"is_compliant": true, "issues": [], "suggestions": [], "verdict": "Compliant"}'

    def fake_parse(raw_text: str):
        captured["raw_text"] = raw_text
        return {
            "passed": True,
            "issues": [],
            "suggestions": [],
            "verdict": "Compliant",
            "critical_gaps": [],
        }

    story = SimpleNamespace(
        title="As a user, I want exports",
        story_description="Export data for audit.",
        acceptance_criteria="Given reports, when exported, then CSV is generated.",
    )
    authority = SimpleNamespace(
        spec_version_id=42,
        compiled_artifact_json='{"compiled": true}',
    )
    artifact = SimpleNamespace(
        model_dump_json=lambda: '{"compiled": "from artifact"}',
    )

    result = run_llm_spec_validation(
        story,
        authority,
        artifact,
        feature=None,
        invoke_spec_validator_async_fn=fake_invoke,
        parse_llm_validator_response_fn=fake_parse,
    )

    assert result["passed"] is True
    assert (
        '"compiled_authority_json": "{\\"compiled\\": \\"from artifact\\"}"'
        in captured["payload"]
    )
    assert captured["raw_text"].startswith('{"is_compliant": true')


def test_resolve_default_validation_mode_uses_environment(monkeypatch):
    from services.specs.story_validation_service import (
        resolve_default_validation_mode,
    )

    monkeypatch.setenv("SPEC_VALIDATION_DEFAULT_MODE", "hybrid")

    assert resolve_default_validation_mode() == "hybrid"


def test_persist_validation_evidence_updates_story_and_acceptance(session):
    from services.specs.story_validation_service import (
        persist_validation_evidence,
    )

    product = Product(name="Evidence Product", vision="Test")
    session.add(product)
    session.commit()
    session.refresh(product)

    story = UserStory(
        product_id=product.product_id,
        title="Story",
        story_description="Description",
        acceptance_criteria="Criteria",
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    spec_version = SpecRegistry(
        product_id=product.product_id,
        content="# Spec",
        content_ref=None,
        spec_hash="a" * 64,
        version_number=1,
        status="approved",
        approved_at=datetime.now(UTC),
        approved_by="tester",
        approval_notes=None,
    )
    session.add(spec_version)
    session.commit()
    session.refresh(spec_version)

    evidence = ValidationEvidence(
        spec_version_id=spec_version.spec_version_id,
        validated_at=datetime.now(UTC),
        passed=True,
        rules_checked=["SPEC_VERSION_EXISTS"],
        invariants_checked=[],
        validator_version="1.0.0",
        input_hash="abc123",
    )

    persist_validation_evidence(session, story, evidence, passed=True)

    session.expire(story)
    updated = session.get(UserStory, story.story_id)

    assert updated.validation_evidence == evidence.model_dump_json()
    assert updated.accepted_spec_version_id == spec_version.spec_version_id


def test_validate_story_with_spec_authority_uses_service_owned_defaults(
    session, monkeypatch
):
    from services.specs import story_validation_service

    product = Product(name="Validation Product", vision="Test")
    session.add(product)
    session.commit()
    session.refresh(product)

    story = UserStory(
        product_id=product.product_id,
        title="Story",
        story_description="Description",
        acceptance_criteria="Criteria",
    )
    session.add(story)
    session.commit()
    session.refresh(story)

    spec_version = SpecRegistry(
        product_id=product.product_id,
        content="# Spec",
        content_ref=None,
        spec_hash="b" * 64,
        version_number=1,
        status="approved",
        approved_at=datetime.now(UTC),
        approved_by="tester",
        approval_notes=None,
    )
    session.add(spec_version)
    session.commit()
    session.refresh(spec_version)

    authority_artifact = SpecAuthorityCompilationSuccess(
        scope_themes=["core"],
        invariants=[],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[
            SourceMapEntry(
                invariant_id="INV-0000000000000001",
                excerpt="Spec excerpt",
                location="spec",
            )
        ],
        compiler_version="1.0.0",
        prompt_hash="0" * 64,
    )
    authority = CompiledSpecAuthority(
        spec_version_id=spec_version.spec_version_id,
        compiler_version="1.0.0",
        prompt_hash="0" * 64,
        scope_themes='["core"]',
        invariants="[]",
        eligible_feature_ids="[]",
        rejected_features="[]",
        spec_gaps="[]",
        compiled_artifact_json=SpecAuthorityCompilerOutput(
            root=authority_artifact
        ).model_dump_json(),
    )
    session.add(authority)
    session.commit()

    monkeypatch.setattr(
        story_validation_service,
        "_resolve_engine",
        lambda: session.get_bind(),
    )

    monkeypatch.setattr(
        story_validation_service,
        "resolve_default_validation_mode",
        lambda: "llm",
    )

    llm_calls = {}

    def fake_run_llm_validation(story_arg, authority_arg, artifact_arg, feature=None):
        llm_calls["story_id"] = story_arg.story_id
        llm_calls["authority_id"] = authority_arg.authority_id
        llm_calls["artifact"] = artifact_arg
        llm_calls["feature"] = feature
        return {
            "passed": True,
            "issues": [],
            "suggestions": [],
            "verdict": "Compliant",
            "critical_gaps": [],
        }

    monkeypatch.setattr(
        story_validation_service,
        "run_llm_spec_validation",
        fake_run_llm_validation,
    )

    persisted = {}

    def fake_persist(session_arg, story_arg, evidence_arg, passed):
        persisted["session"] = session_arg
        persisted["story"] = story_arg
        persisted["evidence"] = evidence_arg
        persisted["passed"] = passed

    monkeypatch.setattr(
        story_validation_service,
        "persist_validation_evidence",
        fake_persist,
    )

    result = story_validation_service.validate_story_with_spec_authority(
        {"story_id": story.story_id, "spec_version_id": spec_version.spec_version_id},
        tool_context=None,
    )

    assert result["success"] is True
    assert result["passed"] is True
    assert result["mode"] == "llm"
    assert llm_calls["story_id"] == story.story_id
    assert persisted["story"].story_id == story.story_id
    assert persisted["passed"] is True
    assert persisted["evidence"].spec_version_id == spec_version.spec_version_id
