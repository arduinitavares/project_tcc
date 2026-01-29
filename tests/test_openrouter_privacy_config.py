"""Tests for OpenRouter privacy routing configuration."""

from utils.model_config import (
    OPENROUTER_PRIVACY_ERROR_MESSAGE,
    OPENROUTER_PROVIDER,
    get_openrouter_extra_body,
)


def test_openrouter_extra_body_includes_provider():
    """Extra body should include a provider object with strict privacy controls."""
    extra_body = get_openrouter_extra_body()
    assert extra_body["provider"] == OPENROUTER_PROVIDER
    assert extra_body["provider"] is not OPENROUTER_PROVIDER


def test_openrouter_privacy_error_message_is_stable():
    """Privacy error message should be explicit and stable for routing failures."""
    assert (
        OPENROUTER_PRIVACY_ERROR_MESSAGE
        == "No ZDR/data_collection=deny provider available for this model"
    )
