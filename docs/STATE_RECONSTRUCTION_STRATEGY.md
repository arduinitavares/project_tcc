# State Reconstruction Strategy for ADK Sub-Agents

## The "Goldfish Memory" Problem

**Symptom:** Sub-agents wrapped in `AgentTool` treat each invocation as isolated, losing context from previous turns.

**Example:**
- Turn 1: "I want a Tinder for Tennis" → Agent identifies `Target User: Tennis Players`
- Turn 2: "The project name is NetSet" → Agent outputs `Target User: null` ❌

**Root Cause:** LLMs are stateless by default. Without explicit instructions, they process only the current input, ignoring conversation history even when it's provided in the context.

---

## Solution: Multi-Layered Prompt Engineering

### Layer 1: Explicit State Reconstruction Protocol

**Key Insight:** You must **command** the LLM to perform state reconstruction as a mandatory first step.

```plaintext
# CRITICAL: STATE RECONSTRUCTION PROTOCOL

⚠️ YOU ARE STATELESS BY DESIGN. Every tool invocation is a fresh function call.
⚠️ THE CONVERSATION HISTORY IS YOUR ONLY MEMORY.

## MANDATORY PRE-PROCESSING (Execute BEFORE analyzing current input)

### STEP 1: RECONSTRUCT STATE FROM HISTORY
Before processing the current input, you MUST:
1. Scan ALL previous messages in the conversation history
2. Extract your own previous outputs (look for JSON objects)
3. Build a "Known Facts Table" containing all previously identified components
```

**Why This Works:**
- Uses imperative language ("MUST", "BEFORE")
- Frames history as "YOUR ONLY MEMORY" (creates urgency)
- Provides concrete steps (scan → extract → build table)

---

### Layer 2: Merge Logic (Not Replacement Logic)

**Key Insight:** Explicitly define how to combine historical state with new input.

```plaintext
### STEP 2: MERGE NEW INPUT (DIFF LOGIC)

Apply MERGE rules (NOT replacement):
- Historical value + No mention in current input = PRESERVE historical value
- Historical value + New value in current input = UPDATE to new value
- No historical value + New value in current input = ADD new value
- No historical value + No mention in current input = REMAINS UNKNOWN

NEVER set a known field to null just because it wasn't mentioned in the latest message.
```

**Why This Works:**
- Provides exhaustive case coverage (4 scenarios)
- Uses database-like terminology ("MERGE", "PRESERVE", "UPDATE")
- Includes explicit anti-pattern ("NEVER set known field to null")

---

### Layer 3: Concrete Examples (Show, Don't Tell)

**Key Insight:** LLMs learn better from examples than abstract rules.

```plaintext
## CONCRETE EXAMPLE

Turn 1:
- Input: "I want a Tinder for Tennis."
- State After Turn 1:
  - Target User: Tennis Players
  - Competitors: Tinder
  - All others: UNKNOWN

Turn 2:
- Input: "The project name is NetSet."
- STEP 1 (Reconstruct): Scan history → Find "Tennis Players" from Turn 1
- STEP 2 (Merge): Current input adds "NetSet" → Merge with historical "Tennis Players"
- Output:
  {
    "project_name": "NetSet",
    "target_user": "Tennis Players",  ← PRESERVED from Turn 1
    ...
  }

✅ CORRECT: "Tennis Players" is preserved
❌ WRONG: Setting Target User to null
```

**Why This Works:**
- Demonstrates the exact scenario you're trying to prevent
- Shows both correct and incorrect behavior
- Uses visual markers (✅/❌) for emphasis

---

### Layer 4: Pre-Output Validation Checklist

**Key Insight:** Force the LLM to self-audit before returning output.

```plaintext
## PRE-OUTPUT VALIDATION CHECKLIST
Before returning your JSON, verify:

✅ State Preservation Check:
- [ ] Did I scan the conversation history?
- [ ] Did I build a "Known Facts Table"?
- [ ] Did I preserve ALL known values from history?

✅ Anti-Goldfish Verification:
- [ ] Would a human reading the history agree my output reflects ALL information gathered?
- [ ] Am I treating this as an incremental update, not a fresh start?

🚨 If you set a previously-known field to null, you have failed the task.
```

**Why This Works:**
- Creates a "pause point" before output generation
- Uses checkbox format (triggers systematic thinking)
- Ends with a strong negative consequence statement

---

### Layer 5: Visual Hierarchy & Emphasis

