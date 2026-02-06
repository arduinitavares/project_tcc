# Theory Reference: Initial Product Backlog Generation

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018).
**Methodological Phase:** Pre-Planning / Roadmap Preparation.
**Target Agent:** `backlog_primer`

---

## 1. Theoretical Foundation
In the framework defined by Layton (2018), the creation of value follows a strict hierarchy known as the **"Roadmap to Value."** This phase bridges the gap between the abstract **Product Vision** (Stage 1) and the temporal **Product Roadmap** (Stage 2).

According to **Chapter 3 (p. 47)**, the generation of a Product Backlog is a mandatory prerequisite constraint:
> *"To create a product roadmap, you need the following: A product vision... [and] A product backlog: The list of what is in scope for a product, ordered by priority."*

This agent functions as the **"Stage Gate"** regarding this constraint, ensuring that no roadmap planning occurs until the scope is identified and quantified.

---

## 2. Object Model & Granularity

### The "Requirement" vs. "User Story" Distinction
A critical distinction in Layton’s methodology is the granularity of items at this stage.
* **Artifact:** High-Level Requirement.
* **Source:** Chapter 3, Page 50 ("Breaking down requirements").
* **Definition:** Functional capabilities that are *"just enough to be able to estimate and prioritize"* (p. 50), but not yet detailed enough for execution.

**Scientific constraint for the Agent:**
The Agent must **reject** detailed User Stories (e.g., "As a user, I want to click the blue button") at this stage. It must focus on **Gross Requirements** (e.g., "User Authentication System") to allow for the *macro-estimation* required for roadmapping.

---

## 3. The Prioritization Algorithm
**Ref: Chapter 3, Pages 50–51.**

The ordering of the backlog is not arbitrary. The agent must apply a value-based sorting algorithm defined by Layton:

> *"The product owner must know which requirements should be uppermost... You prioritize your requirements based on..."* (p. 50)

**The Value Factors (p. 51):**
1.  **Revenue / Financial Impact:** Immediate ROI.
2.  **Customer Satisfaction:** Alignment with the "Key Benefit" defined in the Vision.
3.  **Risk:** Addressing high-risk items early (implied in Roadmap strategy).

**Agent Logic Rule:**
$$Priority = f(Revenue, Customer Satisfaction)$$
The agent must output an **Ordered List**, where $Item_{n}$ is strictly more valuable than $Item_{n+1}$.

---

## 4. The Estimation Heuristic
**Ref: Chapter 3, Page 52.**

To facilitate the Roadmap (Stage 2), items must have a cost associated with them. However, strict time estimation is prohibited at this stage.

> *"You need to know roughly how much effort each requirement will take... You don't need exact time estimates."* (p. 52)

**Relative Estimation Protocol:**
Instead of absolute units (hours/days), the methodology prescribes **Relative Sizing**.
* **Method:** T-Shirt Sizing (S, M, L, XL) or Fibonacci-like relative points.
* **Purpose:** To allow "Capacity Bucket Filling" during the Roadmap phase (e.g., "We can fit 2 XL items in Q1").

---

## 5. Agent Workflow & Constraints

| Step | Action | Theoretical Reference | Constraint |
| :--- | :--- | :--- | :--- |
| **1** | **Decomposition** | *Layton (2018), p. 50* | Break Vision $\rightarrow$ Requirements. Must be "distinct" and "estimable." |
| **2** | **Prioritization** | *Layton (2018), p. 50* | Order by Business Value. No "Must/Should/Could" categories; use strict 1..N ranking. |
| **3** | **Estimation** | *Layton (2018), p. 52* | Apply Relative Sizes (S/M/L/XL). Do not hallucinate exact dates or hours. |

### Exclusion Criteria (Out of Scope)
To maintain the integrity of the *Scrum For Dummies* framework, this agent is explicitly forbidden from generating:
* **Tasks:** (Sprint Planning artifact, Chapter 6).
* **Acceptance Criteria:** (User Story artifact, Chapter 5).
* **Sprints:** (Execution artifact, Chapter 7).