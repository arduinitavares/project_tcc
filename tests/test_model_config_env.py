"""Tests for model config environment overrides."""

from __future__ import annotations

from pathlib import Path

import pytest

from utils import model_config
from utils.model_config import get_model_id, get_openrouter_extra_body, get_story_pipeline_mode


@pytest.fixture
def temp_model_config(tmp_path: Path) -> Path:
    """Create a temporary model config file for tests."""
    config_path = tmp_path / "models.test.yaml"
    config_path.write_text(
        """
models:
  orchestrator: "openrouter/openai/gpt-5-mini"
  spec_authority_compiler: "openrouter/openai/gpt-5-mini"
  product_vision: "openrouter/openai/gpt-5-mini"
  product_roadmap: "openrouter/openai/gpt-5-mini"
  product_user_story: "openrouter/openai/gpt-5-mini"
  story_draft: "openrouter/openai/gpt-5-mini"
  spec_validator: "openrouter/openai/gpt-5-mini"
  story_refiner: "openrouter/openai/gpt-5-mini"
  invest_validator: "openrouter/openai/gpt-5-mini"

story_pipeline:
  mode: "single"
""".lstrip(),
        encoding="utf-8",
    )
    return config_path


def test_model_config_path_env_overrides(monkeypatch: pytest.MonkeyPatch, temp_model_config: Path) -> None:
    """MODEL_CONFIG_PATH should override the default config file."""
    monkeypatch.setenv("MODEL_CONFIG_PATH", str(temp_model_config))
    model_config.clear_config_cache()

    assert get_model_id("orchestrator") == "openrouter/openai/gpt-5-mini"
    assert get_story_pipeline_mode() == "single"


def test_relax_zdr_for_tests_toggles_privacy(monkeypatch: pytest.MonkeyPatch) -> None:
    """RELAX_ZDR_FOR_TESTS should relax the OpenRouter privacy routing."""
    monkeypatch.setenv("RELAX_ZDR_FOR_TESTS", "true")

    extra_body = get_openrouter_extra_body()
    provider = extra_body["provider"]

    assert provider["zdr"] is False
    assert provider["data_collection"] == "allow"
    assert provider["allow_fallbacks"] is True
    assert provider["require_parameters"] is False
