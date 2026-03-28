import html
from typing import Any, Dict


TASK_SCHEMA_VERSION = "task_packet.v2"
STORY_SCHEMA_VERSION = "story_packet.v1"


def _escape_md(text: Any) -> str:
    """Escapes HTML entities and Markdown tokens to prevent XSS and formatting injection."""
    if not text:
        return ""
    safe_str = html.escape(str(text), quote=False)
    return safe_str.replace("#", "&#35;").replace("*", "&#42;")


def _escape_xml(text: Any) -> str:
    """Escapes XML entities to maintain tag boundaries for Agent Prompts."""
    return html.escape(str(text or ""), quote=True) if text else ""


def _render_invariants_markdown(invariants: list) -> str:
    if not invariants:
        return "* No pinned specification invariants found.\n"

    lines = []
    for inv in invariants:
        inv_type = _escape_md(inv.get("type", "RULE"))
        excerpt = _escape_md(inv.get("source_excerpt", ""))
        lines.append(f"- **[{inv_type}]** {excerpt}")
    return "\n".join(lines) + "\n"


def _schema_version(packet: Dict[str, Any]) -> str:
    return str(packet.get("schema_version") or "").strip().lower()


def _task_checklist_items(packet: Dict[str, Any]) -> list:
    task = packet.get("task", {})
    return list(task.get("checklist_items") or [])


def _story_acceptance_criteria_items(packet: Dict[str, Any]) -> list:
    constraints = packet.get("constraints", {})
    return list(constraints.get("story_acceptance_criteria_items") or [])


def _story_task_plan_items(packet: Dict[str, Any]) -> list:
    task_plan = packet.get("task_plan", {})
    tasks = task_plan.get("tasks") or []
    return list(tasks)


def _render_story_task_plan_reference(packet: Dict[str, Any]) -> str:
    tasks = _story_task_plan_items(packet)
    if not tasks:
        return "  (No task plan reference provided)"

    lines = []
    for task in tasks:
        task_id = task.get("id", "unknown")
        description = _escape_xml(task.get("description", ""))
        lines.append(f"  - [{task_id}] {description}")
    return "\n".join(lines)


