# Response to Jules: Persona Enforcement Architecture

**Date:** January 25, 2026  
**RE:** Review-First Human-in-the-Loop Extraction Pipeline - Persona Drift Solution

---

## Summary

Jules, your analysis is **excellent** and demonstrates deep understanding of the problem. I agree with your core architectural direction but recommend some refinements based on:

1. Existing codebase patterns (alignment_checker.py, story pipeline architecture)
2. Avoiding over-engineering (no new agent needed)
3. Lessons from vision constraint enforcement (deterministic + LLM hybrid approach)

**Bottom line:** Your foundation is strong. Let's refine the implementation strategy to match our existing patterns and avoid unnecessary complexity.

---

## ✅ What I Fully Agree With

### 1. Deterministic Validation is Critical
**Jules' Position:** "Make persona correctness a hard invariant" with code-level enforcement.

**My Agreement:** ✅ Absolutely correct. LLM prompts alone have proven insufficient. We need deterministic guards similar to our vision `alignment_checker.py` module.

### 2. Database-Level Enforcement
**Jules' Proposal:** Add persona-related fields to database schema.

**My Agreement:** ✅ Yes, but with refinements (see below). Database schema changes enable queryability and enforcement at the data layer.

### 3. Product-Level Configuration for Extensibility
**Jules' Proposal:** Store persona whitelist per product for multi-product extensibility.

**My Agreement:** ✅ Correct strategic direction. Our system is designed for multiple products, and each may have different user personas.

### 4. Test-Driven Approach
**Jules' Plan:** Create test scripts with dummy "Review-First" product data.

**My Agreement:** ✅ Essential. Testing with synthetic data prevents breaking real datasets and validates the enforcement logic.

---

## 🔧 Recommended Refinements

### Refinement 1: Database Schema - Strategic About `persona` Column

**Jules' Proposal:**
```python
class UserStory:
    persona: str  # New dedicated field
```

**My Recommendation:** Add it, BUT as a **denormalized cache** for querying, not as the primary source of truth.

```python
class UserStory(SQLModel, table=True):
    # ... existing fields ...
    
    # NEW: Extracted persona (denormalized for fast querying/filtering)
    persona: Optional[str] = Field(
        default=None, 
        max_length=100, 
        index=True,
        description="Auto-extracted from description for querying. Source of truth is description field."
    )
    # ☝️ Auto-populated from "As a [persona], I want..." format
    # ☝️ Enables efficient queries: SELECT * WHERE persona = 'automation engineer'
    # ☝️ Kept in sync via ORM hook or validator
```

**Rationale:**
- **User story description** already contains persona: `"As a {persona}, I want..."`
- The `persona` column serves **query optimization** and **validation caching**
- Avoids data duplication issues (description and field out of sync)
- Single source of truth: description field (user stories are fundamentally text-based)
- Column is auto-populated via extraction function on save

**Implementation Pattern:**
```python
# In save operation (tools.py or db_tools.py)
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import extract_persona_from_story

user_story.description = "As an automation engineer, I want..."
user_story.persona = extract_persona_from_story(user_story.description)
# Result: user_story.persona = "automation engineer"
```

**Alternative (if you prefer strict duplication):** Make `persona` a required field and enforce consistency via database constraint/trigger. But this adds complexity without clear benefit over extraction approach.

---

### Refinement 2: Persona Registry - Normalized Table vs JSON

**Jules' Proposal:**
```python
class Product:
    valid_personas: str  # JSON field: ["automation engineer", "QA reviewer"]
```

**My Recommendation:** Use a **separate normalized table** for extensibility and metadata support:

```python
class ProductPersona(SQLModel, table=True):
    """Approved personas for a product with metadata."""
    __tablename__ = "product_personas"
    
    persona_id: int = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.product_id")
    persona_name: str = Field(max_length=100, nullable=False)
    is_default: bool = Field(default=False)  # Default persona for story generation
    category: str = Field(max_length=50)  # "primary_user", "admin", "platform"
    
    # Future extensibility:
    description: Optional[str] = Field(default=None, sa_type=Text)  # Role definition
    synonyms: Optional[str] = Field(default=None)  # JSON: ["control engineer", "automation engineer"]
    
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    product: "Product" = Relationship(back_populates="personas")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("product_id", "persona_name", name="unique_product_persona"),
    )


# Update Product model
class Product(SQLModel, table=True):
    # ... existing fields ...
    personas: List["ProductPersona"] = Relationship(back_populates="product")
```

