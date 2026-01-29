# Spec-Driven Architecture Implementation Plan

**Branch:** `feature/spec-driven-architecture`  
**Created:** 2026-01-27  
**Status:** Draft - Awaiting Review

---

## Executive Summary

This plan transforms the current "simulated Product Owner" model into a **Specification Authority** model where:
- The technical specification is the single source of truth
- Story **acceptance** is deterministic (pass/fail gate), though generation remains non-deterministic (LLM-based)
- Execution is one-story-at-a-time with JIT task breakdown

### Key Architectural Constraints

1. **Determinism applies to acceptance, not generation** - The draft agent is generative (LLM); only the validation gate is deterministic
2. **Single point of eligibility enforcement** - Theme-gating lives in the data-access layer only, never duplicated
3. **Spec Authority is a compiler, not a per-call agent** - Runs once per spec version, outputs are cached
4. **No cross-story task creation** - Enforced at schema level, not by convention
5. **Team Simulation is advisory-only** - Never mutates sprint state
6. **Spikes block without failing** - `ready_to_start=false` is a valid, non-failing outcome
7. **Compilation is not acceptance** - Compiled artifacts require explicit acceptance before use

### Authority Pinning Contract (Validation Boundary)

- **Public entrypoints:** MUST require `spec_version_id` (no defaults).
- **Authority loading:** MUST be done by a single helper using `(product_id, spec_version_id)` and MUST fail fast with clear errors on mismatch/uncompiled.
- **Authority acceptance:** MUST require an explicit acceptance record before use; compiled artifacts alone are not authoritative.
- **Alignment checks:** MUST be pure functions over explicit inputs (compiled authority or invariants).
- **Alignment semantics:** MUST reject ONLY on explicit `FORBIDDEN_CAPABILITY` invariants; it MUST NOT reject on other invariant types (e.g., `REQUIRED_FIELD`).
- **Forbidden capability derivation:** MUST prefer compiled authority artifacts; legacy invariant strings are supported only when explicitly formatted as `FORBIDDEN_CAPABILITY:<term>`.
- **Required-field enforcement:** MUST be handled by deterministic validation (separate from alignment) and MUST never be treated as a forbidden term.
- **No implicit sources:** NEVER read `Product.technical_spec`, product vision, or “latest approved” for validation/alignment.
- **Invariants injection:** INTERNAL-ONLY for tests/composition; never user-facing.
  - Public tools MUST NOT accept `_invariants` in any user-facing schema or orchestrator command input.

### Generation uses compiled authority context (authoritative)

Story generation consumes a **generation context** derived from the pinned, accepted
compiled authority. This context is authoritative for scope and invariants.

- **Authoritative inputs:** `authority_context` built from compiled authority
- **Non-authoritative inputs:** optional raw spec text for phrasing only
- **Acceptance path:** deterministic gates use compiled authority + pinned `spec_version_id` only

**Refiner toggle:** The story refiner remains available for A/B testing and can be
disabled via a `enable_story_refiner` boolean flag (default: true).

### Authority Acceptance Decision (NEW)

**Purpose:** Distinguish “compiled candidate” from “accepted authority.”

**Policy (current):** `AUTO_ACCEPT_ON_COMPILE_SUCCESS`

**Rules:**
- A compiled authority is **not** authoritative until an acceptance record exists.
- Acceptance is append-only: never silently overwrite an accepted decision.
- Story pipeline must fail fast if authority is not accepted for `(product_id, spec_version_id)`.

### Update: Option B Hardening — Authority Pinning Contract (Implemented)

**Status:** COMPLETED. Alignment checking and story pipeline validation are pinned to `spec_version_id` via compiled authority. Vision/spec implicit lookups removed.

**Implemented changes:**
1) **alignment_checker authority pinning**
- alignment_checker functions MUST accept either:
  - `compiled_authority` (preferred), OR
  - `_invariants` (INTERNAL-ONLY; tests/composition only)
- alignment_checker MUST raise a hard error if neither `compiled_authority` nor `_invariants` is provided.
- alignment_checker MUST NOT perform DB/spec lookups or read Product vision / Product.technical_spec / “latest approved”.

2) **Forbidden-capability-only alignment (Implemented)**
- Alignment rejection MUST be driven ONLY by `FORBIDDEN_CAPABILITY` invariants.
- `REQUIRED_FIELD` and other invariant types MUST be enforced in deterministic validation, not alignment.
- Forbidden capabilities MUST be derived from compiled authority artifact JSON when present; fallback parsing only accepts exact `FORBIDDEN_CAPABILITY:<term>` strings (no tokenization).

3) **Single authority load point in story pipeline**
- story pipeline MUST load compiled authority exactly once per call using a single helper:
  - `_load_compiled_authority(product_id, spec_version_id)`
- all alignment computations MUST be pure functions over explicit inputs (compiled_authority or invariants).
- pipeline MUST pass the pinned authority/invariants into alignment_checker; alignment_checker must never perform lookups.

4) **Pinned `spec_version_id` propagation (Implemented)**
- Canonical `spec_version_id` is the value passed into `process_single_story()` / `ProcessStoryInput.spec_version_id`.
- The returned story payload MUST include `story.metadata.spec_version_id` equal to the canonical pinned id.
- The pipeline MUST defensively overwrite any LLM-drifted/hardcoded `metadata.spec_version_id` to the pinned value.

5) **Acceptance-gate hard-stop in smoke harness (Implemented)**
- The smoke harness MUST hard-fail Scenario 3 (compiled but not accepted) before calling the story pipeline.
- Trace MUST clearly show the block condition (e.g., `ACCEPTANCE_GATE_BLOCKED=true`).

6) **Legacy helpers are internal-only**
- legacy validation/extraction helpers are renamed with a leading underscore and treated as internal implementation details.
- public entry points MUST delegate to canonical tools that require explicit `spec_version_id`.

**Non-negotiable prohibitions (strengthened):**
- Public tools MUST NOT accept `_invariants` in any user-facing schema or orchestrator command input.
- Public tools MUST NOT expose any parameter that allows callers to override compiled authority contents.
- No implicit spec sources: NEVER read Product.technical_spec, Product vision, or “latest spec” for validation/alignment.

