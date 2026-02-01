"""
TDD tests for Authority Gate wiring fixes.

These tests verify:
1. P0: tool_context is passed through from story entrypoints to ensure_accepted_spec_authority
2. P0: load_specification_from_file sets pending_spec_path/pending_spec_content
3. P0: ensure_accepted_spec_authority logs structured events with correct fields
4. P1: Proposal mode returns proposal dict instead of raising when source exists
5. P1: Dev escape hatch auto-accepts with logged decision_source
"""

import os
import hashlib
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock
from typing import Optional, Dict, Any

import pytest
from sqlmodel import Session

from agile_sqlmodel import (
    Product,
    SpecRegistry,
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
)


# =============================================================================
# Fixtures
# =============================================================================


class MockToolContext:
    """Mock ToolContext for testing state storage."""
    def __init__(self, state: Optional[Dict[str, Any]] = None):
        self.state = state if state is not None else {}


@pytest.fixture
def sample_product(engine, session: Session) -> Product:
    """Create a sample product for testing."""
    import tools.spec_tools as spec_tools
    import tools.orchestrator_tools as orch_tools
    spec_tools.engine = engine
    orch_tools.engine = engine
    
    product = Product(
        name="Authority Gate Test Product",
        description="Product for authority gate wiring tests",
        vision="Test vision",
    )
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


@pytest.fixture
def spec_file(tmp_path):
    """Create a temporary spec file for testing."""
    spec_content = "# Test Spec\n\n## Scope\n- Feature A\n\n## Invariants\n- Must have user_id"
    spec_path = tmp_path / "test_spec.md"
    spec_path.write_text(spec_content, encoding="utf-8")
    return spec_path, spec_content


# =============================================================================
# P0 Test: tool_context wiring in process_story_batch
# =============================================================================


