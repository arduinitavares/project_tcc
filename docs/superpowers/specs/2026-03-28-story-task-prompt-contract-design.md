# Story and Task Prompt Contract Design

**Date:** 2026-03-28
**Status:** Approved for planning
**Scope:** Platform-level prompt and execution-handoff design

## Summary

The platform currently generates task-level agent prompts that include the parent story's acceptance criteria as the task completion checklist. This creates a scope leak: each task appears responsible for satisfying the full story outcome, even when the task is only one slice of work.

This design introduces a clearer separation between story completion and task completion:

- Story acceptance criteria remain story-scoped.
- Definition of Done remains a cross-cutting quality/compliance bar.
- Tasks use a task-scoped `task checklist` plus task-specific evidence and verification.
- Very small items are modeled as checklist entries inside a task rather than as standalone agent prompts.

The design supports the current manual copy/paste workflow and a future MCP-based workflow without requiring task prompts to be self-contained.

## Problem Statement

The current task prompt contract mixes different levels of responsibility:

- **Story responsibility:** what must be true for the story to be complete.
- **Task responsibility:** what must be true for one execution slice to be complete.
- **Global quality responsibility:** what standards apply regardless of the story or task.

When story acceptance criteria are rendered as the checklist for every task prompt, the platform produces misleading execution handoffs:

- tasks look larger than they really are
- review/storage/coordination items look like full implementation work
- verification becomes ambiguous
- the same story outcome is repeated across sibling tasks

This is not specific to the current thesis/assignment project. Any project with story decomposition can hit the same failure mode.

## Goals

- Preserve story acceptance criteria as the source of truth for story completion.
- Make task prompts describe only the local execution slice.
- Introduce a Scrum-like `task checklist` for task-level completion.
- Keep tiny workflow actions out of first-class prompt generation when they do not justify their own execution contract.
- Support the current workflow of starting a session once and pasting multiple prompts into it.
- Stay compatible with a future MCP that loads story context once and sends task deltas afterward.

## Non-Goals

- Making task prompts fully self-contained for brand-new sessions.
- Replacing story acceptance criteria with task-level checklists.
- Tailoring the design to the current Parking Lot Manager assignment only.
- Finalizing implementation details, API migrations, or UI wiring in this document.

## Source Framing

This design follows the repository's Scrum framing derived from *Scrum For Dummies, 2nd Edition* by Mark C. Layton (2018):

- user stories are the value-centric unit carried into a sprint and confirmed with acceptance criteria
- sprint planning decomposes selected stories into execution tasks
- Definition of Done is a broader quality bar than any single task

Within that framing, story acceptance criteria should define story completion, not the done contract of every decomposed task.

## Contract Hierarchy

The platform should explicitly model four layers:

### 1. Definition of Done

Cross-cutting quality, compliance, and non-functional standards that apply broadly. In this platform, compiled authority and inherited constraints may contribute to this layer.

### 2. Story

The user-value contract. The story owns:

- story statement
- story acceptance criteria
- story-level completion
- inherited DoD / compiled authority context

Story acceptance criteria answer: **"When is the story done?"**

### 3. Task

An execution slice inside the story. The task owns:

- task description
- task checklist
- artifact targets
- task-local hard constraints
- verification expectations
- expected evidence

Task completion answers: **"What must happen for this execution slice to be done?"**

### 4. Task Checklist Item

A very small action inside a task. Good candidates include:

- review
- confirmation
- storage
- attachment
- coordination
- minor cleanup around a larger task

Checklist items do not usually justify separate copyable agent prompts.

## Recommended Session Model

The platform should assume a session-bootstrap workflow.

### Copy Story Prompt

Purpose: initialize a fresh agent session for one story.

It should contain the stable context that should not be repeated in every task prompt:

- role/persona
- sprint goal
- parent story
- story acceptance criteria
- Definition of Done / compiled authority
- relevant project/product context
- expected reporting format for story-level outcomes