**Rationale:**
- **Supports metadata** (defaults, synonyms, descriptions, categories)
- **Queryable** - `JOIN` for analytics, filtering by category
- **Auditable** - Track when personas were added/removed
- **Extensible** - Easy to add fields (e.g., `display_order`, `icon`, `permissions`)
- **Type-safe** - No JSON parsing errors
- **Future-proof** - Supports multi-tenant scenarios, persona hierarchies

**Example Usage:**
```python
# Seed personas for P&ID Review product
personas = [
    ProductPersona(
        product_id=1,
        persona_name="automation engineer",
        is_default=True,
        category="primary_user",
        description="Automation and control engineers performing P&ID review and extraction configuration"
    ),
    ProductPersona(
        product_id=1,
        persona_name="engineering QA reviewer",
        is_default=False,
        category="primary_user",
        description="Engineering QA reviewers performing mandatory validation and sign-off"
    ),
    ProductPersona(
        product_id=1,
        persona_name="IT administrator",
        is_default=False,
        category="admin",
        description="IT administrators managing deployment, security, and user permissions"
    ),
    ProductPersona(
        product_id=1,
        persona_name="ML engineer",
        is_default=False,
        category="platform",
        description="ML engineers training and tuning extraction models"
    ),
]
```

**Alternative for MVP Simplicity:** If you want to ship FAST and iterate later, JSON in `Product` table is acceptable. You can migrate to normalized table when you need >4 personas or metadata. **But if starting fresh, go with the table.**

---

### Refinement 3: PersonaGuard Agent - DON'T Create a New Agent

**Jules' Proposal:**
> "Should this be implemented as a separate 'PersonaGuard' agent/step inserted after the Draft Agent but before the INVEST Validator?"

**My Strong Recommendation:** ❌ **NO new agent**. Use **layered enforcement** in existing pipeline.

#### Why No New Agent?

1. **Your pipeline already has 3 sequential agents:**
   ```
   StoryDraftAgent → InvestValidatorAgent → StoryRefinerAgent
   ```
   Adding a 4th agent increases complexity and latency.

2. **Persona checking is deterministic** (regex extraction + whitelist check)
   - Agent communication overhead is wasteful for a simple validation
   - No LLM intelligence needed for this check
   - Code-level validation is faster and more testable

3. **Existing architecture already supports this pattern:**
   - `alignment_checker.py` enforces vision constraints deterministically
   - It's called in `tools.py` BEFORE pipeline runs (fail-fast)
   - Same pattern should apply to persona checking

4. **Testing complexity:**
   - New agent = new ADK session/state management
   - Deterministic function = simple unit test

#### Recommended Architecture: Layered Enforcement

```
┌─────────────────────────────────────────────────────────────────┐
│ Layer 1: Prompt Hardening (StoryDraftAgent)                    │
│ → Instructions emphasize MANDATORY persona usage                │
│ → "DO NOT substitute persona with generic roles"                │
│ → Cost: Prompt tokens (minimal)                                 │
│ → Effectiveness: 70-80% (LLMs still drift)                      │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 2: LLM Validation (InvestValidatorAgent - EXTENDED)      │
│ → Add persona_alignment field to ValidationResult               │
│ → Validator checks: extracted persona vs required persona       │
│ → Provides feedback for refinement loop                         │
│ → Cost: Already running, just extended output schema            │
│ → Effectiveness: 85-90% (catches most drift)                    │
└─────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────┐
│ Layer 3: Deterministic Guard (persona_checker.py)              │
│ → After pipeline completes, BEFORE database save                │
│ → Code-level validation + auto-correction                       │
│ → FAIL-FAST if persona not in whitelist                         │
│ → Cost: Negligible (regex + dict lookup)                        │
│ → Effectiveness: 100% (hard invariant)                          │
│ → Location: tools.py around line 230                            │
└─────────────────────────────────────────────────────────────────┘
```

#### Implementation Location (Existing Code)

**File:** `orchestrator_agent/agent_tools/story_pipeline/tools.py`  
**Function:** `process_feature_for_stories()`  
**Line:** ~230 (after pipeline completes, before UserStory creation)

