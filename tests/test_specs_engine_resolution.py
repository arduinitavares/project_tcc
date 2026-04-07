from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    "module_name",
    [
        "services.specs.compiler_service",
        "services.specs.lifecycle_service",
        "services.specs.story_validation_service",
    ],
)
def test_resolve_engine_prefers_live_models_db_get_engine_over_stale_default_binding(
    monkeypatch,
    module_name: str,
):
    from models import db as model_db
    from services.specs._engine_resolution import resolve_spec_engine
    from tools import spec_tools

    service_module = importlib.import_module(module_name)
    preferred_engine = object()

    monkeypatch.setattr(model_db, "get_engine", lambda: preferred_engine)
    monkeypatch.setattr(spec_tools, "engine", model_db.engine, raising=False)
    monkeypatch.setattr(spec_tools, "get_engine", service_module.get_engine, raising=False)

    resolved = resolve_spec_engine(
        service_get_engine=service_module.get_engine,
        default_service_get_engine=service_module.get_engine,
    )

    assert resolved is preferred_engine


@pytest.mark.parametrize(
    "module_name",
    [
        "services.specs.compiler_service",
        "services.specs.lifecycle_service",
        "services.specs.story_validation_service",
    ],
)
def test_resolve_engine_preserves_explicit_service_local_get_engine_override(
    monkeypatch,
    module_name: str,
):
    from services.specs._engine_resolution import resolve_spec_engine
    from tools import spec_tools

    service_module = importlib.import_module(module_name)
    default_service_get_engine = service_module.get_engine
    local_engine = object()
    stale_engine = object()

    def local_get_engine():
        return local_engine

    monkeypatch.setattr(service_module, "get_engine", local_get_engine, raising=False)
    monkeypatch.setattr(spec_tools, "engine", stale_engine, raising=False)
    monkeypatch.setattr(spec_tools, "get_engine", local_get_engine, raising=False)

    resolved = resolve_spec_engine(
        service_get_engine=service_module.get_engine,
        default_service_get_engine=default_service_get_engine,
    )

    assert resolved is local_engine
