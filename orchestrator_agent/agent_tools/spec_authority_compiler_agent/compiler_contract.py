"""Deterministic helpers for spec authority compilation contract."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from utils.schemes import (
    Invariant,
    InvariantType,
    ForbiddenCapabilityParams,
    RequiredFieldParams,
    MaxValueParams,
)


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _normalize_token(token: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_\-\s]", "", token)
    collapsed = " ".join(cleaned.strip().lower().split())
    return collapsed.replace(" ", "_")


def compute_prompt_hash(prompt_text: str) -> str:
    """Compute SHA-256 hash of the prompt/instructions."""
    normalized = _normalize_text(prompt_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_spec_hash(spec_content: str) -> str:
    """Compute SHA-256 hash of spec content (normalized)."""
    normalized = _normalize_text(spec_content)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def compute_invariant_id(excerpt: str, invariant_type: InvariantType) -> str:
    """Compute deterministic invariant ID from excerpt and type."""
    normalized_excerpt = _normalize_text(excerpt)
    seed = f"{normalized_excerpt}|{invariant_type.value}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()
    return f"INV-{digest[:16]}"


def classify_invariant_from_text(text: str) -> Optional[Invariant]:
    """Classify a single invariant from a spec sentence using deterministic rules."""
    if not text or not text.strip():
        return None

    original_excerpt = text.strip()

    forbidden_match = re.search(
        r"must\s+not\s+use\s+(.+?)(?:[\.;]|$)",
        original_excerpt,
        flags=re.IGNORECASE,
    )
    if forbidden_match:
        capability = _normalize_token(forbidden_match.group(1))
        invariant_id = compute_invariant_id(original_excerpt, InvariantType.FORBIDDEN_CAPABILITY)
        return Invariant(
            id=invariant_id,
            type=InvariantType.FORBIDDEN_CAPABILITY,
            parameters=ForbiddenCapabilityParams(capability=capability),
        )

    required_match = re.search(
        r"must\s+include\s+(.+?)(?:[\.;]|$)",
        original_excerpt,
        flags=re.IGNORECASE,
    )
    if required_match:
        field_name = _normalize_token(required_match.group(1))
        invariant_id = compute_invariant_id(original_excerpt, InvariantType.REQUIRED_FIELD)
        return Invariant(
            id=invariant_id,
            type=InvariantType.REQUIRED_FIELD,
            parameters=RequiredFieldParams(field_name=field_name),
        )

    max_match = re.search(
        r"(?P<field>[a-zA-Z0-9_\-\s]+?)\s+must\s+be\s*<=\s*(?P<value>\d+(?:\.\d+)?)",
        original_excerpt,
        flags=re.IGNORECASE,
    )
    if max_match:
        field_name = _normalize_token(max_match.group("field"))
        value_raw = max_match.group("value")
        max_value = int(value_raw) if value_raw.isdigit() else float(value_raw)
        invariant_id = compute_invariant_id(original_excerpt, InvariantType.MAX_VALUE)
        return Invariant(
            id=invariant_id,
            type=InvariantType.MAX_VALUE,
            parameters=MaxValueParams(field_name=field_name, max_value=max_value),
        )

    return None