def _render_task_agent_prompt(packet: Dict[str, Any]) -> str:
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})

    story = context.get("story", {})
    sprint = context.get("sprint", {})
    checklist_items = _task_checklist_items(packet)

    parts = []

    parts.append(
        "You are an expert full-stack developer. Your objective is to explicitly implement the provided `<task>` without hallucinating out-of-scope features or ignoring constraints.\n"
    )

    parts.append("<context>")
    if sprint.get("goal"):
        parts.append(f"  <sprint_goal>{_escape_xml(sprint.get('goal'))}</sprint_goal>")
    if story.get("title"):
        parts.append(f"  <parent_story>{_escape_xml(story.get('title'))}")
        if story.get("story_description"):
            parts.append(f"    {_escape_xml(story.get('story_description'))}")
        parts.append("  </parent_story>")
    parts.append("</context>\n")

    parts.append(
        "This prompt assumes the session was already initialized with the parent story prompt. If not, restart with Copy Story Prompt.\n"
    )

    parts.append("<task>")
    parts.append(f"  {_escape_xml(task.get('description', 'Unknown task'))}")
    parts.append("</task>\n")

    parts.append("<task_context>")
    parts.append(f"  <task_kind>{_escape_xml(task.get('task_kind', 'other'))}</task_kind>")
    artifact_targets = task.get("artifact_targets", [])
    parts.append("  <artifact_targets>")
    if artifact_targets:
        for item in artifact_targets:
            parts.append(f"    - {_escape_xml(item)}")
    else:
        parts.append("    (None specified)")
    parts.append("  </artifact_targets>")
    workstream_tags = task.get("workstream_tags", [])
    parts.append("  <workstream_tags>")
    if workstream_tags:
        for item in workstream_tags:
            parts.append(f"    - {_escape_xml(item)}")
    else:
        parts.append("    (None specified)")
    parts.append("  </workstream_tags>")
    parts.append("</task_context>\n")

    parts.append("<task_checklist>")
    if checklist_items:
        for item in checklist_items:
            parts.append(f"  - {_escape_xml(item)}")
    else:
        parts.append("  (No task checklist items provided)")
    parts.append("</task_checklist>\n")

    story_boundaries = constraints.get("story_compliance_boundaries", [])
    if story_boundaries:
        parts.append("<story_compliance_boundaries>")
        for inv in story_boundaries:
            inv_type = _escape_xml(inv.get("type", "RULE"))
            excerpt = _escape_xml(inv.get("source_excerpt", ""))
            parts.append(f"  - [{inv_type}] {excerpt}")
        parts.append("</story_compliance_boundaries>\n")

    parts.append("<hard_constraints>")
    task_constraints = constraints.get("task_hard_constraints", [])
    if task_constraints:
        for inv in task_constraints:
            inv_type = _escape_xml(inv.get("type", "RULE"))
            excerpt = _escape_xml(inv.get("source_excerpt", ""))
            parts.append(f"  - [{inv_type}] {excerpt}")
    else:
        parts.append("  (No task-local hard constraints identified)")
    parts.append("</hard_constraints>\n")

    parts.append("<execution_protocol>")
    parts.append("1. Start by writing a brief, visible work plan before making any changes.")
    parts.append("2. Do not expose internal reasoning, hidden chain-of-thought, or self-talk.")
    parts.append(
        "3. Communicate only observable progress: plan, implementation summary, verification results, and blockers."
    )
    parts.append(
        "4. Treat the packet as the single source of truth: task description, task checklist, task hard constraints, and story compliance boundaries."
    )
    parts.append("5. Verify every task checklist item before claiming completion.")
    parts.append(
        "6. This prompt assumes the session was already initialized with the parent story prompt. If not, restart with Copy Story Prompt."
    )
    parts.append("</execution_protocol>\n")

    task_label = _escape_xml(task.get("label", task.get("description", "Task")))
    parts.append("<completion_report>")
    parts.append(
        "Use this Markdown structure for your final completion report. Preserve normal human-readable text in the final report. Do not include XML/HTML escaping in the final report unless the escaped form is part of the intended literal content.\n"
    )
    parts.append("## Completion Report")
    parts.append(f"**Task**: {task_label}")
    parts.append("**Status**: DONE | PARTIAL | BLOCKED\n")
    parts.append("### Brief Plan")
    parts.append("- ...\n")
    parts.append("### Task Checklist")
    if checklist_items:
        for item in checklist_items:
            parts.append(f"- [ ] {_escape_xml(item)}")
    else:
        parts.append("- No task checklist items were provided in the packet.")
    parts.append("")
    parts.append("### Changes Made")
    parts.append("- [file or area]: [what changed and why]\n")
    parts.append("### Verification")
    parts.append("- [command, check, or review performed]\n")
    parts.append("### Blockers / Follow-ups")
    parts.append("- None")
    parts.append("</completion_report>")

    return "\n".join(parts)


