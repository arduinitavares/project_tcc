# Theory Reference: Sprint Planning

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton.
**Phase:** Sprint Planning (Chapter 6).
**Purpose:** Defines the rules for moving from a "Prioritized Product Backlog" (Stage 2) to a "Committed Sprint Backlog" (Execution).

---

## 1. Definition and Objective
**Source:** Page 83, Chapter 6 ("Sprint Planning").

Sprint Planning is the collaborative meeting that initiates the Sprint. It is not just a mechanism to assign work; it is a design and negotiation session.
> *"The goal of the sprint planning meeting is for the scrum team to answer two basic questions: What can be delivered... and how will that work be achieved?"* (Page 83)

### The Two-Part Structure
The book strictly divides this phase into two distinct halves:
1.  **Part 1: The "What"** (Product Owner Focus)
2.  **Part 2: The "How"** (Development Team Focus)

---

## 2. Part 1: "What Can Be Done?" (Scope Selection)
**Source:** Page 88.

In this first half, the **Product Owner** presents the highest priority items from the Product Backlog (which you generated in the previous phase).

### The Selection Logic
The Development Team—*not the Product Owner*—pulls work into the Sprint based on their capacity.
> *"The development team selects items from the product backlog to include in the current sprint. The scrum team respects the development team’s realistic projection of what it can achieve."* (Page 88)

### Key Artifact: The Sprint Goal
**Source:** Page 89.
Before selecting too many items, the team must define a **Sprint Goal**.
> *"The sprint goal is an objective that will be met within the sprint through the implementation of the product backlog... It provides the development team with guidance on why it is building the increment."* (Page 89)
* **Rule:** The Goal is the "Why." The Stories are the "What."

---

## 3. Part 2: "How Will It Be Done?" (Task Decomposition)
**Source:** Page 91.

Once the stories are selected, the focus shifts to the Development Team. They decompose the "User Stories" (Vertical Slices) into **Tasks** (Technical Steps).

### The Task Breakdown
**Source:** Page 92.
> *"The development team usually starts by designing the system and the work needed to convert the product backlog into a working product increment."* (Page 91)
> *"Work is decomposed into units of one day or less."* (Page 92)

**Distinction:**
* **User Story:** "As a user, I want to login..." (Value).
* **Task:** "Create 'Users' table in DB," "Design login form CSS," "Write authentication API." (Implementation).

---

## 4. The Output: The Sprint Backlog
**Source:** Page 93.

The final output of this phase is the **Sprint Backlog**.
> *"The sprint backlog is the set of product backlog items selected for the sprint, plus a plan for delivering the product increment and realizing the sprint goal."* (Page 93)

**Validation Checklist (Page 93):**
1.  Does it include the selected User Stories?
2.  Does it include the plan (Tasks) for each story?
3.  Is the total work feasible within the team's velocity?
4.  Is there a clear Sprint Goal?

---

## 5. Rules for the AI Agent (`sprint_planner_tool`)

To act as a rigorous Scrum expert during this phase, the AI must enforce:

1.  **Capacity Check:** Do not allow the user to select infinite stories. Ask for a "Velocity" or "Capacity" assumption (e.g., "We can do 3 'Medium' stories").
2.  **Sprint Goal Enforcement:** Require the user to explicitly state a **Sprint Goal** before finalizing the scope. The stories selected must support this goal.
3.  **Task Decomposition (Optional but Recommended):** Ask if the user wants to break the stories down into technical tasks now, or leave that for the team (users) to do manually.
4.  **Commitment:** The output is not a "wishlist"; it is a "commitment." The agent should ask: *"Does this scope feel achievable in [X] weeks?"*