**Regression tests required:**
- alignment_checker cannot run without compiled_authority/_invariants (raises).
- alignment_checker behavior is determined by pinned invariants (no implicit sources).
- pipeline path proves compiled authority is loaded and passed through (no bypass).
- alignment does not reject on `REQUIRED_FIELD` invariants (only `FORBIDDEN_CAPABILITY`).
- returned story payload pins `metadata.spec_version_id` to the input pinned version.
- smoke harness Scenario 3 blocks before story pipeline when authority is not accepted.

**Evidence / audit:**
- Alignment violations MUST be representable in persisted validation evidence (either as failures or warnings) so audits do not require reconstructing behavior from logs.

---

## Phase 1: Pipeline Simplification

### 1.1 Remove Story Refiner Agent

**Goal:** Eliminate the refinement loop. Stories either pass spec validation or get rejected.

> **Determinism Clarification:** The draft agent remains **non-deterministic** (LLM-based generation). 
> What becomes deterministic is the **acceptance gate**: the spec validator and contract enforcer 
> apply fixed rules that produce consistent pass/fail outcomes for identical inputs.

**Files to modify:**

| File | Change |
|------|--------|
| `orchestrator_agent/agent_tools/story_pipeline/pipeline.py` | Remove `story_refiner_agent` from SequentialAgent, change to single-pass |
| `orchestrator_agent/agent_tools/story_pipeline/tools.py` | Update `process_single_story()` to handle pass/fail (no retry logic) |

**New pipeline architecture:**
```
┌─────────────────────────────────────────────────────────────────┐
│           SinglePassPipeline (no loop)                          │
│  ┌─────────────┐        ┌───────────────────────────────────┐  │
│  │ StoryDraft  │   →    │   Spec Validator + Contract       │  │
│  │   Agent     │        │   (DETERMINISTIC acceptance gate) │  │
│  │ (generative)│        └───────────────────────────────────┘  │
│  └─────────────┘                      ↓                         │
│        ↓                       PASS → persist                   │
│   state['draft']               FAIL → reject (deterministic)    │
│   (non-deterministic)                                           │
└─────────────────────────────────────────────────────────────────┘
```

**Behavior change:**
- **Before:** Story fails validation → Refine → Retry (up to 4x)
- **After:** Story fails validation → Deterministic rejection with reason → Feature flagged for spec review

**What "deterministic rejection" guarantees:**
- Same story draft + same spec + same contracts = same pass/fail result
- No LLM judgment in the acceptance path
- Rejection reasons are traceable to specific contract rules

**Files to deprecate (not delete, mark as legacy):**
- `orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/` - Keep but don't import

---

### 1.2 Add Theme-Gating (Eligibility Filter)

**Goal:** Only features in `Now` or `Next` time_frames are eligible for story generation.

> **Single Point of Enforcement:** Theme-gating MUST live exclusively in the data-access layer.
> Do NOT duplicate eligibility checks in `process_single_story()` or anywhere else.
> Split-brain eligibility logic leads to inconsistent behavior and maintenance burden.

**Files to modify:**

| File | Change |
|------|--------|
| `orchestrator_agent/agent_tools/product_user_story_tool/tools.py` | Add `allowed_time_frames` parameter to `query_features_for_stories()` |
| `agile_sqlmodel.py` | Add `FeatureEligibility` validator (schema-level enforcement) |

**Enforcement strategy:**
```
┌─────────────────────────────────────────────────────────────┐
│                 SINGLE GATING POINT                         │
│                                                             │
│  query_features_for_stories(allowed_time_frames=[...])      │
│         ↓                                                   │
│  SQL WHERE theme.time_frame IN ('Now', 'Next')              │
│         ↓                                                   │
│  Features returned are ALREADY eligible                     │
│         ↓                                                   │
│  process_single_story() TRUSTS the query result             │
│  (no redundant checks)                                      │
└─────────────────────────────────────────────────────────────┘
```

**New query signature:**
```python
def query_features_for_stories(
    product_id: int,
    allowed_time_frames: List[str] = ["Now", "Next"],  # Enforced in SQL
    theme_filter: Optional[str] = None,
    epic_filter: Optional[str] = None,
) -> Dict[str, Any]:
    """Query features eligible for story generation.

    IMPORTANT: This is the ONLY place where time_frame eligibility is enforced.
    Downstream functions (process_single_story, etc.) trust this filter.
    """
```

**Schema-level enforcement (optional hardening):**
```python
# In agile_sqlmodel.py or schemas.py
class EligibleFeatureInput(BaseModel):
    """Input that has passed eligibility gate."""
    feature_id: int
    time_frame: Literal["Now", "Next"]  # Schema rejects "Later" at parse time
```

**What NOT to do:**
```python
# WRONG: Duplicating eligibility check in process_single_story
if story_input.time_frame == "Later":
    return {"error": "Not eligible"}  # Split-brain!
```

---

## Phase 2: Specification Authority (Compiler Model)

### 2.1 Create Spec Authority as a Compiler, Not an Agent

**Goal:** Replace subjective PO decisions with deterministic spec-based authority.

> **Critical Design Decision:** The Spec Authority is a **compiler**, not a per-call agent.
> It runs **once per spec version**, and its outputs are **cached and reused** across all 
> orchestration calls. This eliminates hidden variability and reduces LLM costs.

**Architecture: Compiler Model**
```
┌─────────────────────────────────────────────────────────────┐
│                 SPEC COMPILER (runs once)                   │
│                                                             │
│  Input: spec_file.md (version-hashed)                       │
│         ↓                                                   │
│  [LLM extraction pass - ONE TIME]                           │
│         ↓                                                   │
│  Output: CompiledSpecAuthority (cached in DB)               │
│         - scope_themes                                      │
│         - invariants                                        │
│         - eligible_feature_ids                              │
│         - spec_version_hash                                 │
│                                                             │
│  Subsequent calls: Load from cache, skip LLM                │
└─────────────────────────────────────────────────────────────┘
```

**New folder structure:**
```
orchestrator_agent/agent_tools/spec_authority/
├── compiler.py        # compile_spec() - runs once per spec version
├── cache.py           # load_compiled_spec(), invalidate_cache()
├── schemas.py         # CompiledSpecAuthority schema
└── instructions.txt   # LLM extraction rules (used only during compilation)
```

**Key differences from Vision Agent:**

| Vision Agent (Current) | Spec Authority Compiler (Proposed) |
|------------------------|------------------------------------|
| Asks clarifying questions | Extracts from spec or fails |
| Runs every orchestration call | Runs once per spec version |
| Generates vision statement | Produces cached authority record |
| Simulates customer priorities | Enforces spec constraints deterministically |
| Iterative conversation | Single compilation pass |
| Outputs are ephemeral | Outputs are persisted and versioned |