def _render_story_agent_prompt(packet: Dict[str, Any]) -> str:
    story = packet.get("story", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})

    sprint = context.get("sprint", {})
    product = context.get("product", {})
    ac_items = _story_acceptance_criteria_items(packet)
    task_plan_items = _story_task_plan_items(packet)

    parts = []

    parts.append(
        "You are bootstrapping a fresh story session. Use the story acceptance criteria to define the completion contract.\n"
    )

    parts.append("<context>")
    if sprint.get("goal"):
        parts.append(f"  <sprint_goal>{_escape_xml(sprint.get('goal'))}</sprint_goal>")
    if story.get("title"):
        parts.append(f"  <story_title>{_escape_xml(story.get('title'))}</story_title>")
    if story.get("story_description"):
        parts.append(
            f"  <story_description>{_escape_xml(story.get('story_description'))}</story_description>"
        )
    if product.get("vision_excerpt"):
        parts.append(f"  <product_vision>{_escape_xml(product.get('vision_excerpt'))}</product_vision>")
    parts.append("</context>\n")

    parts.append("<story_acceptance_criteria>")
    if ac_items:
        for item in ac_items:
            parts.append(f"  - {_escape_xml(item)}")
    else:
        parts.append("  (No story acceptance criteria provided)")
    parts.append("</story_acceptance_criteria>\n")

    parts.append("<task_plan_reference>")
    task_plan_reference = _render_story_task_plan_reference(packet)
    parts.append(task_plan_reference)
    parts.append("</task_plan_reference>\n")

    story_boundaries = constraints.get("story_compliance_boundaries", [])
    if story_boundaries:
        parts.append("<story_compliance_boundaries>")
        for inv in story_boundaries:
            inv_type = _escape_xml(inv.get("type", "RULE"))
            excerpt = _escape_xml(inv.get("source_excerpt", ""))
            parts.append(f"  - [{inv_type}] {excerpt}")
        parts.append("</story_compliance_boundaries>\n")

    parts.append("<execution_protocol>")
    parts.append("1. Start by writing a brief, visible work plan before making any changes.")
    parts.append("2. Do not expose internal reasoning, hidden chain-of-thought, or self-talk.")
    parts.append(
        "3. Communicate only observable progress: plan, implementation summary, verification results, and blockers."
    )
    parts.append(
        "4. Treat the packet as the single source of truth: story description, story acceptance criteria, task plan reference, and story compliance boundaries."
    )
    parts.append("5. Verify every story acceptance criteria item before claiming completion.")
    parts.append("6. Use the task plan as reference only; it is not the done checklist for the story.")
    parts.append("</execution_protocol>\n")

    story_label = _escape_xml(story.get("title", "Story"))
    parts.append("<completion_report>")
    parts.append(
        "Use this Markdown structure for your final completion report. Preserve normal human-readable text in the final report. Do not include XML/HTML escaping in the final report unless the escaped form is part of the intended literal content.\n"
    )
    parts.append("## Completion Report")
    parts.append(f"**Story**: {story_label}")
    parts.append("**Status**: DONE | PARTIAL | BLOCKED\n")
    parts.append("### Brief Plan")
    parts.append("- ...\n")
    parts.append("### Story Acceptance Criteria")
    if ac_items:
        for item in ac_items:
            parts.append(f"- [ ] {_escape_xml(item)}")
    else:
        parts.append("- No story acceptance criteria were provided in the packet.")
    parts.append("")
    parts.append("### Task Plan Reference")
    if task_plan_items:
        for task in task_plan_items:
            parts.append(f"- [{task.get('id', 'unknown')}] {_escape_xml(task.get('description', ''))}")
    else:
        parts.append("- No task plan reference was provided.")
    parts.append("")
    parts.append("### Changes Made")
    parts.append("- [file or area]: [what changed and why]\n")
    parts.append("### Verification")
    parts.append("- [command, check, or review performed]\n")
    parts.append("### Blockers / Follow-ups")
    parts.append("- None")
    parts.append("</completion_report>")

    return "\n".join(parts)


