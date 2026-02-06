# Theory Reference: Technical Constraints & Authority

**Source Authority:** *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018).
**Methodological Phase:** Feasibility & Compliance (Pre-Planning).
**Target Agent:** `spec_authority_compiler_agent`

---

## 1. Theoretical Foundation
While Scrum focuses on value (Product Owner), it operates within the boundaries of reality (Technology & Business). This agent operationalizes the **"Feasibility Constraints"** required to build a valid Roadmap.

**Definition (Roadmap Inputs, p. 47):**
> *"To create a product roadmap, you need... Technology (What technology do you need to create the product?), Budget, Team capabilities, and Market conditions."*

**Scientific Function:**
This agent acts as the **Feasibility Filter**. It aggregates unstructured technical documentation (PDFs, Markdown specs, API docs) into structured **Constraints**.
$$ValidPlan = Desirable(Vision) \cap Feasible(Specs)$$
Without this agent, the `roadmap_builder` would optimize purely for value, potentially scheduling technically impossible sequences.

---

## 2. The "Definition of Done" (DoD) Standard
**Ref: Chapter 2, Page 26.**

This agent is also responsible for compiling the global standards that apply to *every* User Story, known as the **Definition of Done**.

> *"The definition of done is a clear and concise list of criteria that a software increment must adhere to... ensuring transparency and quality."* (p. 26)

**Agent Logic Rule:**
The Agent must extract "Non-Functional Requirements" (NFRs) from the source documents (e.g., "Must run on CPU," "Response < 200ms") and append them as **Implicit Acceptance Criteria** to every User Story generated later.

---

## 3. Constraint Extraction Logic
**Ref: Chapter 3, Page 48 (Dependencies).**

To support the Roadmapping phase, this agent must identify **Technical Dependencies** that dictate the sequence of work.

> *"You arrange product requirements into a time line... taking into account dependencies."* (p. 48)

**The Compilation Algorithm:**
The Agent scans input files for three types of "Hard Constraints":
1.  **Architecture:** (e.g., "The Ingestion module must consume the Camera API").
2.  **Environment:** (e.g., "The system must operate offline").
3.  **Compliance:** (e.g., "Data must be encrypted at rest").

**Output:** A `GlobalContext` object that overrides any User Story that conflicts with these rules.

---

## 4. The Integration Contract
**Ref: Chapter 4, Page 61 (Release Planning).**

This agent serves as the "Technologist" voice in the Planning Poker/Estimation process.

> *"The product owner brings the 'what' (goals/requirements). The team brings the 'how' (technical feasibility)."* (Implied role, p. 61).

**System Role:**
Since the AI "Team" cannot physically inspect code, this Agent simulates the "Team's Memory." It ensures that when the `sprint_planner_tool` breaks down tasks, it uses the correct terminology (e.g., referencing specific table names or library versions found in the specs).

---

## 5. Agent Workflow & Constraints

| Step | Action | Theoretical Reference | Constraint |
| :--- | :--- | :--- | :--- |
| **1** | **Ingestion** | *Layton (2018), p. 47* | Read "Technology" inputs (Files, Specs, Memos). |
| **2** | **Extraction** | *Layton (2018), p. 26* | Identify global standards (DoD) and NFRs. |
| **3** | **Contextualization**| *Layton (2018), p. 48* | Map technical constraints to Roadmap Themes. |
| **4** | **Enforcement** | *Layton (2018), p. 104* | Provide the "Quality Gate" for future Acceptance Criteria. |

### Exclusion Criteria (Out of Scope)
The Spec Authority is explicitly forbidden from:
* **Inventing Requirements:** It only *reads* existing constraints; it does not create new product features (PO job).
* **Prioritizing:** It defines *feasibility*, not *importance* (PO job).
* **Scheduling:** It identifies *dependencies*, not *dates* (Scrum Master/Team job).