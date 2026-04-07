"""Packet endpoint orchestration helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class PacketServiceError(Exception):
    """Domain-level packet error for router translation."""

    def __init__(self, detail: str, *, status_code: int = 404) -> None:
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code


def get_task_packet(
    *,
    load_packet: Callable[[], dict[str, Any] | None],
    flavor: str | None,
    render_packet: Callable[[dict[str, Any], str], str],
) -> dict[str, Any]:
    packet = load_packet()
    if not packet:
        raise PacketServiceError("Task packet context not found")

    payload = dict(packet)
    if flavor:
        payload["render"] = render_packet(packet, flavor)
    return payload


def get_story_packet(
    *,
    load_packet: Callable[[], dict[str, Any] | None],
    flavor: str | None,
    render_packet: Callable[[dict[str, Any], str], str],
) -> dict[str, Any]:
    packet = load_packet()
    if not packet:
        raise PacketServiceError("Story packet context not found")

    payload = dict(packet)
    if flavor:
        payload["render"] = render_packet(packet, flavor)
    return payload
