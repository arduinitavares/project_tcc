"""Tests for compiled authority generation context usage in story drafting."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Epic,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
    Theme,
)
from orchestrator_agent.agent_tools.story_pipeline.util.story_generation_context import (
    build_generation_context,
)
from utils.schemes import (
    Invariant,
    InvariantType,
    RequiredFieldParams,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
)


# =============================================================================
# CONSTANTS
# =============================================================================

COMPILER_VERSION = "1.0.0"
PROMPT_HASH = "a" * 64
SPEC_HASH = "spec_hash_123"
SPEC_CONTENT = "Spec content"
DEFAULT_DOMAIN = "training"
DEFAULT_SCOPE_THEMES = ["API"]
INVARIANT_FIELD_NAME = "user_id"
INVARIANT_ID = "INV-0000000000000000"


# =============================================================================
# DATA CLASSES FOR TEST FIXTURES
# =============================================================================

@dataclass
class ProductHierarchy:
    """Holds a complete product hierarchy for tests."""

    product: Product
    theme: Theme
    epic: Epic

    @property
    def product_id(self) -> int:
        assert self.product.product_id is not None
        return self.product.product_id

    @property
    def theme_id(self) -> int:
        assert self.theme.theme_id is not None
        return self.theme.theme_id

    @property
    def epic_id(self) -> int:
        assert self.epic.epic_id is not None
        return self.epic.epic_id


@dataclass
class SpecAuthorityFixture:
    """Holds spec authority related records for tests."""

    spec_registry: SpecRegistry
    compiled_authority: CompiledSpecAuthority
    acceptance: SpecAuthorityAcceptance

    @property
    def spec_version_id(self) -> int:
        assert self.spec_registry.spec_version_id is not None
        return self.spec_registry.spec_version_id


# =============================================================================
# FACTORY FUNCTIONS
# =============================================================================

def create_compiled_artifact_json(
    domain: str = DEFAULT_DOMAIN,
    scope_themes: list[str] | None = None,
    invariant_field: str = INVARIANT_FIELD_NAME,
) -> str:
    """Create a valid compiled artifact JSON string.

    Args:
        domain: Domain name for the authority.
        scope_themes: List of scope themes (defaults to DEFAULT_SCOPE_THEMES).
        invariant_field: Field name for the required field invariant.

    Returns:
        JSON string representation of SpecAuthorityCompilerOutput.
    """
    invariant = Invariant(
        id=INVARIANT_ID,
        type=InvariantType.REQUIRED_FIELD,
        parameters=RequiredFieldParams(field_name=invariant_field),
    )
    success = SpecAuthorityCompilationSuccess(
        scope_themes=scope_themes or DEFAULT_SCOPE_THEMES,
        domain=domain,
        invariants=[invariant],
        eligible_feature_rules=[],
        gaps=[],
        assumptions=[],
        source_map=[],
        compiler_version=COMPILER_VERSION,
        prompt_hash=PROMPT_HASH,
    )
    return SpecAuthorityCompilerOutput(root=success).model_dump_json()


def create_compiled_authority_model(
    spec_version_id: int = 1,
    compiled_artifact_json: str | None = None,
) -> CompiledSpecAuthority:
    """Create a CompiledSpecAuthority model (not persisted).

    Args:
        spec_version_id: Associated spec version ID.
        compiled_artifact_json: JSON artifact (creates default if None).

    Returns:
        CompiledSpecAuthority instance (not saved to DB).
    """
    return CompiledSpecAuthority(
        spec_version_id=spec_version_id,
        compiler_version=COMPILER_VERSION,
        prompt_hash=PROMPT_HASH,
        compiled_at=datetime.now(timezone.utc),
        compiled_artifact_json=compiled_artifact_json or create_compiled_artifact_json(),
        scope_themes=json.dumps(DEFAULT_SCOPE_THEMES),
        invariants=json.dumps([]),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )


# =============================================================================
# PYTEST FIXTURES
# =============================================================================

@pytest.fixture
def product_hierarchy(session: Session) -> ProductHierarchy:
    """Create a complete product hierarchy (Product -> Theme -> Epic)."""
    product = Product(name="Test Product", vision="Vision")
    session.add(product)
    session.commit()
    session.refresh(product)

    theme = Theme(title="Theme", product_id=product.product_id)
    session.add(theme)
    session.commit()
    session.refresh(theme)

    epic = Epic(title="Epic", theme_id=theme.theme_id)
    session.add(epic)
    session.commit()
    session.refresh(epic)

    return ProductHierarchy(product=product, theme=theme, epic=epic)


@pytest.fixture
def spec_authority_fixture(
    session: Session, product_hierarchy: ProductHierarchy
) -> SpecAuthorityFixture:
    """Create a complete spec authority chain (Registry -> Compiled -> Acceptance)."""
    spec_registry = SpecRegistry(
        product_id=product_hierarchy.product_id,
        spec_hash=SPEC_HASH,
        content=SPEC_CONTENT,
        status="approved",
        approved_at=datetime.now(timezone.utc),
        approved_by="tester",
    )
    session.add(spec_registry)
    session.commit()
    session.refresh(spec_registry)

    compiled_authority = CompiledSpecAuthority(
        spec_version_id=spec_registry.spec_version_id,
        compiler_version=COMPILER_VERSION,
        prompt_hash=PROMPT_HASH,
        compiled_at=datetime.now(timezone.utc),
        compiled_artifact_json=create_compiled_artifact_json(),
        scope_themes=json.dumps(DEFAULT_SCOPE_THEMES),
        invariants=json.dumps([]),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )
    session.add(compiled_authority)
    session.commit()

    acceptance = SpecAuthorityAcceptance(
        product_id=product_hierarchy.product_id,
        spec_version_id=spec_registry.spec_version_id,
        status="accepted",
        policy="human",
        decided_by="tester",
        compiler_version=COMPILER_VERSION,
        prompt_hash=PROMPT_HASH,
        spec_hash=SPEC_HASH,
    )
    session.add(acceptance)
    session.commit()

    return SpecAuthorityFixture(
        spec_registry=spec_registry,
        compiled_authority=compiled_authority,
        acceptance=acceptance,
    )


# =============================================================================
# FAKE TEST DOUBLES (for async integration test)
# =============================================================================

class FakeSession:
    """Minimal session double for pipeline testing."""

    def __init__(self, state: Dict[str, Any]) -> None:
        self.state = state
        self.id = "session-1"


class FakeSessionService:
    """In-memory session service double that captures state for assertions."""

    def __init__(self) -> None:
        self.session: FakeSession | None = None
        self.captured_state: Dict[str, Any] = {}

    async def create_session(
        self, app_name: str, user_id: str, state: Dict[str, Any]
    ) -> FakeSession:
        self.captured_state = state
        self.session = FakeSession(state)
        return self.session

    async def get_session(
        self, app_name: str, user_id: str, session_id: str
    ) -> FakeSession | None:
        return self.session


class FakeRunner:
    """Pipeline runner double that sets a mock story draft."""

    def __init__(
        self,
        agent: Any,
        app_name: str,
        session_service: FakeSessionService,
        spec_version_id: int,
    ) -> None:
        self.session_service = session_service
        self.spec_version_id = spec_version_id

    async def run_async(
        self, user_id: str, session_id: str, new_message: Any
    ) -> AsyncGenerator[Dict[str, Any], None]:
        assert self.session_service.session is not None
        self.session_service.session.state["story_draft"] = {
            "title": "Title",
            "description": "As a user, I want X so that Y.",
            "acceptance_criteria": "- A\n- B\n- C",
            "story_points": 3,
            "metadata": {"spec_version_id": self.spec_version_id},
        }
        yield type("Event", (), {"content": None, "author": None})()


# =============================================================================
# UNIT TESTS
# =============================================================================


class TestBuildGenerationContext:
    """Tests for build_generation_context helper function."""

    def test_renders_invariants_from_compiled_artifact(self) -> None:
        """Generation context should include canonical invariant strings."""
        compiled_authority = create_compiled_authority_model(spec_version_id=1)

        context = build_generation_context(
            compiled_authority=compiled_authority,
            spec_version_id=1,
            spec_hash=SPEC_HASH,
        )

        assert context["spec_version_id"] == 1
        assert f"REQUIRED_FIELD:{INVARIANT_FIELD_NAME}" in context["invariants"]
        assert context["scope_themes"] == DEFAULT_SCOPE_THEMES
        assert context["domain"] == DEFAULT_DOMAIN
        assert context["spec_hash"] == SPEC_HASH

    def test_uses_custom_domain_and_scope(self) -> None:
        """Generation context should reflect custom domain and scope themes."""
        custom_domain = "billing"
        custom_themes = ["Payments", "Subscriptions"]

        compiled_authority = create_compiled_authority_model(
            spec_version_id=42,
            compiled_artifact_json=create_compiled_artifact_json(
                domain=custom_domain,
                scope_themes=custom_themes,
            ),
        )

        context = build_generation_context(
            compiled_authority=compiled_authority,
            spec_version_id=42,
            spec_hash="custom_hash",
        )

        assert context["domain"] == custom_domain
        assert context["scope_themes"] == custom_themes
        assert context["spec_version_id"] == 42

    def test_handles_missing_spec_hash(self) -> None:
        """Generation context should omit spec_hash when None is provided."""
        compiled_authority = create_compiled_authority_model(spec_version_id=1)

        context = build_generation_context(
            compiled_authority=compiled_authority,
            spec_version_id=1,
            spec_hash=None,
        )

        assert "spec_hash" not in context
        assert context["spec_version_id"] == 1


# =============================================================================
# INTEGRATION TESTS
# =============================================================================


class TestProcessSingleStoryAuthorityContext:
    """Integration tests for authority context propagation in story pipeline."""

    @pytest.fixture
    def fake_session_service(self) -> FakeSessionService:
        """Create a fresh FakeSessionService for each test."""
        return FakeSessionService()

    @pytest.fixture
    def patch_pipeline_dependencies(
        self,
        engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        fake_session_service: FakeSessionService,
        spec_authority_fixture: SpecAuthorityFixture,
    ) -> FakeSessionService:
        """Patch all pipeline dependencies for integration testing.

        Returns the FakeSessionService so tests can inspect captured state.
        """
        import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod
        import orchestrator_agent.agent_tools.story_pipeline.steps.setup as setup_mod
        import orchestrator_agent.agent_tools.story_pipeline.steps.execution as exec_mod

        # Patch engine references
        single_story_mod.engine = engine
        monkeypatch.setattr(setup_mod, "get_engine", lambda: engine)

        # Patch session service
        monkeypatch.setattr(
            single_story_mod, "InMemorySessionService", lambda: fake_session_service
        )

        # Create a factory that captures spec_version_id for FakeRunner
        spec_version_id = spec_authority_fixture.spec_version_id

        def make_fake_runner(agent: Any, app_name: str, session_service: Any) -> FakeRunner:
            return FakeRunner(agent, app_name, session_service, spec_version_id)

        monkeypatch.setattr(exec_mod, "Runner", make_fake_runner)

        return fake_session_service

    @pytest.mark.asyncio
    async def test_draft_payload_includes_authority_context(
        self,
        product_hierarchy: ProductHierarchy,
        spec_authority_fixture: SpecAuthorityFixture,
        patch_pipeline_dependencies: FakeSessionService,
    ) -> None:
        """Draft agent input state should include authority_context and spec_version_id."""
        from orchestrator_agent.agent_tools.story_pipeline.tools import (
            ProcessStoryInput,
            process_single_story,
        )

        story_input = ProcessStoryInput(
            product_id=product_hierarchy.product_id,
            product_name=product_hierarchy.product.name,
            product_vision=product_hierarchy.product.vision,
            feature_id=101,
            feature_title="Feature",
            theme_id=product_hierarchy.theme_id,
            epic_id=product_hierarchy.epic_id,
            theme="Theme",
            epic="Epic",
            time_frame=None,
            theme_justification=None,
            sibling_features=None,
            user_persona="user",
            include_story_points=True,
            spec_version_id=spec_authority_fixture.spec_version_id,
            enable_story_refiner=False,
        )

        result = await process_single_story(story_input)

        assert result["success"] is True
        self._assert_authority_context_in_state(
            captured_state=patch_pipeline_dependencies.captured_state,
            expected_spec_version_id=spec_authority_fixture.spec_version_id,
        )

    def _assert_authority_context_in_state(
        self,
        captured_state: Dict[str, Any],
        expected_spec_version_id: int,
    ) -> None:
        """Assert that authority context is properly set in captured state."""
        assert "authority_context" in captured_state, "State missing authority_context"
        assert "spec_version_id" in captured_state, "State missing spec_version_id"

        authority_context = captured_state["authority_context"]
        if isinstance(authority_context, str):
            authority_context = json.loads(authority_context)
        assert authority_context["spec_version_id"] == expected_spec_version_id
        assert authority_context["domain"] == DEFAULT_DOMAIN