**Key Insight:** Use formatting to make critical sections impossible to miss.

```plaintext
# ═══════════════════════════════════════════════════════════════════════════
# CRITICAL: STATE RECONSTRUCTION PROTOCOL (ANTI-GOLDFISH MEMORY)
# ═══════════════════════════════════════════════════════════════════════════

⚠️ YOU ARE STATELESS BY DESIGN.
⚠️ THE CONVERSATION HISTORY IS YOUR ONLY MEMORY.

🚨 Your output must be a CUMULATIVE MERGE of all conversation turns.
🚨 If you set a previously-known field to null, you have failed the task.
```

**Why This Works:**
- Box drawing characters create visual boundaries
- Warning symbols (⚠️, 🚨) trigger attention
- ALL CAPS for critical terms
- Repetition of key concepts

---

## Advanced Techniques

### Technique 1: Explicit Phase Ordering

Force sequential processing by numbering phases:

```plaintext
PROCESS (Execute in Strict Order)

## PHASE 0: STATE RECONSTRUCTION (MANDATORY FIRST STEP)
1. Scan conversation history
2. Build "Known Facts Table"
3. Identify known vs. unknown components

## PHASE 1: ANALYZE (CONTEXTUALIZE & EXTRACT)
- Start with the Known Facts Table from Phase 0
- Parse current input for new information
- Apply MERGE logic

## PHASE 2: EVALUATE (Using MERGED State)
- Evaluation is based on MERGED state, NOT just current input
```

**Why This Works:**
- "PHASE 0" signals it must happen first
- Each phase references the previous phase's output
- Creates a dependency chain

---

### Technique 2: Negative Examples

Show what NOT to do:

```plaintext
❌ WRONG APPROACH:
def process_input(current_input):
    return extract_components(current_input)  # Ignores history!

✅ CORRECT APPROACH:
def process_input(current_input, conversation_history):
    known_facts = reconstruct_state(conversation_history)
    new_facts = extract_components(current_input)
    return merge(known_facts, new_facts)
```

**Why This Works:**
- Pseudo-code makes the logic concrete
- Side-by-side comparison highlights the difference
- Comments explain the failure mode

---

### Technique 3: Anthropomorphization

Give the agent a "role" that naturally preserves state:

```plaintext
You are a SCRIBE maintaining a LIVING DOCUMENT.

Your job is NOT to answer questions from scratch each time.
Your job is to UPDATE an existing draft based on new information.

Think of yourself as:
- A note-taker who adds to existing notes (not starting fresh each time)
- A form-filler who fills in blanks (not erasing filled fields)
- A database that merges records (not replacing them)
```

**Why This Works:**
- Metaphors create mental models
- "Living document" implies continuity
- Multiple analogies reinforce the same concept

---

### Technique 4: Explicit History Parsing Instructions

Tell the agent HOW to read history:

```plaintext
## HOW TO SCAN CONVERSATION HISTORY

1. Look for messages with role="assistant" (your previous outputs)
2. Parse JSON objects from those messages
3. Extract field values (project_name, target_user, etc.)
4. If a field had a non-null value in ANY previous turn, it is KNOWN
5. Build a table:
   | Component | Last Known Value | Turn # |
   |-----------|------------------|--------|
   | Project Name | "NetSet" | Turn 2 |
   | Target User | "Tennis Players" | Turn 1 |
```

**Why This Works:**
- Provides algorithmic steps
- Specifies exact data structures to look for
- Table format makes the concept tangible

---

### Technique 5: Failure Mode Warnings

Explicitly call out common mistakes:

```plaintext
## COMMON FAILURE MODES (AVOID THESE)

🚫 FAILURE MODE 1: "Current Input Only" Processing
- Symptom: Output only reflects the latest user message
- Fix: Always start with state reconstruction

🚫 FAILURE MODE 2: Null Overwriting
- Symptom: Setting "target_user": null when it was "Tennis Players" in Turn 1
- Fix: Apply PRESERVE rule when component is absent from current input

🚫 FAILURE MODE 3: Ignoring Your Own Outputs
- Symptom: Not reading your previous JSON responses
- Fix: Scan for role="assistant" messages in history
```

**Why This Works:**
- Names the exact problem you're trying to prevent
- Provides diagnostic criteria ("Symptom")
- Offers specific remediation ("Fix")

---

## Testing Your Implementation