**Spec Authority responsibilities:**
1. **Scope Extraction** - What themes/epics are in scope (cached)
2. **Invariant Identification** - Non-negotiable constraints (cached)
3. **Eligibility Ruling** - Which features can generate stories (cached)
4. **Constraint Enforcement** - Deterministic lookup, no LLM call

**Output schema (cached):**
```python
class CompiledSpecAuthority(BaseModel):
    """Cached output from spec compilation. Immutable once created."""
    spec_version_hash: str           # SHA256 of spec content
    compiled_at: datetime
    scope_themes: List[str]          # Themes in scope (Now/Next)
    invariants: List[str]            # MUST/SHALL requirements
    eligible_feature_ids: List[int]  # Pre-computed eligibility
    rejected_features: List[Dict]    # {feature_id, reason}
    spec_gaps: List[str]             # Missing info (blocks until resolved)

# Cache lookup
def get_spec_authority(product_id: int) -> CompiledSpecAuthority:
    """Load cached spec authority. Raises if spec changed and needs recompile."""
```

**Note (implementation detail):** In the current implementation, compiled authority invariants are treated as **typed** records (e.g., `FORBIDDEN_CAPABILITY` vs `REQUIRED_FIELD`) when deriving alignment forbidden terms. Alignment rejection is driven only by `FORBIDDEN_CAPABILITY`; required fields are enforced in deterministic validation.

**Recompilation triggers:**
- Spec file content changes (hash mismatch)
- Manual invalidation via `invalidate_spec_cache(product_id)`
- Roadmap structure changes (themes/features added/removed)

---

### 2.2 Spec Versioning and Review Workflow

> **Critical Governance Requirement:** If the spec is "authority," it must be a **living artifact** 
> with explicit versioning, review gates, and controlled impact on in-flight work.
> Without this, you get silent recompiled behavior and retroactive changes that break traceability.

#### 2.2.1 Spec Versioning Schema

**New database tables:**

```python
# In agile_sqlmodel.py

class SpecRegistry(SQLModel, table=True):
    """Versioned spec content with approval tracking."""
    __tablename__ = "spec_registry"

    spec_version_id: int = Field(primary_key=True)  # Monotonic, never reused
    product_id: int = Field(foreign_key="products.product_id")
    spec_version_hash: str  # SHA-256 of spec content
    content_ref: str        # Path to spec file or inline content
    created_at: datetime
    approved_at: Optional[datetime] = None
    approved_by: Optional[str] = None  # Reviewer identifier
    approval_notes: Optional[str] = None
    status: Literal["draft", "pending_review", "approved", "superseded"] = "draft"


class CompiledSpecAuthority(SQLModel, table=True):
    """Cached compilation output, pinned to a specific spec version."""
    __tablename__ = "compiled_spec_authority"

    id: int = Field(primary_key=True)
    spec_version_id: int = Field(foreign_key="spec_registry.spec_version_id")
    compiler_version: str
    prompt_hash: str
    compiled_at: datetime

    scope_themes: str
    invariants: str
    eligible_feature_ids: str
    rejected_features: str
    spec_gaps: str


class SpecImpactReport(SQLModel, table=True):
    """Impact analysis when spec changes."""
    __tablename__ = "spec_impact_reports"

    id: int = Field(primary_key=True)
    from_spec_version_id: int = Field(foreign_key="spec_registry.spec_version_id")
    to_spec_version_id: int = Field(foreign_key="spec_registry.spec_version_id")
    generated_at: datetime

    changes_summary: str
    no_impact_stories: str
    needs_revalidation: str
    needs_rewrite: str
    blocking_stories: str
    recommended_actions: str
```

**Story/Task spec pinning:**
```python
class UserStory(SQLModel, table=True):
    accepted_spec_version_id: Optional[int] = Field(
        foreign_key="spec_registry.spec_version_id",
        description="Spec version this story was validated against. Never 'latest'."
    )
    validation_evidence: Optional[str] = Field(
        default=None,
        description="JSON: which rules fired, which invariants checked"
    )
```

#### 2.2.2 Spec Review Gate

**Review is required before:**
- Compiling Spec Authority outputs
- Generating new stories
- Re-accepting stories that previously failed

```
┌─────────────────────────────────────────────────────────────────┐
│                    SPEC REVIEW GATE                             │
│                                                                 │
│  Spec v1 (approved) ───────────────────────────────────────────│
│         │                                                       │
│         │  [spec file changes]                                  │
│         ▼                                                       │
│  Spec v2 (draft) ─── hash mismatch detected ───────────────────│
│         │                                                       │
│         │  ❌ AUTO-COMPILE BLOCKED                              │
│         │                                                       │
│         ▼                                                       │
│  "review spec changes" ─── generates impact report (read-only) │
│         │                                                       │
│         ▼                                                       │
│  "approve spec v2" ─── marks reviewed, records rationale       │
│         │                                                       │
│         ▼                                                       │
│  "compile spec v2" ─── produces new CompiledSpecAuthority      │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Review outcome schema:**
```python
class SpecReviewOutcome(BaseModel):
    """Recorded outcome of spec review."""
    spec_version_id: int
    outcome: Literal["approved", "rejected"]
    reviewer: str
    reviewed_at: datetime
    rationale: str
    conditions: Optional[List[str]] = None  # Any caveats or conditions
```

#### 2.2.3 Controlled Recompilation (Never Automatic)

**When spec content changes (hash mismatch):**
1. Mark existing authority cache as `STALE`
2. **DO NOT** auto-recompile during normal orchestration
3. Block story generation until explicit approval

```python
def check_spec_authority_status(product_id: int) -> SpecAuthorityStatus:
    """Check if spec authority is current or stale."""
    current_spec = get_latest_spec(product_id)
    cached_authority = get_cached_authority(product_id)
    
    if cached_authority is None:
        return SpecAuthorityStatus.NOT_COMPILED
    
    if cached_authority.spec_version_id != current_spec.spec_version_id:
        return SpecAuthorityStatus.STALE  # Hash mismatch
    
    if current_spec.status != "approved":
        return SpecAuthorityStatus.PENDING_REVIEW
    
    return SpecAuthorityStatus.CURRENT


