"""Focused unit tests for the packet renderer (prompt contract split)."""

from services.packet_renderer import render_packet, render_human_brief


def _minimal_packet(
    *,
    schema_version="task_packet.v2",
    task_label="Implement feature X",
    task_description="Build the feature",
    ac_items=None,
    task_checklist_items=None,
    sprint_goal=None,
    story_title=None,
    story_description=None,
    task_kind="implementation",
    artifact_targets=None,
    workstream_tags=None,
    task_hard_constraints=None,
    story_compliance_boundaries=None,
    task_plan=None,
):
    """Build the smallest valid packet dict for renderer testing."""
    packet = {
        "schema_version": schema_version,
        "task": {
            "task_id": 1,
            "label": task_label,
            "description": task_description,
            "status": "To Do",
            "task_kind": task_kind,
            "artifact_targets": artifact_targets or [],
            "workstream_tags": workstream_tags or [],
            "checklist_items": task_checklist_items or [],
        },
        "context": {
            "story": {
                "story_id": 7,
                "title": story_title,
                "story_description": story_description,
            },
            "sprint": {
                "sprint_id": 3,
                "goal": sprint_goal,
            },
            "product": {
                "name": "Test Product",
            },
        },
        "constraints": {
            "acceptance_criteria_items": ac_items or [],
            "task_hard_constraints": task_hard_constraints or [],
            "story_compliance_boundaries": story_compliance_boundaries or [],
            "story_acceptance_criteria_items": ac_items or [],
        },
    }
    if task_plan is not None:
        packet["task_plan"] = {"tasks": task_plan}
    return packet


# ------------------------------------------------------------------
# Execution Protocol
# ------------------------------------------------------------------

def test_render_packet_uses_task_checklist_for_task_packets():
    packet = _minimal_packet(
        schema_version="task_packet.v2",
        story_title="Parent Story",
        story_description="Bootstrap the execution session.",
        task_checklist_items=["Confirm request shape", "Add request tests"],
        ac_items=["Story AC should stay out of task prompts"],
    )
    output = render_packet(packet, "cursor")

    assert "Task Checklist" in output
    assert "Verify every task checklist item before claiming completion." in output
    assert "This prompt assumes the session was already initialized with the parent story prompt. If not, restart with Copy Story Prompt." in output
    assert "- [ ] Confirm request shape" in output
    assert "- [ ] Add request tests" in output
    assert "Acceptance Criteria Checklist" not in output
    assert "Story AC should stay out of task prompts" not in output


def test_render_packet_uses_story_acceptance_criteria_for_story_packets():
    packet = _minimal_packet(
        schema_version="story_packet.v1",
        story_title="Parent Story",
        story_description="Bootstrap the execution session.",
        ac_items=["include user_id", "reject invalid payloads"],
        task_plan=[
            {
                "id": 12,
                "description": "Implement request validation",
                "status": "To Do",
                "task_kind": "implementation",
                "artifact_targets": ["validator"],
                "workstream_tags": ["backend"],
                "checklist_items": ["Confirm request shape"],
                "is_executable": True,
            }
        ],
    )
    output = render_packet(packet, "cursor")

    assert "Story Acceptance Criteria" in output
    assert "- [ ] include user_id" in output
    assert "- [ ] reject invalid payloads" in output
    assert "Task Checklist" not in output
    assert "Task Plan Reference" in output
    assert "Implement request validation" in output


def test_human_brief_has_no_execution_contract():
    packet = _minimal_packet(ac_items=["some AC"], task_checklist_items=["some checklist"])
    output = render_human_brief(packet)
    assert "<execution_protocol>" not in output
    assert "<completion_report>" not in output
    assert "## Completion Report" not in output
