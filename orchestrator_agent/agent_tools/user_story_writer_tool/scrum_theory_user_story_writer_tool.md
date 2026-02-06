# Theory Reference: User Story Decomposition

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018).
**Methodological Phase:** Requirement Refinement (Chapter 5).
**Target Agent:** `user_story_writer_tool`

---

## 1. Theoretical Foundation
In the Scrum framework, the "User Story" represents the atomic unit of delivery. It marks the transition from **Strategic Planning** (Roadmap) to **Tactical Execution** (Sprints).

**Definition (p. 69):**
> *"The user story is the smallest unit of work... It describes a specific piece of value for a specific user."*

**Scientific Function:**
Unlike traditional "System Requirements" (which are often bulky and technical), User Stories are designed to be **negotiable placeholders for conversation** (p. 72). They shift the focus from "writing documentation" to "delivering value."

---

## 2. Structural Logic: The "Three Cs" Protocol
**Ref: Chapter 5, Page 72.**

The Agent must construct every story according to the **"Three Cs"** model defined by Ron Jeffries and cited by Layton:

1.  **Card:** The written statement (The "As a..." template).
2.  **Conversation:** The dialogue between PO and Team (Simulated via the `clarifying_questions` output).
3.  **Confirmation:** The Acceptance Criteria (The tests).

### The Canonical Template (p. 72)
The Agent is strictly bound to the following syntax to ensure role-based value definition:
> **"As a [role], I want [feature], so that [benefit]."**

**Constraint:** The `[role]` must not be a generic "User" if a specific persona (e.g., "Admin," "Customer") can be inferred from the context.

---

## 3. Decomposition Logic: Vertical Slicing
**Ref: Chapter 5, Page 70.**

The most critical algorithmic constraint for the Agent is **Vertical Slicing**.

> *"Many teams make the mistake of breaking down requirements horizontally... For example, 'Create the database schema'."* (p. 70)

**The "Layer Cake" Metaphor:**
* **Horizontal Slice (Forbidden):** Work limited to one architectural layer (e.g., DB only, UI only). Delivers zero user value on its own.
* **Vertical Slice (Mandated):** Work that cuts through all layers (UI + Logic + DB) to deliver a tiny but functioning feature.



**Agent Execution Rule:**
If a decomposed story describes a technical task (e.g., "Setup API Endpoint") without a user-facing outcome, it must be rejected or merged.

---

## 4. Validation Heuristic: The INVEST Model
**Ref: Chapter 5, Page 73.**

Every generated story must pass the **INVEST** quality gate. The Agent must evaluate its output against these six dimensions:

* **I - Independent:** Can it be prioritized/released separately?
* **N - Negotiable:** Does it capture the *intent* without dictating the *code*?
* **V - Valuable:** Is the value explicit to the stakeholder?
* **E - Estimable:** Is it clear enough for the team to size?
* **S - Small:** Is it sized for execution (approx. 2-3 days work)?
* **T - Testable:** Does it have binary pass/fail criteria?

---

## 5. Confirmation Logic: Acceptance Criteria
**Ref: Chapter 5, Page 77.**

To satisfy the "Confirmation" aspect of the Three Cs, the Agent must generate **Conditions of Satisfaction**.

> *"Acceptance criteria... define the boundaries of a user story... confirm when a story is complete."* (p. 77)

**Scientific Constraint:**
Criteria must be **Binary** (Pass/Fail) and verifiable.
* *Bad:* "Make it fast." (Subjective).
* *Good:* "Page loads in < 2 seconds." (Objective).

The Agent must derive these criteria from the `technical_spec` and `compiled_authority` contexts provided in the input.

---

## 6. Agent Workflow & Constraints

| Step | Action | Theoretical Reference | Constraint |
| :--- | :--- | :--- | :--- |
| **1** | **Extraction** | *Layton (2018), p. 72* | Identify the `[Role]` and `[Benefit]` from the context. |
| **2** | **Slicing** | *Layton (2018), p. 70* | Decompose the "Parent Requirement" into Vertical Slices. |
| **3** | **Formatting** | *Layton (2018), p. 72* | Apply strict "As a... I want... So that..." syntax. |
| **4** | **Validation** | *Layton (2018), p. 73* | Check against INVEST. If 'Large', slice again. |
| **5** | **Confirmation** | *Layton (2018), p. 77* | Append functional and non-functional Acceptance Criteria. |

### Exclusion Criteria (Out of Scope)
The User Story Writer is explicitly forbidden from:
* **Writing Code:** The "How" is left to the team.
* **Task Lists:** "Update SQL table" is a Task (Chapter 6), not a Story.
* **UI Design:** Descriptions should be functional, not pixel-perfect specs.