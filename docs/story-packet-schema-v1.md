# Story Packet v1 Schema Reference

## Summary

Story Packet v1 is the canonical story-session bootstrap artifact. It is assembled deterministically from persisted project data, anchored by `story_id + sprint_id`, and carries the story completion contract plus inherited product/sprint/spec context.

This packet is the stable bootstrap companion to `task_packet.v2`.

## Canonical Schema

```ts
type StoryPacket = {
  schema_version: "story_packet.v1";

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

    product_updated_at: string;
    sprint_updated_at: string;
    sprint_story_added_at: string;
    story_updated_at: string;
    story_ac_updated_at: string | null;

    accepted_spec_version_id: number | null;
    validation_validated_at: string | null;
    validation_input_hash: string | null;
    compiled_authority_compiled_at: string | null;
  };

  story: {
    story_id: number;
    title: string;
    persona: string | null;
    story_description: string | null;
    acceptance_criteria_text: string | null;
    acceptance_criteria_items: string[];
    status: "To Do" | "In Progress" | "Done" | "Accepted";
    story_points: number | null;
    rank: string | null;
    source_requirement: string | null;
  };

  context: {
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

- A Story Packet is valid only if the requested story belongs to the project and is linked to the requested sprint through `SprintStory`.
- The API must reject invalid story/sprint combinations instead of inferring context.

### Story completion contract

- `acceptance_criteria_text` is copied directly from the persisted story.
- `acceptance_criteria_items` are derived by deterministically normalizing the acceptance criteria text into ordered line items.
- Story completion remains story-scoped; task-local checklist items are not stored here.

### Spec authority and validation

- Story Packet v1 uses only story-pinned authority.
- `story_compliance_boundaries` are derived from validation finding invariant IDs resolved against the pinned compiled authority.
- If the story is unpinned or the compiled artifact is unavailable, the spec binding reflects that state and the boundaries array is empty.

### Source fingerprint

- `source_fingerprint` must change when story, sprint, sprint membership, validation, authority, or product timestamps relevant to the packet change.

## Public Endpoint

`GET /api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet`

Returns the canonical Story Packet v1 JSON payload directly.