```python
# tools.py - Around line 230 (after pipeline, before DB save)

from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    validate_persona,
    auto_correct_persona,
    extract_persona_from_story,
)

# Extract refined story from pipeline state
refined_story = json.loads(state.get("refinement_result", "{}"))

# ============================================
# LAYER 3: Deterministic Persona Enforcement
# ============================================
persona_check = validate_persona(
    story_description=refined_story['description'],
    required_persona=story_input.user_persona,
    allow_synonyms=True  # "control engineer" = "automation engineer"
)

if not persona_check.is_valid:
    print(f"⚠️  Persona violation detected: {persona_check.violation_message}")
    
    # Attempt auto-correction (simple text substitution)
    refined_story = auto_correct_persona(
        refined_story, 
        story_input.user_persona
    )
    print(f"✅ Auto-corrected persona to: {story_input.user_persona}")
    
    # Re-validate after correction
    recheck = validate_persona(
        refined_story['description'], 
        story_input.user_persona
    )
    
    if not recheck.is_valid:
        # Auto-correction failed - FAIL HARD
        raise ValueError(
            f"PERSONA ENFORCEMENT FAILED: Story could not be corrected to use required persona.\n"
            f"  Required: '{story_input.user_persona}'\n"
            f"  Found: '{persona_check.extracted_persona}'\n"
            f"  Story: {refined_story['description'][:100]}..."
        )

# Extract persona to UserStory.persona field (for querying)
extracted_persona = extract_persona_from_story(refined_story['description'])

# Later in UserStory creation:
user_story = UserStory(
    description=refined_story['description'],
    persona=extracted_persona,  # Auto-populated
    # ... other fields
)
```

**Why this location?**
- Pipeline has completed (all LLM refinement done)
- Before database persistence (can reject/correct before save)
- Natural checkpoint for deterministic validation
- Matches existing pattern (alignment_checker is called in same file)

---

### Refinement 4: Repair Strategy - Hybrid Approach

**Jules' Question:**
> "Should automatic correction be in PersonaGuard or Refinement Agent?"

**My Recommendation:** **Both, strategically placed for efficiency:**

#### Strategy A: Deterministic Repair First (90% of cases)

**Location:** Post-processing in `tools.py` (Layer 3 above)  
**Method:** `persona_checker.auto_correct_persona()`  
**Handles:**
- Simple persona substitution: `"data annotator" → "automation engineer"`
- No LLM call needed
- Fast, predictable, testable

**Example:**
```python
# Input:  "As a software engineer, I want to configure extraction rules..."
# Output: "As an automation engineer, I want to configure extraction rules..."
# Cost: ~0.001ms (regex replace)
```

#### Strategy B: LLM-Assisted Repair (10% of complex cases)

**Location:** Refinement loop (Layer 2 - INVEST Validator feedback)  
**Trigger:** When deterministic correction fails or story needs rewriting  
**Method:** Extend `InvestValidatorAgent` to detect persona violations and provide feedback

**Example:**
```python
# InvestValidatorAgent detects:
# "Story uses 'data scientist' but should use 'automation engineer'"
# 
# StoryRefinerAgent receives feedback and rewrites:
# OLD: "As a data scientist, I want to train models to detect P&ID symbols..."
# NEW: "As an ML engineer, I want to train models to detect P&ID symbols..."
# (Correctly identifies ML context, uses approved 'ML engineer' persona)
```

**When to use LLM repair:**
- Story mixes multiple personas (split needed)
- Wrong persona + wrong context (needs semantic understanding)
- Acceptance criteria also reference wrong persona

**Implementation:**
```python
# In InvestValidatorAgent output (extend ValidationResult)
class PersonaAlignment(BaseModel):
    is_correct: bool
    expected_persona: str
    actual_persona: Optional[str]
    issues: list[str] = []

class ValidationResult(BaseModel):
    # ... existing fields ...
    persona_alignment: PersonaAlignment  # NEW

# Validator detects mismatch and provides feedback
# Refiner applies correction in next iteration
# Deterministic guard verifies final result
```

---

## 📋 Revised Implementation Plan

### Phase 1: Foundation (Week 1 - Day 1-2, ~4 hours)

**Task 1.1: Database Schema Updates**

File: `agile_sqlmodel.py`

```python
# Add to UserStory model (around line 200)
class UserStory(SQLModel, table=True):
    # ... existing fields ...
    
    # NEW: Persona field (auto-extracted from description)
    persona: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        description="Extracted from 'As a [persona], I want...' format"
    )

# Add new ProductPersona table (after Product model)
class ProductPersona(SQLModel, table=True):
    """Approved personas for a product."""
    __tablename__ = "product_personas"
    
    persona_id: int = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.product_id")
    persona_name: str = Field(max_length=100, nullable=False)
    is_default: bool = Field(default=False)
    category: str = Field(max_length=50, default="primary_user")
    description: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    product: "Product" = Relationship(back_populates="personas")
    
    # Constraints
    __table_args__ = (
        UniqueConstraint("product_id", "persona_name", name="unique_product_persona"),
    )

# Update Product model
class Product(SQLModel, table=True):
    # ... existing fields ...
    personas: List["ProductPersona"] = Relationship(back_populates="product")
```

**Task 1.2: Persona Checker Module**

✅ **Already implemented:** `orchestrator_agent/agent_tools/story_pipeline/persona_checker.py`

