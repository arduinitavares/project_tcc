from utils import failure_artifacts


def test_write_and_read_failure_artifact_preserves_full_raw_output(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(failure_artifacts, "LOGS_DIR", tmp_path / "logs")
    monkeypatch.setattr(
        failure_artifacts, "FAILURES_DIR", tmp_path / "logs" / "failures"
    )

    raw_output = "x" * 5000
    persisted = failure_artifacts.write_failure_artifact(
        phase="story",
        project_id=17,
        failure_stage="invalid_json",
        failure_summary="Story response is not valid JSON",
        raw_output=raw_output,
        context={"parent_requirement": "Requirement A"},
        model_info={"model_id": "openai/gpt-5-mini"},
    )

    artifact_id = persisted["metadata"]["failure_artifact_id"]
    assert persisted["artifact_path"].exists()
    assert persisted["metadata"]["has_full_artifact"] is True
    assert (
        persisted["metadata"]["raw_output_preview"]
        == raw_output[: failure_artifacts.RAW_OUTPUT_PREVIEW_LIMIT]
    )

    loaded = failure_artifacts.read_failure_artifact(artifact_id)
    assert loaded is not None
    assert loaded["artifact_id"] == artifact_id
    assert loaded["phase"] == "story"
    assert loaded["project_id"] == 17
    assert loaded["raw_output"] == raw_output
    assert loaded["raw_output_length"] == len(raw_output)
