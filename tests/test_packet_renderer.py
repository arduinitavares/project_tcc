"""Focused unit tests for the packet renderer (agent prompt execution contract)."""

from services.packet_renderer import render_agent_prompt, render_human_brief


def _minimal_packet(
    *,
    task_label="Implement feature X",
    task_description="Build the feature",
    ac_items=None,
    sprint_goal=None,
    story_title=None,
    story_description=None,
    task_kind="implementation",
    artifact_targets=None,
    workstream_tags=None,
    task_hard_constraints=None,
    story_compliance_boundaries=None,
):
    """Build the smallest valid packet dict for renderer testing."""
    return {
        "task": {
            "task_id": 1,
            "label": task_label,
            "description": task_description,
            "status": "To Do",
            "task_kind": task_kind,
            "artifact_targets": artifact_targets or [],
            "workstream_tags": workstream_tags or [],
        },
        "context": {
            "story": {
                "title": story_title,
                "story_description": story_description,
            },
            "sprint": {
                "goal": sprint_goal,
            },
            "product": {},
        },
        "constraints": {
            "acceptance_criteria_items": ac_items or [],
            "task_hard_constraints": task_hard_constraints or [],
            "story_compliance_boundaries": story_compliance_boundaries or [],
        },
    }


# ------------------------------------------------------------------
# Execution Protocol
# ------------------------------------------------------------------

def test_agent_prompt_includes_execution_protocol():
    packet = _minimal_packet()
    output = render_agent_prompt(packet)
    assert "<execution_protocol>" in output
    assert "</execution_protocol>" in output
    assert "Verify every acceptance-criteria item before claiming completion" in output


def test_agent_prompt_includes_completion_report():
    packet = _minimal_packet()
    output = render_agent_prompt(packet)
    assert "<completion_report>" in output
    assert "</completion_report>" in output
    assert "## Completion Report" in output
    assert "### Acceptance Criteria Checklist" in output
    assert "### Changes Made" in output
    assert "### Verification" in output
    assert "### Blockers / Follow-ups" in output


# ------------------------------------------------------------------
# Completion Report — task label
# ------------------------------------------------------------------

def test_completion_report_contains_task_label():
    packet = _minimal_packet(task_label="Validate user inputs")
    output = render_agent_prompt(packet)
    assert "**Task**: Validate user inputs" in output


def test_completion_report_escapes_unsafe_task_label():
    packet = _minimal_packet(task_label='<script>alert("xss")</script>')
    output = render_agent_prompt(packet)
    assert "<script>" not in output
    assert "&lt;script&gt;" in output


# ------------------------------------------------------------------
# Completion Report — AC checklist
# ------------------------------------------------------------------

def test_completion_report_prefills_ac_items():
    packet = _minimal_packet(ac_items=["include user_id", "reject invalid payloads"])
    output = render_agent_prompt(packet)
    assert "- [ ] include user_id" in output
    assert "- [ ] reject invalid payloads" in output


def test_no_ac_uses_fallback_line():
    packet = _minimal_packet(ac_items=[])
    output = render_agent_prompt(packet)
    assert "- No explicit acceptance criteria were provided in the packet." in output


def test_completion_report_escapes_unsafe_ac_item():
    packet = _minimal_packet(ac_items=['must escape <xml> & "quotes"'])
    output = render_agent_prompt(packet)
    # Inside the completion report template
    assert "&lt;xml&gt;" in output
    assert "&amp;" in output


# ------------------------------------------------------------------
# Human Brief is unchanged
# ------------------------------------------------------------------

def test_human_brief_has_no_execution_contract():
    packet = _minimal_packet(ac_items=["some AC"])
    output = render_human_brief(packet)
    assert "<execution_protocol>" not in output
    assert "<completion_report>" not in output
    assert "## Completion Report" not in output


# ------------------------------------------------------------------
# Protocol rules content
# ------------------------------------------------------------------

def test_execution_protocol_has_all_rules():
    packet = _minimal_packet()
    output = render_agent_prompt(packet)
    assert "brief, visible work plan" in output
    assert "Do not expose internal reasoning" in output
    assert "observable progress" in output
    assert "source of truth" in output
    assert "Verify every acceptance-criteria item" in output
    assert "blocked or only partially complete" in output


def test_completion_report_has_brief_plan_section():
    packet = _minimal_packet()
    output = render_agent_prompt(packet)
    assert "### Brief Plan" in output
