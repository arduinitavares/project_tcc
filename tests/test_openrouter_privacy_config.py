"""Tests for OpenRouter privacy routing configuration."""

from utils.model_config import (
    OPENROUTER_PRIVACY_ERROR_MESSAGE,
    OPENROUTER_PROVIDER,
    ZDR_MAX_RETRIES,
    ZDR_MAX_BACKOFF_SECONDS,
    get_openrouter_extra_body,
    is_zdr_routing_error,
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


def test_is_zdr_routing_error_detects_zdr_errors():
    """is_zdr_routing_error should detect ZDR/privacy routing failures."""
    # Should detect
    assert is_zdr_routing_error(Exception("No ZDR provider available"))
    assert is_zdr_routing_error(Exception("data_collection=deny not supported"))
    assert is_zdr_routing_error(Exception("No providers available for this model"))
    assert is_zdr_routing_error(Exception("provider unavailable, no matching providers"))
    
    # Should NOT detect (unrelated errors)
    assert not is_zdr_routing_error(Exception("Connection timeout"))
    assert not is_zdr_routing_error(Exception("Invalid API key"))
    assert not is_zdr_routing_error(ValueError("Bad input"))


def test_zdr_retry_constants_are_reasonable():
    """ZDR retry constants should have sensible defaults."""
    assert ZDR_MAX_RETRIES >= 3  # At least 3 retries
    assert ZDR_MAX_RETRIES <= 10  # Not too many
    assert ZDR_MAX_BACKOFF_SECONDS >= 5.0  # At least 5s max backoff
    assert ZDR_MAX_BACKOFF_SECONDS <= 30.0  # Not too long
