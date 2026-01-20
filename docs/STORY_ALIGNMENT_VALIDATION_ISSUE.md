# Story Pipeline Alignment Validation Issue

## Problem Statement

The Story Pipeline's INVEST Validator agent is **not enforcing product vision constraints**, causing it to approve user stories that violate explicit scope boundaries defined in the product vision statement. This results in stories with out-of-scope features (dashboards, real-time sync, notifications, industrial integrations) being marked as `is_valid=True` with high validation scores (~85-95/100) even when they fundamentally contradict the product's vision.

## Context

**System Architecture:**
- **Story Pipeline:** LoopAgent containing SequentialAgent with 3 agents (StoryDraftAgent → INVESTValidatorAgent → StoryRefinerAgent)
- **Validator Model:** `openrouter/openai/gpt-4.1-mini`
- **Refiner Model:** `openrouter/openai/gpt-4.1-mini`
- **State Management:** InMemorySessionService with JSON-serialized context
- **Exit Control:** `exit_loop` tool called by Refiner when `validation_score >= 90` and `is_valid == True`

**Current Validation Logic:**
```python
# tools.py - Current deterministic check
is_valid = validation_score >= 70 AND no alignment_issues
```

**Vision Injection Mechanism:**
1. User provides `product_vision` in `ProcessStoryInput`
2. Vision is serialized to JSON and stored in `initial_state["product_context"]["vision"]`
3. Validator receives vision in state but **does not enforce constraints from it**

## Observed Symptoms

### Test Case 1: Dashboard for Mobile-Only Vision
**Input:**
- Vision: "Tennis Tracker is a **mobile-only app** that helps record scores and stats. Unlike complex **desktop software**, our product focuses on **quick mobile data entry**."
- Feature: "**Web-based analytics dashboard**"

**Expected Behavior:**
Story should be rejected (is_valid=False) because:
- Vision explicitly states "mobile-only app"
- Feature requires "web-based" platform → direct violation

**Actual Behavior:**
- Iteration 1: Validator catches alignment issue, score=40/100
- Iteration 2: Refiner **transforms** the requirement from "web-based dashboard" → "mobile analytics screen"
- Validator scores the transformed story 90/100, marks is_valid=True
- **Pipeline returns the transformed story as valid** ✅ (WRONG)

**Core Problem:** Refiner is treating alignment violations as **refinement opportunities** instead of **hard rejections**. The feature title "Web-based analytics dashboard" should fail outright, not be "repaired" into a mobile feature.

---

### Test Case 2: Real-Time Sync for Offline-First Vision
**Input:**
- Vision: "Workout Logger is an **offline-first mobile app** that stores workouts locally. Unlike cloud-based trackers, our product **works without internet access**."
- Feature: "**Real-time workout synchronization with cloud**"

**Expected Behavior:**
Story should be rejected (is_valid=False) because:
- Vision states "offline-first" and "works without internet"
- Feature requires "real-time" cloud sync → architectural violation

**Actual Behavior:**
- Validator passes the story with score=95/100
- **No alignment issues detected**
- Pipeline returns is_valid=True ✅ (WRONG)

**Core Problem:** Validator agent **does not parse the vision text** to extract constraints. It has the vision in context but doesn't map "offline-first" → forbidden capability: "real-time sync".

---

### Test Case 3: Notifications for Distraction-Free Vision
**Input:**
- Vision: "Reading Journal is a simple note-taking app for tracking books and quotes. Unlike social reading platforms, our product is **private and distraction-free**."
- Feature: "**Push notifications and reading reminders**"

**Expected Behavior:**
Story should be rejected because:
- Vision emphasizes "distraction-free"
- Feature adds notifications → UX philosophy violation

**Actual Behavior:**
- Validator passes the story with score=85/100
- **No alignment issues detected**
- Pipeline returns is_valid=True ✅ (WRONG)

**Core Problem:** "Distraction-free" keyword is not being semantically linked to "notifications/alerts/push" as forbidden capabilities.

---