Key functions:
- `extract_persona_from_story()` - Parse from description
- `validate_persona()` - Check against required persona
- `auto_correct_persona()` - Automated substitution
- `are_personas_equivalent()` - Synonym matching

**Task 1.3: Seed Persona Registry**

File: `tools/db_tools.py` (or wherever product creation happens)

```python
def seed_product_personas(product_id: int, db: Session):
    """
    Seed default personas for Review-First product.
    Call this after product creation.
    """
    DEFAULT_PERSONAS = [
        {
            "name": "automation engineer",
            "is_default": True,
            "category": "primary_user",
            "description": "Automation and control engineers performing P&ID review and extraction configuration"
        },
        {
            "name": "engineering QA reviewer",
            "is_default": False,
            "category": "primary_user",
            "description": "Engineering QA reviewers performing mandatory validation and sign-off"
        },
        {
            "name": "IT administrator",
            "is_default": False,
            "category": "admin",
            "description": "IT administrators managing deployment, security, and user permissions"
        },
        {
            "name": "ML engineer",
            "is_default": False,
            "category": "platform",
            "description": "ML engineers training and tuning extraction models"
        },
    ]
    
    for persona_data in DEFAULT_PERSONAS:
        persona = ProductPersona(
            product_id=product_id,
            persona_name=persona_data["name"],
            is_default=persona_data["is_default"],
            category=persona_data["category"],
            description=persona_data["description"]
        )
        db.add(persona)
    
    db.commit()
```

---

### Phase 2: Validation Layer (Week 1 - Day 2-3, ~3 hours)

**Task 2.1: Extend INVEST Validator Schema**

File: `orchestrator_agent/agent_tools/story_pipeline/invest_validator_agent/agent.py`

```python
# Add new schema (around line 40)
class PersonaAlignment(BaseModel):
    """Persona correctness check result."""
    is_correct: bool = Field(..., description="True if story uses the required persona")
    expected_persona: str = Field(..., description="The persona that should be used")
    actual_persona: Optional[str] = Field(None, description="The persona extracted from story")
    issues: list[str] = Field(default_factory=list, description="Persona mismatch details (empty if correct)")

# Update ValidationResult (around line 55)
class ValidationResult(BaseModel):
    # ... existing fields ...
    persona_alignment: PersonaAlignment = Field(
        ..., 
        description="Persona correctness validation result"
    )
```

**Task 2.2: Update INVEST Validator Instructions**

File: Same file, update `INVEST_VALIDATOR_INSTRUCTION` string

```python
# Add this section to the instruction (around line 100):

## 4. PERSONA ALIGNMENT (CRITICAL)

### Persona Extraction
Extract the persona from the story description using this pattern:
- Format: "As a [PERSONA], I want..."
- The [PERSONA] MUST exactly match the `user_persona` field provided in state

### Persona Validation Rules
- **EXACT MATCH** (case-insensitive): "automation engineer" = "Automation Engineer" ✅
- **SYNONYM MATCH**: "control engineer" = "automation engineer" ✅ (acceptable)
- **GENERIC SUBSTITUTION**: "software engineer" when "automation engineer" required ❌ VIOLATION
- **VAGUE PERSONA**: "user" when specific persona exists ❌ VIOLATION
- **MISSING PERSONA**: Story doesn't follow "As a [persona]" format ❌ VIOLATION

### Common Violations to Flag
- Story uses generic task-based persona:
  - "data annotator" (should be: automation engineer)
  - "software engineer" (should be: automation engineer)
  - "frontend developer" (should be: automation engineer)
  - "QA engineer" (should be: engineering QA reviewer)
  - "data scientist" (should be: ML engineer OR automation engineer)
- Story uses "user" or "customer" when specific persona provided
- Persona is missing entirely from description

### Output Format
Always populate the `persona_alignment` field in your response:
```json
{
  "persona_alignment": {
    "is_correct": true,  // or false
    "expected_persona": "automation engineer",
    "actual_persona": "automation engineer",  // or what you found
    "issues": []  // or ["Persona mismatch: expected 'automation engineer', found 'data annotator'"]
  }
}
```

### Impact on is_valid
A persona violation is a CRITICAL issue:
- If persona_alignment.is_correct = false, then is_valid MUST be false
- Even if INVEST scores are high (90+), wrong persona = invalid story
```

---

### Phase 3: Deterministic Enforcement (Week 1 - Day 3-4, ~2 hours)

**Task 3.1: Integrate Deterministic Guard**

File: `orchestrator_agent/agent_tools/story_pipeline/tools.py`

Location: In `process_feature_for_stories()` function, after pipeline completes (around line 230)

