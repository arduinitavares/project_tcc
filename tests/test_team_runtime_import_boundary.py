"""Focused boundary checks for runtime Team import cleanup."""

from __future__ import annotations

import ast
from pathlib import Path


def _imported_names_from(module_path: Path, import_source: str) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == import_source:
            imported_names.update(alias.name for alias in node.names)

    return imported_names


def _attribute_references_from_import(
    module_path: Path, import_name: str, attrs: set[str]
) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    referenced: set[str] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id == import_name
            and node.attr in attrs
        ):
            referenced.add(node.attr)

    return referenced


def test_sprint_planner_tool_imports_team_from_models_core() -> None:
    """Verify sprint planner tool imports team from models core."""
    root = Path(__file__).resolve().parents[1]
    module_path = root / "orchestrator_agent/agent_tools/sprint_planner_tool/tools.py"

    core_imports = _imported_names_from(module_path, "models.core")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    agile_attr_refs = _attribute_references_from_import(
        module_path, "agile_sqlmodel", {"Team"}
    )

    assert "Team" in core_imports
    assert "Team" not in agile_imports
    assert "Team" not in agile_attr_refs