### Test Case 4: PLC/Industrial for Consumer App Vision
**Input:**
- Vision: "Home Garden Planner is a simple mobile app for tracking plants and harvest dates. Unlike professional agriculture software, our product is designed for **casual home use**."
- Feature: "**Integration with industrial PLC controllers and OPC UA sensors**"

**Expected Behavior:**
Story should be rejected because:
- Vision targets "casual home use"
- Feature mentions "industrial PLC" and "OPC UA" → user segment violation

**Actual Behavior:**
- Iteration 1: Validator detects industrial mismatch, score=55/100
- Iteration 2: Refiner **transforms** "industrial PLC integration" → "consumer IoT sensors"
- Validator scores transformed story 85/100, marks is_valid=True
- **Pipeline returns the transformed story as valid** ✅ (WRONG)

**Core Problem:** Same as Test Case 1 - refiner treating scope violations as fixable instead of rejecting the original feature.

---

## Data Flow Analysis

### What the Validator Receives (Confirmed)
```json
{
  "story_draft": {
    "title": "Synchronize workout data in real-time",
    "description": "As a fitness app user, I want my workout data to be synchronized in real-time with the cloud..."
  },
  "product_context": "{\"product_id\": 999, \"product_name\": \"Workout Logger\", \"vision\": \"For fitness enthusiasts who train in areas with poor connectivity, Workout Logger is an offline-first mobile app that stores workouts locally. Unlike cloud-based trackers, our product works without internet access.\", \"forbidden_capabilities\": [\"web\", \"desktop\", \"browser\", \"real-time\", \"live\", \"cloud sync\", \"server sync\"]}"
}
```

**Key Observations:**
1. ✅ Vision text IS injected into state
2. ✅ `forbidden_capabilities` array IS extracted from vision keywords (`tools.py` lines 186-214)
3. ❌ Validator agent's instruction DOES include "Section 0: Product Alignment Check"
4. ❌ Validator LLM is **NOT following** the alignment check instruction
5. ❌ Validator output schema has `alignment_issues` field but it's always empty

### Where Detection Fails

**Root Cause Analysis:**

1. **LLM Non-Compliance:** The validator agent instruction contains detailed alignment checking steps but the LLM (gpt-4.1-mini) is:
   - Not parsing the `forbidden_capabilities` array from `product_context`
   - Not comparing story capabilities against the forbidden list
   - Not populating `alignment_issues` array even when violations exist
   - Scoring stories purely on INVEST criteria, ignoring vision context

2. **Requirement Transformation:** When validator DOES detect alignment issues:
   - Refiner agent receives feedback: "Remove web dashboard, focus on mobile"
   - Refiner **changes the requirement** instead of rejecting it
   - Validator scores the NEW requirement (which is valid but different)
   - Pipeline returns is_valid=True for a **different feature than requested**

3. **No Source-of-Truth Enforcement:** The system has no mechanism to verify that the final story implements the **original feature requirement**. Feature title is treated as a suggestion, not a contract.

## Technical Details

### Current Code State (tools.py)

**Constraint Extraction (Lines 186-214):**
```python
vision_lower = (story_input.product_vision or "").lower()
forbidden_capabilities = []

if "mobile-only" in vision_lower or "mobile app" in vision_lower:
    forbidden_capabilities.extend(["web", "desktop", "browser"])
if "offline-first" in vision_lower or "without internet" in vision_lower:
    forbidden_capabilities.extend(["real-time", "live", "cloud sync", "server sync"])
if "distraction-free" in vision_lower or "private" in vision_lower:
    forbidden_capabilities.extend(["notifications", "alerts", "push", "reminders"])
# ... more patterns
```
**Status:** ✅ Working - forbidden_capabilities are correctly extracted

**State Injection (Lines 246-250):**
```python
"product_context": json.dumps({
    "product_id": story_input.product_id,
    "product_name": story_input.product_name,
    "vision": story_input.product_vision or "",
    "forbidden_capabilities": forbidden_capabilities,
})
```
**Status:** ✅ Working - vision and constraints are passed to validator