```python
# Add imports at top of file
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    validate_persona,
    auto_correct_persona,
    extract_persona_from_story,
)

# In process_feature_for_stories(), after pipeline completes:
# (Around line 230, after extracting refinement_result from state)

# --- Extract refined story from state ---
refinement_result = state.get("refinement_result")
if not refinement_result:
    raise ValueError("Pipeline did not produce refinement_result")

refined_story = json.loads(refinement_result) if isinstance(refinement_result, str) else refinement_result

# ============================================
# DETERMINISTIC PERSONA ENFORCEMENT (Layer 3)
# ============================================
print(f"{CYAN}[Persona Guard] Validating persona...{RESET}")

persona_check = validate_persona(
    story_description=refined_story['description'],
    required_persona=story_input.user_persona,
    allow_synonyms=True
)

if not persona_check.is_valid:
    print(f"{YELLOW}⚠️  Persona violation: {persona_check.violation_message}{RESET}")
    
    # Attempt auto-correction
    refined_story = auto_correct_persona(refined_story, story_input.user_persona)
    print(f"{GREEN}✅ Auto-corrected persona to: {story_input.user_persona}{RESET}")
    
    # Re-validate
    recheck = validate_persona(refined_story['description'], story_input.user_persona)
    if not recheck.is_valid:
        raise ValueError(
            f"PERSONA ENFORCEMENT FAILED: Story could not be corrected.\n"
            f"  Required: '{story_input.user_persona}'\n"
            f"  Found: '{persona_check.extracted_persona}'\n"
            f"  Story: {refined_story['description'][:150]}..."
        )

print(f"{GREEN}✅ Persona validation passed: {story_input.user_persona}{RESET}")

# Extract persona for UserStory.persona field
extracted_persona = extract_persona_from_story(refined_story['description'])

# Later when creating UserStory object:
user_story = UserStory(
    # ... existing fields ...
    description=refined_story['description'],
    persona=extracted_persona,  # NEW: Auto-populated
    # ...
)
```

**Task 3.2: Update Story Draft Agent Prompt**

File: `orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py`

Update `STORY_DRAFT_INSTRUCTION` (around line 30):

```python
# Replace this section:
# - `user_persona`: The target user persona (e.g., "junior frontend developer")

# With this:
# - `user_persona`: The MANDATORY target user persona. The story MUST use this exact persona in the description.

# Add new section after input description:

# ⚠️ CRITICAL PERSONA ENFORCEMENT RULES
The `user_persona` field is MANDATORY and NON-NEGOTIABLE:
1. Use the exact persona in "As a {user_persona}, I want..." format
2. DO NOT substitute with generic roles even if the feature involves:
   - UI interaction → Still use provided persona, NOT "frontend developer"
   - Configuration → Still use provided persona, NOT "software engineer"
   - Data validation → Still use provided persona, NOT "data annotator"
   - Review workflows → Still use provided persona, NOT "QA engineer"
3. DO NOT generalize to "user" or "customer" unless that's the actual persona provided
4. The persona reflects WHO uses the feature, not WHAT the feature does
5. If persona is "automation engineer", they may perform UI work, config, validation, AND review tasks

WRONG EXAMPLES:
- Provided: "automation engineer" → Story uses: "software engineer" ❌
- Provided: "automation engineer" → Story uses: "data annotator" ❌
- Provided: "engineering QA reviewer" → Story uses: "QA engineer" ❌

CORRECT EXAMPLE:
- Provided: "automation engineer" → Story uses: "automation engineer" ✅
```

---

### Phase 4: Testing & Validation (Week 2 - Day 1-2, ~3 hours)

**Task 4.1: Unit Tests for Persona Checker**

File: `tests/test_persona_checker.py` (NEW)

```python
import pytest
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    extract_persona_from_story,
    validate_persona,
    auto_correct_persona,
    are_personas_equivalent,
)

def test_extract_persona_standard_format():
    """Test persona extraction from standard format."""
    description = "As an automation engineer, I want to configure rules so that extraction is accurate."
    result = extract_persona_from_story(description)
    assert result == "automation engineer"

def test_extract_persona_with_article_a():
    """Test extraction with 'a' article."""
    description = "As a software engineer, I want to deploy the system..."
    result = extract_persona_from_story(description)
    assert result == "software engineer"

def test_validate_persona_correct():
    """Test validation with correct persona."""
    description = "As an automation engineer, I want..."
    result = validate_persona(description, "automation engineer")
    assert result.is_valid == True
    assert result.violation_message is None

def test_validate_persona_mismatch():
    """Test validation detects persona mismatch."""
    description = "As a data annotator, I want to label symbols..."
    result = validate_persona(description, "automation engineer")
    assert result.is_valid == False
    assert "data annotator" in result.violation_message
    assert result.corrected_description is not None

def test_auto_correct_persona():
    """Test automatic persona correction."""
    story = {
        "description": "As a software engineer, I want to configure rules...",
        "title": "Configure extraction rules"
    }
    corrected = auto_correct_persona(story, "automation engineer")
    assert "automation engineer" in corrected["description"]
    assert "software engineer" not in corrected["description"]

def test_persona_synonyms():
    """Test synonym matching."""
    assert are_personas_equivalent("automation engineer", "control engineer") == True
    assert are_personas_equivalent("automation engineer", "data scientist") == False
```