class TestToolContextWiring:
    """Tests that tool_context is passed through to ensure_accepted_spec_authority."""

    def test_process_story_batch_passes_tool_context_to_authority_gate(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: process_story_batch must pass tool_context (not None) to
        ensure_accepted_spec_authority so that session state can be used for
        fallback/proposals and logging correlation.
        
        This test verifies the wiring bug is fixed.
        """
        from orchestrator_agent.agent_tools.story_pipeline.tools import (
            process_story_batch,
            ProcessBatchInput,
        )
        import orchestrator_agent.agent_tools.story_pipeline.batch as batch_mod
        batch_mod.engine = engine
        
        # Create a mock tool_context with pending spec in state
        mock_context = MockToolContext(state={
            "pending_spec_path": "test_specs/genai_spec.md",
            "pending_spec_content": "# Test Spec Content",
        })
        
        # Patch ensure_accepted_spec_authority to capture what it receives
        captured_calls = []
        
        def capture_ensure_call(
            product_id,
            *,
            spec_content=None,
            content_ref=None,
            recompile=False,
            tool_context=None,
        ):
            captured_calls.append({
                "product_id": product_id,
                "spec_content": spec_content,
                "content_ref": content_ref,
                "tool_context": tool_context,
            })
            # Return a fake spec_version_id to let the function proceed
            raise RuntimeError("Captured - stopping here")
        
        batch_input = ProcessBatchInput(
            product_id=sample_product.product_id,
            product_name=sample_product.name,
            product_vision=sample_product.vision or "",
            user_persona="Test Engineer",
            include_story_points=False,
            features=[],  # Empty to trigger early exit
        )
        
        with patch(
            "orchestrator_agent.agent_tools.story_pipeline.batch.ensure_accepted_spec_authority",
            side_effect=capture_ensure_call,
        ):
            import asyncio
            try:
                asyncio.run(process_story_batch(batch_input, tool_context=mock_context))
            except RuntimeError as e:
                if "Captured" not in str(e):
                    raise
        
        # ASSERTION: tool_context must NOT be None
        assert len(captured_calls) == 1, "ensure_accepted_spec_authority should be called once"
        call = captured_calls[0]
        
        # THIS IS THE KEY ASSERTION - currently fails because of tool_context=None bug
        assert call["tool_context"] is not None, (
            "tool_context must be passed through, not None. "
            "The wiring bug causes tool_context=None which prevents session state access."
        )
        assert call["tool_context"] is mock_context, (
            "tool_context should be the same instance passed to process_story_batch"
        )

    def test_process_single_story_passes_tool_context_to_authority_gate(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: process_single_story must also pass tool_context through.
        """
        from orchestrator_agent.agent_tools.story_pipeline.tools import (
            process_single_story,
            ProcessStoryInput,
        )
        import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod
        single_story_mod.engine = engine
        
        mock_context = MockToolContext(state={
            "pending_spec_path": "test_specs/genai_spec.md",
        })
        
        captured_calls = []
        
        def capture_ensure_call(
            product_id,
            *,
            spec_content=None,
            content_ref=None,
            recompile=False,
            tool_context=None,
        ):
            captured_calls.append({"tool_context": tool_context})
            raise RuntimeError("Captured - stopping here")
        
        story_input = ProcessStoryInput(
            product_id=sample_product.product_id,
            product_name=sample_product.name,
            product_vision=sample_product.vision or "",
            user_persona="Test Engineer",
            theme="Test Theme",
            epic="Test Epic",
            feature_id=1,
            feature_title="Test Feature",
        )
        
        with patch(
            "orchestrator_agent.agent_tools.story_pipeline.single_story.ensure_accepted_spec_authority",
            side_effect=capture_ensure_call,
        ):
            import asyncio
            try:
                asyncio.run(process_single_story(story_input, tool_context=mock_context))
            except RuntimeError as e:
                if "Captured" not in str(e):
                    raise
        
        assert len(captured_calls) == 1
        assert captured_calls[0]["tool_context"] is not None, (
            "process_single_story must also pass tool_context through"
        )


# =============================================================================
# P0 Test: State key alignment in load_specification_from_file
# =============================================================================


class TestStateKeyAlignment:
    """Tests that load_specification_from_file sets the correct state keys."""

    def test_load_specification_sets_pending_spec_path(self, spec_file):
        """
        REQUIREMENT: load_specification_from_file must set pending_spec_path
        (not just last_loaded_spec_path) so ensure_accepted_spec_authority
        can find it for proposal fallback.
        """
        from tools.orchestrator_tools import load_specification_from_file
        
        spec_path, expected_content = spec_file
        # Note: use non-empty dict because empty dict is falsy in Python
        mock_context = MockToolContext(state={"_init": True})
        
        content = load_specification_from_file(str(spec_path), tool_context=mock_context)
        
        assert content == expected_content
        
        # KEY ASSERTION: pending_spec_path must be set
        assert "pending_spec_path" in mock_context.state, (
            "load_specification_from_file must set pending_spec_path for authority gate fallback"
        )
        assert mock_context.state["pending_spec_path"] == str(spec_path.absolute())

    def test_load_specification_sets_pending_spec_content(self, spec_file):
        """
        REQUIREMENT: load_specification_from_file must also set pending_spec_content.
        """
        from tools.orchestrator_tools import load_specification_from_file
        
        spec_path, expected_content = spec_file
        mock_context = MockToolContext(state={"_init": True})
        
        content = load_specification_from_file(str(spec_path), tool_context=mock_context)
        
        # KEY ASSERTION: pending_spec_content must be set
        assert "pending_spec_content" in mock_context.state, (
            "load_specification_from_file must set pending_spec_content for authority gate fallback"
        )
        assert mock_context.state["pending_spec_content"] == expected_content

    def test_load_specification_preserves_backward_compat_keys(self, spec_file):
        """
        Backward compatibility: last_loaded_spec_path should still be set.
        """
        from tools.orchestrator_tools import load_specification_from_file
        
        spec_path, _ = spec_file
        mock_context = MockToolContext(state={"_init": True})
        
        load_specification_from_file(str(spec_path), tool_context=mock_context)
        
        # Backward compat - old key should still exist
        assert "last_loaded_spec_path" in mock_context.state
        assert "last_loaded_spec_size_kb" in mock_context.state


# =============================================================================
# P0 Test: Observability logging in ensure_accepted_spec_authority
# =============================================================================


class TestObservabilityLogging:
    """Tests that ensure_accepted_spec_authority logs structured events."""

    def test_authority_gate_logs_check_event_with_required_fields(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: ensure_accepted_spec_authority must log authority_gate.check
        with boolean fields for debugging.
        """
        import tools.spec_tools as spec_tools
        spec_tools.engine = engine
        
        from tools.spec_tools import ensure_accepted_spec_authority
        
        log_records = []
        
        def capture_log(msg, *args, **kwargs):
            extra = kwargs.get("extra", {})
            log_records.append({"msg": msg, "extra": extra})
        
        with patch.object(spec_tools.logger, "info", side_effect=capture_log):
            with patch.object(spec_tools.logger, "error", side_effect=capture_log):
                with pytest.raises(RuntimeError):
                    ensure_accepted_spec_authority(
                        sample_product.product_id,
                        spec_content=None,
                        content_ref=None,
                    )
        
        # Find the check event
        check_events = [r for r in log_records if "authority_gate" in r["msg"]]
        assert len(check_events) > 0, "Should log authority_gate events"
        
        # Verify check event has required fields (renamed from start to check)
        check_event = next((r for r in check_events if r["msg"] == "authority_gate.check"), None)
        assert check_event is not None, "Must log authority_gate.check"
        
        extra = check_event["extra"]
        assert "product_id" in extra
        assert extra["product_id"] == sample_product.product_id

    def test_authority_gate_logs_path_used_enum(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: Logs must include path_used with one of:
        existing_authority | proposal_from_state | explicit_args | fail_no_source
        """
        import tools.spec_tools as spec_tools
        spec_tools.engine = engine
        
        from tools.spec_tools import ensure_accepted_spec_authority
        
        log_records = []
        
        def capture_log(msg, *args, **kwargs):
            extra = kwargs.get("extra", {})
            log_records.append({"msg": msg, "extra": extra})
        
        with patch.object(spec_tools.logger, "info", side_effect=capture_log):
            with patch.object(spec_tools.logger, "error", side_effect=capture_log):
                with pytest.raises(RuntimeError):
                    ensure_accepted_spec_authority(
                        sample_product.product_id,
                        spec_content=None,
                        content_ref=None,
                    )
        
        # Find fail event - should have path_used
        fail_events = [r for r in log_records if "fail" in r["msg"]]
        assert len(fail_events) > 0, "Should log failure"
        
        # Check for path_used or reason field
        fail_extra = fail_events[0]["extra"]
        assert "reason" in fail_extra or "path_used" in fail_extra, (
            "Failure log must indicate the path/reason for debugging"
        )


# =============================================================================
# P1 Test: Proposal mode behavior
# =============================================================================


class TestProposalMode:
    """Tests for lazy propose-and-confirm behavior."""

    def test_authority_gate_returns_proposal_when_source_exists_but_no_authority(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: When no accepted authority exists but a spec source is available
        (from state or args), return a proposal dict instead of immediately compiling.
        
        This enables the orchestrator to ask for user confirmation.
        """
        import tools.spec_tools as spec_tools
        spec_tools.engine = engine
        
        from tools.spec_tools import ensure_accepted_spec_authority
        
        mock_context = MockToolContext(state={
            "pending_spec_path": "test_specs/genai_spec.md",
            "pending_spec_content": "# Test Spec",
        })
        
        # NOTE: This test documents the DESIRED behavior.
        # Current behavior raises RuntimeError or compiles immediately.
        # The fix should make this return a proposal dict when
        # proposal_mode=True or similar flag is set.
        
        # For now, we test that when spec source is provided via args,
        # the gate doesn't fail with "no source" error
        # (it may still fail for other reasons like missing product, etc.)
        
        # This test will be updated when proposal mode is implemented
        pytest.skip("Proposal mode not yet implemented - test documents desired behavior")

    def test_authority_gate_raises_when_no_source_at_all(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: When no accepted authority and NO spec source exists,
        fail-fast with actionable error.
        """
        import tools.spec_tools as spec_tools
        spec_tools.engine = engine
        
        from tools.spec_tools import ensure_accepted_spec_authority
        
        with pytest.raises(RuntimeError) as exc_info:
            ensure_accepted_spec_authority(
                sample_product.product_id,
                spec_content=None,
                content_ref=None,
                tool_context=None,
            )
        
        error_msg = str(exc_info.value).lower()
        assert "no accepted spec authority" in error_msg
        assert "provide" in error_msg  # Actionable guidance


# =============================================================================
# P1 Test: Dev escape hatch
# =============================================================================


class TestDevEscapeHatch:
    """Tests for SPEC_AUTHORITY_AUTO_ACCEPT environment variable."""

    def test_auto_accept_env_var_proceeds_without_confirmation(
        self, engine, sample_product: Product, session: Session, spec_file
    ):
        """
        REQUIREMENT: When SPEC_AUTHORITY_AUTO_ACCEPT=true, auto-accept
        proposals without confirmation, but log decision_source="auto_dev".
        """
        import tools.spec_tools as spec_tools
        spec_tools.engine = engine
        
        spec_path, spec_content = spec_file
        
        # This test documents desired behavior - skip until implemented
        pytest.skip("Dev escape hatch not yet implemented")

    def test_auto_accept_still_logs_what_was_accepted(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REQUIREMENT: Even with auto-accept, the response must show what was accepted.
        """
        pytest.skip("Dev escape hatch not yet implemented")


class TestDualSpecSourceHandling:
    """Tests for handling when both spec_content and content_ref are available."""

    def test_process_story_batch_prefers_content_ref_over_spec_content(
        self, engine, sample_product: Product, session: Session
    ):
        """
        REGRESSION TEST: When tool_context has pending_spec_content AND batch_input
        has content_ref, process_story_batch should prefer content_ref to avoid
        ValueError("Provide exactly one of spec_content or content_ref").
        
        This was the root cause of the authority_gate.compile_result error.
        """
        from orchestrator_agent.agent_tools.story_pipeline.tools import (
            process_story_batch,
            ProcessBatchInput,
        )
        from tools.story_query_tools import FeatureForStory
        import orchestrator_agent.agent_tools.story_pipeline.batch as batch_mod
        batch_mod.engine = engine

        # Simulate the scenario: tool_context has pending_spec_content from load_specification_from_file
        mock_context = MockToolContext(state={
            "pending_spec_path": "/some/path/spec.md",
            "pending_spec_content": "# Spec content from state",
        })

        # Batch input has content_ref (from agent's tool call)
        batch_input = ProcessBatchInput(
            product_id=sample_product.product_id,
            product_name=sample_product.name,
            product_vision=sample_product.vision or "",
            user_persona="Test Engineer",
            include_story_points=False,
            content_ref="specs/hashbrown.md",  # Explicit content_ref
            features=[
                FeatureForStory(
                    feature_id=1,
                    feature_title="Test Feature",
                    theme="Test Theme",
                    epic="Test Epic",
                )
            ],
        )

        captured_calls = []

        def capture_ensure_call(
            product_id,
            *,
            spec_content=None,
            content_ref=None,
            recompile=False,
            tool_context=None,
        ):
            captured_calls.append({
                "product_id": product_id,
                "spec_content": spec_content,
                "content_ref": content_ref,
            })
            raise RuntimeError("Captured - stopping here")

        with patch(
            "orchestrator_agent.agent_tools.story_pipeline.batch.ensure_accepted_spec_authority",
            side_effect=capture_ensure_call,
        ):
            import asyncio
            try:
                asyncio.run(process_story_batch(batch_input, tool_context=mock_context))
            except RuntimeError as e:
                if "Captured" not in str(e):
                    raise

        assert len(captured_calls) == 1
        call = captured_calls[0]

        # KEY ASSERTION: Only one of spec_content or content_ref should be set
        # When both are available, content_ref should be preferred
        assert call["content_ref"] == "specs/hashbrown.md", "content_ref should be preserved"
        assert call["spec_content"] is None, (
            "spec_content should be None when content_ref is set to avoid "
            "ValueError('Provide exactly one of spec_content or content_ref')"
        )

    def test_process_single_story_prefers_content_ref_over_spec_content(
        self, engine, sample_product: Product, session: Session
    ):
        """
        Same regression test for process_single_story.
        """
        from orchestrator_agent.agent_tools.story_pipeline.tools import (
            process_single_story,
            ProcessStoryInput,
        )
        import orchestrator_agent.agent_tools.story_pipeline.single_story as single_story_mod
        single_story_mod.engine = engine

        mock_context = MockToolContext(state={
            "pending_spec_path": "/some/path/spec.md",
            "pending_spec_content": "# Spec content from state",
        })

        story_input = ProcessStoryInput(
            product_id=sample_product.product_id,
            product_name=sample_product.name,
            product_vision=sample_product.vision or "",
            feature_id=1,
            feature_title="Test Feature",
            theme="Test Theme",
            epic="Test Epic",
            user_persona="Test Engineer",
            include_story_points=False,
            content_ref="specs/hashbrown.md",
        )

        captured_calls = []

        def capture_ensure_call(
            product_id,
            *,
            spec_content=None,
            content_ref=None,
            recompile=False,
            tool_context=None,
        ):
            captured_calls.append({
                "product_id": product_id,
                "spec_content": spec_content,
                "content_ref": content_ref,
            })
            raise RuntimeError("Captured - stopping here")

        with patch(
            "orchestrator_agent.agent_tools.story_pipeline.single_story.ensure_accepted_spec_authority",
            side_effect=capture_ensure_call,
        ):
            import asyncio
            try:
                asyncio.run(process_single_story(story_input, tool_context=mock_context))
            except RuntimeError as e:
                if "Captured" not in str(e):
                    raise

        assert len(captured_calls) == 1
        call = captured_calls[0]

        assert call["content_ref"] == "specs/hashbrown.md"
        assert call["spec_content"] is None