**Deterministic Validation (Lines 476-480):**
```python
is_valid_deterministic = final_score >= 70 and (
    not alignment_issues or len(alignment_issues) == 0
)
```
**Status:** ⚠️ Partially working - checks alignment_issues but they're never populated by validator

### Validator Agent State (invest_validator_agent/agent.py)

**Instruction Section 0 (Lines 45-105):**
```
## 0. Product Alignment Check (MANDATORY - EVALUATED FIRST)

**STEP 1: Extract vision and constraints from product_context**
- Read `product_context` from state (it's a JSON string, parse it)
- Extract the `vision` field
- Extract the `forbidden_capabilities` array

**STEP 4: Compare story vs vision - CHECK FOR MISMATCHES**
a) Platform Mismatch:
   - Vision says "offline-first" BUT story mentions "real-time", "sync", "cloud" → YES = violation

**STEP 5: If ANY check = YES, do ALL of the following:**
1. Add violation to `alignment_issues` array
2. Deduct 20 points from final score PER violation
3. Set `is_valid = false`
```
**Status:** ❌ Not being followed by LLM

**Output Schema (Lines 155-162):**
```python
"alignment_issues": [
    "<alignment violation 1>",
    "<alignment violation 2>"
]
```
**Status:** ✅ Schema is correct, but validator never populates this field

### Refiner Agent State (story_refiner_agent/agent.py)

**Exit Loop Tool (Lines 34-94):**
```python
def exit_loop(tool_context: ToolContext) -> dict:
    validation_score = validation_result.get("validation_score", 0)
    alignment_issues = validation_result.get("alignment_issues", [])

    if validation_score < 70:
        return {"loop_exit": False, "reason": "Score too low"}
    if alignment_issues and len(alignment_issues) > 0:
        return {"loop_exit": False, "reason": "Alignment violations"}

    tool_context.actions.escalate = True
    return {"loop_exit": True}
```
**Status:** ✅ Would work IF alignment_issues were populated

**Refinement Guidelines (Lines 142-156):**
```
## For Alignment Violations (HIGHEST PRIORITY):
- Remove features not mentioned in product vision
- Replace out-of-scope capabilities with in-scope alternatives:
  * Dashboard → Simple list view or summary screen
  * Real-time sync → Local storage with manual refresh
```
**Status:** ❌ This is the wrong behavior - should REJECT, not TRANSFORM

## Why This Matters

1. **Scope Creep Prevention:** Product vision defines what the product IS and ISN'T. If a feature violates vision, it should be rejected during planning, not "fixed" by rewording.

2. **Requirement Fidelity:** When a Product Owner requests "web-based analytics dashboard", they mean web-based. The system shouldn't silently change it to "mobile analytics screen" - that's a different feature.

3. **Trust in Automation:** If the Story Pipeline can't be trusted to respect vision constraints, users won't trust it to generate product-aligned stories.

4. **Development Efficiency:** Invalid features should fail fast during story generation, not after development when team realizes "wait, this isn't what the product is supposed to do".

## Attempted Solutions (Unsuccessful)

### Attempt 1: Enhanced Validator Instructions
- Added detailed Section 0 with step-by-step alignment checking
- Result: LLM still ignores it, scores purely on INVEST

### Attempt 2: Explicit Examples in Prompt
- Added 3 example outputs showing alignment violations with -20 point penalties
- Result: No improvement in detection rate

### Attempt 3: Gated Exit Loop
- Modified `exit_loop` tool to block early exit when `alignment_issues` present
- Result: Works correctly BUT alignment_issues is always empty array

### Attempt 4: Deterministic Post-Check
- Added code-level validation after pipeline completes
- Result: Can catch violations IF validator populates alignment_issues, but it doesn't

### Attempt 5: Requirement Drift Detection
- Added function to compare original feature vs final story keywords
- Result: Successfully detects platform/capability transformations, but only AFTER refiner has transformed them

### Attempt 6: Code-Level Alignment Check Function
- Created `check_alignment_violation()` to deterministically check forbidden capabilities
- Result: Function works but needs to be called at the right point in pipeline
- **Problem:** Calling it after validation means validator LLM already scored the story

## Environment Details

