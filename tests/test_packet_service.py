"""Tests for packet service."""

import pytest

from services.packets.packet_service import (
    PacketServiceError,
    get_story_packet,
    get_task_packet,
)


def test_get_task_packet_returns_payload_without_render() -> None:
    """Verify get task packet returns payload without render."""
    packet = {"schema_version": "task_packet.v2", "task": {"task_id": 7}}

    payload = get_task_packet(
        load_packet=lambda: packet,
        flavor=None,
        render_packet=lambda _packet, _flavor: "unused",
    )

    assert payload == packet


def test_get_task_packet_adds_render_when_flavor_is_requested() -> None:
    """Verify get task packet adds render when flavor is requested."""
    packet = {"schema_version": "task_packet.v2", "task": {"task_id": 7}}

    payload = get_task_packet(
        load_packet=lambda: packet,
        flavor="cursor",
        render_packet=lambda input_packet, flavor: (
            f"{flavor}:{input_packet['schema_version']}"
        ),
    )

    assert payload == {
        "schema_version": "task_packet.v2",
        "task": {"task_id": 7},
        "render": "cursor:task_packet.v2",
    }


def test_get_story_packet_raises_not_found_when_packet_missing() -> None:
    """Verify get story packet raises not found when packet missing."""
    with pytest.raises(PacketServiceError) as exc_info:
        get_story_packet(
            load_packet=lambda: None,
            flavor=None,
            render_packet=lambda _packet, _flavor: "unused",
        )

    assert exc_info.value.status_code == 404  # noqa: PLR2004
    assert exc_info.value.detail == "Story packet context not found"
