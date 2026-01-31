# Planning Workflow Documentation
## Vision → Specification → Roadmap → Features → Stories → Sprint Planning (COMPLETE PIPELINE)

**Last Updated**: January 31, 2026  
**Status**: ✅ **Spec-Driven Architecture Implemented**  
**Purpose**: Reference document for understanding the multi-agent planning workflow in the Autonomous Agile Management Platform

---

## Table of Contents
1. [Overview](#overview)
2. [Phase 1: Vision Planning](#phase-1-vision-planning)
3. [Phase 2: Specification Authority](#phase-2-specification-authority)
4. [Phase 3: Roadmap Planning](#phase-3-roadmap-planning)
5. [Phase 4: Database Structure Creation](#phase-4-database-structure-creation)
6. [Phase 5: User Story Generation with Spec Validation](#phase-5-user-story-generation)
7. [Phase 6: Sprint Planning](#phase-6-sprint-planning)
8. [Phase 7: Sprint Execution](#phase-7-sprint-execution)
9. [State Management Architecture](#state-management-architecture)
10. [Orchestrator State Machine](#orchestrator-state-machine)
11. [Key Design Patterns](#key-design-patterns)
12. [Code Examples](#code-examples)

---

## Overview

The system implements a **conversational, iterative planning workflow** where specialized agents guide users through structured product discovery. The workflow progresses through five main phases:

```
User Requirements (Unstructured)
         ↓
    Vision Agent
         ↓
Vision Statement (7 Components)
         ↓
  Spec Authority (Compiler)
         ↓
Compiled Invariants & Gates
         ↓
    Roadmap Agent
         ↓
Roadmap Themes (With Features)
         ↓
  Database Creation
         ↓
Theme → Epic → Feature Hierarchy
         ↓
   Story Pipeline
         ↓
Story Draft → INVEST Validation (Pinned to Spec) → Refinement
         ↓
User Stories (Backlog Ready)
         ↓
   Sprint Planning

         ↓
Sprint Goal + Story Selection + Team
         ↓
   Sprint Execution
         ↓
Status Updates → Sprint Completion → Velocity Metrics
```

### Core Principles
- **Stateless Agents**: Agents don't maintain memory; state is injected as JSON
- **Incremental Refinement**: Each turn merges new input with preserved data
- **Structured Output**: All agents return validated Pydantic schemas
- **Persistent State**: Orchestrator maintains conversation state in SQLite

---

## Phase 1: Vision Planning

### Agent: `product_vision_tool` (Product Vision Agent)

**Objective**: Build a complete product vision through multi-turn conversation

### The 7 Required Components

| Component | Description | Example |
|-----------|-------------|---------|
| `project_name` | Product/project name | "TaskMaster Pro" |
| `target_user` | Who is the customer | "Busy professionals managing multiple projects" |
| `problem` | Pain point being solved | "Scattered task management across different tools" |
| `product_category` | What type of product | "Web-based task management application" |
| `key_benefit` | Primary value proposition | "Unified inbox that consolidates all tasks" |
| `competitors` | Existing alternatives | "Asana, Trello, Monday.com" |
| `differentiator` | Unique selling point | "AI-powered priority suggestions based on deadlines" |

### Conversation Flow

```
1. User provides initial input
   ↓
2. Agent analyzes and extracts known components
   ↓
3. Agent sets unknown components to `null`
   ↓
4. Agent generates clarifying questions for `null` fields
   ↓
5. User answers questions
   ↓
6. Agent MERGES answers with previous data (preserves existing)
   ↓
7. Repeat steps 3-6 until all 7 components are filled
   ↓
8. Agent sets `is_complete: true`
   ↓
9. Agent generates final vision statement
```

### Vision Statement Template

```
For [target_user] who [problem], 
[project_name] is a [product_category] that [key_benefit]. 
Unlike [competitors], our product [differentiator].
```

### State Management Pattern

**Input Schema:**
```python
{
    "user_raw_text": "User's new input or feedback",
    "prior_vision_state": "JSON string of VisionComponents OR 'NO_HISTORY'"
}
```

**Output Schema:**
```python
{
    "updated_components": {
        "project_name": "TaskMaster Pro",
        "target_user": "Busy professionals",
        # ... all 7 components
    },
    "is_complete": true,
    "product_vision_statement": "For busy professionals who...",
    "clarifying_questions": []
}
```

### Critical Merge Logic

The agent MUST preserve existing data when processing new input:

**Example:**
```python
# Scenario
prior_vision_state = {
    "project_name": "Alpha",
    "target_user": null
}
user_raw_text = "The target user is Chefs."

# ✅ CORRECT: Preserve project_name, update target_user
result = {
    "project_name": "Alpha",      # KEPT
    "target_user": "Chefs"         # UPDATED
}

# ❌ INCORRECT: Losing existing data
result = {
    "project_name": null,          # LOST!
    "target_user": "Chefs"
}
```

### Database Persistence

When user confirms (says "Save", "Yes", "Looks good"):

```python
save_vision_tool(vision_input={
    "project_name": "TaskMaster Pro",
    "product_vision_statement": "For busy professionals...",
    "updated_components": { ... }  # All 7 components
})
```

**Database Action:**
- Creates or updates `products` table record
- Sets `vision` field with the statement
- Creates base product structure for roadmap phase

---

## Phase 2: Specification Authority

### Agent: `spec_authority_compiler_agent`

**Objective**: Compile Technical Specification into deterministic authority.

**Inputs**:
- Product ID
- Raw Technical Specification (text or file)

**Process**:
1. **Spec Ingestion**: User provides spec text.
2. **Compilation**: Agent compiles spec into `CompiledSpecAuthority` with invariants.
3. **Acceptance**: Authority is accepted (Status: CURRENT).
4. **Pinning**: Spec Version ID is pinned for downstream generation.

**Outputs**:
- `SpecRegistry` entry
- `CompiledSpecAuthority` artifact (Validation Gates)

---

## Phase 3: Roadmap Planning

### Agent: `product_roadmap_tool` (Product Roadmap Agent)

**Objective**: Convert vision into prioritized themes and features

### The 4-Step Roadmap Process

#### Step 1: Identify Requirements (Epics/Themes)
- Agent asks: "What are the high-level capabilities or feature groups?"
- User provides unstructured requirements
- **State**: `is_complete: false`, `roadmap_draft: []`

#### Step 2: Arrange and Group Requirements
- Agent creates `RoadmapTheme` objects
- Each theme contains:
  - `theme_name`: Descriptive name (e.g., "User Management")
  - `key_features`: List of feature names under this theme
  - `time_frame`: null (not yet prioritized)
  - `justification`: null (not yet explained)
- Agent asks: "How should we prioritize these themes?"
- **State**: `is_complete: false`, themes populated

#### Step 3: Estimate and Order (Prioritize)
- Agent analyzes prioritization feedback
- Updates existing themes (NEVER replaces):
  - Adds `time_frame`: "Now" | "Next" | "Later"
  - Adds `justification`: Reasoning for priority
- Agent asks: "Does this timeline make sense?"
- **State**: `is_complete: false`, themes enhanced

#### Step 4: Attach High-Level Time Frames (Complete)
- User confirms timeline
- Agent sets: `is_complete: true`, `clarifying_questions: []`
- **State**: Ready for database persistence

### Roadmap Theme Schema

```python
{
    "theme_name": "Core Authentication",
    "key_features": [
        "User registration",
        "Login/logout",
        "Password reset",
        "OAuth integration"
    ],
    "time_frame": "Now",
    "justification": "Foundation for all other features; enables user identity"
}
```

### Example Roadmap Draft

```json
{
    "roadmap_draft": [
        {
            "theme_name": "Core Authentication",
            "key_features": ["User registration", "Login/logout", "OAuth integration"],
            "time_frame": "Now",
            "justification": "Essential foundation"
        },
        {
            "theme_name": "Task Management",
            "key_features": ["Create tasks", "Assign tasks", "Task filtering"],
            "time_frame": "Next",
            "justification": "Primary product value"
        },
        {
            "theme_name": "AI Suggestions",
            "key_features": ["Priority prediction", "Smart scheduling"],
            "time_frame": "Next",
            "justification": "Differentiator; requires task data first"
        },
        {
            "theme_name": "Team Collaboration",
            "key_features": ["Comments", "File sharing", "Notifications"],
            "time_frame": "Later",
            "justification": "Enhancement after core functionality proven"
        }
    ],
    "is_complete": true,
    "clarifying_questions": []
}
```

### State Management Pattern

**Input Schema:**
```python
{
    "product_vision_statement": "For busy professionals who...",
    "prior_roadmap_state": "JSON string of previous draft OR 'NO_HISTORY'",
    "user_input": "User's requirements, answers, or refinements"
}
```

**Critical Rule**: ALWAYS preserve and refine `roadmap_draft` from `prior_roadmap_state`. Add to it, don't replace it.

---

## Phase 4: Database Structure Creation

### Function: `save_roadmap_tool()`

When the roadmap is saved, the system creates a **hierarchical database structure**:

```
Product (existing record, ID already known)
    ├── Theme 1: "Now - Core Authentication"
    │       └── Epic: "Core Authentication"
    │               ├── Feature: "User registration"
    │               ├── Feature: "Login/logout"
    │               ├── Feature: "Password reset"
    │               └── Feature: "OAuth integration"
    │
    ├── Theme 2: "Now - Task Management"
    │       └── Epic: "Task Management"
    │               ├── Feature: "Create tasks"
    │               ├── Feature: "Assign tasks"
    │               └── Feature: "Task filtering"
    │
    └── Theme 3: "Next - AI Suggestions"
            └── Epic: "AI Suggestions"
                    ├── Feature: "Priority prediction"
                    └── Feature: "Smart scheduling"
```

### Database Schema Mapping

| Roadmap Concept | Database Table | Relationships |
|-----------------|----------------|---------------|
| Roadmap Theme | `themes` | belongs to `products` |
| Theme Epic | `epics` | belongs to `themes` |
| Key Feature | `features` | belongs to `epics` |

### Creation Logic

```python
def _create_structure_from_themes(session, product_id, themes):
    for theme_input in themes:
        # 1. Create Theme
        theme_title = f"{theme_input.time_frame} - {theme_input.theme_name}"
        theme = Theme(
            title=theme_title,
            description=theme_input.justification,
            product_id=product_id
        )
        session.add(theme)
        session.commit()
        
        # 2. Create ONE Epic per theme (uses theme name)
        epic = Epic(
            title=theme_input.theme_name,
            summary=theme_input.justification,
            theme_id=theme.theme_id
        )
        session.add(epic)
        session.commit()
        
        # 3. Create Features from key_features list
        for feature_name in theme_input.key_features:
            feature = Feature(
                title=feature_name,
                description="",
                epic_id=epic.epic_id
            )
            session.add(feature)
            session.commit()
```

### Database Tables

**Key Fields:**

```sql
-- themes table
CREATE TABLE themes (
    theme_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    product_id INTEGER,
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

-- epics table
CREATE TABLE epics (
    epic_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    summary TEXT,
    theme_id INTEGER,
    FOREIGN KEY (theme_id) REFERENCES themes(theme_id)
);

-- features table
CREATE TABLE features (
    feature_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    epic_id INTEGER,
    FOREIGN KEY (epic_id) REFERENCES epics(epic_id)
);
```

---

## Phase 5: User Story Generation with Spec Validation

### Agent System: Story Pipeline (2-Agent LoopAgent)

**Objective**: Transform features into INVEST-ready, spec-compliant user stories through iterative refinement

> **Note:** INVEST principles (Independent, Negotiable, Valuable, Estimable, Small, Testable) are enforced directly by the Draft Agent's instructions. The separate INVEST Validator was removed as it was redundant—the Draft Agent already generates INVEST-compliant stories.

### Story Pipeline Architecture

**Location:** `orchestrator_agent/agent_tools/story_pipeline/`

The story pipeline uses a **LoopAgent + SequentialAgent hybrid** pattern:

```
LoopAgent: story_validation_loop (max 4 iterations)
    ↓
SequentialAgent: Draft → Spec Validate → Refine
    ↓
Early Exit: Spec compliant OR max iterations reached
    ↓
Save to Database: status=TO_DO
```

### Two-Agent Pipeline Flow

> **Architecture Change:** The INVEST Validator Agent was removed. INVEST principles are now enforced directly by the Draft Agent's instructions, which explicitly require Independent, Negotiable, Valuable, Estimable, Small, and Testable stories. The Spec Validator focuses on domain-specific compliance.

#### Agent 1: Story Draft Agent
**File:** `story_pipeline/story_draft_agent/agent.py`

**Input:**
- Feature description (title + epic context)
- Product vision statement
- Alignment constraints from `alignment_checker.py`

**INVEST Enforcement (Built-in):**
The Draft Agent's instructions explicitly require INVEST-compliant stories:
- **Independent**: Story can be developed without depending on other stories
- **Negotiable**: Details can be discussed, not a rigid contract
- **Valuable**: Delivers clear value to the user
- **Estimable**: Small enough to estimate accurately
- **Small**: Fits in a single sprint (1-8 story points)
- **Testable**: Acceptance criteria are verifiable

**Output:**
- Story title (user-centric format: "As a [role], I want [goal] so that [benefit]")
- Story description (context, scope, constraints)
- Acceptance Criteria (3-5 testable conditions)

**Example:**
```python
# Feature: "Email notifications for task updates"
# Output:
{
    "title": "As a team member, I want email alerts for task changes so that I stay informed without checking the app constantly",
    "description": "Users receive configurable email notifications when tasks assigned to them are updated...",
    "acceptance_criteria": [
        "Email sent within 5 minutes of task update",
        "Notification includes task name, what changed, and who changed it",
        "Users can disable notifications in settings"
    ]
}
```

#### Agent 2: Spec Validator Agent
**File:** `story_pipeline/spec_validator_agent/agent.py`

**Purpose:** Validates stories against the technical specification requirements

**Domain-Aware Validation:**
The spec validator uses `spec_requirement_extractor.py` to:
1. Extract hard requirements from the spec (MUST, SHALL, REQUIRED patterns)
2. Bind requirements to stories based on domain keywords (ingestion, review, audit, etc.)
3. Check acceptance criteria for concrete artifacts and invariants

| Domain | Example Keywords | Required Artifacts |
|--------|------------------|-------------------|
| **Ingestion** | upload, pdf, document | `doc_revision_id`, `input_hash` |
| **Revision** | version, change, update | `revision_id`, event log |
| **Review** | approve, reject, corrections | `review_actions_vN.jsonl` |
| **Provenance** | model, inference, training | `model_provenance` |
| **Audit** | history, tracking, log | event-sourced deltas |

**Output:**
```json
{
    "is_compliant": false,
    "issues": [
        "Missing required artifact: immutable doc_revision_id",
        "AC lacks input hash reference for traceability"
    ],
    "suggestions": [
        "Add AC: 'System generates immutable doc_revision_id from SHA-256 hash'",
        "Add AC: 'System captures input_hash for each uploaded PDF'"
    ],
    "domain_compliance": {
        "domain_name": "ingestion",
        "requirements_satisfied": 3,
        "requirements_bound": 6,
        "critical_gaps": ["immutable doc_revision_id invariant"]
    }
}
```

#### Agent 3: Story Refiner Agent
**File:** `story_pipeline/story_refiner_agent/agent.py`

**Input:**
- Original story draft
- Spec validator feedback
- Vision constraints

**Refinement Strategy:**
- **Spec compliance is BLOCKING** - must fix spec violations before story is valid
- **Add missing artifacts** using exact names from suggestions
- **Maintain vision alignment** (don't introduce forbidden capabilities)

**Example Refinement:**
```python
# Iteration 1: Spec NOT compliant (missing doc_revision_id)
# Original AC: "User can upload PDF documents"

# Refinement:
# - AC 1: "User can upload PDF documents via upload interface"
# - AC 2: "System generates immutable doc_revision_id from SHA-256(pdf_content)"
# - AC 3: "System captures input_hash for each uploaded PDF"
# Result: Spec compliant → ACCEPT
```

### Vision Alignment Enforcement

**File:** `orchestrator_agent/agent_tools/story_pipeline/alignment_checker.py`

**Purpose:** Prevent LLM drift from product vision through deterministic constraint checking

#### 5 Vision Constraint Categories

| Category | Vision Keyword | Forbidden Story Elements | Example |
|----------|----------------|--------------------------|---------|
| **Platform** | "mobile-only", "web-only" | Desktop, web, mobile (opposite) | Vision: "mobile-only" → Story can't mention "web dashboard" |
| **Connectivity** | "offline-first", "cloud-native" | Real-time sync, local storage (opposite) | Vision: "offline-first" → Story can't require "live cloud sync" |
| **UX Philosophy** | "distraction-free", "gamified" | Notifications, badges (opposite) | Vision: "distraction-free" → Story can't add "push notifications" |
| **User Segment** | "enterprise", "casual users" | Industrial terms, complex features (opposite) | Vision: "casual users" → Story can't require "SAML SSO" |
| **Scope** | "simple", "AI-powered" | Advanced analytics, manual config (opposite) | Vision: "simple" → Story can't need "custom SQL queries" |

#### FAIL-FAST Validation Flow

```python
# BEFORE pipeline runs
alignment_result = check_alignment_before_pipeline(
    vision="offline-first mobile app for casual recipe browsing",
    feature_description="Real-time collaborative editing with cloud sync"
)

# Returns:
{
    "aligned": False,
    "violations": [
        "Forbidden: real-time (conflicts with offline-first)",
        "Forbidden: cloud sync (conflicts with offline-first)",
        "Forbidden: collaborative (too complex for casual users)"
    ]
}
# Pipeline does NOT run → Save LLM tokens, prevent bad stories
```

#### Post-Validation Drift Detection

```python
# AFTER pipeline generates story
alignment_result = check_alignment_after_validation(
    vision="mobile-only app",
    story_title="As a user, I want to access my data from the web dashboard...",
    story_description="...",
    acceptance_criteria=[...]
)

# Returns:
{
    "aligned": False,
    "violations": ["Forbidden: web dashboard (conflicts with mobile-only)"]
}
# Story rejected, pipeline re-runs with stricter constraints
```

### Complete Pipeline Iteration Example

**Scenario:** Feature "User profile management" in "Now" roadmap

```
┌─────────────────────────────────────────────────────────┐
│ ITERATION 1                                             │
├─────────────────────────────────────────────────────────┤
│ 1. Alignment Check: ✅ PASS                            │
│ 2. Draft Agent: Generates story                        │
│    - Title: "As a user, I want to manage my profile"   │
│    - AC: "Profile page exists", "Users can edit"       │
│ 3. INVEST Validator: Score 65                          │
│    - Independent: 20, Negotiable: 15, Valuable: 10     │
│    - Estimable: 5, Small: 15, Testable: 0             │
│    - Feedback: "Too vague, no clear benefit"           │
│ 4. Continue? YES (score < 90)                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ ITERATION 2                                             │
├─────────────────────────────────────────────────────────┤
│ 1. Refiner Agent: Improves Valuable, Testable          │
│    - Title: "...so that I can keep my contact info up  │
│      to date and control privacy settings"             │
│    - AC: "Edit name, email, phone (saved on submit)"   │
│           "Toggle profile visibility (public/private)"  │
│           "Changes reflected within 5 seconds"         │
│ 2. INVEST Validator: Score 85                          │
│    - Valuable: 20 ↑, Testable: 15 ↑                    │
│    - Feedback: "Estimable improved but scope unclear"   │
│ 3. Continue? YES (score < 90)                          │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ ITERATION 3                                             │
├─────────────────────────────────────────────────────────┤
│ 1. Refiner Agent: Narrows scope                        │
│    - Description: "Limited to name, email, phone only. │
│      Avatar upload is separate story."                 │
│    - AC: Added acceptance test scenario                │
│ 2. INVEST Validator: Score 92 ✅                       │
│    - All dimensions ≥ 15                               │
│ 3. Alignment Check: ✅ PASS                            │
│ 4. Continue? NO (score ≥ 90) → ACCEPT                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│ SAVE TO DATABASE                                        │
├─────────────────────────────────────────────────────────┤
│ UserStory record created:                               │
│   - status: TO_DO                                       │
│   - validation_score: 92                                │
│   - feature_id: 24                                      │
│ WorkflowEvent emitted:                                  │
│   - event_type: STORY_GENERATED                        │
│   - metadata: {score: 92, iterations: 3}               │
└─────────────────────────────────────────────────────────┘
```

### Pipeline Tools API

#### 1. Process Single Feature
```python
process_feature_for_stories(
    product_id=10,
    feature_id=24,
    product_vision="For casual cooks who want quick recipes...",
    max_iterations=4
)

# Returns:
{
    "success": True,
    "stories_created": 1,
    "feature_title": "User profile management",
    "iterations_used": 3,
    "final_score": 92,
    "story_ids": [45]
}
```

#### 2. Batch Process Features
```python
process_features_batch(
    product_id=10,
    feature_ids=[24, 25, 26],
    product_vision="...",
    max_features=10
)

# Returns:
{
    "success": True,
    "total_stories_created": 3,
    "results": [
        {"feature_id": 24, "stories": 1, "score": 92},
        {"feature_id": 25, "stories": 1, "score": 88},
        {"feature_id": 26, "stories": 0, "error": "Alignment violation"}
    ]
}
```

#### 3. Save Pre-Validated Stories
```python
# For stories generated externally or manually
save_validated_stories(
    product_id=10,
    stories=[
        {
            "title": "As a user...",
            "description": "...",
            "acceptance_criteria": ["AC1", "AC2"],
            "feature_id": 24,
            "validation_score": 95
        }
    ]
)
```

### Exit Conditions

The pipeline terminates when:
1. **Early Success:** INVEST score ≥ 90 (story accepted)
2. **Max Iterations:** 4 refinement cycles completed (accept best score)
3. **Alignment Failure:** Vision violations persist after 2 attempts (reject feature)

**Quality Thresholds:**
- **90-100:** Production-ready, save immediately
- **70-89:** Acceptable after max iterations, flag for review
- **< 70:** Manual intervention required, pipeline failed

### State Management

**Pipeline does NOT persist state between features:**
- Each feature starts fresh (no accumulated context)
- Vision statement passed to every feature
- Alignment constraints re-evaluated per feature

**Story state after pipeline:**
```python
UserStory(
    story_id=45,
    title="As a user, I want to manage my profile...",
    description="...",
    acceptance_criteria=["AC1", "AC2", "AC3"],
    status=StoryStatus.TO_DO,  # Ready for sprint planning
    validation_score=92,
    feature_id=24,
    product_id=10
)
```

---

## Phase 6: Sprint Planning

### Tools: Sprint Planning Toolkit (Scrum Master MVP)

**Objective**: Plan sprints using the Draft → Review → Commit pattern

### Sprint Planning Flow

```
1. User requests sprint planning
   ↓
2. get_backlog_for_planning() → Shows TO_DO stories grouped by theme
   ↓
3. User provides: Sprint Goal, Capacity, Story Selection
   ↓
4. plan_sprint_tool() → Creates draft with validation
   ↓
5. User reviews draft
   ↓
6. save_sprint_tool() → Persists sprint with WorkflowEvent metrics
```

### Sprint Planning Tools

| Tool | Purpose | Input |
|------|---------|-------|
| `get_backlog_for_planning` | Query stories ready for sprint | `{product_id, only_ready: true}` |
| `plan_sprint_tool` | Create draft sprint | `{product_id, sprint_goal, selected_story_ids, duration_days}` |
| `save_sprint_tool` | Persist sprint to DB | `{product_id, team_id, sprint_goal, selected_story_ids, start_date, end_date}` |
| `get_sprint_details` | View sprint info | `{sprint_id}` or `{product_id}` |
| `list_sprints` | List all sprints | `{product_id}` |

### Sprint Draft Schema

```python
{
    "product_id": 10,
    "product_name": "MealMuse",
    "team_id": 2,
    "team_name": "Team MealMuse",
    "team_auto_created": false,
    "sprint_goal": "Deliver MVP for recipe discovery",
    "start_date": "2026-01-17",
    "end_date": "2026-01-31",
    "duration_days": 14,
    "validated_stories": [
        {
            "story_id": 35,
            "title": "Access app on iOS and Android",
            "story_points": null,
            "feature_title": "Cross-platform mobile app"
        }
    ],
    "invalid_stories": [],
    "total_story_points": 0,
    "capacity_points": null
}
```

### Team Auto-Creation Pattern

When no team exists for a product, the system auto-creates one:

```python
# Auto-create team with disclosure
team = Team(name=f"Team {product.name}")
session.add(team)

# Link to product
product_team = ProductTeam(product_id=product.product_id, team_id=team.team_id)
session.add(product_team)

# Return disclosure message
return {
    "team_auto_created": True,
    "team_disclosure": "ℹ️ Created 'Team MealMuse' as your default team."
}
```

### WorkflowEvent Metrics

Sprint planning emits events for TCC evaluation:

```python
# On draft creation
WorkflowEvent(
    event_type=WorkflowEventType.SPRINT_PLAN_DRAFT,
    product_id=product_id,
    event_metadata={"story_count": 5, "total_points": 0}
)

# On save
WorkflowEvent(
    event_type=WorkflowEventType.SPRINT_PLAN_SAVED,
    sprint_id=sprint.sprint_id,
    duration_seconds=435.26,  # Planning duration
    event_metadata={"stories_linked": 5, "tasks_created": 0}
)
```

---

## Phase 7: Sprint Execution

### Tools: Sprint Execution Toolkit

**Objective**: Execute sprints by updating story status and tracking progress

### Sprint Execution Flow

```
1. Sprint is PLANNED
   ↓
2. Work begins → Stories move TO_DO → IN_PROGRESS
   ↓
3. update_story_status() → Track progress
   ↓
4. Stories complete → IN_PROGRESS → DONE
   ↓
5. Sprint ends → complete_sprint()
   ↓
6. Velocity metrics captured
```

### Sprint Execution Tools

| Tool | Purpose | Input |
|------|---------|-------|
| `update_story_status` | Change story status | `{story_id, new_status, sprint_id}` |
| `complete_story_with_notes` | Mark DONE with documentation | `{story_id, resolution_type, completion_notes, evidence_links}` |
| `update_acceptance_criteria` | Update AC mid-sprint | `{story_id, updated_criteria, update_reason}` |
| `create_followup_story` | Create descoped work story | `{parent_story_id, title, description, known_gaps}` |
| `batch_update_story_status` | Update multiple stories | `{updates: [{story_id, new_status}], sprint_id}` |
| `modify_sprint_stories` | Add/remove stories | `{sprint_id, add_story_ids, remove_story_ids}` |
| `complete_sprint` | Mark sprint complete | `{sprint_id, notes}` |

### Story Status Transitions

```
TO_DO ──────→ IN_PROGRESS ──────→ DONE
  ↑               │                 │
  └───────────────┴─────────────────┘
       (Can revert if needed)
```

### Update Story Status

```python
# Single story
update_story_status({
    "story_id": 35,
    "new_status": "DONE",
    "sprint_id": 1  # Optional validation
})

# Returns:
{
    "success": True,
    "story_id": 35,
    "title": "Access app on iOS and Android",
    "old_status": "IN_PROGRESS",
    "new_status": "DONE",
    "message": "✅ Story #35 updated: IN_PROGRESS → DONE"
}
```

### Batch Update (Daily Standup)

```python
batch_update_story_status({
    "updates": [
        {"story_id": 35, "new_status": "DONE"},
        {"story_id": 37, "new_status": "DONE"},
        {"story_id": 38, "new_status": "IN_PROGRESS"}
    ],
    "sprint_id": 1
})

# Returns:
{
    "success": True,
    "total": 3,
    "success_count": 3,
    "failure_count": 0,
    "message": "Updated 3/3 stories"
}
```

### Modify Sprint Stories

```python
# Add stories mid-sprint
modify_sprint_stories({
    "sprint_id": 1,
    "add_story_ids": [36, 39]
})

# Remove stories (returns to backlog)
modify_sprint_stories({
    "sprint_id": 1,
    "remove_story_ids": [43]  # Cannot remove DONE stories
})

# Returns:
{
    "success": True,
    "sprint_id": 1,
    "added": [{"story_id": 36, "title": "..."}],
    "removed": [{"story_id": 43, "title": "..."}],
    "new_totals": {"story_count": 6, "total_points": 0},
    "message": "Sprint updated: +1 added, -1 removed. Now has 6 stories."
}
```

### Complete Sprint

```python
complete_sprint({
    "sprint_id": 1,
    "notes": "Good sprint, all MVP features delivered"
})

# Returns:
{
    "success": True,
    "sprint_id": 1,
    "status": "COMPLETED",
    "metrics": {
        "total_stories": 5,
        "completed_stories": 4,
        "completion_rate": 80.0,
        "total_points": 13,
        "completed_points": 10,
        "velocity": 10
    },
    "incomplete_stories": [
        {"story_id": 43, "title": "View recipe details", "status": "IN_PROGRESS"}
    ],
    "message": "🏁 Sprint #1 completed! 4/5 stories done (80.0%). Velocity: 10 points."
}
```

### Sprint Execution Rules

1. **Backlog Gating**: Only TO_DO stories can be added to a sprint
2. **Completed Stories**: Cannot remove DONE stories from sprint
3. **Sprint Status**: Cannot modify COMPLETED sprints
4. **Idempotent Operations**: Re-running same operation is safe
5. **Story Status on Add**: Stories added to sprint become IN_PROGRESS
6. **Story Status on Remove**: Stories removed return to TO_DO

### Story Completion Tracking

#### Complete Story with Documentation

**Tool:** `complete_story_with_notes()`

**Purpose:** Mark stories DONE with detailed completion documentation for audit trail and TCC evaluation

**Input Schema:**
```python
{
    "story_id": 35,
    "resolution_type": "COMPLETED",  # COMPLETED | COMPLETED_WITH_CHANGES | PARTIAL | WONT_DO
    "completion_notes": "Implemented for iOS and Android. Flutter framework used for cross-platform development.",
    "evidence_links": ["https://github.com/repo/pull/123", "demo-video.mp4"],
    "acceptance_criteria_updates": None,  # Optional: If ACs were modified
    "known_gaps": None,  # Optional: If PARTIAL completion
    "completion_confidence": 95  # Optional: 0-100 confidence score
}
```

**Resolution Types:**

| Type | When to Use | Example |
|------|-------------|---------|
| `COMPLETED` | All ACs met as originally defined | Story delivered exactly as planned |
| `COMPLETED_WITH_CHANGES` | ACs were updated mid-sprint but all met | AC simplified due to time constraint |
| `PARTIAL` | Some ACs met, others descoped | Login works but password reset descoped to next sprint |
| `WONT_DO` | Story cancelled (e.g., priority change) | Feature no longer needed per product pivot |

**Returns:**
```json
{
    "success": true,
    "story_id": 35,
    "status": "DONE",
    "resolution_type": "COMPLETED",
    "completion_log_id": 12,
    "message": "✅ Story #35 marked DONE (COMPLETED). Completion logged."
}
```

**Database Actions:**
1. Updates `user_stories.status` to `DONE`
2. Sets `user_stories.resolution_type`, `completion_notes`, `evidence_links`, etc.
3. Creates `StoryCompletionLog` record with timestamp, author, reason

#### Update Acceptance Criteria Mid-Sprint

**Tool:** `update_acceptance_criteria()`

**Purpose:** Modify ACs during sprint with full traceability (preserves original ACs)

**Input:**
```python
{
    "story_id": 35,
    "updated_criteria": [
        "User can log in with email/password (Google OAuth descoped)",
        "Session persists for 7 days",
        "Logout button visible on all screens"
    ],
    "update_reason": "Google OAuth API quota exceeded; simplified to email/password only for MVP sprint"
}
```

**Traceability Pattern:**
```python
# BEFORE update
story.acceptance_criteria = ["AC1 original", "AC2 original", "AC3 original"]
story.acceptance_criteria_updates = None

# AFTER update
story.acceptance_criteria = ["AC1 updated", "AC2 updated", "AC3 updated"]
story.acceptance_criteria_updates = {
    "original": ["AC1 original", "AC2 original", "AC3 original"],
    "reason": "Google OAuth API quota exceeded...",
    "updated_at": "2026-01-15T14:30:00Z"
}
```

**Returns:**
```json
{
    "success": true,
    "story_id": 35,
    "original_criteria": ["AC1 original", "AC2 original"],
    "updated_criteria": ["AC1 updated", "AC2 updated"],
    "message": "✅ Acceptance criteria updated. Original ACs preserved in 'acceptance_criteria_updates' field."
}
```

#### Create Follow-Up Story

**Tool:** `create_followup_story()`

**Purpose:** Descope work to future sprint while maintaining parent-child traceability

**Input:**
```python
{
    "parent_story_id": 35,
    "title": "As a user, I want to log in with Google OAuth so that I can access the app faster",
    "description": "Descoped from Story #35 due to API quota constraints. Implement Google OAuth login flow.",
    "acceptance_criteria": [
        "User can click 'Sign in with Google' button",
        "OAuth flow redirects to Google consent screen",
        "Successful auth creates user session"
    ],
    "known_gaps": "Requires Google OAuth API approval (waiting on vendor)",
    "feature_id": 24  # Optional: Link to same feature as parent
}
```

**Returns:**
```json
{
    "success": true,
    "parent_story_id": 35,
    "followup_story_id": 46,
    "title": "As a user, I want to log in with Google OAuth...",
    "status": "TO_DO",
    "message": "✅ Follow-up story #46 created and linked to parent #35."
}
```

**Database Relationships:**
```sql
-- parent story
SELECT story_id, title, follow_up_story_id FROM user_stories WHERE story_id = 35;
-- Result: (35, "User login", 46)

-- followup story
SELECT story_id, title, status FROM user_stories WHERE story_id = 46;
-- Result: (46, "Google OAuth login", "TO_DO")
```

### Story Completion Audit System

**Table:** `story_completion_log` (in `agile_sqlmodel.py`)

**Purpose:** Immutable audit trail for all story status changes (TCC traceability requirement)

**Schema:**
```python
class StoryCompletionLog(SQLModel, table=True):
    log_id: int  # Primary key
    story_id: int  # Foreign key to user_stories
    changed_by: str  # User/agent who made change
    changed_at: datetime  # Timestamp
    old_status: str  # Previous status (e.g., "IN_PROGRESS")
    new_status: str  # New status (e.g., "DONE")
    resolution_type: Optional[str]  # COMPLETED, PARTIAL, etc.
    completion_notes: Optional[str]  # Why/how completed
    evidence_links: Optional[str]  # JSON array of proof links
    known_gaps: Optional[str]  # What wasn't completed
```

**Automatic Logging:**
- Every call to `complete_story_with_notes()` creates log entry
- Every call to `update_story_status()` creates log entry (if changing to DONE)
- Log entries are **immutable** (INSERT only, no UPDATE/DELETE)

**Querying Audit Trail:**
```python
# Get all changes for a story
logs = session.exec(
    select(StoryCompletionLog)
    .where(StoryCompletionLog.story_id == 35)
    .order_by(StoryCompletionLog.changed_at)
).all()

# Result:
# [
#   Log(old_status="TO_DO", new_status="IN_PROGRESS", changed_at="2026-01-10 09:00"),
#   Log(old_status="IN_PROGRESS", new_status="DONE", resolution_type="COMPLETED", changed_at="2026-01-15 14:30")
# ]
```

**TCC Evaluation Use Cases:**
1. **Cycle Time Measurement:** Time between TO_DO → DONE (first log entry to last)
2. **Scope Change Analysis:** Count stories with `resolution_type=COMPLETED_WITH_CHANGES`
3. **Completion Quality:** Analyze `completion_confidence` scores across sprints
4. **Evidence Compliance:** Verify all DONE stories have `evidence_links` populated

---

## State Management Architecture

### Two-Layer State System

#### 1. Volatile State (Orchestrator Memory)
- **Location**: SQLite `sessions` table
- **Scope**: Per conversation session
- **Purpose**: Track current phase, accumulated requirements, active project
- **Lifespan**: Single session (random UUID per run in current implementation)

**State Keys:**
```python
{
    "active_project": {
        "product_id": 3,
        "name": "TaskMaster Pro",
        "vision": "For busy professionals...",
        "roadmap": "Theme: Core Auth..."
    },
    "unstructured_requirements": [
        "User: I need a task manager",
        "User: It should have AI suggestions"
    ],
    "product_vision_statement": "For busy professionals...",
    "product_roadmap": "Complete roadmap text",
    "is_complete": true
}
```

#### 2. Persistent State (Business Database)
- **Location**: SQLite `agile_sqlmodel.db`
- **Scope**: All projects, all sessions
- **Purpose**: Store committed artifacts (products, themes, epics, features)
- **Lifespan**: Permanent

### State Flow Diagram

```
User Input
    ↓
Orchestrator reads volatile state (sessions table)
    ↓
Orchestrator calls Vision Agent
    ↓
Vision Agent receives prior_vision_state from volatile memory
    ↓
Vision Agent returns updated_components
    ↓
Orchestrator updates volatile state
    ↓
User confirms "Save"
    ↓
Orchestrator calls save_vision_tool
    ↓
Tool writes to persistent database (products table)
    ↓
Orchestrator updates volatile state with product_id
```

### Context Accumulation Pattern

**Critical for multi-turn conversations:**

```python
# ❌ WRONG: Only passing latest message
response = await run_vision_agent(
    accumulated_requirements=user_text  # Missing previous context!
)

# ✅ CORRECT: Passing full accumulated history
state["unstructured_requirements"].append(user_text)
response = await run_vision_agent(
    accumulated_requirements=str(state["unstructured_requirements"])  # Full context
)
```

**Why this matters:**
- Agents are stateless; they only see what's in the input
- Multi-turn interviews require full conversation history
- Prevents agents from "forgetting" previous answers

---

## Orchestrator State Machine

### State Transitions

The orchestrator operates as a finite state machine with these states:

#### STATE 1: INTERVIEW MODE (Drafting)
**Trigger**: Last agent output has `"is_complete": false`

**Actions**:
1. Display lead-in message
2. Construct agent arguments:
   - `user_raw_text`: Current user input
   - `prior_vision_state`: JSON from previous tool output
3. Call agent tool
4. Update volatile state with response
5. STOP (wait for user)

#### STATE 2: REVIEW MODE (Approval)
**Trigger**: Last agent output has `"is_complete": true` AND user hasn't confirmed

**Actions**:
1. Display the completed artifact (vision statement or roadmap)
2. Ask: "Would you like to save this, or make changes?"
3. STOP (wait for user)

#### STATE 3: PERSISTENCE MODE (Saving)
**Trigger**: Completed artifact exists AND user says "Save", "Yes", "Confirm"

**Actions**:
1. Extract artifact data from volatile state
2. Call save tool (`save_vision_tool` or `save_roadmap_tool`)
3. Update volatile state with returned `product_id`
4. Ask about next phase
5. STOP

#### STATE 4: ROUTING MODE (New/Other)
**Trigger**: Start of conversation, or user changes topic

**Actions**:
1. Determine intent:
   - **Existing project**: Call `select_project(product_id)`
   - **New project**: Initialize vision phase
   - **Status query**: Call `list_projects()` or `count_projects()`
2. STOP

### Sprint Planning States (11-13)

#### STATE 11: SPRINT PLANNING SETUP
**Trigger**: User says "plan sprint", "sprint planning"

**Actions**:
1. Verify active project has backlog-ready stories
2. Call `get_backlog_for_planning({product_id, only_ready: true})`
3. Display stories grouped by theme
4. Ask for sprint goal, capacity, and story selection
5. STOP

#### STATE 12: SPRINT DRAFT MODE
**Trigger**: User provides sprint parameters

**Actions**:
1. Call `plan_sprint_tool({product_id, sprint_goal, selected_story_ids, duration_days})`
2. Display draft: goal, dates, selected stories, team
3. Ask: "Would you like to save this sprint, or make changes?"
4. STOP

#### STATE 13: SPRINT PERSISTENCE MODE
**Trigger**: User confirms sprint draft

**Actions**:
1. Call `save_sprint_tool({product_id, team_id, sprint_goal, selected_story_ids, ...})`
2. Display: Sprint ID, stories linked, planning duration
3. Show TLX prompt for cognitive load measurement
4. Offer next steps: view details, start execution, return to backlog
5. STOP

### Sprint Query States (14-15)

#### STATE 14: SPRINT VIEW MODE
**Trigger**: User says "view sprint", "sprint details"

**Actions**:
1. Call `get_sprint_details({sprint_id})` or `get_sprint_details({product_id})`
2. Display: goal, dates, stories with status, progress metrics
3. Offer actions: update status, modify stories, complete sprint
4. STOP

#### STATE 15: SPRINT LIST MODE
**Trigger**: User says "list sprints", "sprint history"

**Actions**:
1. Call `list_sprints({product_id})`
2. Display all sprints with summary info
3. Allow selection for details
4. STOP

### Sprint Execution States (16-18)

#### STATE 16: UPDATE STORY STATUS MODE
**Trigger**: User says "mark story as done", "update status"

**Actions**:
1. Parse story ID(s) and target status
2. Call `update_story_status({story_id, new_status})` or `batch_update_story_status({...})`
3. Display status change confirmation
4. STOP

#### STATE 17: MODIFY SPRINT STORIES MODE
**Trigger**: User says "add story to sprint", "remove story"

**Actions**:
1. Parse add/remove intent and story IDs
2. Call `modify_sprint_stories({sprint_id, add_story_ids, remove_story_ids})`
3. Display changes and new sprint totals
4. STOP

#### STATE 18: COMPLETE SPRINT MODE
**Trigger**: User says "complete sprint", "end sprint"

**Actions**:
1. Show current sprint status summary
2. Confirm completion intent
3. Call `complete_sprint({sprint_id, notes})`
4. Display: completion rate, velocity, incomplete stories
5. Offer: plan next sprint, view backlog
6. STOP

### Orchestrator Instruction Snippets

From `orchestrator_agent/instructions.txt`:

```plaintext
## STATE 1 — INTERVIEW MODE (Drafting)
**Trigger:** The last `product_vision_tool` output contains `"is_complete": false`.

**Behavior:**
1. **Output Lead-in:** *"I am handing this response to the Product Vision Agent…"*
2. **Construct Arguments:**
   - `user_raw_text`: The EXACT new string from the user.
   - `prior_vision_state`: **COPY** the entire JSON string from the *previous* 
     `product_vision_tool` output found in the chat history.
3. **Execute Call:** `product_vision_tool(user_raw_text=..., prior_vision_state=...)`
4. **STOP.**
```

---

## Key Design Patterns

### 1. Stateless Agents with State Injection

**Pattern**: Agents don't maintain memory; state is injected as serialized JSON

**Rationale**:
- Predictable behavior (no hidden state)
- Easy to debug (inspect JSON input/output)
- Supports conversation replay and testing

**Implementation**:
```python
root_agent = Agent(
    name="product_vision_agent",
    input_schema=InputSchema,  # Includes prior_vision_state: str
    output_schema=OutputSchema,  # Includes updated_components: dict
    instruction=load_instruction(...),
    disallow_transfer_to_parent=True,  # No agent switching
    disallow_transfer_to_peers=True
)
```

### 2. Bucket Brigade Communication

**Pattern**: Each agent receives, processes, and passes structured state

```
Orchestrator
    ↓ (passes state JSON)
Vision Agent
    ↓ (returns updated JSON)
Orchestrator
    ↓ (stores in volatile state)
User confirms
    ↓
Orchestrator
    ↓ (passes state JSON)
Roadmap Agent
    ↓ (returns roadmap JSON)
Orchestrator
```

### 3. Incremental Refinement (Never Replace)

**Pattern**: Each agent turn adds/updates data, never discards previous work

**Vision Agent Example**:
```python
# Turn 1
{
    "project_name": "TaskMaster",
    "target_user": null
}

# Turn 2 (user provides target_user)
{
    "project_name": "TaskMaster",  # PRESERVED
    "target_user": "Busy professionals"  # ADDED
}

# Turn 3 (user refines project_name)
{
    "project_name": "TaskMaster Pro",  # UPDATED
    "target_user": "Busy professionals"  # PRESERVED
}
```

**Roadmap Agent Example**:
```python
# Turn 1 (themes created)
roadmap_draft = [
    {"theme_name": "Auth", "key_features": [...], "time_frame": null}
]

# Turn 2 (prioritization added)
roadmap_draft = [
    {"theme_name": "Auth", "key_features": [...], "time_frame": "Now"}  # ENHANCED
]
# Original theme preserved, just enhanced with new field
```

### 4. Schema-Driven Validation

**Pattern**: All agent I/O validated by Pydantic schemas

**Benefits**:
- Type safety
- Automatic validation
- Clear API contracts
- Self-documenting

**Example**:
```python
class VisionComponents(BaseModel):
    project_name: Optional[str] = Field(
        description="Name of project. Return null if not yet defined."
    )
    target_user: Optional[str] = Field(
        description="Who is the customer? Return null if ambiguous."
    )
    # ... 5 more fields
```

### 5. Tool Context for Caching

**Pattern**: Read-only tools accept optional `ToolContext` for transparent caching

**Implementation**:
```python
def count_projects(tool_context: ToolContext | None = None) -> int:
    # Check cache first
    if tool_context and "projects_count" in tool_context.state:
        cache_time = tool_context.state.get("projects_last_refreshed_utc")
        if is_cache_valid(cache_time, ttl_minutes=5):
            return tool_context.state["projects_count"]
    
    # Cache miss, hit database
    count = query_database()
    
    # Store in cache
    if tool_context:
        tool_context.state["projects_count"] = count
        tool_context.state["projects_last_refreshed_utc"] = utc_now()
    
    return count
```

### 6. Multi-Agent Orchestration via AgentTool

**Pattern**: Child agents wrapped as tools in parent agent's toolset

```python
# Child agent definition
vision_agent = Agent(name="product_vision_agent", ...)

# Parent orchestrator
orchestrator = Agent(
    name="orchestrator_agent",
    tools=[
        AgentTool(agent=vision_agent),  # Child as tool
        AgentTool(agent=roadmap_agent),
        count_projects,  # Regular function tool
    ]
)
```

**How it works**:
- Orchestrator calls `product_vision_tool(user_raw_text=..., prior_vision_state=...)`
- ADK routes this to the wrapped vision agent
- Vision agent processes and returns structured output
- Orchestrator receives the response and continues workflow

---

## Code Examples

### Example 1: Vision Agent Call

```python
# Orchestrator calling vision agent
response = await runner.run(
    agent=orchestrator,
    user_input={
        "user_message": "I need a task manager for busy professionals"
    }
)

# Behind the scenes, orchestrator calls:
# product_vision_tool(
#     user_raw_text="I need a task manager for busy professionals",
#     prior_vision_state="NO_HISTORY"
# )

# Vision agent returns:
# {
#     "updated_components": {
#         "project_name": null,
#         "target_user": "Busy professionals",
#         "problem": "Task management challenges",
#         "product_category": "Task manager",
#         "key_benefit": null,
#         "competitors": null,
#         "differentiator": null
#     },
#     "is_complete": false,
#     "product_vision_statement": "For [target_user] who [problem]...",
#     "clarifying_questions": [
#         "What should we call this product?",
#         "What's the primary benefit users will get?",
#         "Who are the main competitors?",
#         "What makes your solution unique?"
#     ]
# }
```

### Example 2: Roadmap Theme Structure

```python
# Input to save_roadmap_tool
roadmap_input = SaveRoadmapInput(
    project_name="TaskMaster Pro",
    roadmap_text="Complete roadmap with themes...",
    roadmap_structure=[
        RoadmapThemeInput(
            theme_name="Core Authentication",
            key_features=[
                "User registration",
                "Login/logout",
                "Password reset",
                "OAuth integration"
            ],
            time_frame="Now",
            justification="Essential foundation for user identity"
        ),
        RoadmapThemeInput(
            theme_name="Task Management",
            key_features=[
                "Create tasks",
                "Assign tasks",
                "Task filtering",
                "Due dates"
            ],
            time_frame="Now",
            justification="Core product functionality"
        )
    ]
)

# Creates in database:
# Theme: "Now - Core Authentication"
#   └── Epic: "Core Authentication"
#         ├── Feature: "User registration"
#         ├── Feature: "Login/logout"
#         ├── Feature: "Password reset"
#         └── Feature: "OAuth integration"
#
# Theme: "Now - Task Management"
#   └── Epic: "Task Management"
#         ├── Feature: "Create tasks"
#         ├── Feature: "Assign tasks"
#         ├── Feature: "Task filtering"
#         └── Feature: "Due dates"
```

### Example 3: State Reconstruction

```python
# Get current volatile state
state = get_current_state(APP_NAME, USER_ID, SESSION_ID)

# Accumulate user input (multi-turn context)
user_text = "The target user is chefs in restaurants"
state.setdefault("unstructured_requirements", [])
state["unstructured_requirements"].append(f"User: {user_text}")

# Call agent with full context
response = await runner.run(
    agent=orchestrator,
    user_input={
        "user_message": user_text
    }
)

# Update state with agent response
state["product_vision_statement"] = response.get("product_vision_statement")
update_state_in_db(state)
```

### Example 4: Session Initialization

```python
# Initialize session service (persistent)
session_service = DatabaseSessionService(db_url=f"sqlite:///{DB_PATH}")

# Create runner with session
runner = Runner(
    app_name=APP_NAME,
    user_id=USER_ID,
    session_id=SESSION_ID,  # Random UUID for volatile memory
    session_service=session_service,
)

# Run agent
response = await runner.run(
    agent=root_agent,
    user_input={"user_message": "Start new project"}
)
```

---

## Next Steps / Extension Points

### 1. User Story Generation
**Current Gap**: Features exist but no user stories created yet

**Planned Workflow**:
- Input: Selected feature(s) from roadmap
- Agent: Story Draft Agent → INVEST Validator → Story Refiner
- Output: INVEST-compliant user stories linked to features

**Files to examine**:
- `orchestrator_agent/agent_tools/story_pipeline/`
- `orchestrator_agent/agent_tools/product_user_story_tool/`

### 2. Sprint Planning
**Current Gap**: No sprint creation or story assignment

**Planned Workflow**:
- Input: User stories from backlog
- Agent: Scrum Master Agent
- Output: Sprint with assigned stories, tasks, and team members

**Database tables ready**:
- `sprints` (start_date, end_date, status)
- `sprint_story` (link table)
- `tasks` (linked to stories)

### 3. Definition of Done (DoD) Tracking
**Current Gap**: No acceptance criteria or DoD validation

**Planned Enhancement**:
- Add `acceptance_criteria` field to user stories
- Create DoD validation agent
- Track story completion status

### 4. Workflow Orchestration
**Current Gap**: Manual phase transitions

**Planned Enhancement**:
- Auto-suggest next phase when current complete
- Workflow templates (Vision → Roadmap → Backlog → Sprint)
- Phase dependency validation

---

## File Reference Guide

| File | Purpose |
|------|---------|
| `main.py` | Entry point; session initialization; orchestrator bootstrap |
| `orchestrator_agent/agent.py` | Root agent definition with all tools |
| `orchestrator_agent/instructions.txt` | State machine logic for routing |
| `orchestrator_agent/agent_tools/product_vision_tool/agent.py` | Vision agent definition |
| `orchestrator_agent/agent_tools/product_vision_tool/instructions.txt` | Vision gathering logic |
| `orchestrator_agent/agent_tools/product_vision_tool/tools.py` | `save_vision_tool` implementation |
| `orchestrator_agent/agent_tools/product_roadmap_agent/agent.py` | Roadmap agent definition |
| `orchestrator_agent/agent_tools/product_roadmap_agent/instructions.txt` | Roadmap creation logic |
| `orchestrator_agent/agent_tools/product_roadmap_agent/tools.py` | `save_roadmap_tool` + structure creation |
| `utils/schemes.py` | Shared Pydantic schemas (VisionComponents, etc.) |
| `utils/response_parser.py` | JSON validation and parsing utilities |
| `tools/orchestrator_tools.py` | Read-only project query tools |
| `agile_sqlmodel.py` | Database schema and initialization |

---

## Troubleshooting Common Issues

### Issue: Agent "forgets" previous answers
**Cause**: `prior_*_state` not being passed correctly  
**Solution**: Ensure orchestrator copies full JSON from previous tool output

### Issue: Database foreign key errors
**Cause**: SQLite foreign key enforcement not enabled  
**Solution**: Check `agile_sqlmodel.py` for `PRAGMA foreign_keys=ON` event listener

### Issue: Features not created during roadmap save
**Cause**: `roadmap_structure` not passed to `save_roadmap_tool`  
**Solution**: Ensure `SaveRoadmapInput` includes populated `roadmap_structure` list

### Issue: State lost between sessions
**Cause**: Random session UUID regenerated on each run  
**Solution**: For persistent sessions, use fixed SESSION_ID or implement session recovery

### Issue: Agent returns invalid JSON
**Cause**: LLM hallucination or schema mismatch  
**Solution**: Use `parse_agent_output()` for robust parsing; check OutputSchema matches agent definition

---

## Appendix: Database ERD

```
products
├── product_id (PK)
├── name
├── vision
├── roadmap
└── created_at

themes
├── theme_id (PK)
├── title
├── description
├── product_id (FK → products)
└── created_at

epics
├── epic_id (PK)
├── title
├── summary
├── theme_id (FK → themes)
└── created_at

features
├── feature_id (PK)
├── title
├── description
├── epic_id (FK → epics)
└── created_at

user_stories
├── story_id (PK)
├── title
├── story_description
├── acceptance_criteria
├── status (TO_DO, IN_PROGRESS, DONE)
├── story_points
├── rank
├── product_id (FK → products)
├── feature_id (FK → features)
└── created_at

teams
├── team_id (PK)
├── name
└── created_at

product_teams (link table)
├── product_id (FK → products)
└── team_id (FK → teams)

sprints
├── sprint_id (PK)
├── goal
├── start_date
├── end_date
├── status (PLANNED, ACTIVE, COMPLETED)
├── product_id (FK → products)
├── team_id (FK → teams)
└── created_at

sprint_stories (link table)
├── sprint_id (FK → sprints)
├── story_id (FK → user_stories)
└── added_at

workflow_events
├── event_id (PK)
├── event_type (SPRINT_PLAN_DRAFT, SPRINT_PLAN_REVIEW, SPRINT_PLAN_SAVED)
├── timestamp
├── duration_seconds
├── turn_count
├── product_id (FK → products)
├── sprint_id (FK → sprints)
├── session_id
└── event_metadata (JSON)
```

---

## Appendix: Tool Reference

### Sprint Planning Tools

| Tool | State | Description |
|------|-------|-------------|
| `get_backlog_for_planning` | 11 | Query TO_DO stories for sprint planning |
| `plan_sprint_tool` | 12 | Create sprint draft with validation |
| `save_sprint_tool` | 13 | Persist sprint to database |

### Sprint Query Tools

| Tool | State | Description |
|------|-------|-------------|
| `get_sprint_details` | 14 | View sprint details with stories and progress |
| `list_sprints` | 15 | List all sprints for a product |

### Sprint Execution Tools

| Tool | State | Description |
|------|-------|-------------|
| `update_story_status` | 16 | Change single story status |
| `batch_update_story_status` | 16 | Change multiple story statuses |
| `modify_sprint_stories` | 17 | Add/remove stories from sprint |
| `complete_sprint` | 18 | Mark sprint as completed |

---

**End of Document**
