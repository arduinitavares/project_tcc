# Task Packet Vision

## Purpose

We are extending the platform from a planning system into an execution handoff system.

Today, the product already produces structured planning artifacts such as product vision, backlog items, roadmap milestones, user stories, sprint scope, and decomposed technical tasks. The next step is to make that planning output directly consumable during execution.

## Current Framing

The handoff model now uses two canonical artifacts instead of one overloaded task prompt:

- **Story Packet**: the stable bootstrap context for a story session
- **Task Packet**: the task-local execution delta for one decomposed task inside that story

Neither packet is itself the prompt. Prompts, briefs, and agent-specific formats are renderings built on top of these canonical payloads.

## Product Principle

The core principle remains:

**The packet is the product. The prompt is only one rendering of the packet.**

This matters because prompts are delivery formats, not durable source-of-truth objects. If we model only prompt text, we make the system brittle, hard to version, and hard to adapt for different audiences and tools.

## Why Split Story and Task Context

The earlier task-packet contract reused story acceptance criteria as the checklist for every task prompt. That created a scope leak:

- each task looked responsible for the full story outcome
- review and coordination slices looked like full implementation tasks
- sibling tasks repeated the same story-level completion contract
- task execution and story completion became ambiguous

The new framing separates those responsibilities cleanly:

- story acceptance criteria stay story-scoped
- task checklist items stay task-scoped
- spec/validation metadata can still be inherited where execution needs it
- renderers can later combine story bootstrap and task delta without collapsing them into one canonical payload

## Canonical Artifacts

### Story Packet

The Story Packet is the session-bootstrap artifact. It owns:

- story statement and identity
- story acceptance criteria in canonical constraints fields
- story-scoped task plan context
- sprint context
- product context
- pinned spec-binding metadata
- validation freshness and findings
- story-level compliance boundaries

### Task Packet

The Task Packet is the task-local execution artifact. It owns:

- task description and identity
- task-local checklist items
- executable/non-executable status
- artifact targets and workstream tags
- task-local hard constraints
- compact parent-story orientation
- inherited spec-binding and validation metadata needed during execution

The Task Packet does **not** treat story acceptance criteria as the task checklist.

## Deterministic Rules

Both packets follow the same platform rules:

- assembled by deterministic backend code, not by an LLM
- generated on demand from current persisted state
- anchored by sprint-scoped identity
- freshness-aware through source snapshot and source fingerprint metadata
- bound only to pinned story authority, never silent latest-authority fallback

Packet identity is:

- Story Packet: `story_id + sprint_id`
- Task Packet: `task_id + sprint_id`

## Current Data Reality

The current data model already supports deterministic assembly:

- `UserStory` carries story title, description, acceptance criteria, persona, and validation evidence
- `Task` carries the execution slice plus canonical `metadata_json`
- `Sprint` carries goal, dates, status, and team context
- `Product` carries vision/product context
- `SprintStory` provides the authoritative story-to-sprint membership

Important current limitations still shape the contract:

- tasks do not have a dedicated title field
- there is no direct `task -> sprint` foreign key
- project-level Definition of Done is not yet modeled explicitly
- validation/spec artifacts are structured audit data, not human-written summaries
- renderer behavior can evolve independently of the canonical packet schemas

## In Scope

The current packet phase focuses on:

- one canonical story packet per story+sprint context
- one canonical task packet per task+sprint context
- deterministic packet generation from existing project/story/task/sprint/validation data
- preserving story bootstrap context separately from task-local execution context
- supporting later renderers for story briefs and task prompts

## Out of Scope

This phase does not attempt to solve:

- automatic agent execution
- writing work results back into project state automatically
- broad codebase/context dumps in every packet
- replacing stories or tasks as the source of truth
- final renderer wording or UI affordances

Those belong to later work once the packet contracts are stable.

## Achieved State

The canonical handoff layer now consists of:

- [`story_packet.v1`](./story-packet-schema-v1.md) for story bootstrap context
- [`task_packet.v2`](./task-packet-schema-v2.md) for task-local execution context

The backend assembles both packets on demand, deterministically from the database, with strict sprint-scoped identity plus pinned spec-binding and validation metadata.

Task Packet v2 now carries explicit task-local checklist fields:

- `checklist_items`
- `is_executable`

This allows task completion to remain task-scoped without silently inheriting story acceptance criteria as the task’s done checklist.

## Next Step

The next step is to build richer consumption flows on top of the canonical artifacts:

1. expose story bootstrap and task delta actions clearly in the UI
2. update renderers so task prompts use task checklist terminology while story prompts keep story acceptance criteria terminology
3. consider later metadata editing and smarter task decomposition once the packet-driven workflow proves useful

## Working Decision

**We are building canonical Story and Task Packet models for execution handoff, generated deterministically from current state, anchored by sprint-scoped story/task identities, and rendered later into prompts or briefs without treating those renderings as the source of truth.**
