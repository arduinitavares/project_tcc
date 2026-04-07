"""Transitional sprint route registration.

This module keeps route declarations out of ``api.py`` while the handler
implementations still live there during the first extraction phase.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import FastAPI


Handler = Callable[..., Any]


def register_manual_sprint_routes(
    app: FastAPI,
    *,
    get_sprint_close: Handler,
    post_sprint_close: Handler,
    get_project_task_packet: Handler,
    get_project_story_packet: Handler,
    get_task_execution: Handler,
    post_task_execution: Handler,
    get_story_close: Handler,
    post_story_close: Handler,
) -> None:
    """Register the manual sprint close/execution/packet routes."""
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/close",
        get_sprint_close,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/close",
        post_sprint_close,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/packet",
        get_project_task_packet,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/packet",
        get_project_story_packet,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        get_task_execution,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/tasks/{task_id}/execution",
        post_task_execution,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        get_story_close,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/stories/{story_id}/close",
        post_story_close,
        methods=["POST"],
    )


def register_sprint_routes(
    app: FastAPI,
    *,
    get_project_sprint_candidates: Handler,
    generate_project_sprint: Handler,
    get_project_sprint_history: Handler,
    reset_project_sprint_planner: Handler,
    list_project_sprints: Handler,
    get_project_sprint: Handler,
    save_project_sprint: Handler,
    start_project_sprint: Handler,
    get_sprint_close: Handler,
    post_sprint_close: Handler,
    get_project_task_packet: Handler,
    get_project_story_packet: Handler,
    get_task_execution: Handler,
    post_task_execution: Handler,
    get_story_close: Handler,
    post_story_close: Handler,
) -> None:
    """Register the full sprint HTTP surface for the transitional router split."""
    app.add_api_route(
        "/api/projects/{project_id}/sprint/candidates",
        get_project_sprint_candidates,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprint/generate",
        generate_project_sprint,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprint/history",
        get_project_sprint_history,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprint/planner/reset",
        reset_project_sprint_planner,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints",
        list_project_sprints,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}",
        get_project_sprint,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprint/save",
        save_project_sprint,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/projects/{project_id}/sprints/{sprint_id}/start",
        start_project_sprint,
        methods=["PATCH"],
    )
    register_manual_sprint_routes(
        app,
        get_sprint_close=get_sprint_close,
        post_sprint_close=post_sprint_close,
        get_project_task_packet=get_project_task_packet,
        get_project_story_packet=get_project_story_packet,
        get_task_execution=get_task_execution,
        post_task_execution=post_task_execution,
        get_story_close=get_story_close,
        post_story_close=post_story_close,
    )
