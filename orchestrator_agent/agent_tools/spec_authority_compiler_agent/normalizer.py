"""Host-side normalizer/validator for spec_authority_compiler_agent output.

This enforces compiler semantics on the host side:
- prompt_hash is anchored to SPEC_AUTHORITY_COMPILER_INSTRUCTIONS
- invariant IDs are deterministically computed from source_map excerpt + invariant.type

The caller MUST use the normalized output downstream.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from utils.schemes import (
    SpecAuthorityCompilerOutput,
    SpecAuthorityCompilerEnvelope,
    SpecAuthorityCompilationFailure,
    SpecAuthorityCompilationSuccess,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.compiler_contract import (
    compute_invariant_id,
    compute_prompt_hash,
)
from orchestrator_agent.agent_tools.spec_authority_compiler_agent.instructions_source import (
    SPEC_AUTHORITY_COMPILER_INSTRUCTIONS,
    SPEC_AUTHORITY_COMPILER_VERSION,
)


def _failure(reason: str, blocking_gaps: List[str]) -> SpecAuthorityCompilerOutput:
    return SpecAuthorityCompilerOutput(
        root=SpecAuthorityCompilationFailure(
            error="SPEC_COMPILATION_FAILED",
            reason=reason,
            blocking_gaps=blocking_gaps,
        )
    )


def normalize_compiler_output(raw_json: str) -> SpecAuthorityCompilerOutput:
    """Normalize a raw agent JSON string into a deterministic compiler artifact.

    Args:
        raw_json: Raw JSON string emitted by the agent.

    Returns:
        SpecAuthorityCompilerOutput (success or failure). On success, prompt_hash and
        invariant/source_map IDs are rewritten deterministically.
    """
    print("[spec_authority_compiler] normalize_compiler_output: parsing raw JSON")
    try:
        parsed = SpecAuthorityCompilerOutput.model_validate_json(raw_json)
        print("[spec_authority_compiler] Parsed as SpecAuthorityCompilerOutput")
    except (ValidationError, ValueError):
        try:
            envelope = SpecAuthorityCompilerEnvelope.model_validate_json(raw_json)
            parsed = SpecAuthorityCompilerOutput(root=envelope.result)
            print("[spec_authority_compiler] Parsed as SpecAuthorityCompilerEnvelope")
        except ValidationError as exc:
            print("[spec_authority_compiler] Envelope validation failed")
            print(str(exc))
            return _failure(
                reason="JSON_VALIDATION_FAILED",
                blocking_gaps=[str(exc)],
            )
        except ValueError as exc:
            print("[spec_authority_compiler] Invalid JSON")
            print(str(exc))
            return _failure(
                reason="INVALID_JSON",
                blocking_gaps=[str(exc)],
            )

    if isinstance(parsed.root, SpecAuthorityCompilationFailure):
        print("[spec_authority_compiler] Compiler returned failure")
        print(parsed.root.model_dump())
        return parsed

    success: SpecAuthorityCompilationSuccess = parsed.root

    expected_prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
    if not success.prompt_hash or not re.match(r"^[0-9a-f]{64}$", success.prompt_hash):
        success.prompt_hash = expected_prompt_hash
    else:
        success.prompt_hash = expected_prompt_hash
    success.compiler_version = SPEC_AUTHORITY_COMPILER_VERSION

    if not success.invariants:
        print("[spec_authority_compiler] Missing invariants")
        return _failure(
            reason="MISSING_INVARIANTS",
            blocking_gaps=["No invariants present in success output"],
        )

    if not success.source_map:
        print("[spec_authority_compiler] Missing source_map")
        return _failure(
            reason="MISSING_SOURCE_MAP",
            blocking_gaps=["Missing source_map required for deterministic IDs"],
        )

    # Snapshot original invariant IDs/types before rewriting
    original_invariants = list(success.invariants)
    original_id_to_type: Dict[str, Any] = {inv.id: inv.type for inv in original_invariants}

    id_to_excerpt: Dict[str, str] = {}
    for entry in success.source_map:
        if entry.invariant_id and entry.excerpt and entry.excerpt.strip():
            id_to_excerpt[entry.invariant_id] = entry.excerpt

    def choose_excerpt(invariant_index: int, invariant_id: str) -> Optional[str]:
        if invariant_id and invariant_id in id_to_excerpt:
            return id_to_excerpt[invariant_id]
        if len(success.source_map) == len(success.invariants):
            return success.source_map[invariant_index].excerpt
        if len(success.invariants) == 1 and len(success.source_map) >= 1:
            return success.source_map[0].excerpt
        return None

    # Rewrite invariant IDs deterministically
    for idx, inv in enumerate(success.invariants):
        excerpt = choose_excerpt(idx, inv.id)
        if not excerpt or not excerpt.strip():
            print("[spec_authority_compiler] Invariant/source_map mismatch")
            return _failure(
                reason="SOURCE_MAP_INVARIANT_MISMATCH",
                blocking_gaps=[
                    "Cannot choose deterministic excerpt for invariant",
                    f"invariant_index={idx}",
                ],
            )
        inv.id = compute_invariant_id(excerpt, inv.type)

    # Rewrite source_map invariant_id deterministically
    for entry_index, entry in enumerate(success.source_map):
        excerpt = (entry.excerpt or "").strip()
        if not excerpt:
            print("[spec_authority_compiler] Empty source_map excerpt")
            return _failure(
                reason="SOURCE_MAP_INVARIANT_MISMATCH",
                blocking_gaps=["source_map entry has empty excerpt"],
            )

        inv_type = original_id_to_type.get(entry.invariant_id)
        if inv_type is None:
            if len(success.invariants) == 1:
                inv_type = success.invariants[0].type
            elif len(success.source_map) == len(original_invariants):
                inv_type = original_invariants[entry_index].type
            else:
                print("[spec_authority_compiler] Cannot match source_map entry to invariant type")
                return _failure(
                    reason="SOURCE_MAP_INVARIANT_MISMATCH",
                    blocking_gaps=[
                        "Cannot match source_map entry to an invariant type",
                        f"source_map_index={entry_index}",
                    ],
                )

        entry.invariant_id = compute_invariant_id(excerpt, inv_type)

    # Verify auditability: every invariant has at least one source_map entry
    normalized_ids = {inv.id for inv in success.invariants}
    source_map_ids = {entry.invariant_id for entry in success.source_map}
    missing = sorted(normalized_ids - source_map_ids)
    if missing:
        print("[spec_authority_compiler] Missing source_map entries for invariants")
        return _failure(
            reason="SOURCE_MAP_INVARIANT_MISMATCH",
            blocking_gaps=[f"No source_map entries for invariants: {missing}"],
        )

    return SpecAuthorityCompilerOutput(root=success)
