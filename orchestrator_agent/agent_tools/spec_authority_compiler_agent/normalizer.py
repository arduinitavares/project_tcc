"""Host-side normalizer/validator for spec_authority_compiler_agent output.

This enforces compiler semantics on the host side:
- prompt_hash is anchored to SPEC_AUTHORITY_COMPILER_INSTRUCTIONS
- invariant IDs are deterministically computed from source_map excerpt + invariant.type

The caller MUST use the normalized output downstream.
"""

from __future__ import annotations

import json
import logging
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

logger = logging.getLogger(__name__)


def _failure(reason: str, blocking_gaps: List[str]) -> SpecAuthorityCompilerOutput:
    return SpecAuthorityCompilerOutput(
        root=SpecAuthorityCompilationFailure(
            error="SPEC_COMPILATION_FAILED",
            reason=reason,
            blocking_gaps=blocking_gaps,
        )
    )


def _strip_markdown_fence(raw_text: str) -> str:
    text = raw_text.strip()
    if not text.startswith("```"):
        return text

    lines = text.splitlines()
    if not lines:
        return text

    lines = lines[1:]
    while lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_json_candidate(raw_text: str) -> str:
    text = _strip_markdown_fence(raw_text)
    if not text:
        return text

    try:
        json.loads(text)
        return text
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end < start:
            return text
        return text[start:end + 1].strip()


def _summarize_validation_error(label: str, exc: ValidationError) -> str:
    errors = exc.errors()
    if errors:
        first = errors[0]
        loc = ".".join(str(part) for part in first.get("loc", []))
        msg = first.get("msg", "validation error")
        if loc:
            return f"{label}: {loc}: {msg}"
        return f"{label}: {msg}"
    return f"{label}: {exc}"


