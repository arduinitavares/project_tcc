import html
from typing import Dict, Any

def _escape_md(text: Any) -> str:
    """Escapes HTML entities and Markdown tokens to prevent XSS and formatting injection."""
    if not text:
        return ""
    # Escape HTML to prevent XSS
    safe_str = html.escape(str(text), quote=False)
    # Encode markdown characters to prevent JS regex match interference
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

def render_human_brief(packet: Dict[str, Any]) -> str:
    """Renders the canonical packet into a clean Markdown brief for human developers."""
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})
    
    story = context.get("story", {})
    sprint = context.get("sprint", {})
    product = context.get("product", {})
    
    parts = []
    
    task_label = _escape_md(task.get("label", "Task"))
    parts.append(f"# Task: {task_label}")
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

    parts.append("## Context & Background")
    if story.get("title"):
        parts.append(f"**Parent Story**: {_escape_md(story.get('title'))}")
        if story.get("story_description"):
            parts.append(f"> {_escape_md(story.get('story_description'))}\n")
            
    if sprint.get("goal"):
        parts.append(f"**Sprint Goal**: {_escape_md(sprint.get('goal'))}\n")

    if product.get("vision_excerpt"):
        parts.append(f"**Product Vision**: {_escape_md(product.get('vision_excerpt'))}\n")

    parts.append("## Acceptance Criteria")
    ac_items = constraints.get("acceptance_criteria_items", [])
    if ac_items:
        for item in ac_items:
            parts.append(f"- [ ] {_escape_md(item)}")
    else:
        parts.append("* No acceptance criteria provided.")
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
    task = packet.get("task", {})
    context = packet.get("context", {})
    constraints = packet.get("constraints", {})
    
    story = context.get("story", {})
    sprint = context.get("sprint", {})
    
    parts = []
    
    parts.append("You are an expert full-stack developer. Your objective is to explicitly implement the provided `<task>` without hallucinating out-of-scope features or ignoring constraints.\n")
    
    parts.append("<context>")
    if sprint.get('goal'):
        parts.append(f"  <sprint_goal>{_escape_xml(sprint.get('goal'))}</sprint_goal>")
    if story.get('title'):
        parts.append(f"  <parent_story>{_escape_xml(story.get('title'))}")
        if story.get('story_description'):
            parts.append(f"    {_escape_xml(story.get('story_description'))}")
        parts.append("  </parent_story>")
    parts.append("</context>\n")
    
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

    parts.append("<acceptance_criteria>")
    ac_items = constraints.get("acceptance_criteria_items", [])
    if ac_items:
        for item in ac_items:
            parts.append(f"  - {_escape_xml(item)}")
    else:
        parts.append("  (None provided)")
    parts.append("</acceptance_criteria>\n")
    
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

    # --- Execution Protocol (fixed renderer text) ---
    parts.append("<execution_protocol>")
    parts.append("1. Start by writing a brief, visible work plan before making any changes.")
    parts.append("2. Do not expose internal reasoning, hidden chain-of-thought, or self-talk.")
    parts.append("3. Communicate only observable progress: plan, implementation summary, verification results, and blockers.")
    parts.append("4. Treat the packet as the single source of truth: task description, acceptance criteria, task hard constraints, and story compliance boundaries.")
    parts.append("5. Verify every acceptance-criteria item before claiming completion.")
    parts.append("6. If blocked or only partially complete, state so explicitly instead of implying success.")
    parts.append("</execution_protocol>\n")

    # --- Completion Report (dynamic AC checklist) ---
    task_label = _escape_xml(task.get("label", task.get("description", "Task")))
    parts.append("<completion_report>")
    parts.append("When you finish, output your completion report in exactly this Markdown format:\n")
    parts.append("## Completion Report")
    parts.append(f"**Task**: {task_label}")
    parts.append("**Status**: DONE | PARTIAL | BLOCKED\n")
    parts.append("### Brief Plan")
    parts.append("- ...\n")
    parts.append("### Acceptance Criteria Checklist")
    if ac_items:
        for item in ac_items:
            parts.append(f"- [ ] {_escape_xml(item)}")
    else:
        parts.append("- No explicit acceptance criteria were provided in the packet.")
    parts.append("")
    parts.append("### Changes Made")
    parts.append("- <file or area>: <what changed and why>\n")
    parts.append("### Verification")
    parts.append("- <command, check, or review performed>\n")
    parts.append("### Blockers / Follow-ups")
    parts.append("- None")
    parts.append("</completion_report>")

    return "\n".join(parts)


def render_packet(packet: Dict[str, Any], flavor: str) -> str:
    """Dispatcher for packet rendering flavors."""
    normalized = flavor.strip().lower()
    if normalized in ("human", "markdown", "brief"):
        return render_human_brief(packet)
    elif normalized in ("cursor", "copilot", "agent", "xml"):
        return render_agent_prompt(packet)
    else:
        return render_agent_prompt(packet)
