#!/usr/bin/env python3
"""Debug: show why specific stories fail validation."""
import sys, json
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from tools.spec_tools import validate_story_with_spec_authority

SPEC_VERSION_ID = 9
STORY_IDS = [62, 63, 64, 75]  # sample of fails + a pass

for sid in STORY_IDS:
    res = validate_story_with_spec_authority({"story_id": sid, "spec_version_id": SPEC_VERSION_ID})
    print(f"\n=== Story {sid}: {'PASS' if res.get('passed') else 'FAIL'} ===")
    print(json.dumps(res, indent=2, default=str)[:1000])