# In story generation flow:
def process_story_batch(...):
    status = check_spec_authority_status(product_id)
    
    if status == SpecAuthorityStatus.STALE:
        return {
            "success": False,
            "error": "Spec authority is STALE. Spec content has changed.",
            "action": "Run 'review spec changes', then 'approve spec vN', then 'compile spec vN'",
            "blocked_reason": "Cannot generate stories against outdated spec authority"
        }
```

#### 2.2.4 Mandatory Impact Analysis on Spec Change

**On new spec version, before any approval:**

```python
def generate_spec_impact_report(
    product_id: int,
    from_version: int,
    to_version: int
) -> SpecImpactReport:
    """Deterministic impact analysis - read-only, no mutations."""
    
    # 1. Diff the specs
    changes = diff_spec_versions(from_version, to_version)
    
    # 2. Find affected stories
    all_stories = get_product_stories(product_id)
    
    classification = {
        "no_impact": [],
        "needs_revalidation": [],
        "needs_rewrite": [],
        "blocking": []
    }
    
    for story in all_stories:
        if story.status == StoryStatus.DONE:
            # Completed stories: check if invariants they relied on changed
            if not invariants_changed(story.validation_evidence, changes):
                classification["no_impact"].append(story.story_id)
            else:
                # Historical record - flag for audit but don't block
                classification["needs_revalidation"].append(story.story_id)
        
        elif story.status == StoryStatus.IN_PROGRESS:
            # In-flight work: most sensitive
            if breaking_change_affects(story, changes):
                classification["blocking"].append(story.story_id)
            elif minor_change_affects(story, changes):
                classification["needs_revalidation"].append(story.story_id)
            else:
                classification["no_impact"].append(story.story_id)
        
        else:  # TO_DO
            # Backlog stories: re-validate before pulling into sprint
            if any_change_affects(story, changes):
                classification["needs_revalidation"].append(story.story_id)
    
    return SpecImpactReport(
        from_spec_version_id=from_version,
        to_spec_version_id=to_version,
        generated_at=datetime.now(timezone.utc),
        changes_summary=json.dumps(changes),
        no_impact_stories=json.dumps(classification["no_impact"]),
        needs_revalidation=json.dumps(classification["needs_revalidation"]),
        needs_rewrite=json.dumps(classification["needs_rewrite"]),
        blocking_stories=json.dumps(classification["blocking"]),
        recommended_actions=json.dumps(generate_recommendations(classification))
    )
```

**Impact report output example:**
```
┌─────────────────────────────────────────────────────────────────┐
│              SPEC IMPACT REPORT: v3 → v4                        │
├─────────────────────────────────────────────────────────────────┤
│ CHANGES SUMMARY:                                                │
│   + Added invariant: "All API responses must include trace_id"  │
│   ~ Modified: Authentication timeout 30s → 60s                  │
│   - Removed: Legacy OAuth1 support                              │
├─────────────────────────────────────────────────────────────────┤
│ AFFECTED STORIES:                                               │
│                                                                 │
│ ✅ NO IMPACT (12 stories):                                      │
│    #45, #46, #47, #48, #50, #51, #52, #53, #54, #55, #56, #57  │
│                                                                 │
│ ⚠️  NEEDS RE-VALIDATION (3 stories):                            │
│    #49 - "User login flow" (auth timeout change)                │
│    #58 - "API error handling" (trace_id requirement)            │
│    #59 - "Session management" (auth timeout change)             │
│                                                                 │
│ 🛑 BLOCKING - STOP WORK (1 story):                              │
│    #60 - "OAuth1 migration" (IN_PROGRESS, relies on removed     │
│           OAuth1 support - BREAKING CHANGE)                     │
├─────────────────────────────────────────────────────────────────┤
│ RECOMMENDED ACTIONS:                                            │
│   1. Complete or pause story #60 before approving spec v4       │
│   2. Re-validate #49, #58, #59 after compile                    │
│   3. Review if #60 should become a tech debt story              │
└─────────────────────────────────────────────────────────────────┘
```

#### 2.2.5 In-Flight Sprint Stability

**Core rule:** Stories already IN_PROGRESS continue under their **pinned spec_version_id**.

```python
def get_story_spec_authority(story_id: int) -> CompiledSpecAuthority:
    """Get the spec authority for a specific story - uses PINNED version."""
    story = get_story(story_id)
    
    # Always use the version the story was accepted against
    # NEVER silently upgrade to "latest"
    return get_compiled_authority(story.accepted_spec_version_id)


def validate_story_completion(story_id: int) -> ValidationResult:
    """Validate story against its PINNED spec version."""
    story = get_story(story_id)
    authority = get_story_spec_authority(story_id)  # Pinned, not latest
    
    result = run_validation(story, authority)
    
    # If newer spec exists, flag but don't fail
    latest_spec = get_latest_approved_spec(story.product_id)
    if latest_spec.spec_version_id != story.accepted_spec_version_id:
        result.warnings.append(
            f"Story validated against spec v{story.accepted_spec_version_id}, "
            f"but v{latest_spec.spec_version_id} is now current. "
            f"Consider migration if appropriate."
        )
    
    return result
```

**If new spec introduces breaking changes:**
```python
# Option A: Create a new story for alignment
def create_spec_alignment_story(
    original_story_id: int,
    new_spec_version_id: int,
    alignment_notes: str
) -> UserStory:
    """Create a follow-up story to align with new spec."""
    pass

# Option B: Explicit migration (triggers re-validation)
def migrate_story_to_spec_version(
    story_id: int,
    new_spec_version_id: int,
    migration_rationale: str
) -> MigrationResult:
    """Explicitly migrate story to new spec version.
    
    This is AUDITABLE and triggers re-validation.
    Never happens silently.
    """
    story = get_story(story_id)
    old_version = story.accepted_spec_version_id
    
    # Re-validate against new spec
    new_authority = get_compiled_authority(new_spec_version_id)
    validation = run_validation(story, new_authority)
    
    if not validation.passed:
        return MigrationResult(
            success=False,
            error="Story fails validation against new spec",
            validation_failures=validation.failures,
            action="Story needs modification before migration"
        )
    
    # Record the migration
    story.accepted_spec_version_id = new_spec_version_id
    story.validation_evidence = json.dumps(validation.evidence)
    
    log_spec_migration(
        story_id=story_id,
        from_version=old_version,
        to_version=new_spec_version_id,
        rationale=migration_rationale,
        migrated_at=datetime.now(timezone.utc)
    )
    
    return MigrationResult(success=True)
