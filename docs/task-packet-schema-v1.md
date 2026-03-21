# Task Packet v1 Schema Reference

## Summary

Task Packet v1 is a deterministic, on-demand execution handoff artifact. It is assembled directly from existing project data without LLM involvement and is anchored by the combination of `task_id` and `sprint_id`.

The packet is the canonical execution handoff model. Future human briefs and agent prompts must render from this payload instead of bypassing it.

## Canonical Schema

```ts
type TaskPacket = {
  schema_version: "task_packet.v1";

  metadata: {
    packet_id: string;
    generated_at: string;
    generator_version: "v1";
    source_fingerprint: string;
  };

  source_snapshot: {
    product_id: number;
    sprint_id: number;
    story_id: number;
    task_id: number;

    product_updated_at: string;
    sprint_updated_at: string;
    sprint_story_added_at: string;
    story_updated_at: string;
    story_ac_updated_at: string | null;
    task_updated_at: string;

    accepted_spec_version_id: number | null;
    validation_validated_at: string | null;
    validation_input_hash: string | null;
    compiled_authority_compiled_at: string | null;
  };

  task: {
    task_id: number;
    label: string;
    description: string;
    status: "To Do" | "In Progress" | "Done";
    assignee_member_id: number | null;
    assignee_name: string | null;
  };

  context: {
    story: {
      story_id: number;
      title: string;
      persona: string | null;
      story_description: string | null;
      status: "To Do" | "In Progress" | "Done" | "Accepted";
      story_points: number | null;
      rank: string | null;
      source_requirement: string | null;
    };

    sprint: {
      sprint_id: number;
      goal: string | null;
      status: "Planned" | "Active" | "Completed";
      started_at: string | null;
      start_date: string;
      end_date: string;
      team_id: number | null;
      team_name: string | null;
    };

    product: {
      product_id: number;
      name: string;
      vision_excerpt: string | null;
    };
  };

  constraints: {
    acceptance_criteria_text: string | null;
    acceptance_criteria_items: string[];

    spec_binding: {
      mode: "pinned_story_authority";
      binding_status: "pinned" | "unpinned";
      spec_version_id: number | null;
      authority_artifact_status: "available" | "missing";
    };

    validation: {
      present: boolean;
      passed: boolean | null;
      freshness_status: "current" | "stale" | "missing";
      validated_at: string | null;
      validator_version: string | null;
      current_story_input_hash: string;
      validation_input_hash: string | null;
      input_hash_matches: boolean | null;
      rules_checked: string[];
    };

    task_hard_constraints: Array<{
      invariant_id: string;
      type: "FORBIDDEN_CAPABILITY" | "REQUIRED_FIELD" | "MAX_VALUE";
      parameters: Record<string, string | number>;
      source_excerpt: string | null;
      source_location: string | null;
    }>;

    story_compliance_boundaries: Array<{
      invariant_id: string;
      type: "FORBIDDEN_CAPABILITY" | "REQUIRED_FIELD" | "MAX_VALUE";
      parameters: Record<string, string | number>;
      source_excerpt: string | null;
      source_location: string | null;
    }>;

    findings: Array<{
      severity: "warning" | "failure";
      source: "validation_failure" | "validation_warning" | "alignment_warning" | "alignment_failure";
      code: string;
      message: string;
      invariant_id: string | null;
      rule: string | null;
      capability: string | null;
    }>;
  };
};
```

## Assembly Rules

### Identity and linkage
- A packet is valid only if the requested task belongs to a story and that story is linked to the requested sprint through `SprintStory`.
- The API must reject invalid task/sprint combinations instead of inferring context.

### Deterministic helper fields
- `packet_id` is deterministic and derived from the tuple `(schema_version, sprint_id, task_id)`.
- `label` is a deterministic display label derived from the task description.
- `vision_excerpt` is the first non-empty paragraph of product vision, truncated deterministically.
- `acceptance_criteria_items` are derived by normalizing the raw acceptance criteria text into ordered line items.

### Spec authority
- Task Packet v1 uses **story-pinned authority only**.
- If `accepted_spec_version_id` exists, the packet may expose relevant invariants from that exact compiled authority.
- If `accepted_spec_version_id` is missing, the packet must set the spec binding to `unpinned`.
- The packet must never silently fall back to the latest product authority.

### Scoped Constraints
- Task Packet v1 removes `relevant_invariants` to avoid polluting narrow task bounds with broad story-level architectural context.
- `task_hard_constraints` handles specific execution bounds for the task. It remains explicitly empty in Phase 1 (until task metadata fields are introduced).
- `story_compliance_boundaries` is derived from the pinned compiled authority joined to invariant IDs referenced by alignment findings (`finding_invariant_ids`).
- If the compiled authority artifact is unavailable or unparsable, `authority_artifact_status` becomes `missing` and both constraint arrays remain empty.

### Validation freshness
- Validation freshness is based on the recomputed current story input hash versus the stored validation evidence input hash.
- `current` means the hashes match.
- `stale` means validation evidence exists but the hashes differ.
- `missing` means no validation evidence is present.

### Source fingerprint
- `source_fingerprint` must change when any of the following change:
  - task update
  - story update
  - acceptance criteria update
  - sprint update
  - sprint-story membership timestamp
  - validation evidence timestamp or input hash
  - pinned spec version
  - compiled authority compilation timestamp
  - product update

## Public Endpoint

`GET /api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet`

Returns the canonical Task Packet JSON payload directly. No packet persistence table or packet migration is required for v1.

## Explicit Non-Goals

Task Packet v1 does **not** include:
- prompt text
- human brief text
- agent-flavor formatting
- roadmap dumps
- sibling task dumps
- target file guesses
- codebase hints not already modeled upstream

Those belong in later renderers or future schema extensions, not in the canonical v1 packet.
