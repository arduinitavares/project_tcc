# PHASE: Generating the Initial Product Backlog
**Source:** Scrum For Dummies, 2nd Edition (Layton), Chapter 3
**Prerequisite:** A completed Product Vision (Page 36).
**Goal:** Satisfy the requirement on Page 47 to have a "Product Backlog" before building a Roadmap.

## 1. Phase Scope Rules
| IN SCOPE (Do this now) | OUT OF SCOPE (Do NOT do this yet) |
| :--- | :--- |
| **High-Level Requirements:** "Large" items that deliver the Vision (p. 50). | **User Stories:** "As a user, I want..." (Chapter 5). |
| **Rough Prioritization:** Ranking by ROI/Value (p. 50). | **Acceptance Criteria:** Detailed tests (Chapter 6). |
| **Relative Estimation:** T-shirt sizing (S/M/L/XL) (p. 52). | **Tasks:** The "how-to" code/design steps. |
| **Business Value:** "Why do we want this?" | **Sprints:** Assigning items to dates. |

---

## 2. AI Agent Prompts (Execute in Order)

### Step 1: Decomposition (Ref: Page 50)
**System Instruction:**
"Review the Product Vision previously generated. Acting as the Product Owner, break down that Vision into a list of **High-Level Requirements**.

**Constraints:**
1. Do not write full User Stories yet.
2. Focus on 'large' features or capabilities that directly support the 'Key Benefit' identified in the Vision.
3. List at least 10 requirements that are distinct and 'just enough to be able to estimate'."

### Step 2: Prioritization (Ref: Pages 50–51)
**System Instruction:**
"Take the list of High-Level Requirements above and **prioritize them** into an ordered list (1 being highest priority).

**Reasoning Logic:**
You must rank them based on the factors defined in *Scrum For Dummies*:
1. **Revenue/Value:** Which items provide the most immediate value?
2. **Customer Satisfaction:** Which items solve the user's 'Need' (from the Vision) best?

**Output format:**
[Rank] - [Requirement Name] - [Brief Justification based on Value]"

### Step 3: Estimation (Ref: Page 52)
**System Instruction:**
"Now, estimate the effort for each prioritized requirement using **Relative Estimation**.

**Constraints:**
1. Do not use hours or days.
2. Use **T-Shirt Sizes** (S, M, L, XL) to indicate the complexity and effort relative to each other.
3. Assume 'S' is a simple feature and 'XL' is a complex, multi-part feature.

**Final Output:**
Present a table with columns: [Priority], [Requirement], [Value Justification], [Estimated Effort (Size)]."