**Task 4.2: Integration Test with Full Pipeline**

File: `tests/test_persona_enforcement_integration.py` (NEW)

```python
import pytest
import asyncio
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput, process_feature_for_stories
from agile_sqlmodel import Product, ProductPersona, engine
from sqlmodel import Session, select

@pytest.fixture
def review_first_product(db_session):
    """Create Review-First product with persona whitelist."""
    product = Product(
        product_name="Review-First P&ID Extraction",
        vision="AI-powered P&ID review tool for automation engineers"
    )
    db_session.add(product)
    db_session.commit()
    db_session.refresh(product)
    
    # Add approved personas
    personas = [
        ProductPersona(product_id=product.product_id, persona_name="automation engineer", is_default=True, category="primary_user"),
        ProductPersona(product_id=product.product_id, persona_name="engineering QA reviewer", is_default=False, category="primary_user"),
        ProductPersona(product_id=product.product_id, persona_name="IT administrator", is_default=False, category="admin"),
        ProductPersona(product_id=product.product_id, persona_name="ML engineer", is_default=False, category="platform"),
    ]
    for p in personas:
        db_session.add(p)
    db_session.commit()
    
    return product

@pytest.mark.asyncio
async def test_persona_drift_prevented_ui_feature(review_first_product):
    """Ensure UI features don't drift to 'frontend developer' persona."""
    story_input = ProcessStoryInput(
        product_id=review_first_product.product_id,
        product_name=review_first_product.product_name,
        product_vision=review_first_product.vision,
        feature_id=1,
        feature_title="Interactive P&ID annotation interface",
        theme="Core Extraction",
        epic="Review Workflow",
        user_persona="automation engineer",  # Explicitly provided
        time_frame="Now",
    )
    
    result = await process_feature_for_stories(story_input)
    
    # Validate persona enforcement
    assert "automation engineer" in result['description'].lower()
    assert "frontend developer" not in result['description'].lower()
    assert "software engineer" not in result['description'].lower()
    assert result.get('persona') == "automation engineer"

@pytest.mark.asyncio
async def test_persona_drift_prevented_config_feature(review_first_product):
    """Ensure config features don't drift to 'software engineer' persona."""
    story_input = ProcessStoryInput(
        product_id=review_first_product.product_id,
        product_name=review_first_product.product_name,
        product_vision=review_first_product.vision,
        feature_id=2,
        feature_title="Configure extraction rule templates",
        theme="Configuration",
        epic="Rule Management",
        user_persona="automation engineer",
        time_frame="Now",
    )
    
    result = await process_feature_for_stories(story_input)
    
    assert "automation engineer" in result['description'].lower()
    assert "software engineer" not in result['description'].lower()
    assert result.get('persona') == "automation engineer"

@pytest.mark.asyncio
async def test_persona_whitelist_enforced(review_first_product):
    """Ensure only approved personas are allowed."""
    story_input = ProcessStoryInput(
        product_id=review_first_product.product_id,
        product_name=review_first_product.product_name,
        product_vision=review_first_product.vision,
        feature_id=3,
        feature_title="Export validation reports",
        theme="Reporting",
        epic="Export",
        user_persona="random engineer",  # NOT in whitelist
        time_frame="Now",
    )
    
    # Should raise ValueError during persona validation
    with pytest.raises(ValueError, match="Persona.*not approved"):
        await process_feature_for_stories(story_input)
```

**Task 4.3: Manual Validation with Dummy Product**

File: `scripts/test_persona_enforcement.py` (NEW)

