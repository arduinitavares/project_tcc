#!/usr/bin/env python3
"""One-shot: recompile spec authority for a given spec_version_id."""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from tools.spec_tools import compile_spec_authority_for_version

spec_version_id = int(sys.argv[1]) if len(sys.argv) > 1 else 9

print(f"Recompiling authority for spec_version_id={spec_version_id} ...")
result = compile_spec_authority_for_version(
    {"spec_version_id": spec_version_id, "force_recompile": True},
    tool_context=None,
)

import json
print(json.dumps(result, indent=2, default=str))