def normalize_compiler_output(raw_json: str) -> SpecAuthorityCompilerOutput:
    """Normalize a raw agent JSON string into a deterministic compiler artifact.

    Args:
        raw_json: Raw JSON string emitted by the agent.

    Returns:
        SpecAuthorityCompilerOutput (success or failure). On success, prompt_hash and
        invariant/source_map IDs are rewritten deterministically.
    """
    logger.info("Normalizing spec authority compiler output")

    raw_json = _extract_json_candidate(raw_json)

    try:
        payload = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        logger.error("Spec authority compiler returned invalid JSON: %s", exc)
        return _failure(
            reason="INVALID_JSON",
            blocking_gaps=[str(exc)],
        )

    parsed: Optional[SpecAuthorityCompilerOutput] = None
    validation_gaps: List[str] = []

    try:
        parsed = SpecAuthorityCompilerOutput.model_validate(payload)
        logger.info("Parsed compiler output as SpecAuthorityCompilerOutput")
    except ValidationError as output_exc:
        validation_gaps.append(_summarize_validation_error("output", output_exc))

        if isinstance(payload, dict) and "result" in payload:
            try:
                envelope = SpecAuthorityCompilerEnvelope.model_validate(payload)
                parsed = SpecAuthorityCompilerOutput(root=envelope.result)
                logger.info("Parsed compiler output as SpecAuthorityCompilerEnvelope")
            except ValidationError as envelope_exc:
                validation_gaps.append(_summarize_validation_error("envelope", envelope_exc))
                try:
                    parsed = SpecAuthorityCompilerOutput.model_validate(payload.get("result"))
                    logger.info("Parsed compiler output using envelope.result payload")
                except ValidationError as result_exc:
                    validation_gaps.append(
                        _summarize_validation_error("envelope.result", result_exc)
                    )

    if parsed is None:
        logger.error("Spec authority compiler JSON schema validation failed")
        for gap in validation_gaps:
            logger.error("%s", gap)
        return _failure(
            reason="JSON_VALIDATION_FAILED",
            blocking_gaps=validation_gaps or ["No schema variant matched"],
        )

    if isinstance(parsed.root, SpecAuthorityCompilationFailure):
        logger.error("Spec authority compiler returned failure: %s", parsed.root.model_dump())
        return parsed

    success: SpecAuthorityCompilationSuccess = parsed.root

    expected_prompt_hash = compute_prompt_hash(SPEC_AUTHORITY_COMPILER_INSTRUCTIONS)
    if not success.prompt_hash or not re.match(r"^[0-9a-f]{64}$", success.prompt_hash):
        success.prompt_hash = expected_prompt_hash
    else:
        success.prompt_hash = expected_prompt_hash
    success.compiler_version = SPEC_AUTHORITY_COMPILER_VERSION

    if not success.invariants:
        logger.warning("No invariants extracted from spec authority compiler output")
        if "No invariants extracted from spec" not in success.gaps:
            success.gaps.append("No invariants extracted from spec")
        return SpecAuthorityCompilerOutput(root=success)

    if not success.source_map:
        logger.error("Spec authority compiler output is missing source_map")
        return _failure(
            reason="MISSING_SOURCE_MAP",
            blocking_gaps=["Missing source_map required for deterministic IDs"],
        )

    # Snapshot original invariant IDs/types before rewriting
    original_invariants = list(success.invariants)
    # Multi-map: an original ID may appear on several invariants with
    # different types (common LLM behaviour).  A plain dict loses all
    # but the last type; we keep them all so source_map rewriting can
    # try each candidate.
    original_id_to_types: Dict[str, List[Any]] = {}
    for _inv in original_invariants:
        original_id_to_types.setdefault(_inv.id, []).append(_inv.type)

    # Check if all invariants have duplicate/placeholder IDs (common LLM behavior)
    original_ids = [inv.id for inv in original_invariants]
    has_duplicate_ids = len(set(original_ids)) < len(original_ids)
    
    # When IDs are duplicated, prefer positional matching.
    # This is safe when source_map has at least as many entries as invariants
    # (the first N source_map entries align with the N invariants; extras are
    # additional evidence for the same invariants).
    use_positional_matching = (
        has_duplicate_ids
        and len(success.source_map) >= len(success.invariants)
    )

    id_to_excerpt: Dict[str, str] = {}
    for entry in success.source_map:
        if entry.invariant_id and entry.excerpt and entry.excerpt.strip():
            id_to_excerpt[entry.invariant_id] = entry.excerpt

    def choose_excerpt(invariant_index: int, invariant_id: str) -> Optional[str]:
        # Prefer positional matching when IDs are duplicated
        if use_positional_matching:
            return success.source_map[invariant_index].excerpt
        if invariant_id and invariant_id in id_to_excerpt:
            # Guard against last-wins collision: when multiple invariants
            # share a placeholder ID, id_to_excerpt holds only the last
            # excerpt.  Fall back to positional if the index is in range.
            if has_duplicate_ids and invariant_index < len(success.source_map):
                return success.source_map[invariant_index].excerpt
            return id_to_excerpt[invariant_id]
        if invariant_index < len(success.source_map):
            return success.source_map[invariant_index].excerpt
        if len(success.invariants) == 1 and len(success.source_map) >= 1:
            return success.source_map[0].excerpt
        return None

    # Rewrite invariant IDs deterministically
    for idx, inv in enumerate(success.invariants):
        excerpt = choose_excerpt(idx, inv.id)
        if not excerpt or not excerpt.strip():
            logger.error("Spec authority compiler invariant/source_map mismatch")
            return _failure(
                reason="SOURCE_MAP_INVARIANT_MISMATCH",
                blocking_gaps=[
                    "Cannot choose deterministic excerpt for invariant",
                    f"invariant_index={idx}",
                ],
            )
        inv.id = compute_invariant_id(excerpt, inv.type)

    # Build the set of already-rewritten invariant IDs so that the
    # source_map loop can disambiguate duplicate-ID / different-type cases.
    normalized_inv_ids = {inv.id for inv in success.invariants}

    # Rewrite source_map invariant_id deterministically
    # use_positional_matching is already computed above
    for entry_index, entry in enumerate(success.source_map):
        excerpt = (entry.excerpt or "").strip()
        if not excerpt:
            logger.error("Spec authority compiler source_map entry has empty excerpt")
            return _failure(
                reason="SOURCE_MAP_INVARIANT_MISMATCH",
                blocking_gaps=["source_map entry has empty excerpt"],
            )

        inv_type = None
        
        # Prefer positional matching when IDs are duplicated/placeholder
        if use_positional_matching and entry_index < len(original_invariants):
            inv_type = original_invariants[entry_index].type
        elif use_positional_matching:
            # Extra source_map entry beyond invariant count.
            # Try each candidate type and pick the one whose computed ID
            # matches a known (already-rewritten) invariant.
            candidate_types = original_id_to_types.get(entry.invariant_id, [])
            for ctype in candidate_types:
                if compute_invariant_id(excerpt, ctype) in normalized_inv_ids:
                    inv_type = ctype
                    break
            if inv_type is None and candidate_types:
                inv_type = candidate_types[0]
            elif inv_type is None:
                inv_type = original_invariants[0].type
        else:
            candidate_types = original_id_to_types.get(entry.invariant_id, [])
            if len(candidate_types) == 1:
                inv_type = candidate_types[0]
            elif len(candidate_types) > 1:
                # Multiple invariants share this LLM-generated ID with
                # different types.  Try each type and pick the one whose
                # computed ID matches a known (already-rewritten) invariant.
                for ctype in candidate_types:
                    if compute_invariant_id(excerpt, ctype) in normalized_inv_ids:
                        inv_type = ctype
                        break
                if inv_type is None:
                    # Fallback: use the first candidate type
                    inv_type = candidate_types[0]
            else:
                # No matching invariant for this source_map entry
                if len(success.invariants) == 1:
                    inv_type = success.invariants[0].type
                elif len(success.source_map) == len(original_invariants):
                    inv_type = original_invariants[entry_index].type
                else:
                    logger.error("Cannot match source_map entry to invariant type")
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
        logger.warning(
            "Spec authority compiler output has %s invariant(s) without source_map coverage: %s",
            len(missing),
            missing,
        )

    return SpecAuthorityCompilerOutput(root=success)