```python
"""
Manual test script for persona enforcement.
Seeds a dummy Review-First product and generates test stories.
"""
import asyncio
from sqlmodel import Session, select
from agile_sqlmodel import Product, ProductPersona, engine
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput, process_feature_for_stories

async def main():
    # Create test product
    with Session(engine) as session:
        product = Product(
            product_name="Review-First P&ID Extraction (TEST)",
            vision="AI-powered P&ID review tool for automation and control engineers"
        )
        session.add(product)
        session.commit()
        session.refresh(product)
        
        # Seed personas
        personas_data = [
            ("automation engineer", True, "primary_user"),
            ("engineering QA reviewer", False, "primary_user"),
            ("IT administrator", False, "admin"),
            ("ML engineer", False, "platform"),
        ]
        
        for name, is_default, category in personas_data:
            persona = ProductPersona(
                product_id=product.product_id,
                persona_name=name,
                is_default=is_default,
                category=category
            )
            session.add(persona)
        session.commit()
        
        print(f"✅ Created test product: {product.product_name} (ID: {product.product_id})")
        print(f"   Approved personas: {[p[0] for p in personas_data]}")
        
        # Test features that commonly cause drift
        test_features = [
            {
                "title": "Interactive P&ID annotation UI",
                "theme": "Review Workflow",
                "epic": "Annotation",
                "expected_drift": "frontend developer"
            },
            {
                "title": "Configure extraction rule templates",
                "theme": "Configuration",
                "epic": "Rules",
                "expected_drift": "software engineer"
            },
            {
                "title": "Validate extraction accuracy metrics",
                "theme": "Quality Control",
                "epic": "Validation",
                "expected_drift": "QA engineer"
            },
            {
                "title": "Label training dataset for model improvement",
                "theme": "ML Pipeline",
                "epic": "Training",
                "expected_drift": "data annotator"
            },
        ]
        
        print(f"\n{'='*60}")
        print("PERSONA ENFORCEMENT TEST")
        print(f"{'='*60}\n")
        
        for i, feature in enumerate(test_features, 1):
            print(f"Test {i}/4: {feature['title']}")
            print(f"  Expected drift risk: '{feature['expected_drift']}'")
            
            story_input = ProcessStoryInput(
                product_id=product.product_id,
                product_name=product.product_name,
                product_vision=product.vision,
                feature_id=i,
                feature_title=feature['title'],
                theme=feature['theme'],
                epic=feature['epic'],
                user_persona="automation engineer",  # Always require this
                time_frame="Now",
            )
            
            try:
                result = await process_feature_for_stories(story_input)
                
                # Check if persona was enforced
                description_lower = result['description'].lower()
                if "automation engineer" in description_lower:
                    print(f"  ✅ PASS - Persona enforced correctly")
                else:
                    print(f"  ❌ FAIL - Persona drift detected!")
                    print(f"     Description: {result['description'][:100]}...")
                
                # Check for drift persona
                if feature['expected_drift'].lower() in description_lower:
                    print(f"  ❌ FAIL - Found drift persona '{feature['expected_drift']}'")
                
            except Exception as e:
                print(f"  ❌ ERROR: {str(e)[:100]}")
            
            print()

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 🚨 Edge Cases to Watch

### 1. Synonym Handling
**Issue:** "control engineer" vs "automation engineer"  
**Solution:** `are_personas_equivalent()` function with synonym registry  
**Config:** Update `PERSONA_SYNONYMS` dict in persona_checker.py

### 2. Capitalization Variations
**Issue:** "Automation Engineer" vs "automation engineer"  
**Solution:** Normalize to lowercase for comparison  
**Already handled:** `normalize_persona()` function

### 3. Plural Forms
**Issue:** "automation engineers" (plural)  
**Solution:** Strip trailing 's' in extraction regex or normalize  
**Todo:** Update `PERSONA_PATTERN` regex if needed

### 4. Article Choice (a vs an)
**Issue:** "As a automation engineer" (grammatically incorrect)  
**Solution:** Auto-select article based on first letter vowel  
**Already handled:** `auto_correct_persona()` checks first letter

### 5. Multi-Word Personas
**Issue:** "engineering QA reviewer" (3 words with spaces)  
**Solution:** Regex must capture until comma, not just one word  
**Already handled:** `[^,]+` in regex captures multiple words

### 6. Legacy Stories Without Persona Field
**Issue:** Existing stories in DB don't have `persona` column  
**Solution:** Backfill migration or populate on first read  
**Migration script:**
```python
# scripts/migrate_persona_field.py
with Session(engine) as session:
    stories = session.exec(select(UserStory).where(UserStory.persona == None)).all()
    for story in stories:
        story.persona = extract_persona_from_story(story.description)
    session.commit()
```

### 7. Empty Persona Whitelist
**Issue:** Product has no personas defined in registry  
**Solution:** Fall back to global defaults or block story generation  
**Recommendation:**
```python
def get_approved_personas(product_id, session):
    personas = session.exec(
        select(ProductPersona.persona_name)
        .where(ProductPersona.product_id == product_id)
    ).all()
    
    if not personas:
        # Fallback to global defaults
        return ["automation engineer", "engineering QA reviewer"]
    
    return list(personas)
