"""Unit tests for host-side normalization of spec authority compiler outputs."""

import json
import re
from typing import Any, Dict

import pytest

from utils.schemes import (
    SpecAuthorityCompilationFailure,
    SpecAuthorityCompilationSuccess,
    SpecAuthorityCompilerOutput,
    InvariantType,
    RequiredFieldParams,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_invariant_id,
    compute_prompt_hash,
)


def test_normalizer_rewrites_bad_ids_from_llm() -> None:
    """Normalizer must rewrite bad prompt_hash and invariant IDs deterministically."""
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
        SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
        SPEC_AUTHORITY_COMPILER_VERSION,
    )
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
        normalize_compiler_output,
    )

    excerpt = "The payload must include user_id."

    raw: Dict[str, Any] = {
        "scope_themes": [],
        "invariants": [
            {
                "id": "INV-0000000000000000",
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "user_id"},
            }
        ],
        "eligible_feature_rules": [],
        "gaps": [],
        "assumptions": [],
        "source_map": [
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt,
                "location": "spec:line:1",
            }
        ],
        "compiler_version": "0.0.0",
        "prompt_hash": "b" * 64,
    }

    normalized = normalize_compiler_output(json.dumps(raw))
    assert isinstance(normalized.root, SpecAuthorityCompilationSuccess)

    expected_prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
    assert normalized.root.prompt_hash == expected_prompt_hash
    assert normalized.root.compiler_version == SPEC_AUTHORITY_COMPILER_VERSION

    assert len(normalized.root.invariants) == 1
    inv = normalized.root.invariants[0]
    assert inv.type == InvariantType.REQUIRED_FIELD
    assert isinstance(inv.parameters, RequiredFieldParams)
    assert inv.parameters.field_name == "user_id"

    # ID must be derived from the source_map excerpt
    assert len(normalized.root.source_map) == 1
    sm = normalized.root.source_map[0]
    expected_id = compute_invariant_id(sm.excerpt, inv.type)
    assert inv.id == expected_id
    assert sm.invariant_id == expected_id
    assert re.match(r"^INV-[0-9a-f]{16}$", inv.id)


def test_normalizer_fails_when_source_map_missing_or_unmatchable() -> None:
    """Normalizer must fail deterministically if source_map cannot support ID mapping."""
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
        normalize_compiler_output,
    )

    raw: Dict[str, Any] = {
        "scope_themes": [],
        "invariants": [
            {
                "id": "INV-0000000000000000",
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "user_id"},
            }
        ],
        "eligible_feature_rules": [],
        "gaps": [],
        "assumptions": [],
        "source_map": [],
        "compiler_version": "1.0.0",
        "prompt_hash": "a" * 64,
    }

    normalized = normalize_compiler_output(json.dumps(raw))
    assert isinstance(normalized.root, SpecAuthorityCompilationFailure)
    assert normalized.root.error == "SPEC_COMPILATION_FAILED"
    assert "source_map" in normalized.root.reason.lower() or any(
        "source_map" in gap.lower() for gap in normalized.root.blocking_gaps
    )


def test_normalizer_returns_failure_for_invalid_json() -> None:
    """Normalizer must return structured failure if raw output is not valid JSON."""
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
        normalize_compiler_output,
    )

    normalized = normalize_compiler_output("{not-json")
    assert isinstance(normalized.root, SpecAuthorityCompilationFailure)
    assert normalized.root.error == "SPEC_COMPILATION_FAILED"
    assert "json" in normalized.root.reason.lower()
