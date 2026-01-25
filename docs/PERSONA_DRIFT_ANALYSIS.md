# Persona Drift in Story Generation - Analysis & Solutions

**Date:** January 25, 2026  
**Product:** Review-First Human-in-the-Loop Extraction Pipeline (P&ID Review Tool)  
**Issue:** Story generation produces generic/incorrect personas despite correct feature scope

---

## Executive Summary

**Problem:** Story pipeline generates user stories with generic personas ("data annotator", "software engineer", "frontend developer") instead of domain-specific personas ("automation engineer", "engineering QA reviewer") for internal engineering tools.

**Root Cause:** Persona is treated as a soft suggestion rather than an enforced constraint. The INVEST validator validates 6 dimensions but NOT persona correctness. LLM training bias defaults to task-based personas for UI/config/validation features.

**Impact:** Stories are technically correct (features, ACs, scope) but use wrong user voice, causing confusion in sprint planning and stakeholder communication.

**Recommended Solution:** 3-tier approach combining prompt hardening, validation extension, and deterministic enforcement.

---

## Root Cause Analysis

### 1. Architectural Gaps

#### 1.1 Persona is "Suggested" Not "Enforced"
- **Current Flow:** `user_persona` parameter → passed to story draft agent → LLM ignores or overrides
- **No Validation:** INVEST validator checks 6 dimensions (Independent, Negotiable, Valuable, Estimable, Small, Testable) but NOT persona correctness
- **No Deterministic Check:** No code-level verification that final story uses provided persona

#### 1.2 LLM Training Bias Toward Generic Personas
When features involve:
- **UI Interaction** → defaults to "frontend developer" or "software engineer"
- **Configuration/Settings** → defaults to "system administrator" or "DevOps engineer"
- **Data Validation/Review** → defaults to "data annotator" or "data scientist"
- **Audit/Compliance** → defaults to "compliance officer" or "QA engineer"

The LLM lacks training data for **domain-specific engineering tools** where automation engineers perform ALL these activities.

#### 1.3 Vision `target_user` Not Propagated
- `VisionComponents.target_user` exists in schema (e.g., "automation engineers")
- Vision alignment checker enforces **capability constraints** (mobile-only, offline-first)
- But vision persona is **never enforced** in story generation pipeline

#### 1.4 No Persona Registry or Validation Rules
- No approved persona whitelist
- No role-to-feature mapping (e.g., "UI review features → automation engineer, not frontend developer")
- No deterministic persona substitution rules

---

## Why Engineering Tools Are Particularly Vulnerable

Generic consumer apps have clear persona boundaries:
- "User" = end consumer
- "Admin" = IT administrator
- "Developer" = software team

Engineering tools collapse these boundaries:
- Automation engineer = **performs review** (not "annotates data")
- Automation engineer = **configures extraction rules** (not "develops software")
- QA reviewer = **validates outputs** (not generic "QA engineer")
- ML engineer = **trains models** (separate persona, but rare in stories)

LLMs trained on consumer software patterns don't recognize this domain-specific persona consolidation.

---

## Systemic Improvements - Three Tiers

### **Tier 1: Immediate Fixes (No Architecture Changes)**

#### 1.1 Strengthen Story Draft Agent Prompt

**Current Instruction (Line 38):**
```
- `user_persona`: The target user persona (e.g., "junior frontend developer")
```

**Recommended Change:**
```
- `user_persona`: The MANDATORY target user persona. The story MUST use this exact persona in the description. DO NOT substitute with generic roles like "user", "developer", or "software engineer" even if the feature involves UI, configuration, or data work.

PERSONA ENFORCEMENT RULES:
- Use the provided persona verbatim: "As a {user_persona}, I want..."
- DO NOT generalize to task-based personas (data annotator, frontend dev, QA engineer)
- DO NOT assume domain knowledge - if persona is "automation engineer", they may perform UI work, data validation, configuration, AND review tasks
- The persona reflects WHO uses the feature, not WHAT the feature does
```

#### 1.2 Add Persona Validation to INVEST Validator