```

### 8. Persona Validation During Editing
**Issue:** User manually edits story description and changes persona  
**Solution:** Re-validate persona on story update operations  
**Implementation:** Add validation hook in story update endpoint/function

### 9. Multi-Persona Stories (Edge Case)
**Issue:** Story involves multiple personas (rare but possible)  
**Example:** "As an automation engineer, I want to submit P&IDs for QA reviewer approval..."  
**Solution:** Primary persona is in "As a [X]" clause, secondary mentioned in benefit  
**Validation:** Only validate primary persona in standard format

### 10. Context-Dependent Persona Selection
**Issue:** Same feature type needs different personas based on context  
**Example:** "Train ML model" → "ML engineer" vs "Review training data" → "automation engineer"  
**Solution:** Implement feature-to-persona mapping rules (Tier 3 - optional)  
**For MVP:** Require caller to specify correct persona explicitly

---

## 🎯 Success Metrics

Track these after implementation:

1. **Persona Accuracy Rate:**  
   `(Stories with correct persona / Total stories) × 100`  
   **Target:** 98%+ (before implementation: likely 60-70%)

2. **Auto-Correction Success Rate:**  
   `(Stories fixed by auto_correct / Stories with violations) × 100`  
   **Target:** 90%+ (simple substitutions should succeed)

3. **Pipeline Rejection Rate:**  
   `(Stories rejected for persona violations / Total stories) × 100`  
   **Target:** <2% (most should pass after LLM refinement + auto-correct)

4. **Validation Layer Effectiveness:**
   - Layer 1 (Prompts): % of stories generated correctly on first draft
   - Layer 2 (Validator): % of violations caught by INVEST agent
   - Layer 3 (Guard): % requiring deterministic correction

5. **Stakeholder Feedback:**  
   Qualitative: Do sprint planning participants understand story personas?  
   **Measure:** Survey after 2 weeks of using enforced personas

---

## 📊 Implementation Timeline

| Week | Phase | Hours | Deliverables |
|------|-------|-------|--------------|
| Week 1, Day 1-2 | Phase 1: Foundation | 4h | ✅ DB schema + persona_checker.py + registry seeding |
| Week 1, Day 2-3 | Phase 2: Validation | 3h | ✅ INVEST validator extension + prompt updates |
| Week 1, Day 3-4 | Phase 3: Enforcement | 2h | ✅ Deterministic guard in tools.py |
| Week 2, Day 1-2 | Phase 4: Testing | 3h | ✅ Unit tests + integration tests + manual validation |
| **Total** | **All Phases** | **~12h** | **Production-ready persona enforcement** |

---

## 💡 Final Recommendations

### What to Do First (Priority Order)

1. **Add database schema** (ProductPersona table + UserStory.persona field)
2. **Integrate persona_checker.py into tools.py** (deterministic guard - highest ROI)
3. **Extend INVEST validator** (persona_alignment field)
4. **Update prompts** (story draft agent persona rules)
5. **Write tests** (validate enforcement works)
6. **Seed persona registry** for Review-First product

### What to Skip for MVP

- ❌ Feature-to-persona mapping rules (Tier 3 - complex, low value for 4 personas)
- ❌ Persona synonyms beyond basic ones (can add incrementally)
- ❌ Persona metadata (descriptions, icons) - add when needed
- ❌ Multi-persona story support - defer until real use case appears

### What to Document

- ✅ Approved persona list in Product README
- ✅ How to add new personas to registry (for future products)
- ✅ Persona selection guidelines (when to use each persona)
- ✅ Migration guide for existing stories (if needed)

---

## ✅ Conclusion

Jules, your architectural direction is **sound and well-reasoned**. The refinements I'm suggesting are about:

1. **Leveraging existing patterns** (alignment_checker.py, layered validation)
2. **Avoiding over-engineering** (no new agent, deterministic-first approach)
3. **Future-proofing** (normalized table vs JSON, extensible schema)

**The core insight is correct:** Persona enforcement needs to be a **hard invariant**, not a soft suggestion. The implementation plan above gives you a production-ready solution in ~12 hours of focused work.

**I've already provided:**
- ✅ `persona_checker.py` - Complete deterministic validation module
- ✅ `fix_persona_drift.py` - Batch remediation script for existing stories
- ✅ `PERSONA_DRIFT_ANALYSIS.md` - Comprehensive architecture documentation

**You need to add:**
- Database schema changes (ProductPersona table, UserStory.persona field)
- Integration points (tools.py, invest_validator_agent.py)
- Test suite (validate enforcement works end-to-end)

Let me know if you want me to implement any of these phases directly. I can start with Phase 1 (database schema + integration) if you're ready to proceed.

---

**Ready to implement?** Let's start with Phase 1 and get the foundation in place.