### Test Case 1: Basic Accumulation
```
Turn 1: "I want a Tinder for Tennis"
Expected: Extract "Tennis Players" as target user

Turn 2: "The project name is NetSet"
Expected: Output BOTH "NetSet" AND "Tennis Players"
```

### Test Case 2: Explicit Update
```
Turn 1: "Target users are tennis players"
Turn 2: "Actually, target users are pickleball players"
Expected: UPDATE to "pickleball players" (not preserve "tennis players")
```

### Test Case 3: Partial Information Across Turns
```
Turn 1: "Name: NetSet"
Turn 2: "Target: Tennis players"
Turn 3: "Problem: Hard to find partners"
Expected: Output includes ALL THREE components
```

### Test Case 4: Clarifying Questions Loop
```
Turn 1: "Tinder for Tennis"
Agent: Asks 5 questions
Turn 2: User answers question 1 only
Expected: Output includes answer to Q1 + original "Tennis" context
```

---

## Debugging Checklist

If state loss still occurs:

1. **Check if history is actually provided:**
   - Add a debug tool that prints conversation history
   - Verify the ADK framework is passing full context

2. **Verify schema alignment:**
   - Ensure `OutputSchema` matches the JSON structure in examples
   - Check that field names are consistent

3. **Test with explicit history references:**
   - Add a prompt: "List all components you found in previous turns before processing the current input"
   - This forces the agent to verbalize its reconstruction

4. **Increase emphasis:**
   - Add more visual markers (⚠️, 🚨, ❌, ✅)
   - Repeat critical rules in multiple sections
   - Use CAPS for key terms

5. **Simplify the merge logic:**
   - If 4-case logic is too complex, start with 2 cases:
     - "If known from history → preserve"
     - "If new in current input → add/update"

---

## Why This Works (Cognitive Science Perspective)

### Principle 1: Explicit Task Decomposition
LLMs perform better when complex tasks are broken into sequential steps. By forcing "PHASE 0: STATE RECONSTRUCTION" before analysis, you prevent the model from jumping directly to extraction.

### Principle 2: Negative Priming
Showing incorrect examples (❌) creates a "don't do this" anchor in the model's attention mechanism.

### Principle 3: Repetition with Variation
The same concept ("preserve historical state") is stated:
- As a rule ("PRESERVE historical value")
- As an example (Turn 1 → Turn 2 scenario)
- As a checklist item ("Did I preserve ALL known values?")
- As a warning ("If you set a known field to null, you have failed")

This redundancy ensures the instruction survives attention dropout.

### Principle 4: Metacognitive Scaffolding
The validation checklist forces the model to "think about its thinking" before outputting, similar to chain-of-thought prompting.

---

## Alternative Approaches (If Prompting Alone Fails)

### Option 1: Explicit State Parameter
Modify the `InputSchema` to include a `previous_state` field:

```python
class InputSchema(BaseModel):
    unstructured_requirements: str
    previous_state: Optional[dict] = None  # Orchestrator passes last known state
```

Then the orchestrator extracts the last agent output and passes it back:

```python
last_output = extract_last_vision_output(history)
response = await vision_agent.run(
    unstructured_requirements=user_input,
    previous_state=last_output  # Explicit state passing
)
```

### Option 2: State Reconstruction Tool
Give the agent a tool to query its own history:

```python
@tool
def get_previous_vision_state(context: ToolContext) -> dict:
    """Retrieve the last vision assessment from conversation history."""
    history = context.conversation_history
    for msg in reversed(history):
        if msg.role == "assistant" and "product_vision_statement" in msg.content:
            return parse_json(msg.content)
    return {}
```

Then instruct the agent: "ALWAYS call `get_previous_vision_state()` before processing input."

### Option 3: Hybrid Approach
Combine prompting + explicit state passing:
- Orchestrator maintains state in its own memory
- Passes accumulated state as a structured field
- Agent instructions still emphasize merge logic (defense in depth)

---

## Conclusion

The solution is **multi-layered prompt engineering** that:
1. **Commands** state reconstruction as a mandatory first step
2. **Defines** explicit merge logic (4 cases)
3. **Demonstrates** correct behavior with concrete examples
4. **Validates** output with a pre-flight checklist
5. **Emphasizes** critical rules through visual hierarchy and repetition

This approach works because it compensates for the LLM's stateless nature by making state reconstruction an **explicit, unavoidable part of the task definition**.

The key insight: **Don't assume the LLM will "figure out" it should preserve state. Tell it explicitly, repeatedly, and with examples.**
