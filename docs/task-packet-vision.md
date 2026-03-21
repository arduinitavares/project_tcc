# Task Packet Vision

## Purpose

We are extending the platform from a planning system into an execution handoff system.

Today, the product takes a project from Vision through Sprint Planning. It already produces structured artifacts such as product vision, backlog items, roadmap milestones, user stories, sprint scope, and decomposed technical tasks. The next step is to make that work immediately consumable by developers and agents.

The feature we are building is a **Task Packet** system: a structured, canonical handoff artifact for a single unit of execution work.

## What We Are Building

A **Task Packet** is a structured representation of one task that contains the minimum complete context required for a human developer or coding agent to begin work without hunting across multiple screens or artifacts.

The Task Packet is not the prompt itself. It is the source artifact from which multiple delivery formats can be rendered.

Those delivery formats may include:
- a human-readable task brief
- a copyable agent prompt
- a machine-readable JSON payload
- later, agent-specific renderers for different tools or models

The Task Packet must be generated from the platform's structured source of truth, not manually authored as free text.

## Product Principle

The core principle is:

**The packet is the product. The prompt is only one rendering of the packet.**

This matters because prompts are delivery formats, not durable source-of-truth objects. If we model only prompt text, we will make the system brittle, hard to version, and hard to adapt for different audiences.

If we model a canonical Task Packet first, we can later support:
- multiple prompt styles
- multiple agent flavors
- human briefs
- auditability and versioning
- future execution feedback loops

## Why We Are Building It

The current system is strong at planning, but there is still friction between planning and execution.

Without Task Packets:
- users must manually gather context from stories, sprint scope, and project artifacts
- agents begin with incomplete context and must guess constraints, scope, and intent
- handoff quality varies depending on who is consuming the task
- execution is disconnected from the planning data already available in the system

With Task Packets:
- execution can start immediately from a single artifact
- human and agent handoffs become consistent
- the system's structured planning data becomes directly useful during development
- planning and execution become part of one continuous workflow

## Intended Consumers

Task Packets are intended for two primary audiences:

**Human developers**  
They need a concise execution brief with enough context to understand what to build, why it matters, what constraints apply, and how to know when the work is done.

**Coding agents**  
They need explicit, structured instructions with scoped context, acceptance criteria, constraints, and validation expectations so they can begin effectively and avoid hallucinating missing details.

These audiences overlap, but they should not be treated as identical. The underlying packet should be shared; the rendered presentation may differ.

## v1 Decisions

The first version of Task Packets is locked around these decisions:

### 1. Generation Model
Task Packets are assembled by a **deterministic backend/service**, not by an LLM and not by a new planning agent.

This means:
- packet fields come from existing persisted data and deterministic transformations
- the canonical packet is trustworthy and testable
- LLMs may be used later in renderers, but not in the packet model itself

### 2. Generation Lifecycle
Task Packets are generated **on demand** from current state.

This means:
- the system does not pre-generate packets at sprint save
- the system does not store prompt text as the primary artifact
- packets include freshness/version metadata so staleness can be detected

### 3. Packet Depth
v1 uses a **standard depth** context boundary.

Each packet includes:
- the task
- the parent story
- the sprint context
- a short product context
- applicable constraints and validation context

v1 does not include broad roadmap history, sibling-task dumps, or unrelated project context.

### 4. Packet Identity
The canonical handoff is anchored by **`task_id + sprint_id`**, not by `task_id` alone.

This matters because the same task may be consumed under different sprint contexts, and sprint context changes the meaning of the handoff.

### 5. Spec Authority Rule
Task Packets trust only **pinned story authority**.

This means:
- if a story has `accepted_spec_version_id`, the packet may include constraints derived from that pinned spec context
- if a story is not pinned, the packet must explicitly say spec context is unavailable or unpinned
- the packet must **not** silently fall back to the latest product authority

This preserves traceability and prevents accidental scope drift during execution.

## Current Data Reality

The current data model already supports deterministic packet assembly.

Relevant entities already exist:
- `Task` carries the execution unit and status
- `UserStory` carries title, description, acceptance criteria, persona, and validation evidence
- `Sprint` carries goal, dates, status, and team context
- `Product` carries vision and product-level context
- story-to-sprint linkage already exists through `SprintStory`

Important current limitations:
- tasks do not currently have a dedicated title field
- there is no project-level Definition of Done model yet
- there is no direct `task -> sprint` foreign key; sprint context must be resolved through story linkage
- validation evidence and compiled authority exist, but they are audit-style structured data, not human-authored summaries

These realities should shape the schema instead of being hidden by it.

## Initial Scope

The initial unit of handoff is the **task**, not the full story.

Stories are often too large for one implementation session. Sprint planning already decomposes selected stories into technical tasks, which makes task-level handoff the most practical starting point.

For v1, the system focuses on:
- one canonical packet per task+sprint context
- packet generation from existing project, story, sprint, and validation data
- future rendering into a human brief and an agent prompt
- freshness/version awareness so users know whether a copied packet may be stale

## Out of Scope for the First Version

The first version should not try to solve every execution problem.

Out of scope for v1:
- automatic agent execution from the platform
- writing work results back into project state automatically
- full agent-specific prompt tuning for many tools
- large codebase dumps embedded into every packet
- replacing the task, story, or sprint records as the source of truth
- inventing narrative summaries with LLMs inside the canonical packet model

These may become later extensions, but they are not required to prove the value of the Task Packet system.

## Desired Outcome

When a user opens a planned sprint and selects a task, they should be able to immediately obtain a clean, trustworthy execution handoff.

The experience should feel like:
- the system understands the task
- the system knows why the task exists
- the system knows what good completion looks like
- the system can package that context in a format suitable for execution

The user should not need to manually reconstruct context from multiple planning artifacts.

## Risks To Avoid

There are a few design risks we should explicitly avoid:

- treating prompt text as the primary model instead of structured packet data
- generating packets that are too large and noisy to be useful
- mixing task context with too much unrelated sprint or project history
- silently substituting newer spec authority for a story that was never pinned to it
- failing to track packet freshness when stories, tasks, sprint membership, or validation context change
- designing only for AI agents and forgetting human readability

## Achieved State

The canonical Task Packet v1 model has been successfully defined and implemented. The backend endpoint correctly assembles the packet on demand, deterministically from the database, using strict component identity (`task_id` + `sprint_id`) and capturing the required context boundaries and pinned invariants. 

The exact canonical data contract is defined in [Task Packet v1 Schema Reference](./task-packet-schema-v1.md).

## Next Step

The next step is to design and implement the **Renderer Layer**.

This layer sits directly on top of the canonical JSON packet and translates the structured data into consumable execution instructions, without modifying the source of truth.

The first renderers will focus on:
1. **The Human Brief**: A beautifully formatted Markdown summary for presentation in the platform UI.
2. **The Agentic Prompts**: Highly structured text blocks (often utilizing XML tags) designed specifically to be copied and pasted into tools like Cursor, GitHub Copilot Workspace, or standalone AI agents.

## Working Decision

For this project, we will proceed with this framing:

**We are building a canonical Task Packet model for execution handoff, generated deterministically from current state, anchored by task+sprint context, and rendered later into prompts or briefs without treating those renderings as the source of truth.**
