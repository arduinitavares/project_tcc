# Theory Reference: Roadmap to User Stories Transformation

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton.
**Purpose:** Defines the strict logical rules for decomposing a "Roadmap Requirement" into "User Stories" (Stage 2 $\rightarrow$ Chapter 5).
**Target Agent:** `user_story_writer_tool`

---

## 1. The Transformation Object Model

The transition moves from a high-level **Planning Artifact** (Roadmap) to an executable **Delivery Artifact** (User Story).

### Input: The Roadmap Requirement
* **Definition (Page 46):** A "high-level view of the product requirements" placed on a timeline.
* **Characteristics:**
    * **Scope:** Large (e.g., "Offline Dataset Ingestion").
    * **Estimation:** Coarse-grained (T-Shirt Sizes: S, M, L, XL) (Page 52).
    * **Status:** "Placement in time" (Page 48).

### Output: The User Story (`UserStoryItem`)
* **Definition (Page 69):** "The user story is the smallest unit of work... It describes a specific piece of value."
* **Characteristics:**
    * **Scope:** Small ("Vertical Slice").
    * **Estimation:** Fine-grained (Points or Hours - *Note: Done in Sprint Planning, but the story must be 'Estimable'*).
    * **Status:** Ready for Sprinting.

---

## 2. Core Logic: Vertical Slicing

**Rule:** The AI must decompose requirements by **functionality**, not by architectural layer.

### The Problem (Page 70)
> *"Many teams make the mistake of breaking down requirements horizontally... For example, 'Create the database schema' or 'Design the user interface'."*
>
> **Why this is forbidden:** Horizontal slices do not deliver independent value to the customer. You cannot "release" a database schema without the code that uses it.

### The Solution: Vertical Slicing (Page 70)
> *"You start with large, high-level requirements... Break these requirements down just enough to be able to estimate and prioritize them."*
>
> **Implementation Rule for AI:**
> Every generated `UserStoryItem` must touch all necessary layers (UI, Logic, Data) to deliver a *complete* tiny feature.
> * *Bad:* "Create API endpoint for login." (Horizontal)
> * *Good:* "As a user, I want to log in, so that I can access my account." (Vertical - implies UI, API, and DB work).

---

## 3. The Constraint: INVEST Compliance

**Rule:** Every generated story must be validated against the **INVEST** acronym defined on **Page 73**.

| Letter | Attribute | Book Definition / AI Logic Rule |
| :--- | :--- | :--- |
| **I** | **Independent** | *"Dependencies between stories... make prioritization and planning difficult."* <br> **AI Rule:** Can this story be deployed if other stories in the list are deleted? If no, merge them or minimize the dependency. |
| **N** | **Negotiable** | *"Stories are not contracts... they are invitations to a conversation."* <br> **AI Rule:** The details (Acceptance Criteria) should be clear but not exhaustive specs. Leave room for the "How." |
| **V** | **Valuable** | *"If a story doesn't have value to the customer... you shouldn't do it."* <br> **AI Rule:** Every story must have a clear "So that [benefit]" clause. If the benefit is technical only (e.g., "So that the code is clean"), reject it. |
| **E** | **Estimable** | *"The team needs enough information to estimate the size."* <br> **AI Rule:** Is the scope vague? (e.g., "Improve performance"). If yes, reject. It must be specific (e.g., "Load within 2 seconds"). |
| **S** | **Small** | *"Stories should be small enough to complete in a sprint... ideally 2–3 days."* <br> **AI Rule:** If a Roadmap Requirement is "XL", it must break into 5+ stories. If "S", maybe 1-2 stories. |
| **T** | **Testable** | *"If you can't test it, you can't know when it's done."* <br> **AI Rule:** Must have binary Acceptance Criteria (Pass/Fail). |

---

## 4. The Format: The "Three Cs"

**Rule:** The output text must follow the structure defined on **Page 72**.

### 1. Card (The Statement)
> *"As a [type of user], I want [capability], so that [benefit]."*

* **Role Constraint (Page 72):** *"Avoid the generic 'user' role... Be specific."*
    * *AI Action:* Extract the persona from the `requirement_context` (e.g., "Quality Engineer", "Compliance Officer").

### 2. Confirmation (Acceptance Criteria) (Page 77)
> *"Acceptance criteria... define the boundaries of a user story... confirm when a story is complete."*

* **Implementation Rule:**
    * The AI must generate a list of **Conditions of Satisfaction**.
    * **Functional:** "Verify that..."
    * **Non-Functional:** "Ensure that..." (Derived strictly from `technical_spec`).

---

## 5. Summary Checklist for AI Generation

Before finalizing the `user_stories` list, the Agent must verify:
1.  [ ] **Vertical:** Does every story deliver runnable value?
2.  [ ] **Format:** Is it strictly *"As a... I want... So that..."*?
3.  [ ] **Small:** Is the scope $\approx$ 2-3 days?
4.  [ ] **Contextual:** Are specific roles used (no generic "Users" if avoidable)?
5.  [ ] **Criteria:** Are pass/fail criteria included?