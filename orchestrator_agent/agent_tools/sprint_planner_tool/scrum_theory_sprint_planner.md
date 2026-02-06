# Theory Reference: Sprint Planning & Task Decomposition

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018).
**Methodological Phase:** Tactical Planning (Chapter 6).
**Target Agent:** `sprint_planner_tool`

---

## 1. Theoretical Foundation
Sprint Planning is the critical event that transitions the project from **Strategic Intent** (Product Backlog) to **Tactical Commitment** (Sprint Backlog).

**Definition (p. 83):**
> *"The goal of the sprint planning meeting is for the scrum team to answer two basic questions: What can be delivered... and how will that work be achieved?"*

### The Two-Part Structural Constraint
The methodology strictly divides this phase into two distinct, sequential halves:
1.  **The "What" (Scope Selection):** Driven by the Product Owner (Value) and bounded by Team Capacity.
2.  **The "How" (Task Decomposition):** Driven solely by the Development Team (Execution).

---

## 2. Part 1: Scope Selection (The "What")
**Ref: Chapter 6, Pages 88–89.**

The Agent must enforce a **"Pull System"** logic. The business cannot force work into the Sprint; the team must pull it based on empirical capacity.

### The Capacity Heuristic (p. 88)
The selection of items is governed by a strict inequality constraint:
$$SelectedItems = \sum(Size(Stories)) \le TeamVelocity$$

**Agent Logic Rule:**
The Agent must prompt for a "Velocity Assumption" (Low/Medium/High) to act as the limiting factor. If the user attempts to select stories exceeding this limit, the Agent must trigger a "Capacity Overload" warning.

### The Sprint Goal Constraint (p. 89)
Before finalizing the selection, the Agent must synthesize a **Sprint Goal**.
> *"The sprint goal is an objective that will be met within the sprint... It provides the development team with guidance on why it is building the increment."*

**Constraint:** The Agent must reject a "Random Bag of Stories." It must enforce **Cohesion** (e.g., "All selected stories support the 'Ingestion' goal").

---

## 3. Part 2: Decomposition (The "How")
**Ref: Chapter 6, Pages 91–92.**

Once stories are selected, the granularity shifts from *User Value* to *Technical Execution*. The Agent must facilitate the transformation of **Vertical Slices** (User Stories) into **Horizontal Steps** (Tasks).

### The Transformation Object Model
* **Input (User Story):** "As a user, I want to login..." (Value-centric).
* **Output (Tasks):** "Create 'Users' table," "Write Auth API," "Design Login CSS" (Implementation-centric).



**Agent Execution Rule:**
For every selected Story, the Agent must generate a `Task List` that covers three dimensions:
1.  **Design/Schema:** Structural changes (e.g., DB tables, API specs).
2.  **Logic/Code:** The actual implementation steps.
3.  **Validation:** Testing requirements (e.g., "Write Unit Tests").

> *"Work is decomposed into units of one day or less."* (p. 92)

---

## 4. The Final Output: The Sprint Backlog
**Ref: Chapter 6, Page 93.**

The final artifact is the **Sprint Backlog**. It differs from the Product Backlog in that it is **owned solely by the Development Team** and serves as the immutable plan for the iteration.

**Validation Checklist:**
The Agent must validate the output against these four criteria before saving:
1.  **Alignment:** Does the scope support the Sprint Goal?
2.  **Completeness:** Do the Tasks fully implement the User Stories?
3.  **Feasibility:** Is the total effort within the Velocity assumption?
4.  **Commitment:** Has the Agent explicitly asked: *"Does this scope feel achievable?"*

---

## 5. Agent Workflow & Constraints

| Step | Action | Theoretical Reference | Constraint |
| :--- | :--- | :--- | :--- |
| **1** | **Goal Setting** | *Layton (2018), p. 89* | Define the "Why" (Sprint Goal) before selecting the "What." |
| **2** | **Capacity Check** | *Layton (2018), p. 88* | Establish Velocity limit. "Pull" items only until limit is reached. |
| **3** | **Selection** | *Layton (2018), p. 88* | Select top-priority items that align with the Goal. |
| **4** | **Decomposition** | *Layton (2018), p. 91* | Break Stories into Technical Tasks (1 day max effort). |

### Exclusion Criteria (Out of Scope)
The Sprint Planner is explicitly forbidden from:
* **Assigning Users:** Scrum relies on self-organization; the Agent lists *work*, not *workers*.
* **Changing Priorities:** The Product Backlog priority is fixed by the PO in the previous phase.
* **Expanding Scope:** No new Features can be added here; only Tasks *for* existing Features.