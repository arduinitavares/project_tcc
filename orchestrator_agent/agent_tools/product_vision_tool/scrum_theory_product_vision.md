# Theory Reference: Product Vision Generation

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018).
**Methodological Phase:** Strategic Initiation (Stage 1 / Chapter 2).
**Target Agent:** `product_vision_tool`

---

## 1. Theoretical Foundation
The Product Vision is the immutable starting point of the Scrum lifecycle. It serves as the "True North" against which all future roadmap items, user stories, and sprint goals are validated.

**Definition (p. 35):**
> *"The product vision is a brief statement of the desired future state that would be achieved by developing and deploying the product."*

**Scientific Function:**
In the "Roadmap to Value" pipeline, the Vision functions as the **Root Node**.
$$Roadmap \subset Backlog \subset Vision$$
If the Vision is ambiguous, the derivative artifacts (Roadmap, Backlog) will fail the "Cohesion" test.

---

## 2. Construction Algorithm: The "Vision Statement" Template
**Ref: Chapter 2, Page 35.**

The Agent must strictly enforce the industry-standard template (derived from Geoffrey Moore, adopted by Layton) to ensure all strategic dimensions are covered.

### The Six-Variable Constraint
The Agent must extract or synthesize exactly six variables to complete the statement:

1.  **For:** The Target Customer (Who is this for?).
2.  **Who:** The Statement of Need (What implies the demand?).
3.  **The:** The Product Name.
4.  **Is a:** The Product Category (Frame of reference).
5.  **That:** The Key Benefit / Compelling Reason to Buy.
6.  **Unlike:** The Primary Competitor or Status Quo.
7.  **Our Product:** The Key Differentiator.

### The Template Syntax
> *"**For** [target customer], **who** [statement of need], **the** [product name] **is a** [product category] **that** [key benefit]. **Unlike** [competitor/alternative], **our product** [primary differentiator]."*



---

## 3. Validation Logic: The "Elevator Pitch" Test
**Ref: Chapter 2, Page 36.**

The Vision must be concise and actionable. The Agent must evaluate the generated Vision against these quality gates:

* **Clarity:** Is it jargon-free? (Can a non-technical stakeholder understand it?)
* **Stability:** Is it broad enough to last for the entire project lifecycle? (Strategies change; Visions rarely do).
* **Focus:** Does it promise *one* primary benefit, or does it dilute value across many?

**Agent Logic Rule:**
If `Count(Benefits) > 2`, the Agent must request refinement. A vision with too many benefits is a "Feature List," not a Vision.

---

## 4. The Output: The Strategic Context
**Ref: Chapter 3, Page 47.**

The output of this agent is not just text; it is the **Input Contract** for the next agent (`backlog_primer`).

> *"To create a product roadmap, you need... A product vision."* (p. 47)

**Integration Constraint:**
The Agent must save the Vision in a structured format (JSON) so that the `backlog_primer` can programmatically query the "Key Benefit" to prioritize requirements.

---

## 5. Agent Workflow & Constraints

| Step | Action | Theoretical Reference | Constraint |
| :--- | :--- | :--- | :--- |
| **1** | **Elicitation** | *Layton (2018), p. 34* | Ask the user for the "Why," "Who," and "What." |
| **2** | **Synthesis** | *Layton (2018), p. 35* | Map user inputs into the "For... Who... The..." template. |
| **3** | **Refinement** | *Layton (2018), p. 36* | Critique the draft. Is it too long? Too vague? |
| **4** | **Finalization** | *Layton (2018), p. 37* | Output the final "Statement" and the "Business Goal." |

### Exclusion Criteria (Out of Scope)
The Product Vision Tool is explicitly forbidden from:
* **Listing Features:** "It will have a login screen" is a Requirement (Stage 2), not a Vision.
* **Setting Dates:** "Available by Q3" is a Roadmap concern (Stage 2).
* **Defining Tech:** "Built in Python" is a Technical Spec, not a Product Vision (unless the product *is* a dev tool).