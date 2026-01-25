# Jules: Missing Whitelist Validation Fix

## Issue Summary

Test `test_unapproved_persona_rejected` is **failing** because the pipeline doesn't validate input personas against the `ProductPersona` registry.

**Current behavior:**
1. User submits story request with `user_persona="random hacker"`
2. Pipeline runs (3 iterations!)
3. LLM correctly changes persona to "automation engineer"
4. Persona guard detects mismatch (expected "random hacker", found "automation engineer")
5. Guard **auto-corrects BACK** to "random hacker" ❌
6. Story succeeds with unapproved persona ❌

**Expected behavior:**
1. User submits story request with `user_persona="random hacker"`
2. **FAIL-FAST**: "random hacker" not in ProductPersona registry → reject immediately
3. No pipeline execution (save LLM tokens)

---

## Root Cause

`tools.py::process_single_story()` never queries the database to verify that `story_input.user_persona` is in the approved `ProductPersona` table for the given product.

---

## Required Fix

Add whitelist validation **BEFORE** the feature alignment check in `process_single_story()`:

### Step 1: Add import

At the top of `tools.py`:

```python
from agile_sqlmodel import UserStory, ProductPersona, engine
```

### Step 2: Add validation function

Add this helper function before `process_single_story()`:

```python
def validate_persona_against_registry(
    product_id: int,
    persona_name: str
) -> tuple[bool, Optional[str]]:
    """
    Check if persona_name is in the ProductPersona registry for this product.
    
    Returns:
        (True, None) if valid
        (False, error_message) if invalid
    """
    from sqlmodel import Session, select
    
    with Session(engine) as session:
        # Query approved personas for this product
        personas = session.exec(
            select(ProductPersona.persona_name)
            .where(ProductPersona.product_id == product_id)
        ).all()
        
        approved_names = [p.lower() for p in personas]
        
        if persona_name.lower() not in approved_names:
            return (
                False,
                f"Persona '{persona_name}' not in approved list for product {product_id}. "
                f"Approved personas: {personas}"
            )
        
        return (True, None)
```

### Step 3: Add FAIL-FAST check in process_single_story()

Add this **BEFORE** the feature alignment check (around line 140):

```python
async def process_single_story(
    story_input: ProcessStoryInput,
    output_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    # ... existing log helper setup ...

    log(
        f"\n{CYAN}[Pipeline]{RESET} Processing feature: {BOLD}'{story_input.feature_title}'{RESET}"
    )
    log(f"{DIM}   Theme: {story_input.theme} | Epic: {story_input.epic}{RESET}")

    # --- NEW: FAIL-FAST - Validate persona against registry ---
    is_valid_persona, persona_error = validate_persona_against_registry(
        product_id=story_input.product_id,
        persona_name=story_input.user_persona
    )
    
    if not is_valid_persona:
        log(f"{RED}[Persona REJECTED]{RESET} {persona_error}")
        return {
            "success": False,
            "error": persona_error,  # Contains "not in approved list"
            "feature_id": story_input.feature_id,
            "feature_title": story_input.feature_title,
        }

    # --- Continue with existing forbidden capabilities extraction ---
    forbidden_capabilities = extract_forbidden_capabilities(story_input.product_vision)
    # ... rest of function ...
```

---

## Test Expectation

The test expects this specific error message:
```python
assert "not in approved list" in result['error']
```

So the error message **must** contain the substring `"not in approved list"`.

---

## Files to Modify

| File | Change |
|------|--------|
| `orchestrator_agent/agent_tools/story_pipeline/tools.py` | Add import, validation function, FAIL-FAST check |

---

## Verification

After applying the fix, run:
```bash
python -m pytest tests/test_persona_enforcement_integration.py -v
```

All 3 tests should pass:
- ✅ `test_persona_drift_prevented`
- ✅ `test_unapproved_persona_rejected`  ← Currently failing
- ✅ `test_persona_field_population`