- **Python Version:** 3.13.7
- **Google ADK Version:** (from .venv)
- **LiteLLM Model:** openrouter/openai/gpt-4.1-mini
- **Database:** SQLite (agile_sqlmodel.db)
- **Framework:** Google Agent Development Kit (ADK)
- **Agent Pattern:** LoopAgent (max_iterations=3) → SequentialAgent (Draft → Validate → Refine)

## Test Evidence Location

Test file was created as `tests/test_story_alignment_violations.py` with 5 test cases:
1. `test_dashboard_story_fails_for_mobile_only_vision` - Platform violation
2. `test_realtime_story_fails_for_offline_first_vision` - Technical constraint violation
3. `test_notification_story_fails_when_vision_excludes_alerts` - UX philosophy violation
4. `test_aligned_story_passes_validation` - Control test (should pass)
5. `test_industrial_integration_story_fails_for_consumer_app_vision` - User segment violation

**Test Results (Last Run):**
- Test 1: ✅ PASS (drift detection caught platform change web→mobile)
- Test 2: ❌ FAIL (validator passed real-time sync for offline-first vision)
- Test 3: ❌ FAIL (validator passed notifications for distraction-free vision)
- Test 4: ✅ PASS (aligned story correctly passed)
- Test 5: ❌ FAIL (validator allowed PLC→consumer transformation)

## Key Question for Next Approach

**Should alignment validation be:**

**Option A:** LLM-based semantic checking
- Pro: Can understand nuanced violations ("casual home use" excludes "industrial PLC")
- Con: Non-deterministic, requires prompt engineering, gpt-4.1-mini isn't following instructions

**Option B:** Code-level deterministic checking
- Pro: Reliable, testable, fast, no LLM costs
- Con: Requires comprehensive keyword mapping, might miss edge cases

**Option C:** Hybrid approach
- Code checks exact keyword violations (mobile-only + web = reject)
- LLM checks semantic violations (casual home use + industrial PLC = ???)
- Code has final veto authority

**Current recommendation:** Option B (deterministic) because:
1. Constraint extraction already exists in code (lines 186-214 of tools.py)
2. Vision statements use predictable keywords ("mobile-only", "offline-first", "distraction-free")
3. Forbidden capability lists are explicit and mappable
4. LLM has proven unreliable for following multi-step validation procedures

## Next Debugging Steps (If Continuing LLM Approach)

1. **Isolation Test:** Call validator agent directly with minimal state, log exact input/output
2. **Model Comparison:** Test with different models (gpt-4o, claude-3.5-sonnet) to see if it's model-specific
3. **Prompt Simplification:** Reduce instruction to ONLY alignment check, remove INVEST scoring
4. **Schema Enforcement:** Use Pydantic validators to force alignment_issues to be non-empty when violations exist
5. **Few-Shot Examples:** Add 10+ examples of alignment violations to instruction

## Logs/Evidence

**Console Output from Failed Test:**
```
[Constraints] Forbidden capabilities detected: ['web', 'desktop', 'browser', 'real-time', 'live', 'cloud sync', 'server sync']

Iteration 1:
📝 DRAFT: Title: Synchronize workout data in real-time
🔍 VALIDATION: ✅ PASS (Score: 95/100)
   INVEST: I:20 | N:15 | V:20 | E:20 | S:20 | T:20

✅ FINAL: 'Synchronize workout data in real-time' | Score: 95/100 | Iterations: 1
```

**Key Observation:** Even though forbidden_capabilities contains "real-time", validator scored story 95/100 and marked it valid. No alignment_issues were detected.

---

## Summary

The Story Pipeline has a **critical gap in vision enforcement**:
1. ✅ Vision text is extracted and injected correctly
2. ✅ Forbidden capabilities are derived from vision keywords
3. ❌ Validator LLM ignores the alignment check instruction
4. ❌ Refiner transforms violating requirements instead of rejecting them
5. ❌ No deterministic enforcement layer exists

**Result:** Out-of-scope features pass validation and get "repaired" into different features, violating requirement fidelity and product vision boundaries.
