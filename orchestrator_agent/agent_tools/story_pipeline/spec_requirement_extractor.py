# orchestrator_agent/agent_tools/story_pipeline/spec_requirement_extractor.py
"""
Deterministic Spec Requirement Extractor and Binder.

This module extracts HARD REQUIREMENTS from technical specifications and binds
them to stories based on domain/theme keywords. Unlike LLM-based validation,
this provides deterministic, auditable compliance checking.

Key Concepts:
- Hard Requirements: Statements with MUST/SHALL/REQUIRED/ALWAYS/NEVER keywords
- Domain Binding: Maps requirements to feature themes/keywords
- Artifact Checking: Validates acceptance criteria mention required artifacts

The goal is to FAIL stories that omit must-have invariants, forcing refinement
to add them before exit_loop.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from enum import Enum


class RequirementStrength(Enum):
    """RFC 2119 requirement strength levels."""
    MUST = "must"           # Absolute requirement
    MUST_NOT = "must_not"   # Absolute prohibition
    SHALL = "shall"         # Equivalent to MUST
    SHALL_NOT = "shall_not" # Equivalent to MUST NOT
    REQUIRED = "required"   # Equivalent to MUST
    ALWAYS = "always"       # Temporal MUST
    NEVER = "never"         # Temporal MUST NOT
    

@dataclass
class HardRequirement:
    """A hard requirement extracted from the specification."""
    id: str                         # Unique ID (e.g., "REQ-001")
    text: str                       # Original requirement text
    strength: RequirementStrength   # MUST/SHALL/REQUIRED etc.
    domain_keywords: List[str]      # Keywords that bind this to stories
    required_artifacts: List[str]   # Named artifacts that must appear in AC
    source_section: str             # Section header where found
    line_number: int                # Line in spec (for traceability)


@dataclass
class DomainBinding:
    """Maps feature themes/keywords to requirements."""
    domain_name: str                # e.g., "ingestion", "review", "audit"
    trigger_keywords: Set[str]      # Keywords that activate this domain
    bound_requirements: List[str]   # Requirement IDs that apply


@dataclass
class SpecComplianceCheckResult:
    """Result of checking a story against bound requirements."""
    is_compliant: bool
    missing_requirements: List[HardRequirement]
    missing_artifacts: List[str]
    blocking_suggestions: List[str]
    matched_domain: Optional[str]
    

# --- Requirement Strength Patterns ---
# Regex patterns to identify hard requirements
REQUIREMENT_PATTERNS: Dict[RequirementStrength, re.Pattern] = {
    RequirementStrength.MUST: re.compile(
        r'\b(?:must|MUST)\b(?!\s+not\b)', re.IGNORECASE
    ),
    RequirementStrength.MUST_NOT: re.compile(
        r'\b(?:must\s+not|MUST\s+NOT)\b', re.IGNORECASE
    ),
    RequirementStrength.SHALL: re.compile(
        r'\b(?:shall|SHALL)\b(?!\s+not\b)', re.IGNORECASE
    ),
    RequirementStrength.SHALL_NOT: re.compile(
        r'\b(?:shall\s+not|SHALL\s+NOT)\b', re.IGNORECASE
    ),
    RequirementStrength.REQUIRED: re.compile(
        r'\b(?:required|REQUIRED|is\s+required)\b', re.IGNORECASE
    ),
    RequirementStrength.ALWAYS: re.compile(
        r'\b(?:always|ALWAYS)\b', re.IGNORECASE
    ),
    RequirementStrength.NEVER: re.compile(
        r'\b(?:never|NEVER)\b', re.IGNORECASE
    ),
}


# --- Domain Keyword Mappings ---
# These map feature themes to domain contexts
DOMAIN_KEYWORD_MAPPINGS: Dict[str, Set[str]] = {
    "ingestion": {
        "ingest", "ingestion", "upload", "import", "load", "parse", "extract",
        "pdf", "document", "file", "input", "source", "primitive", "detection",
        "ocr", "scan", "digitize", "digitization"
    },
    "revision": {
        "revision", "version", "versioning", "immutable", "snapshot", "history",
        "audit", "trail", "checkpoint", "rollback", "delta", "change", "update"
    },
    "review": {
        "review", "reviewer", "approve", "approval", "reject", "validate",
        "validation", "human", "loop", "feedback", "correction", "edit",
        "checkpoint", "gate", "stage"
    },
    "training": {
        "train", "training", "dataset", "gold", "label", "annotation",
        "retrain", "export", "coco", "model", "machine", "learning"
    },
    "provenance": {
        "provenance", "lineage", "traceability", "trace", "origin", "source",
        "model", "config", "configuration", "version", "hash", "sha"
    },
    "workflow": {
        "workflow", "pipeline", "stage", "checkpoint", "emit", "artifact",
        "output", "process", "step", "phase", "gate"
    },
    "audit": {
        "audit", "log", "event", "track", "record", "history", "delta",
        "action", "change", "who", "when", "why"
    },
}


# --- Artifact Patterns ---
# Common artifacts that specs require (used for extraction)
ARTIFACT_NAME_PATTERNS = [
    # Versioned outputs (e.g., primitives_v{n}.jsonl)
    r'\b(\w+_v\{?n\}?\.(?:json|jsonl|parquet|xml|aasx))\b',
    # Snake_case artifacts with common prefixes
    r'\b((?:gold|review|machine|training|primitives|graph|dexpi|aas)_\w+)\b',
    # Specific schema fields and IDs
    r'\b(doc_revision_id|model_provenance|review_delta|checkpoint_\w+|action_id|reviewer_id|target_id)\b',
    # Hash references
    r'\b(\w+_hash|sha[_-]?\d+|pdf_sha\w*|input_hash)\b',
    # Version references
    r'\b(model_version|config_version|model_versions|config_versions)\b',
]


def extract_hard_requirements(spec_text: str) -> List[HardRequirement]:
    """
    Extract all hard requirements (MUST/SHALL/REQUIRED) from specification.
    
    Parses the spec text line-by-line, identifying statements that contain
    requirement keywords. Extracts associated artifacts from the requirement
    line AND subsequent bullet points (for "MUST create:" patterns).
    
    Args:
        spec_text: Full technical specification text (markdown supported)
        
    Returns:
        List of HardRequirement objects with traceability info
    """
    if not spec_text or not spec_text.strip():
        return []
    
    requirements: List[HardRequirement] = []
    current_section = "General"
    req_counter = 0
    
    lines = spec_text.split('\n')
    
    for line_num, line in enumerate(lines, start=1):
        stripped = line.strip()
        
        # Track section headers (markdown)
        if stripped.startswith('#'):
            current_section = stripped.lstrip('#').strip()
            continue
        
        # Skip empty lines and comments
        if not stripped or stripped.startswith('<!--'):
            continue
        
        # Check for requirement keywords
        for strength, pattern in REQUIREMENT_PATTERNS.items():
            if pattern.search(stripped):
                req_counter += 1
                req_id = f"REQ-{req_counter:03d}"
                
                # Extract domain keywords from the line
                domain_keywords = _extract_domain_keywords(stripped)
                
                # Extract artifact names from the line
                artifacts = _extract_artifact_names(stripped)
                
                # ENHANCED: Look at subsequent bullet lines for artifacts
                # This handles "MUST create:" followed by bullet list
                if stripped.endswith(':'):
                    # Look ahead at bullet points
                    for lookahead in range(1, 10):  # Check up to 10 lines ahead
                        if line_num + lookahead - 1 >= len(lines):
                            break
                        next_line = lines[line_num + lookahead - 1].strip()
                        
                        # Stop at empty line, header, or non-bullet
                        if not next_line or next_line.startswith('#'):
                            break
                        if not next_line.startswith('-') and not next_line.startswith('*'):
                            break
                        
                        # Extract artifacts from bullet points
                        bullet_artifacts = _extract_artifact_names(next_line)
                        for artifact in bullet_artifacts:
                            if artifact not in artifacts:
                                artifacts.append(artifact)
                        
                        # Also extract domain keywords from bullets
                        bullet_keywords = _extract_domain_keywords(next_line)
                        for kw in bullet_keywords:
                            if kw not in domain_keywords:
                                domain_keywords.append(kw)
                
                requirements.append(HardRequirement(
                    id=req_id,
                    text=stripped,
                    strength=strength,
                    domain_keywords=domain_keywords,
                    required_artifacts=artifacts,
                    source_section=current_section,
                    line_number=line_num,
                ))
                break  # One match per line is enough
    
    return requirements


def _extract_domain_keywords(text: str) -> List[str]:
    """Extract domain keywords from requirement text."""
    text_lower = text.lower()
    found_keywords: List[str] = []
    
    for domain, keywords in DOMAIN_KEYWORD_MAPPINGS.items():
        for keyword in keywords:
            if keyword in text_lower:
                if keyword not in found_keywords:
                    found_keywords.append(keyword)
    
    return found_keywords


def _extract_artifact_names(text: str) -> List[str]:
    """Extract artifact names (filenames, fields) from text."""
    artifacts: List[str] = []
    
    for pattern in ARTIFACT_NAME_PATTERNS:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if match not in artifacts:
                artifacts.append(match)
    
    # Also extract backtick-quoted terms (common in specs)
    backtick_matches = re.findall(r'`([^`]+)`', text)
    for match in backtick_matches:
        # Filter to likely artifact names (snake_case, has underscore)
        if '_' in match and len(match) < 50:
            if match not in artifacts:
                artifacts.append(match)
    
    return artifacts


def bind_requirements_to_story(
    feature_title: str,
    theme: str,
    epic: str,
    requirements: List[HardRequirement],
) -> Tuple[List[HardRequirement], str]:
    """
    Bind relevant requirements to a story based on its feature/theme/epic.
    
    Uses keyword matching to determine which domain(s) a story belongs to,
    then returns all requirements bound to those domains.
    
    Args:
        feature_title: The feature being developed
        theme: Theme grouping
        epic: Epic grouping
        requirements: All extracted requirements
        
    Returns:
        Tuple of (bound_requirements, matched_domain_name)
    """
    # Combine all text for matching
    search_text = f"{feature_title} {theme} {epic}".lower()
    
    # Find matching domains
    matched_domains: List[str] = []
    domain_scores: Dict[str, int] = {}
    
    for domain, keywords in DOMAIN_KEYWORD_MAPPINGS.items():
        score = sum(1 for kw in keywords if kw in search_text)
        if score > 0:
            domain_scores[domain] = score
            matched_domains.append(domain)
    
    if not matched_domains:
        # No domain match - return empty (story doesn't need domain-specific validation)
        return [], ""
    
    # Get primary domain (highest score)
    primary_domain = max(domain_scores, key=domain_scores.get)
    
    # Filter requirements that match this domain
    bound_reqs: List[HardRequirement] = []
    all_matched_keywords = DOMAIN_KEYWORD_MAPPINGS.get(primary_domain, set())
    
    for req in requirements:
        # Check if requirement has keywords overlapping with matched domain
        req_keywords_set = set(req.domain_keywords)
        if req_keywords_set & all_matched_keywords:
            bound_reqs.append(req)
    
    return bound_reqs, primary_domain


def check_acceptance_criteria_compliance(
    acceptance_criteria: List[str],
    bound_requirements: List[HardRequirement],
    feature_context: str,
) -> SpecComplianceCheckResult:
    """
    Check if acceptance criteria satisfy bound requirements.
    
    This is the core compliance check. It verifies:
    1. Required artifacts are mentioned in acceptance criteria
    2. Key invariants from requirements are addressed
    3. Criteria are concrete (not generic UI behaviors)
    
    Args:
        acceptance_criteria: List of AC strings from story
        bound_requirements: Requirements bound to this story's domain
        feature_context: Feature title/description for context
        
    Returns:
        SpecComplianceCheckResult with compliance status and gaps
    """
    if not bound_requirements:
        # No requirements bound - compliant by default
        return SpecComplianceCheckResult(
            is_compliant=True,
            missing_requirements=[],
            missing_artifacts=[],
            blocking_suggestions=[],
            matched_domain=None,
        )
    
    # Combine all AC text for searching
    ac_text = " ".join(acceptance_criteria).lower() if acceptance_criteria else ""
    
    missing_reqs: List[HardRequirement] = []
    missing_artifacts: List[str] = []
    blocking_suggestions: List[str] = []
    
    # Track which requirement concepts are covered
    for req in bound_requirements:
        # Check if any required artifact from this requirement is mentioned
        req_artifacts_found = False
        for artifact in req.required_artifacts:
            if artifact.lower() in ac_text:
                req_artifacts_found = True
                break
        
        # Check if key concepts from requirement are addressed
        req_concepts_found = _check_requirement_concepts(req.text, ac_text) if ac_text else False
        
        if req.required_artifacts and not req_artifacts_found:
            # Has explicit artifacts that are missing
            missing_artifacts.extend(req.required_artifacts)
            blocking_suggestions.append(
                f"Add acceptance criterion for artifact(s): {', '.join(req.required_artifacts)} "
                f"(from {req.source_section}: \"{req.text[:80]}...\")"
            )
            missing_reqs.append(req)
        elif not req_concepts_found:
            # No explicit artifacts, but concepts not found - still a gap
            missing_reqs.append(req)
            # Generate a suggestion based on the requirement text
            suggestion = _generate_suggestion_from_requirement(req)
            if suggestion:
                blocking_suggestions.append(suggestion)
    
    # Check for generic/vague acceptance criteria
    if acceptance_criteria:
        generic_issues = _detect_generic_criteria(acceptance_criteria)
        if generic_issues:
            blocking_suggestions.extend(generic_issues)
    elif bound_requirements:
        # Empty AC with bound requirements is always non-compliant
        blocking_suggestions.append(
            f"Acceptance criteria are empty but {len(bound_requirements)} domain requirements apply. "
            f"Add specific, testable criteria addressing: {', '.join(r.source_section for r in bound_requirements[:3])}"
        )
    
    is_compliant = len(missing_reqs) == 0 and len(blocking_suggestions) == 0
    
    return SpecComplianceCheckResult(
        is_compliant=is_compliant,
        missing_requirements=missing_reqs,
        missing_artifacts=list(set(missing_artifacts)),
        blocking_suggestions=blocking_suggestions,
        matched_domain=None,  # Will be set by caller
    )


def _generate_suggestion_from_requirement(req: HardRequirement) -> Optional[str]:
    """
    Generate a blocking suggestion from a requirement that lacks explicit artifacts.
    
    Analyzes the requirement text to suggest what should be in acceptance criteria.
    """
    text_lower = req.text.lower()
    
    # Pattern-based suggestions for common requirement types
    if "emit" in text_lower and "artifact" in text_lower:
        return (
            f"Add AC specifying which artifact(s) this feature emits "
            f"(requirement: \"{req.text[:60]}...\")"
        )
    
    if "event-sourced" in text_lower or "delta" in text_lower:
        return (
            f"Add AC for event-sourced delta storage with before/after state capture "
            f"(requirement: \"{req.text[:60]}...\")"
        )
    
    if "checkpoint" in text_lower and ("create" in text_lower or "approval" in text_lower):
        return (
            f"Add AC specifying checkpoint outputs (machine output, review artifact, gold snapshot) "
            f"(requirement: \"{req.text[:60]}...\")"
        )
    
    if "provenance" in text_lower or "version" in text_lower:
        return (
            f"Add AC capturing model/config provenance metadata "
            f"(requirement: \"{req.text[:60]}...\")"
        )
    
    if "immutable" in text_lower or "revision" in text_lower:
        return (
            f"Add AC for immutable revision ID generation "
            f"(requirement: \"{req.text[:60]}...\")"
        )
    
    # Generic fallback
    return (
        f"Add AC addressing: \"{req.text[:80]}...\" "
        f"(from {req.source_section})"
    )


def _check_requirement_concepts(requirement_text: str, ac_text: str) -> bool:
    """
    Check if key concepts from a requirement appear in acceptance criteria.
    
    Extracts nouns/concepts from requirement and checks for presence in AC.
    """
    # Extract key technical terms (4+ char words, likely nouns)
    words = re.findall(r'\b([a-z]{4,})\b', requirement_text.lower())
    
    # Filter to domain-relevant terms (not common words)
    common_words = {
        'must', 'shall', 'should', 'will', 'that', 'this', 'with', 'from',
        'each', 'every', 'when', 'where', 'what', 'which', 'have', 'been',
        'their', 'they', 'there', 'than', 'then', 'also', 'only', 'into'
    }
    technical_terms = [w for w in words if w not in common_words]
    
    if not technical_terms:
        return True  # No specific terms to check
    
    # Check if at least 30% of technical terms are mentioned
    matches = sum(1 for term in technical_terms if term in ac_text)
    coverage = matches / len(technical_terms) if technical_terms else 1.0
    
    return coverage >= 0.3


def _detect_generic_criteria(acceptance_criteria: List[str]) -> List[str]:
    """
    Detect acceptance criteria that are too generic/vague.
    
    Returns suggestions for making them concrete.
    """
    issues: List[str] = []
    
    # Patterns indicating generic criteria
    GENERIC_PATTERNS = [
        (r'\buser can see\b', "Replace 'user can see' with specific data fields/artifacts shown"),
        (r'\bsystem displays\b(?!.*\b(field|artifact|json|xml|version|id)\b)', 
         "Add specific field/artifact names to 'system displays' criterion"),
        (r'\bworks correctly\b', "Replace 'works correctly' with measurable outcome"),
        (r'\bhandles? errors?\b(?!.*\b(message|code|log|retry)\b)', 
         "Specify error handling behavior (message, logging, retry logic)"),
        (r'\bsuccessfully\b(?!.*\b(output|artifact|file|record|log)\b)', 
         "Replace vague 'successfully' with specific output/artifact verification"),
        (r'\buser experience\b', "Replace UX language with functional requirements"),
        (r'\bintuitively?\b', "Remove subjective term 'intuitive', add concrete behavior"),
    ]
    
    for ac in acceptance_criteria:
        ac_lower = ac.lower()
        for pattern, suggestion in GENERIC_PATTERNS:
            if re.search(pattern, ac_lower):
                issues.append(f"Vague criterion detected: \"{ac[:60]}...\" - {suggestion}")
                break  # One issue per criterion is enough
    
    return issues


def validate_story_against_spec(
    story_title: str,
    story_description: str,
    acceptance_criteria: List[str],
    feature_title: str,
    theme: str,
    epic: str,
    spec_text: str,
) -> SpecComplianceCheckResult:
    """
    Main entry point: Full spec compliance validation for a story.
    
    This function:
    1. Extracts hard requirements from spec
    2. Binds requirements to story based on domain
    3. Checks acceptance criteria against bound requirements
    4. Returns compliance result with blocking suggestions
    
    Args:
        story_title: Generated story title
        story_description: Story description
        acceptance_criteria: List of AC strings
        feature_title: Original feature title
        theme: Theme grouping
        epic: Epic grouping
        spec_text: Full technical specification
        
    Returns:
        SpecComplianceCheckResult with actionable compliance info
    """
    # Step 1: Extract requirements
    requirements = extract_hard_requirements(spec_text)
    
    if not requirements:
        # No hard requirements in spec - compliant by default
        return SpecComplianceCheckResult(
            is_compliant=True,
            missing_requirements=[],
            missing_artifacts=[],
            blocking_suggestions=[],
            matched_domain=None,
        )
    
    # Step 2: Bind requirements to story's domain
    bound_reqs, matched_domain = bind_requirements_to_story(
        feature_title=feature_title,
        theme=theme,
        epic=epic,
        requirements=requirements,
    )
    
    if not bound_reqs:
        # No requirements for this domain - compliant by default
        return SpecComplianceCheckResult(
            is_compliant=True,
            missing_requirements=[],
            missing_artifacts=[],
            blocking_suggestions=[],
            matched_domain=matched_domain or "general",
        )
    
    # Step 3: Check acceptance criteria compliance
    result = check_acceptance_criteria_compliance(
        acceptance_criteria=acceptance_criteria,
        bound_requirements=bound_reqs,
        feature_context=f"{feature_title} ({theme}/{epic})",
    )
    result.matched_domain = matched_domain
    
    return result


def format_compliance_report(result: SpecComplianceCheckResult) -> str:
    """Format compliance result as human-readable report for logging."""
    lines = []
    
    status = "✅ COMPLIANT" if result.is_compliant else "❌ NON-COMPLIANT"
    lines.append(f"Spec Compliance: {status}")
    
    if result.matched_domain:
        lines.append(f"  Domain: {result.matched_domain}")
    
    if result.missing_requirements:
        lines.append(f"  Missing Requirements: {len(result.missing_requirements)}")
        for req in result.missing_requirements[:3]:
            lines.append(f"    - [{req.id}] {req.text[:60]}...")
    
    if result.missing_artifacts:
        lines.append(f"  Missing Artifacts: {', '.join(result.missing_artifacts[:5])}")
    
    if result.blocking_suggestions:
        lines.append(f"  Blocking Suggestions ({len(result.blocking_suggestions)}):")
        for sug in result.blocking_suggestions[:3]:
            lines.append(f"    → {sug}")
    
    return "\n".join(lines)
