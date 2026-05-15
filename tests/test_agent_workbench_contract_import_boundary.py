"""Import-boundary tests for CLI contract hardening modules."""

from __future__ import annotations

import json
import subprocess  # nosec B404
import sys


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

    result = subprocess.run(  # noqa: S603  # nosec B603
        [sys.executable, "-c", script],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"api": False, "fastapi": False}
