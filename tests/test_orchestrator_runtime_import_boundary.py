"""Focused boundary checks for orchestrator runtime import cleanup."""

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


def _attribute_references_from_import(
    module_path: Path, import_names: set[str], attrs: set[str]
) -> set[str]:
    source_text = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source_text, filename=str(module_path))
    referenced: set[str] = set()

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in import_names
            and node.attr in attrs
        ):
            referenced.add(node.attr)

    return referenced


def test_orchestrator_query_service_import_boundary() -> None:
    module_path = ROOT / "services/orchestrator_query_service.py"

    core_imports = _imported_names_from(module_path, "models.core")
    core_bound_imports = _bound_import_names_from(module_path, "models.core")
    db_imports = _imported_names_from(module_path, "models.db")
    db_bound_imports = _bound_import_names_from(module_path, "models.db")
    enum_imports = _imported_names_from(module_path, "models.enums")
    enum_bound_imports = _bound_import_names_from(module_path, "models.enums")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    agile_aliases = _module_import_aliases(module_path, "agile_sqlmodel")
    agile_attr_refs = _attribute_references_from_import(
        module_path,
        {"agile_sqlmodel", *agile_aliases},
        {"Sprint"},
    )

    assert "Sprint" in core_imports
    assert "Sprint" in core_bound_imports
    assert "get_engine" in db_imports
    assert "get_engine" in db_bound_imports
    assert "SprintStatus" in enum_imports
    assert "SprintStatus" in enum_bound_imports
    assert "Sprint" not in agile_imports
    assert not agile_attr_refs


def test_orchestrator_context_service_import_boundary() -> None:
    module_path = ROOT / "services/orchestrator_context_service.py"

    core_imports = _imported_names_from(module_path, "models.core")
    core_bound_imports = _bound_import_names_from(module_path, "models.core")
    db_imports = _imported_names_from(module_path, "models.db")
    db_bound_imports = _bound_import_names_from(module_path, "models.db")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    agile_aliases = _module_import_aliases(module_path, "agile_sqlmodel")
    agile_attr_refs = _attribute_references_from_import(
        module_path,
        {"agile_sqlmodel", *agile_aliases},
        {"Sprint"},
    )

    assert "Sprint" in core_imports
    assert "Sprint" in core_bound_imports
    assert "get_engine" in db_imports
    assert "get_engine" in db_bound_imports
    assert "Sprint" not in agile_imports
    assert not agile_attr_refs


def test_orchestrator_tools_import_boundary() -> None:
    module_path = ROOT / "tools/orchestrator_tools.py"

    core_imports = _imported_names_from(module_path, "models.core")
    core_bound_imports = _bound_import_names_from(module_path, "models.core")
    db_imports = _imported_names_from(module_path, "models.db")
    db_bound_imports = _bound_import_names_from(module_path, "models.db")
    enum_imports = _imported_names_from(module_path, "models.enums")
    enum_bound_imports = _bound_import_names_from(module_path, "models.enums")
    agile_imports = _imported_names_from(module_path, "agile_sqlmodel")
    agile_aliases = _module_import_aliases(module_path, "agile_sqlmodel")
    db_aliases = _module_import_aliases(module_path, "models.db")
    enum_aliases = _module_import_aliases(module_path, "models.enums")
    agile_attr_refs = _attribute_references_from_import(
        module_path,
        {"agile_sqlmodel", *agile_aliases},
        {"Product", "get_engine", "StoryStatus"},
    )

    assert {"Product", "UserStory"} <= core_imports
    assert {"Product", "UserStory"} <= core_bound_imports
    assert db_imports == {"get_engine"}
    assert db_bound_imports == {"get_engine"}
    assert enum_imports == {"StoryStatus"}
    assert enum_bound_imports == {"StoryStatus"}
    assert not agile_imports
    assert not db_aliases
    assert not enum_aliases
    assert not agile_aliases
    assert not agile_attr_refs
