"""Focused boundary checks for api.py runtime import cleanup."""

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


def _bound_import_names_from(module_path: Path, import_source: str) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    imported_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == import_source:
            imported_names.update(alias.asname or alias.name for alias in node.names)

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


def _legacy_agile_imports(module_path: Path) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    legacy_imports: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == "agile_sqlmodel" or node.module.startswith(
                "agile_sqlmodel."
            ):
                legacy_imports.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "agile_sqlmodel" or alias.name.startswith(
                    "agile_sqlmodel."
                ):
                    legacy_imports.add(alias.name)

    return legacy_imports


def test_api_import_boundary_for_moved_runtime_surfaces() -> None:
    module_path = ROOT / "api.py"

    core_imports = _imported_names_from(module_path, "models.core")
    core_bound_imports = _bound_import_names_from(module_path, "models.core")
    enum_imports = _imported_names_from(module_path, "models.enums")
    enum_bound_imports = _bound_import_names_from(module_path, "models.enums")
    legacy_agile_imports = _legacy_agile_imports(module_path)

    assert {"Product", "Sprint", "SprintStory", "Task", "UserStory"} <= core_imports
    assert {"Product", "Sprint", "SprintStory", "Task", "UserStory"} <= core_bound_imports
    assert {"SprintStatus", "StoryStatus", "TaskStatus", "WorkflowEventType"} <= enum_imports
    assert {"SprintStatus", "StoryStatus", "TaskStatus", "WorkflowEventType"} <= enum_bound_imports
    assert not legacy_agile_imports
