"""
Build generation-time authority context from compiled spec authority.

This helper derives a JSON-serializable context object from the pinned,
compiled authority. It performs no database access.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional, cast

from agile_sqlmodel import CompiledSpecAuthority
from utils.schemes import SpecAuthorityCompilerOutput, SpecAuthorityCompilationFailure
from orchestrator_agent.agent_tools.story_pipeline.alignment_checker import (
    extract_invariants_from_authority,
)


def _safe_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if isinstance(value, list):
        value_list = cast(List[Any], value)
        return [str(item) for item in value_list]
    return []


def build_generation_context(
    *,
    compiled_authority: CompiledSpecAuthority,
    spec_version_id: int,
    spec_hash: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a generation context from compiled authority.

    Args:
        compiled_authority: Pinned compiled authority record.
        spec_version_id: Pinned spec version ID (required).
        spec_hash: Optional spec hash for traceability.

    Returns:
        JSON-serializable dict with authority context fields.
    """
    scope_themes: List[str] = []
    gaps: List[str] = []
    assumptions: List[str] = []
    compiler_version: Optional[str] = None
    prompt_hash: Optional[str] = None
    domain: Optional[str] = None

    if compiled_authority.compiled_artifact_json:
        try:
            parsed = SpecAuthorityCompilerOutput.model_validate_json(
                compiled_authority.compiled_artifact_json
            )
        except (ValueError, TypeError):
            parsed = None
        if parsed and not isinstance(parsed.root, SpecAuthorityCompilationFailure):
            success = parsed.root
            scope_themes = list(success.scope_themes)
            gaps = list(success.gaps)
            assumptions = list(success.assumptions)
            compiler_version = success.compiler_version
            prompt_hash = success.prompt_hash
            domain = success.domain

    if not scope_themes:
        scope_themes = _safe_json_list(compiled_authority.scope_themes)

    if not gaps:
        gaps = _safe_json_list(compiled_authority.spec_gaps)

    if not compiler_version:
        compiler_version = compiled_authority.compiler_version

    if not prompt_hash:
        prompt_hash = compiled_authority.prompt_hash

    invariants = extract_invariants_from_authority(compiled_authority)

    context: Dict[str, Any] = {
        "spec_version_id": spec_version_id,
        "scope_themes": scope_themes,
        "domain": domain,
        "invariants": invariants,
        "gaps": gaps,
        "assumptions": assumptions,
        "compiler_version": compiler_version,
        "prompt_hash": prompt_hash,
    }

    if spec_hash:
        context["spec_hash"] = spec_hash

    return context