```

#### 2.2.6 Validation Evidence Storage

**Every acceptance stores evidence:**

```python
class ValidationEvidence(BaseModel):
    """Traceable record of what was checked during validation."""
    spec_version_id: int
    validated_at: datetime
    
    # What was checked
    contract_rules_applied: List[str]      # e.g., ["PERSONA_MATCH", "STORY_POINTS_RANGE"]
    invariants_checked: List[str]          # e.g., ["REQ-001", "REQ-042"]
    
    # Results
    passed: bool
    failures: List[Dict]                   # {rule, expected, actual, message}
    warnings: List[str]
    
    # Reproducibility
    validator_version: str
    input_hash: str                        # Hash of story content at validation time
```

**Validation function signature:**
```python
def validate_story(
    story: UserStory,
    spec_version_id: int  # EXPLICIT - never implicit "latest"
) -> Tuple[bool, ValidationEvidence]:
    """Deterministic validation against specific spec version.
    
    Returns (passed, evidence) where evidence is always populated
    regardless of pass/fail for traceability.
    """
```

#### 2.2.7 Definition of Done Includes Spec Alignment Evidence

**Story completion requirements:**

```python
class StoryCompletionInput(BaseModel):
    """Required fields to mark a story as DONE."""
    story_id: int
    completion_notes: str
    
    # REQUIRED: Spec alignment evidence
    spec_version_id: int                  # Which version was used
    validation_passed: bool               # Must be True to complete
    validation_evidence_id: int           # Reference to stored evidence
    
    # REQUIRED if newer spec exists
    spec_migration_declined_reason: Optional[str] = Field(
        default=None,
        description="If a newer spec exists, explain why story wasn't migrated"
    )


def complete_story(input: StoryCompletionInput) -> CompletionResult:
    """Complete a story with full spec alignment evidence."""
    story = get_story(input.story_id)
    latest_spec = get_latest_approved_spec(story.product_id)
    
    # Enforce spec alignment evidence
    if input.spec_version_id != story.accepted_spec_version_id:
        return CompletionResult(
            success=False,
            error="spec_version_id doesn't match story's pinned version"
        )
    
    # If newer spec exists, require explanation
    if latest_spec.spec_version_id > input.spec_version_id:
        if not input.spec_migration_declined_reason:
            return CompletionResult(
                success=False,
                error=f"Newer spec v{latest_spec.spec_version_id} exists. "
                      f"Provide spec_migration_declined_reason or migrate first."
            )
    
    # Record completion with full evidence
    story.status = StoryStatus.DONE
    story.completion_evidence = json.dumps({
        "spec_version_id": input.spec_version_id,
        "validation_evidence_id": input.validation_evidence_id,
        "newer_spec_available": latest_spec.spec_version_id > input.spec_version_id,
        "migration_declined_reason": input.spec_migration_declined_reason,
        "completed_at": datetime.now(timezone.utc).isoformat()
    })
```

#### 2.2.8 New Orchestrator Commands

**Add these commands to orchestrator instructions:**

```
STATE 14 — SPEC_REVIEW_CHANGES (read-only)
  Trigger: User says "review spec changes", "show spec diff", "what changed in spec"
  Action: Generate SpecImpactReport between current approved and latest draft
  Output: Display impact report with affected stories
  DOES NOT MUTATE anything

STATE 15 — SPEC_APPROVE
  Trigger: User says "approve spec vN", "approve spec changes"
  Precondition: Impact report has been reviewed
  Action: Mark spec version as approved, record reviewer + rationale
  Output: "Spec v{N} approved. Run 'compile spec v{N}' to generate authority cache."

STATE 16 — SPEC_COMPILE
  Trigger: User says "compile spec vN", "build spec authority"
  Precondition: Spec version is approved
  Action: Run LLM extraction pass, store CompiledSpecAuthority
  Output: "Spec v{N} compiled. {X} themes in scope, {Y} invariants extracted."

STATE 17 — REVALIDATE_STORY
  Trigger: User says "revalidate story <id>", "check story <id> against spec"
  Action: Run validation against story's pinned spec version (or specified version)
  Output: Pass/fail with evidence trace

STATE 18 — MIGRATE_STORY_SPEC
  Trigger: User says "migrate story <id> to spec vN"
  Precondition: Target spec is approved and compiled
  Action: Re-validate story, update pinned version if passes, record migration
  Output: Migration result with validation evidence
```

**Command summary:**

| Command | Type | Purpose |
|---------|------|---------|
| `review spec changes` | Read-only | Generate impact report |
| `approve spec vN` | Write | Mark spec as reviewed/approved |
| `compile spec vN` | Write | Produce cached authority |
| `revalidate story <id>` | Read-only | Check story against spec |
| `migrate story <id> to spec vN` | Write | Update story's pinned spec version |

---

### 2.3 Scrum Alignment (Without PO Pretense)

**How spec versioning maps to Scrum concepts:**

| Scrum Concept | Spec-Driven Equivalent |
|---------------|------------------------|
| Backlog refinement | Spec changes + impact analysis |
| Sprint boundary | "Approve + compile spec" gate |
| Definition of Ready | Story passes validation against compiled spec |
| Definition of Done | Completion includes spec alignment evidence |
| Sprint stability | Pinned spec versions for IN_PROGRESS work |
| PO decision | Spec authority ruling (cached, deterministic) |

**Key principle:** You decide what rules you're building against by controlling when specs are approved and compiled. This preserves sprint stability while allowing evolution.

---

### 2.4 Modify Orchestrator Flow

**Current flow:**
```
User Input → Vision Agent (iterative) → Save Vision → Roadmap Agent → Stories
```

**Proposed flow:**
```
Spec File → Spec Authority (single-pass) → Eligible Features → Stories (pass/fail)
```

**Files to modify:**

| File | Change |
|------|--------|
| `orchestrator_agent/instructions.txt` | Replace STATE 1-3 (Vision) with Spec Authority states |
| `orchestrator_agent/agent.py` | Replace `AgentTool(vision_agent)` with `AgentTool(spec_authority_agent)` |

---

## Phase 3: Sprint Framing (No Task Breakdown)

### 3.1 Simplify Sprint Planning

**Goal:** Sprint planning selects stories only - no task decomposition.

> ⚠️ **Schema-Level Enforcement:** The prohibition on early task creation MUST be enforced 
> at the schema level, not by convention. Otherwise, future tools or UI will violate this rule.

**Current `plan_sprint_tool` behavior:**
- Accepts optional `task_breakdown` parameter
- Creates `Task` records during planning

**Proposed behavior:**
- Remove `task_breakdown` parameter from planning phase
- Sprint contains only: goal + selected stories + capacity
- Tasks created later in JIT phase (Phase 5)
- **Schema rejects task creation attempts during planning**

**Files to modify:**

| File | Change |
|------|--------|
| `orchestrator_agent/agent_tools/sprint_planning/tools.py` | Remove `task_breakdown` from `PlanSprintInput` and `SaveSprintInput` |
| `agile_sqlmodel.py` | Add constraint: Tasks require `story.status == IN_PROGRESS` |

**Schema-level task creation constraint:**
```python
# In agile_sqlmodel.py or sprint_planning/schemas.py
class CreateTaskInput(BaseModel):
    """Task creation is only allowed for the currently active story."""
    story_id: int
    title: str
    
    @model_validator(mode='after')
    def validate_story_is_active(self) -> 'CreateTaskInput':
        """Enforce: Tasks can only be created for IN_PROGRESS stories."""
        # This validation runs at schema parse time
        # Actual DB check happens in the tool
        return self

