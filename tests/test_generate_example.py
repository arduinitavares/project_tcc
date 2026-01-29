import json
from pathlib import Path

from scripts.generate_example import build_demo_artifacts, save_artifacts


def test_build_demo_artifacts_contains_expected_keys() -> None:
    artifacts = build_demo_artifacts()
    assert "software_example" in artifacts
    assert "construction_forbidden_example" in artifacts
    assert "construction_required_field_example" in artifacts


def test_save_artifacts_writes_json_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "artifacts"
    written = save_artifacts(output_dir)

    assert len(written) == 3
    for path in written:
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert "input" in payload
        assert "invariants" in payload
        assert "result" in payload
        assert "passed" in payload["result"]
        assert "findings" in payload["result"]