def render_human_brief(packet: Dict[str, Any]) -> str:
    """Renders the canonical packet into a clean Markdown brief for human developers."""
    schema_version = _schema_version(packet)
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})

    story = context.get("story", {})
    sprint = context.get("sprint", {})
    product = context.get("product", {})

    parts = []

    if schema_version == STORY_SCHEMA_VERSION:
        parts.append(f"# Story: {_escape_md(story.get('title', 'Story'))}")
        if story.get("story_description"):
            parts.append(f"{_escape_md(story.get('story_description'))}\n")
        parts.append("## Story Brief")
        if sprint.get("goal"):
            parts.append(f"**Sprint Goal**: {_escape_md(sprint.get('goal'))}")
        if product.get("vision_excerpt"):
            parts.append(f"**Product Vision**: {_escape_md(product.get('vision_excerpt'))}\n")

        parts.append("## Story Acceptance Criteria")
        ac_items = _story_acceptance_criteria_items(packet)
        if ac_items:
            for item in ac_items:
                parts.append(f"- [ ] {_escape_md(item)}")
        else:
            parts.append("* No story acceptance criteria provided.")
        parts.append("")

        task_plan_items = _story_task_plan_items(packet)
        parts.append("## Task Plan Reference")
        if task_plan_items:
            for task_item in task_plan_items:
                parts.append(
                    f"- [{task_item.get('id', 'unknown')}] {_escape_md(task_item.get('description', ''))}"
                )
        else:
            parts.append("* No task plan reference provided.")
        parts.append("")

        story_boundaries = constraints.get("story_compliance_boundaries", [])
        if story_boundaries:
            parts.append("## Story Compliance Boundaries")
            parts.append(_render_invariants_markdown(story_boundaries))
        return "\n".join(parts)

    parts.append(f"# Task: {_escape_md(task.get('label', 'Task'))}")
    parts.append(f"{_escape_md(task.get('description', ''))}\n")

    task_kind = _escape_md(task.get("task_kind", "other"))
    parts.append("## Task Profile")
    parts.append(f"**Task Kind**: {task_kind}")
    artifact_targets = task.get("artifact_targets", [])
    if artifact_targets:
        parts.append(f"**Artifact Targets**: {_escape_md(', '.join(artifact_targets))}")
    else:
        parts.append("**Artifact Targets**: None specified")
    workstream_tags = task.get("workstream_tags", [])
    if workstream_tags:
        parts.append(f"**Workstream Tags**: {_escape_md(', '.join(workstream_tags))}\n")
    else:
        parts.append("**Workstream Tags**: None specified\n")

    parts.append("## Parent Story Orientation")
    if story.get("title"):
        parts.append(f"**Parent Story**: {_escape_md(story.get('title'))}")
        if story.get("story_description"):
            parts.append(f"> {_escape_md(story.get('story_description'))}\n")

    if sprint.get("goal"):
        parts.append(f"**Sprint Goal**: {_escape_md(sprint.get('goal'))}\n")

    if product.get("vision_excerpt"):
        parts.append(f"**Product Vision**: {_escape_md(product.get('vision_excerpt'))}\n")

    parts.append("## Task Checklist")
    checklist_items = _task_checklist_items(packet)
    if checklist_items:
        for item in checklist_items:
            parts.append(f"- [ ] {_escape_md(item)}")
    else:
        parts.append("* No task checklist items provided.")
    parts.append("")

    parts.append("## Task-Local Hard Constraints")
    task_constraints = constraints.get("task_hard_constraints", [])
    if task_constraints:
        parts.append(_render_invariants_markdown(task_constraints))
    else:
        parts.append("* (No task-local hard constraints identified)\n")

    story_boundaries = constraints.get("story_compliance_boundaries", [])
    if story_boundaries:
        parts.append("## Story Compliance Boundaries")
        parts.append(_render_invariants_markdown(story_boundaries))

    return "\n".join(parts)


def render_agent_prompt(packet: Dict[str, Any]) -> str:
    """Renders the canonical packet into a strict, XML-tagged prompt optimized for AI Coding Agents."""
    schema_version = _schema_version(packet)
    if schema_version == STORY_SCHEMA_VERSION:
        return _render_story_agent_prompt(packet)
    return _render_task_agent_prompt(packet)


def render_packet(packet: Dict[str, Any], flavor: str) -> str:
    """Dispatcher for packet rendering flavors."""
    normalized = (flavor or "").strip().lower()
    if normalized in ("human", "markdown", "brief"):
        return render_human_brief(packet)
    if normalized in ("cursor", "copilot", "agent", "xml"):
        return render_agent_prompt(packet)
    return render_agent_prompt(packet)