**Extend `ValidationResult` schema:**
```python
class PersonaAlignment(BaseModel):
    """Persona correctness check."""
    is_correct: bool = Field(..., description="True if story uses the required persona")
    expected_persona: str = Field(..., description="The persona that should be used")
    actual_persona: Optional[str] = Field(None, description="The persona extracted from story description")
    issues: list[str] = Field(default_factory=list, description="Persona mismatch details")

class ValidationResult(BaseModel):
    # ... existing fields ...
    persona_alignment: PersonaAlignment = Field(..., description="Persona correctness check")
```

**Add validation logic:**
```python
# In INVEST_VALIDATOR_INSTRUCTION:
## 4. PERSONA ALIGNMENT (CRITICAL)

Extract the persona from the story description:
- Format: "As a [PERSONA], I want..."
- The [PERSONA] MUST exactly match the `user_persona` provided in state

### Persona Violations (CRITICAL ISSUES):
- Story uses generic persona when specific persona was provided
- Story substitutes task-based persona (e.g., "frontend developer" when "automation engineer" was required)
- Story uses "user" or "customer" when a specific persona exists

Example INVALID:
- Required: "automation engineer"
- Story: "As a software engineer, I want..." → VIOLATION
- Story: "As a user, I want..." → VIOLATION

Example VALID:
- Required: "automation engineer"
- Story: "As an automation engineer, I want..." → CORRECT
```

**Update validation threshold:**
```python
is_valid = (
    validation_score >= 70 
    AND no_critical_issues 
    AND time_frame_aligned 
    AND persona_alignment.is_correct  # NEW
)
```

#### 1.3 Strengthen Story Refiner Persona Rules

Add explicit persona correction logic:
```python
# In STORY_REFINER_INSTRUCTION:
## Persona Correction (Priority 1)
If validation_result.persona_alignment.is_correct == False:
1. Extract expected_persona from validation_result
2. Replace the persona in the description with expected_persona
3. DO NOT change any other part of the story
4. Ensure format: "As a {expected_persona}, I want [original action] so that [original benefit]."

Example:
- Original: "As a data annotator, I want to mark regions on P&IDs so that..."
- Expected Persona: "automation engineer"
- Corrected: "As an automation engineer, I want to mark regions on P&IDs so that..."
```

---

### **Tier 2: Deterministic Enforcement (Code-Level Validation)**

#### 2.1 Create Persona Checker Module

Similar to `alignment_checker.py` for vision constraints, create `persona_checker.py`:

```python
# orchestrator_agent/agent_tools/story_pipeline/persona_checker.py
"""
Deterministic persona enforcement for story generation.

Extracts persona from story description and validates against required persona.
Provides automated correction for simple mismatches.
"""

import re
from dataclasses import dataclass
from typing import Optional

@dataclass
class PersonaCheckResult:
    """Result of persona validation."""
    is_valid: bool
    required_persona: str
    extracted_persona: Optional[str]
    violation_message: Optional[str]
    corrected_description: Optional[str]  # Auto-corrected if simple substitution

# Regex to extract persona from user story description
PERSONA_PATTERN = r'^As (?:a|an)\s+([^,]+),\s+I want'

def extract_persona_from_story(description: str) -> Optional[str]:
    """Extract persona from 'As a [persona], I want...' format."""
    match = re.match(PERSONA_PATTERN, description.strip(), re.IGNORECASE)
    return match.group(1).strip() if match else None

def validate_persona(
    story_description: str,
    required_persona: str,
    allow_synonyms: bool = False
) -> PersonaCheckResult:
    """
    Validate that story uses the required persona.
    
    Args:
        story_description: The story description text
        required_persona: The persona that MUST be used
        allow_synonyms: If True, allows close matches (e.g., "QA reviewer" == "QA engineer")
    
    Returns:
        PersonaCheckResult with validation status and optional correction
    """
    extracted = extract_persona_from_story(story_description)
    
    if not extracted:
        return PersonaCheckResult(
            is_valid=False,
            required_persona=required_persona,
            extracted_persona=None,
            violation_message=f"Story does not follow 'As a [persona], I want...' format",
            corrected_description=None
        )
    
    # Normalize for comparison
    required_lower = required_persona.lower().strip()
    extracted_lower = extracted.lower().strip()
    
    # Exact match
    if required_lower == extracted_lower:
        return PersonaCheckResult(
            is_valid=True,
            required_persona=required_persona,
            extracted_persona=extracted,
            violation_message=None,
            corrected_description=None
        )
    
    # Synonym matching (optional)
    if allow_synonyms and _are_synonyms(required_lower, extracted_lower):
        return PersonaCheckResult(
            is_valid=True,
            required_persona=required_persona,
            extracted_persona=extracted,
            violation_message=None,
            corrected_description=None
        )
    
    # Violation - provide auto-correction
    corrected = re.sub(
        PERSONA_PATTERN,
        f"As {'an' if required_persona[0].lower() in 'aeiou' else 'a'} {required_persona}, I want",
        story_description,
        count=1,
        flags=re.IGNORECASE
    )
    
    return PersonaCheckResult(
        is_valid=False,
        required_persona=required_persona,
        extracted_persona=extracted,
        violation_message=f"Persona mismatch: expected '{required_persona}', found '{extracted}'",
        corrected_description=corrected
    )

def _are_synonyms(persona1: str, persona2: str) -> bool:
    """Check if two personas are acceptable synonyms."""
    SYNONYM_GROUPS = [
        {"automation engineer", "control engineer", "controls engineer"},
        {"qa reviewer", "quality reviewer", "engineering reviewer"},
        {"ml engineer", "machine learning engineer"},
    ]
    
    for group in SYNONYM_GROUPS:
        if persona1 in group and persona2 in group:
            return True
    
    return False

def auto_correct_persona(
    story_dict: dict,
    required_persona: str
) -> dict:
    """
    Automatically correct persona in story description.
    
    Args:
        story_dict: Story object with 'description' field
        required_persona: The correct persona to use
    
    Returns:
        Updated story dict with corrected description
    """
    result = validate_persona(story_dict['description'], required_persona)
    
    if not result.is_valid and result.corrected_description:
        story_dict['description'] = result.corrected_description
    
    return story_dict
```

#### 2.2 Integrate Persona Checker into Pipeline

**In `tools.py` (process_feature_for_stories):**
```python
# After pipeline completes, before saving to database
from orchestrator_agent.agent_tools.story_pipeline.persona_checker import (
    validate_persona,
    auto_correct_persona
)

# Extract refined story from state
refined_story = json.loads(state.get("refinement_result", "{}"))

# Deterministic persona check
persona_check = validate_persona(
    refined_story['description'],
    story_input.user_persona
)

if not persona_check.is_valid:
    print(f"⚠️  Persona violation detected: {persona_check.violation_message}")
    
    # Auto-correct if possible
    refined_story = auto_correct_persona(refined_story, story_input.user_persona)
    print(f"✅ Auto-corrected persona to: {story_input.user_persona}")
```

---

### **Tier 3: Strategic Persona Management**

#### 3.1 Persona Registry System

Create a product-level persona registry:

```python
# agile_sqlmodel.py - Add new table
class ProductPersona(SQLModel, table=True):
    """Approved personas for a product."""
    __tablename__ = "product_personas"
    
    persona_id: int = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.product_id")
    persona_name: str = Field(max_length=100, nullable=False)  # "automation engineer"
    persona_category: str = Field(max_length=50)  # "primary_user", "admin", "platform"
    description: Optional[str] = Field(default=None, sa_type=Text)  # Role definition
    is_default: bool = Field(default=False)  # Default persona for stories
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    product: "Product" = Relationship(back_populates="personas")

# Update Product model
class Product(SQLModel, table=True):
    # ... existing fields ...
    personas: List["ProductPersona"] = Relationship(back_populates="product")
```

**Populate on product creation:**
```python
# In save_vision_tool or create_or_get_product
vision_components = VisionComponents.model_validate_json(vision_json)

# Extract personas from target_user
if vision_components.target_user:
    personas = extract_personas(vision_components.target_user)
    # e.g., "automation engineers and QA reviewers" → ["automation engineer", "QA reviewer"]
    
    for persona_name in personas:
        db.add(ProductPersona(
            product_id=product.product_id,
            persona_name=persona_name,
            persona_category="primary_user",
            is_default=(persona_name == personas[0])  # First is default
        ))
```