# In tools, enforce at runtime:
def create_task(task_input: CreateTaskInput, session: Session):
    story = session.get(UserStory, task_input.story_id)
    if story.status != StoryStatus.IN_PROGRESS:
        raise ValueError(
            f"Cannot create tasks for story {story.story_id}: "
            f"status is {story.status}, must be IN_PROGRESS. "
            f"Tasks are created JIT when story execution begins."
        )
```

**What this prevents:**
- ❌ Creating tasks for all sprint stories upfront
- ❌ Speculative task breakdown during planning
- ❌ Cross-story task creation (tasks for story B while story A is active)
- ✅ JIT task creation only for the current IN_PROGRESS story

---

## Phase 4: Team Simulation Agent (Advisory Only)

### 4.1 Create Team Simulation Agent

**Goal:** Intelligent story ordering without task speculation.

> ⚠️ **Advisory-Only Constraint:** The Team Simulation Agent provides **recommendations only**.
> It MUST NEVER mutate sprint state, story status, or any database records.
> Without this constraint, it will drift into a pseudo-scrum-master role.

**New folder structure:**
```
orchestrator_agent/agent_tools/team_simulation_agent/
├── agent.py           # Agent definition (NO write tools)
├── instructions.txt   # Ordering heuristics
├── tools.py          # analyze_dependencies(), suggest_order() (READ-ONLY)
└── schemas.py        # TeamSimulationOutput
```

**Responsibilities (READ-ONLY):**
1. **Dependency Analysis** - Which stories block others
2. **Risk Assessment** - Flag high-uncertainty stories
3. **Setup Detection** - Find shared infrastructure needs
4. **Order Recommendation** - Suggest starting story + sequence
5. **Parallelization Warning** - Flag unsafe concurrent work

**Explicitly NOT responsible for:**
- ❌ Changing story status
- ❌ Modifying sprint composition
- ❌ Creating/updating any database records
- ❌ Making binding decisions

**Output schema:**
```python
class TeamSimulationOutput(BaseModel):
    """Advisory output only. No mutations."""
    recommended_first_story_id: int
    recommended_order: List[int]  # Story IDs in suggested order
    dependencies: List[Dict]      # {story_id, depends_on: [ids]}
    risk_flags: List[Dict]        # {story_id, risk, reason}
    shared_setup: List[str]       # Common infrastructure needs
    parallelization_warnings: List[str]
    
    # Explicit advisory marker
    is_advisory: Literal[True] = True  # Schema enforces this is always True
```

**Enforcement in agent definition:**
```python
# In agent.py - NO write tools allowed
team_simulation_agent = Agent(
    name="team_simulation_agent",
    tools=[
        # READ-ONLY tools only
        get_sprint_stories,      # Query
        analyze_story_content,   # Analysis
        # NO: update_story_status, modify_sprint, save_*, etc.
    ],
    instruction="You are an ADVISORY agent. You provide recommendations only. "
               "You cannot and must not attempt to modify any data."
)
```

---

## Phase 5: Just-In-Time Task Breakdown

### 5.1 Create JIT Task Agent



**Goal:** Break down ONE story into tasks only when it's about to be executed.

> ⚠️ **Critical: Spikes Block Without Failing**

> The biggest architectural risk is biasing the system toward under-discovery.

> `ready_to_start = false` MUST be a **valid, non-failing outcome**.
> Spikes are legitimate work that blocks execution without indicating story failure.

**New folder structure:**
```
orchestrator_agent/agent_tools/jit_task_agent/
├── agent.py           # Agent definition
├── instructions.txt   # Task decomposition rules
├── tools.py          # break_down_story(), identify_spikes()
└── schemas.py        # TaskBreakdownOutput
```

**Trigger:** Called only when:
1. Sprint is active
2. Previous story is DONE (or sprint just started)
3. Next story is selected

**Output schema:**
```python
class TaskBreakdownOutput(BaseModel):
    """JIT task breakdown result.
    
    IMPORTANT: ready_to_start=False is NOT a failure.
    It indicates spikes must be resolved before story work begins.
    This is a valid, expected outcome that should not be penalized.
    """
    story_id: int
    tasks: List[Dict]           # {title, description, estimated_hours}
    spikes: List[Dict]          # {question, time_box_hours}
    unknowns: List[str]         # Risks discovered during breakdown
    ready_to_start: bool        # False if spikes must resolve first
    
    # Explicit success semantics
    @property
    def breakdown_succeeded(self) -> bool:
        """Breakdown succeeded if we produced tasks OR identified spikes.
        
        Both outcomes are valid:
        - ready_to_start=True, tasks=[...] → Start working
        - ready_to_start=False, spikes=[...] → Resolve spikes first
        
        Only fails if we produced neither tasks nor spikes.
        """
        return len(self.tasks) > 0 or len(self.spikes) > 0
