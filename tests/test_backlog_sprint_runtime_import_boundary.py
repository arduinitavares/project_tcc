"""Focused boundary checks for backlog and sprint runtime import cleanup."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _imported_names_from(module_path: Path, import_source: str) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == import_source:
            imported_names.update(alias.name for alias in node.names)

    return imported_names


def _module_import_aliases(module_path: Path, module_name: str) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    aliases: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    aliases.add(alias.asname or alias.name)

    return aliases


def _module_import_access_paths(module_path: Path, module_name: str) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    access_paths: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == module_name:
                    access_paths.add(alias.asname or alias.name)

    return access_paths


def _dotted_attribute_references(module_path: Path) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    references: set[str] = set()

    def _as_dotted_name(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = _as_dotted_name(node.value)
            if parent is None:
                return None
            return f"{parent}.{node.attr}"
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            dotted_name = _as_dotted_name(node)
            if dotted_name is not None:
                references.add(dotted_name)

    return references


def test_backlog_primer_tool_import_boundary() -> None:
    module_path = ROOT / "orchestrator_agent/agent_tools/backlog_primer/tools.py"

    core_imports = _imported_names_from(module_path, "models.core")
    db_imports = _imported_names_from(module_path, "models.db")
    event_imports = _imported_names_from(module_path, "models.events")
    enum_imports = _imported_names_from(module_path, "models.enums")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    agile_aliases = _module_import_aliases(module_path, "agile_sqlmodel")
    dotted_refs = _dotted_attribute_references(module_path)
    agile_attr_refs = {
        f"{access_path}.{attr}"
        for access_path in {"agile_sqlmodel", *agile_aliases}
        for attr in (
            "UserStory",
            "get_engine",
            "StoryStatus",
            "WorkflowEvent",
            "WorkflowEventType",
        )
    }

    assert "UserStory" in core_imports
    assert "get_engine" in db_imports
    assert "WorkflowEvent" in event_imports
    assert "StoryStatus" in enum_imports
    assert "WorkflowEventType" in enum_imports

    assert "UserStory" not in agile_imports
    assert "get_engine" not in agile_imports
    assert "StoryStatus" not in agile_imports
    assert "WorkflowEvent" not in agile_imports
    assert "WorkflowEventType" not in agile_imports
    assert not (agile_attr_refs & dotted_refs)


def test_sprint_planner_tool_import_boundary() -> None:
    module_path = ROOT / "orchestrator_agent/agent_tools/sprint_planner_tool/tools.py"

    core_imports = _imported_names_from(module_path, "models.core")
    db_imports = _imported_names_from(module_path, "models.db")
    event_imports = _imported_names_from(module_path, "models.events")
    enum_imports = _imported_names_from(module_path, "models.enums")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    dotted_refs = _dotted_attribute_references(module_path)
    agile_runtime_attr_refs = {
        f"{access_path}.{attr}"
        for access_path in _module_import_access_paths(module_path, "agile_sqlmodel")
        for attr in (
            "Product",
            "SprintStatus",
            "Sprint",
            "SprintStory",
            "Task",
            "Team",
            "UserStory",
            "get_engine",
            "WorkflowEvent",
            "WorkflowEventType",
        )
    }

    assert {
        "Product",
        "Sprint",
        "SprintStory",
        "Task",
        "Team",
        "UserStory",
    } <= core_imports
    assert "get_engine" in db_imports
    assert "WorkflowEvent" in event_imports
    assert {"SprintStatus", "WorkflowEventType"} <= enum_imports
    assert "get_engine" not in agile_imports
    assert "SprintStatus" not in agile_imports
    assert "SprintStory" not in agile_imports
    assert "Team" not in agile_imports
    assert "WorkflowEvent" not in agile_imports
    assert "WorkflowEventType" not in agile_imports
    assert "Task" not in agile_imports
    assert "Product" not in agile_imports
    assert "UserStory" not in agile_imports
    assert not (agile_runtime_attr_refs & dotted_refs)