#### 3.2 Persona-Aware Story Generation

**Extend `ProcessStoryInput` schema:**
```python
class ProcessStoryInput(BaseModel):
    # ... existing fields ...
    
    # Option 1: Use default from product
    use_default_persona: bool = Field(
        default=True,
        description="If True, use product's default persona from registry"
    )
    
    # Option 2: Explicit persona selection
    user_persona: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Override persona (must exist in product persona registry)"
        )
    ]
    
    # Option 3: Persona category filtering
    persona_category: Annotated[
        Optional[str],
        Field(
            default=None,
            description="Use persona from specific category: 'primary_user', 'admin', 'platform'"
        )
    ]
```

**Validation before pipeline:**
```python
def validate_persona_from_registry(
    product_id: int,
    requested_persona: str,
    db: Session
) -> Tuple[bool, Optional[str]]:
    """Check if persona is approved for this product."""
    approved = db.exec(
        select(ProductPersona)
        .where(ProductPersona.product_id == product_id)
        .where(ProductPersona.persona_name == requested_persona)
    ).first()
    
    if not approved:
        available = db.exec(
            select(ProductPersona.persona_name)
            .where(ProductPersona.product_id == product_id)
        ).all()
        return False, f"Persona '{requested_persona}' not approved. Use: {available}"
    
    return True, None
```

#### 3.3 Feature-to-Persona Mapping (Advanced)

For complex products with multiple personas, map feature types to personas:

```python
class FeaturePersonaRule(SQLModel, table=True):
    """Maps feature keywords to preferred personas."""
    __tablename__ = "feature_persona_rules"
    
    rule_id: int = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.product_id")
    feature_keyword: str = Field(max_length=100)  # "UI", "review", "export", "admin"
    preferred_persona_id: int = Field(foreign_key="product_personas.persona_id")
    priority: int = Field(default=0)  # Higher = stronger match

# Example rules for P&ID tool:
# feature_keyword="review" → persona="automation engineer"
# feature_keyword="admin" → persona="IT administrator"
# feature_keyword="training" → persona="ML engineer"
```

---

## Practical Remediation - Fixing Existing Stories

### Option 1: Automated Persona Substitution (Safest)

**When to use:** Stories have correct ACs and scope, only persona is wrong

**Implementation:**
```python
# scripts/fix_persona_drift.py
from sqlmodel import Session, select
from agile_sqlmodel import UserStory, Product, engine

# Define substitution rules
PERSONA_FIXES = {
    "data annotator": "automation engineer",
    "software engineer": "automation engineer",
    "frontend developer": "automation engineer",
    "data scientist": "automation engineer",
    "QA engineer": "engineering QA reviewer",
}

def fix_story_personas(product_id: int, dry_run: bool = True):
    """Fix personas in all stories for a product."""
    with Session(engine) as session:
        product = session.get(Product, product_id)
        default_persona = session.exec(
            select(ProductPersona.persona_name)
            .where(ProductPersona.product_id == product_id)
            .where(ProductPersona.is_default == True)
        ).first()
        
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()
        
        fixed_count = 0
        for story in stories:
            # Extract current persona
            extracted = extract_persona_from_story(story.description)
            
            if extracted and extracted.lower() in PERSONA_FIXES:
                new_persona = PERSONA_FIXES[extracted.lower()]
                
                # Replace persona in description
                old_desc = story.description
                new_desc = old_desc.replace(
                    f"As a {extracted},",
                    f"As {'an' if new_persona[0] in 'aeiou' else 'a'} {new_persona},"
                )
                
                print(f"Story {story.story_id}: '{extracted}' → '{new_persona}'")
                
                if not dry_run:
                    story.description = new_desc
                    session.add(story)
                
                fixed_count += 1
        
        if not dry_run:
            session.commit()
        
        print(f"\n{'Would fix' if dry_run else 'Fixed'} {fixed_count}/{len(stories)} stories")

# Run with dry_run=True first to preview
fix_story_personas(product_id=1, dry_run=True)

# Then apply
fix_story_personas(product_id=1, dry_run=False)
```

### Option 2: Selective Re-Generation

**When to use:** Some stories have more serious issues beyond persona