```

**Spike handling flow:**
```
┌─────────────────────────────────────────────────────────────┐
│                 JIT TASK BREAKDOWN                          │
│                                                             │
│  Story selected for execution                               │
│         ↓                                                   │
│  JIT Agent analyzes story                                   │
│         ↓                                                   │
│  ┌─────────────────┐    ┌─────────────────────────────┐    │
│  │ ready_to_start  │    │ ready_to_start = false      │    │
│  │ = true          │    │ spikes identified           │    │
│  │                 │    │                             │    │
│  │ → Execute tasks │    │ → Resolve spikes first      │    │
│  │                 │    │ → Re-run JIT after spikes   │    │
│  │ (normal flow)   │    │ (NOT a failure)             │    │
│  └─────────────────┘    └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘
```

**What this enables:**
- ✅ Discovering unknowns during breakdown (encouraged)
- ✅ Time-boxed spikes as legitimate sprint work
- ✅ Re-running breakdown after spike resolution
- ❌ Penalizing stories that surface complexity
- ❌ Rushing past unknowns to avoid "failure"

---

## Phase 6: One-Story-at-a-Time Execution

### 6.1 Add Serial Execution States to Orchestrator

**New orchestrator states:**

```
STATE 10 — STORY_SELECTION
  Trigger: Sprint active, no story IN_PROGRESS
  Action: Call Team Simulation Agent for next story
  Output: "Next story to work on: [title]"

STATE 11 — TASK_BREAKDOWN  
  Trigger: Story selected, no tasks exist
  Action: Call JIT Task Agent
  Output: Display tasks and spikes

STATE 12 — STORY_EXECUTION
  Trigger: Tasks exist, story IN_PROGRESS
  Behavior: Track task completion (external/manual)

STATE 13 — STORY_COMPLETION
  Trigger: All tasks done OR user marks complete
  Action: Validate AC, call complete_story_with_notes()
  Next: Return to STATE 10
```

**Files to modify:**

| File | Change |
|------|--------|
| `orchestrator_agent/instructions.txt` | Add STATE 10-13 |
| `orchestrator_agent/agent_tools/sprint_planning/sprint_execution_tools.py` | Add `select_next_story()` tool |

---

## Implementation Order

| Phase | Description | Estimated Hours | Dependencies |
|-------|-------------|-----------------|--------------|
| 1.1 | Remove refiner, single-pass pipeline | 2-3h | None |
| 1.2 | Theme-gating filter | 1-2h | None |
| 2.1 | Spec Authority Compiler | 4-6h | Phase 1 |
| 2.2 | Spec Versioning Schema (DB tables) | 3-4h | Phase 2.1 |
| 2.3 | Spec Review Gate + Impact Analysis | 4-5h | Phase 2.2 |
| 2.4 | Spec Migration Commands | 2-3h | Phase 2.3 |
| 2.5 | Orchestrator flow update | 2-3h | Phase 2.4 |
| 3.1 | Sprint planning simplification | 1-2h | None |
| 4.1 | Team Simulation Agent | 6-8h | Phase 3 |
| 5.1 | JIT Task Agent | 4-6h | Phase 4 |
| 6.1 | Serial execution states | 4-6h | Phase 5 |
| - | Testing & Integration | 8-10h | All phases |

**Total: 42-58 hours**

---

## Testing Strategy

### Unit Tests (per phase)
- Phase 1: Test pipeline rejects on spec fail, test theme-gate filter
- Phase 2: Test spec extraction, test invariant enforcement
- Phase 3: Test sprint saves without tasks
- Phase 4: Test dependency detection, test order recommendations
- Phase 5: Test task breakdown, test spike identification
- Phase 6: Test state transitions, test completion validation

### Integration Tests
- Full flow: Spec → Authority → Features → Stories → Sprint → Execution
- Rejection scenarios: Spec violation, theme-gate, contract failure

---

## Rollback Plan

Each phase is isolated. If issues arise:
1. Revert specific phase commits
2. Re-enable deprecated components (e.g., story_refiner_agent)
3. Feature flags can disable new agents without code changes

---

## Questions Before Proceeding

1. **Phase 1:** Should rejected stories be logged to a "rejected_stories" table for review, or just returned as errors?

2. **Phase 2:** Should Spec Authority completely replace Vision Agent, or coexist for projects without specs?

3. **Phase 4:** What heuristics should Team Simulation use for dependency detection? (keyword matching? explicit links?)

4. ~~**Phase 5:** Should spikes block story start, or be tracked as parallel tasks?~~
   **RESOLVED:** Spikes block story start (`ready_to_start=false`). This is a valid, non-failing outcome.

---

## Resolved Design Decisions

| Decision | Resolution | Rationale |
|----------|------------|------------|
| Determinism scope | Acceptance only, not generation | Draft agent is LLM-based (non-deterministic) |
| Eligibility enforcement | Data-access layer only | Prevents split-brain logic |
| Spec Authority model | Compiler (once per spec) | Eliminates per-call variability and cost |
| Task creation timing | Schema-enforced JIT only | Prevents speculative decomposition |
| Team Simulation role | Advisory-only, no mutations | Prevents drift into scrum-master |
| Spike handling | Blocks without failing | Encourages discovery, not under-reporting |
| Spec versioning | Explicit versions, never "latest" | Traceability + sprint stability |
| Spec recompilation | Manual gate, never automatic | Prevents silent behavioral changes |
| In-flight work | Pinned to accepted spec version | Sprint stability preserved |
| Story completion | Must include spec evidence | DoD enforces alignment proof |
| Spec changes | Mandatory impact analysis first | No surprises, deterministic report |

---

## Implementation Handoff: Spec Review + Versioning

> **Purpose:** This section provides a copy-pasteable specification for implementing the spec versioning 
> workflow. It is structured as a two-part handoff: (1) intent/constraints, (2) concrete implementation spec.
> Do NOT simplify or summarize this section—it is the authoritative implementation guide.

---

### PART 1 — ASSESSMENT (INTENT & NON-NEGOTIABLES)

We are extending the Spec-Driven Architecture to support Scrum-compatible evolution of specifications. The spec is authoritative but not static. It must be versioned, reviewed, and explicitly recompiled. Acceptance is deterministic per spec version, and in-flight work must never be silently reinterpreted against a newer spec. Any change to the spec must be auditable, impact-analyzed, and opt-in for existing stories. Automatic recompilation or retroactive validation is explicitly forbidden.

**Non-negotiable constraints:**
- Spec authority is versioned and pinned; "latest spec" must never be implied.
- Acceptance and validation are always evaluated against a specific `spec_version_id`.
- Spec changes do NOT automatically affect stories or sprints.
- Recompilation and migration are explicit user actions.
- In-progress stories remain stable unless explicitly migrated.
- Determinism applies to acceptance, not LLM generation.

---

### PART 2 — SPEC REVIEW + VERSIONING IMPLEMENTATION

#### 1) Spec Registry and Versioning

Introduce `SpecRegistry` table:
```sql
CREATE TABLE spec_registry (
    spec_version_id INTEGER PRIMARY KEY,  -- Monotonic, never reused
    product_id INTEGER NOT NULL REFERENCES products(product_id),
    spec_hash TEXT NOT NULL,              -- SHA-256 of content
    content_ref TEXT NOT NULL,            -- Path or blob reference
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_at TIMESTAMP,                -- NULL until reviewed
    approved_by TEXT,                     -- Reviewer identifier
    review_notes TEXT,
    status TEXT NOT NULL DEFAULT 'draft'  -- draft | pending_review | approved | superseded
);
```

**Rules:**
- A spec version is **immutable once approved**.
- All stories, tasks, and validations must reference `spec_version_id` explicitly.
- Never use "latest" or implicit version lookups.

#### 2) Controlled Compilation (No Auto-Recompile)

Modify Spec Authority to operate as a compiler tied to `spec_version_id`.

Add `CompiledSpecAuthority` table:
```sql
CREATE TABLE compiled_spec_authority (
    id INTEGER PRIMARY KEY,
    spec_version_id INTEGER NOT NULL REFERENCES spec_registry(spec_version_id),
    compiler_version TEXT NOT NULL,       -- Version of compilation logic
    prompt_hash TEXT NOT NULL,            -- Hash of LLM prompt for reproducibility
    compiled_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    scope_themes TEXT NOT NULL,           -- JSON array
    invariants TEXT NOT NULL,             -- JSON array
    eligible_feature_ids TEXT NOT NULL,   -- JSON array
    rejected_features TEXT,               -- JSON array of {feature_id, reason}
    spec_gaps TEXT                        -- JSON array of blocking gaps
);
```

**Rules:**
- If `spec_hash` changes, mark authority cache as `STALE`.
- **NEVER** auto-compile on mismatch.
- Require explicit command sequence: `approve spec vN` → `compile spec vN`.

#### 3) Deterministic Impact Analysis on Spec Change

On creation of a new spec version, generate `SpecImpactReport` (read-only):

```sql
CREATE TABLE spec_impact_reports (
    id INTEGER PRIMARY KEY,
    from_spec_version_id INTEGER NOT NULL REFERENCES spec_registry(spec_version_id),
    to_spec_version_id INTEGER NOT NULL REFERENCES spec_registry(spec_version_id),
    generated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    changes_summary TEXT NOT NULL,        -- JSON: what changed
    no_impact_story_ids TEXT NOT NULL,    -- JSON array
    needs_revalidation_story_ids TEXT NOT NULL,  -- JSON array
    needs_rewrite_story_ids TEXT NOT NULL,       -- JSON array
    blocking_story_ids TEXT NOT NULL,            -- JSON array
    recommended_actions TEXT NOT NULL     -- JSON array
);
```

**Classification per story:**
- `NO_IMPACT` — Story unaffected by changes
- `NEEDS_REVALIDATION` — Story should be re-checked
- `NEEDS_REWRITE` — Story conflicts with new spec
- `BLOCKING` — Story must stop work (IN_PROGRESS + breaking change)

**Rule:** No story or sprint state may change during impact analysis.

#### 4) Pinned Spec Semantics for Stories

Add `spec_version_id` field to `UserStory` (required):

```sql
ALTER TABLE user_stories ADD COLUMN accepted_spec_version_id INTEGER REFERENCES spec_registry(spec_version_id);
ALTER TABLE user_stories ADD COLUMN validation_evidence TEXT;  -- JSON
```

**Rules:**
- Stories are validated **ONLY** against their pinned `spec_version_id`.
- In-progress stories continue under their pinned spec version by default.
- Migrating a story to a new spec requires explicit action:
  - Command: `migrate story <id> to spec vN` → triggers re-validation.
  - If re-validation fails, migration is rejected.
  - Migration is logged with timestamp, old version, new version, rationale.

#### 5) Acceptance and Completion Evidence

Validation functions must accept `(story_id, spec_version_id)`.

Store validation evidence:
```python
class ValidationEvidence(BaseModel):
    spec_version_id: int
    validated_at: datetime
    rules_checked: List[str]       # Contract rules applied
    invariants_applied: List[str]  # Spec invariants checked
    passed: bool
    failures: List[Dict]           # {rule, expected, actual, message}
    warnings: List[str]
    validator_version: str
    input_hash: str                # Hash of story content at validation time
