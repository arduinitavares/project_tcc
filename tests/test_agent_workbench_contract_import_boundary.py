"""Import-boundary tests for CLI contract hardening modules."""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys


def _run_import_boundary_script(script: str) -> subprocess.CompletedProcess[str]:
    """Run an import-boundary script in a clean Python process."""
    return subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )


def test_contract_modules_do_not_import_dashboard_api() -> None:
    """Keep CLI contract modules independent from FastAPI/dashboard imports."""
    script = """
import importlib
import json
import sys

importlib.import_module("services.agent_workbench.command_schema")
importlib.import_module("services.agent_workbench.diagnostics")
importlib.import_module("services.agent_workbench.mutation_ledger")

print(json.dumps({"api": "api" in sys.modules, "fastapi": "fastapi" in sys.modules}))
"""

    result = _run_import_boundary_script(script)

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"api": False, "fastapi": False}


def test_project_setup_modules_do_not_import_dashboard_or_route_handlers() -> None:
    """Keep Phase 2B CLI setup modules out of dashboard/API boundaries."""
    script = """
import importlib
import json
import sys

modules = [
    "cli.main",
    "services.agent_workbench.application",
    "services.agent_workbench.project_setup",
    "services.specs.pending_authority_service",
]
for module in modules:
    importlib.import_module(module)

def is_forbidden(module_name):
    if module_name == "api" or module_name.startswith("api."):
        return True
    if module_name == "fastapi" or module_name.startswith("fastapi."):
        return True
    parts = module_name.split(".")
    return bool({"dashboard", "dashboards", "routes", "route_handlers"} & set(parts))

forbidden = sorted(name for name in sys.modules if is_forbidden(name))
required_safe_modules = [
    "models.core",
    "services.agent_workbench.project_setup",
    "services.specs.pending_authority_service",
    "sqlmodel",
    "sqlalchemy",
]
runtime_only_modules = [
    "services.workflow",
    "services.specs.compiler_service",
    "repositories.session",
]
print(
    json.dumps(
        {
            "forbidden": forbidden,
            "required_safe_loaded": {
                name: name in sys.modules for name in required_safe_modules
            },
            "runtime_only_loaded": {
                name: name in sys.modules for name in runtime_only_modules
            },
        },
        sort_keys=True,
    )
)
"""

    result = _run_import_boundary_script(script)

    assert result.returncode == 0, result.stderr
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["forbidden"] == []
    assert all(payload["required_safe_loaded"].values())
    assert not any(payload["runtime_only_loaded"].values())
