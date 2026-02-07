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


def test_normalizer_handles_duplicate_placeholder_invariant_ids() -> None:
    """Normalizer must correctly handle when LLM returns duplicate placeholder IDs.
    
    This is a common scenario where the LLM returns INV-0000000000000000 for all
    invariants instead of generating unique IDs. The normalizer must use positional
    matching to assign correct types to source_map entries.
    """
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
        normalize_compiler_output,
    )

    excerpt1 = "The payload must include user_id."
    excerpt2 = "The system must not use OAuth1 authentication."

    # LLM returns same placeholder ID for both invariants
    raw: Dict[str, Any] = {
        "scope_themes": ["payload validation", "authentication security"],
        "domain": None,
        "invariants": [
            {
                "id": "INV-0000000000000000",
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "user_id"},
            },
            {
                "id": "INV-0000000000000000",
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "OAuth1"},
            },
        ],
        "eligible_feature_rules": [],
        "gaps": [],
        "assumptions": [],
        "source_map": [
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt1,
                "location": None,
            },
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt2,
                "location": None,
            },
        ],
        "compiler_version": "1.0.0",
        "prompt_hash": "0" * 64,
    }

    normalized = normalize_compiler_output(json.dumps(raw))
    
    # Must succeed, not fail with SOURCE_MAP_INVARIANT_MISMATCH
    assert isinstance(normalized.root, SpecAuthorityCompilationSuccess), (
        f"Expected success but got failure: {normalized.root}"
    )

    # Two distinct invariants with deterministic IDs
    assert len(normalized.root.invariants) == 2
    inv_ids = [inv.id for inv in normalized.root.invariants]
    assert len(set(inv_ids)) == 2, "Invariant IDs must be unique after normalization"

    # Source map entries must match invariant IDs
    source_map_ids = {entry.invariant_id for entry in normalized.root.source_map}
    invariant_ids = {inv.id for inv in normalized.root.invariants}
    assert source_map_ids == invariant_ids, (
        f"Source map IDs {source_map_ids} must match invariant IDs {invariant_ids}"
    )


def test_normalizer_handles_duplicate_ids_different_types_length_mismatch() -> None:
    """Normalizer must succeed when LLM returns duplicate IDs with different types
    AND the number of source_map entries doesn't match the number of invariants.

    Regression: original_id_to_type dict loses type information for duplicate IDs
    because dict construction keeps only the last value per key.  When
    use_positional_matching is False (length mismatch), source_map entries all
    resolve to the last-wins type, producing an ID that covers only one invariant
    while leaving the other as SOURCE_MAP_INVARIANT_MISMATCH.
    """
    from orchestrator_agent.agent_tools.spec_authority_compiler_agent.normalizer import (
        normalize_compiler_output,
    )

    excerpt1 = "The payload must include user_id."
    excerpt2 = "The system must not use OAuth1 authentication."
    # Extra source_map entry for the same invariant (different excerpt location)
    excerpt3 = "user_id is mandatory in all API payloads."

    raw: Dict[str, Any] = {
        "scope_themes": ["payload validation", "authentication security"],
        "domain": None,
        "invariants": [
            {
                "id": "INV-0000000000000000",
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "user_id"},
            },
            {
                "id": "INV-0000000000000000",
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "OAuth1"},
            },
        ],
        "eligible_feature_rules": [],
        "gaps": [],
        "assumptions": [],
        "source_map": [
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt1,
                "location": "spec:section:1",
            },
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt2,
                "location": "spec:section:2",
            },
            {
                "invariant_id": "INV-0000000000000000",
                "excerpt": excerpt3,
                "location": "spec:section:1:para:2",
            },
        ],
        "compiler_version": "1.0.0",
        "prompt_hash": "0" * 64,
    }

    normalized = normalize_compiler_output(json.dumps(raw))

    # Must succeed — not fail with SOURCE_MAP_INVARIANT_MISMATCH
    assert isinstance(normalized.root, SpecAuthorityCompilationSuccess), (
        f"Expected success but got failure: {normalized.root}"
    )

    # Two distinct invariants with deterministic IDs
    assert len(normalized.root.invariants) == 2
    inv_ids = [inv.id for inv in normalized.root.invariants]
    assert len(set(inv_ids)) == 2, "Invariant IDs must be unique after normalization"

    # Every invariant must have at least one source_map entry
    source_map_ids = {entry.invariant_id for entry in normalized.root.source_map}
    invariant_ids = {inv.id for inv in normalized.root.invariants}
    assert invariant_ids.issubset(source_map_ids), (
        f"Every invariant ID must be covered by source_map. "
        f"Missing: {sorted(invariant_ids - source_map_ids)}"
    )