```

**Definition of Done must record:**
- `spec_version_id` used
- Validation evidence reference
- Note if newer spec exists and why it was not adopted

#### 6) Orchestrator Commands to Add

| Command | Type | Action |
|---------|------|--------|
| `review spec changes` | Read-only | Produce `SpecImpactReport` comparing current approved vs draft |
| `approve spec vN` | Write | Mark spec version as reviewed/approved |
| `compile spec vN` | Write | Generate `CompiledSpecAuthority` for approved spec |
| `revalidate story <id>` | Read-only | Run deterministic validation against pinned spec |
| `revalidate story <id> against spec vN` | Read-only | Run validation against specified spec version |
| `migrate story <id> to spec vN` | Write | Update pinned `spec_version_id` (requires re-validation pass) |

#### 7) Explicit Prohibitions

| Prohibited Pattern | Reason |
|--------------------|--------|
| ❌ "latest spec" lookups | Breaks traceability, causes silent behavioral drift |
| ❌ Automatic recompilation | Violates controlled change principle |
| ❌ Retroactive acceptance changes | Breaks audit trail, invalidates completed work |
| ❌ Silent story migration | Violates sprint stability guarantee |
| ❌ Acceptance without `spec_version_id` | Cannot trace which rules were applied |
| ❌ Validation against implicit version | All validation must be explicit |

---

**This change aligns spec authority with Scrum reality:** specs evolve, but execution remains stable, auditable, and explicitly controlled.

---

## Approval

- [ ] Phase 1 approach approved (Pipeline Simplification)
- [ ] Phase 2.1 approach approved (Spec Authority Compiler)
- [ ] Phase 2.2-2.4 approach approved (Spec Versioning & Review Workflow)
- [ ] Phase 3 approach approved (Sprint Framing)
- [ ] Phase 4 approach approved (Team Simulation - Advisory)
- [ ] Phase 5 approach approved (JIT Task Breakdown)
- [ ] Phase 6 approach approved (Serial Execution)

**Reviewer:** ________________  
**Date:** ________________