### Copy Task Prompt

Purpose: send only the local execution slice into an already configured story session.

It should contain:

- task description
- task checklist
- artifact targets
- task-local hard constraints
- task-specific verification/evidence expectations

`Copy Task Prompt` is intentionally **not** self-contained. The product should assume the user has already configured the session with the story prompt.

## Rendering Rules

### Story Prompt Rendering

The story prompt should:

- render story acceptance criteria
- render inherited DoD / compiled authority
- establish story scope for the session
- optionally show the decomposed task list as reference only

### Task Prompt Rendering

The task prompt should:

- not render story acceptance criteria as the task checklist
- render only the task checklist as the completion checklist
- include artifact targets and task-local constraints
- request task-specific evidence and verification
- optionally include a compact parent-story reference block for orientation only

### Critical Safeguard

If a task has no meaningful task checklist of its own, the platform must **not** synthesize one by copying story acceptance criteria.

Instead, the platform should either:

- keep the task informational/reference-only, or
- fold the work into another task as checklist items

## Task Checklist Heuristics

A task should remain a first-class prompt only when it has a meaningful execution outcome. Strong signals include:

- produces a real artifact
- changes system state in a reviewable way
- has distinct verification evidence
- benefits from independent execution tracking

An item should become a checklist entry instead of a standalone task when it is mostly:

- review
- confirm
- store
- attach
- coordinate
- close out a larger task

This allows task size to vary without forcing tiny administrative steps into full execution contracts.

## Verification and Logging Model

The platform should verify and record progress at two separate levels.

### Story Completion

Verified against:

- story acceptance criteria
- inherited DoD / compiled authority

Only story completion should claim that the full requested outcome exists.

### Task Completion

Verified against:

- task checklist
- task-local constraints
- task-specific evidence

Task completion should never require proving that the whole story is already complete.

### Task Evidence

The platform should support logging evidence such as:

- artifact produced
- file or document reference
- review note
- verification command or check
- blocker note when partial

This keeps tasks auditable without turning them into mini-stories.

## Edge Cases

### Single-Slice Stories

Some stories may have only one meaningful execution slice. In those cases, story and task can be close in size. The model should allow that without forcing unnecessary decomposition.

### Tiny Workflow Actions

If an item is too small to justify independent evidence, it should usually be modeled as a task checklist item rather than as a standalone task.

### Mixed Human/Agent Execution

The same contract should work whether tasks are executed by:

- a human developer
- a copy/paste agent workflow
- a future MCP-enabled agent

The transport may change, but the story/task contract should stay the same.

## Recommended Platform Terminology

Use the Scrum-like name **`task checklist`** for task-scoped completion items.

Recommended distinction:

- `story acceptance criteria`
- `task checklist`
- `definition of done`

This keeps the language understandable and avoids implying that task checklists replace story acceptance criteria.

## Consequences for the Current System

At a high level, the current prompt and packet model should evolve so that:

- story completion artifacts and task completion artifacts are separated
- task prompts no longer inherit story acceptance criteria as their done checklist
- first-class task generation becomes more selective
- checklist-worthy micro-actions are folded into larger execution tasks

This is a platform-level correction, not a project-specific workaround.

## Out-of-Scope Decisions Deferred to Planning

The following are intentionally deferred to the implementation-planning phase:

- exact schema changes for task checklist storage
- migration path for existing tasks
- UI changes for `Copy Story Prompt` and `Copy Task Prompt`
- API shape for story-level versus task-level prompt rendering
- evidence/logging persistence details

## Decision

Adopt a two-layer prompt model with a story-session bootstrap and task-level delta prompts.

The final contract is:

- story acceptance criteria define story completion
- task checklists define task completion
- Definition of Done applies across stories/increments
- tiny workflow actions should live as task checklist items, not standalone prompts
- task prompts assume the session was already configured by a story prompt