**Process:**
1. Query stories with wrong personas: `SELECT * FROM user_stories WHERE description LIKE '%As a data annotator%'`
2. For each story, call `process_feature_for_stories` with correct persona
3. Compare new story with old story (acceptance criteria should match)
4. Replace story if acceptable

### Option 3: Manual Review Workflow

**When to use:** High-stakes stories requiring human validation

**Implementation:**
```python
# scripts/persona_review_report.py
def generate_persona_review_report(product_id: int):
    """Generate CSV for manual review."""
    import csv
    
    with Session(engine) as session:
        stories = session.exec(
            select(UserStory).where(UserStory.product_id == product_id)
        ).all()
        
        with open('persona_review.csv', 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['Story ID', 'Feature', 'Current Persona', 'Suggested Fix', 'Description', 'Review Status'])
            
            for story in stories:
                current_persona = extract_persona_from_story(story.description)
                suggested = PERSONA_FIXES.get(current_persona.lower(), "MANUAL_REVIEW")
                
                writer.writerow([
                    story.story_id,
                    story.feature.feature_title if story.feature else "N/A",
                    current_persona,
                    suggested,
                    story.description[:100],
                    "PENDING"
                ])
    
    print("Review report saved to persona_review.csv")
```

---

## Recommendations Summary

### For Your P&ID Tool (Immediate Action)

1. **Deploy Tier 1 fixes** (prompt strengthening + validation extension) - 2-4 hours work
2. **Run automated persona substitution** on existing stories - 30 minutes
3. **Add persona registry** with approved personas:
   - Primary: "automation engineer" (default)
   - Secondary: "engineering QA reviewer"
   - Platform: "ML engineer" (for training/model stories only)
   - Admin: "IT administrator" (for deployment/security stories)

### For Future Products

1. **Tier 2 enforcement** (deterministic persona checker) - Prevents future drift
2. **Tier 3 registry** (if product has >2 personas or complex role boundaries)

### Persona Strategy Decision

**Recommended: Small Explicit Whitelist**

✅ **Use this approach** for engineering tools with clear role boundaries:
- Define 2-4 approved personas at product creation
- Set one as default (automation engineer)
- Allow explicit persona selection for special cases (admin, platform)
- Reject stories with personas outside the whitelist

❌ **Avoid single persona** - too rigid for products with admin/platform needs  
❌ **Avoid free-form personas** - causes the drift you're experiencing now

---

## Success Metrics

Track these after implementing fixes:

1. **Persona Accuracy Rate:** % of stories using approved personas (target: 95%+)
2. **Persona Correction Rate:** % of stories requiring post-generation persona fixes (target: <5%)
3. **Validation Rejection Rate:** % of stories rejected by validator due to persona issues (should increase initially, then drop to near-zero)
4. **Stakeholder Confusion:** Qualitative feedback - do sprint planning participants understand story context? (target: "personas make sense")

---

## Implementation Priority

**Week 1 (MVP):**
- [ ] Update story draft agent instructions (Tier 1.1)
- [ ] Add persona_alignment to INVEST validator (Tier 1.2)
- [ ] Run automated persona substitution on existing stories (Remediation Option 1)

**Week 2 (Robust):**
- [ ] Create persona_checker.py module (Tier 2.1)
- [ ] Integrate deterministic checks into pipeline (Tier 2.2)
- [ ] Add ProductPersona table (Tier 3.1)

**Week 3 (Advanced - Optional):**
- [ ] Implement persona-aware story generation (Tier 3.2)
- [ ] Add feature-to-persona mapping for complex products (Tier 3.3)

---

## References

- Story Draft Agent: `orchestrator_agent/agent_tools/story_pipeline/story_draft_agent/agent.py`
- INVEST Validator: `orchestrator_agent/agent_tools/story_pipeline/invest_validator_agent/agent.py`
- Story Refiner: `orchestrator_agent/agent_tools/story_pipeline/story_refiner_agent/agent.py`
- Alignment Checker (vision constraints): `orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py`
- Pipeline Orchestration: `orchestrator_agent/agent_tools/story_pipeline/pipeline.py`
- Vision Schema: `utils/schemes.py` (VisionComponents.target_user)
