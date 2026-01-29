from utils import model_config
from utils.model_config import get_story_pipeline_mode


def test_get_story_pipeline_mode_defaults_to_batch(monkeypatch):
    """Default to batch when config is missing."""
    monkeypatch.setattr(model_config, "_load_config", lambda: {})
    assert get_story_pipeline_mode() == "batch"


def test_get_story_pipeline_mode_reads_single(monkeypatch):
    """Read single mode from config."""
    monkeypatch.setattr(
        model_config,
        "_load_config",
        lambda: {"story_pipeline": {"mode": "single"}},
    )
    assert get_story_pipeline_mode() == "single"
