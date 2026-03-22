# Improve the Copy Agent Prompt

The [render_agent_prompt](file:///Users/aaat/projects/project_tcc/services/packet_renderer.py#94-171) function in [services/packet_renderer.py](file:///Users/aaat/projects/project_tcc/services/packet_renderer.py) renders a task packet as an XML-tagged prompt optimized for AI coding agents (Cursor, Copilot, etc.). The current implementation has three issues the user wants to address:

1. **Empty info pollution** — sections like [(None specified)](file:///Users/aaat/projects/project_tcc/api.py#954-957) or [(No task-local hard constraints identified)](file:///Users/aaat/projects/project_tcc/api.py#954-957) add noise with no value.
2. **No modern prompting pattern** — the prompt lacks a ReAct-style reasoning loop and structured AC verification checklist.
3. **Unstructured output** — the prompt doesn't request structured progress/completion output that the user can quickly parse when reviewing work.

## Proposed Changes

### Core Renderer

#### [MODIFY] [packet_renderer.py](file:///Users/aaat/projects/project_tcc/services/packet_renderer.py)

**1. Suppress empty sections** instead of emitting placeholders:

```diff
-    parts.append("  <artifact_targets>")
-    if artifact_targets:
-        for item in artifact_targets:
-            parts.append(f"    - {_escape_xml(item)}")
-    else:
-        parts.append("    (None specified)")
-    parts.append("  </artifact_targets>")
+    if artifact_targets:
+        parts.append("  <artifact_targets>")
+        for item in artifact_targets:
+            parts.append(f"    - {_escape_xml(item)}")
+        parts.append("  </artifact_targets>")
```

Apply the same pattern to: `sprint_goal`, `parent_story`, `workstream_tags`, [story_compliance_boundaries](file:///Users/aaat/projects/project_tcc/api.py#530-569), [hard_constraints](file:///Users/aaat/projects/project_tcc/api.py#571-608), and [acceptance_criteria](file:///Users/aaat/projects/project_tcc/api.py#429-447). If a section has no data, omit it entirely. Empty `<context>` and `<task_context>` wrappers should also be omitted when all their children are empty.

**2. Add ReAct reasoning loop with AC verification** as a `<execution_protocol>` block:

After the existing content, append a structured execution protocol that instructs the coding agent to:
- **Think** before acting (state your plan before writing code)
- **Act** on one AC at a time
- **Observe** the result after each change
- After all work is done, run through every AC item and verify each one

**3. Add structured output template** as a `<completion_report>` block:

After the execution protocol, include a structured output template that the agent should fill in when the work is done. This template will make review faster by producing parseable output:

```xml
<completion_report>
When you finish, output your completion report in exactly this format:

## Completion Report
**Task**: [task label]
**Status**: DONE | PARTIAL | BLOCKED

### Acceptance Criteria Checklist
- [x] AC item 1 — brief note on how it was met
- [ ] AC item 2 — reason it was not met

### Changes Made
- file_path: what changed and why

### Verification
- What you tested and how

### Blockers / Follow-ups
- Any issues or open items (or "None")
</completion_report>
```

> [!IMPORTANT]
> The completion report template dynamically includes the actual AC items from the packet, so the agent gets pre-filled checkboxes matching the real acceptance criteria.

## Verification Plan

### Automated Tests

The existing test [test_packet_renderer_escapes_html_and_xml_safely](file:///Users/aaat/projects/project_tcc/tests/test_api_sprint_flow.py#954-988) in [test_api_sprint_flow.py](file:///Users/aaat/projects/project_tcc/tests/test_api_sprint_flow.py) tests the agent flavor rendering. We will write new, focused unit tests in a new file for the renderer:

#### [NEW] [test_packet_renderer.py](file:///Users/aaat/projects/project_tcc/tests/test_packet_renderer.py)

Unit tests that directly test [render_agent_prompt](file:///Users/aaat/projects/project_tcc/services/packet_renderer.py#94-171) and [render_human_brief](file:///Users/aaat/projects/project_tcc/services/packet_renderer.py#28-92) with controlled packet dicts:

1. **`test_agent_prompt_omits_empty_sections`** — pass a packet with no sprint goal, no story description, no artifact targets, no workstream tags, no constraints → assert none of the placeholder strings appear.
2. **`test_agent_prompt_includes_populated_sections`** — pass a fully populated packet → assert all XML tags are present.
3. **`test_agent_prompt_has_execution_protocol`** — assert the output contains `<execution_protocol>` and ReAct keywords ("Think", "Act", "Verify").
4. **`test_agent_prompt_has_completion_report_with_ac_items`** — pass a packet with specific AC items → assert the completion report template includes those exact items as checkboxes.
5. **`test_agent_prompt_no_ac_omits_ac_section`** — pass a packet with empty AC → assert no `<acceptance_criteria>` tag appears.

Run with:
```bash
python -m pytest tests/test_packet_renderer.py -v
```

### Existing Tests

All existing tests must continue to pass:
```bash
python -m pytest tests/test_api_sprint_flow.py -v
```
