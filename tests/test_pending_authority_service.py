"""Tests for pending spec authority project setup."""

import inspect
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import get_type_hints

import pytest
from sqlalchemy.engine import Engine
from sqlmodel import Session, select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
)
from tests.typing_helpers import require_id

EXPECTED_APPROVAL_NOTES = (
    "Required compiler precondition for pending authority generation"
)


def _pending_service() -> ModuleType:
    from services.specs import pending_authority_service  # noqa: PLC0415

    return pending_authority_service


def _create_product(session: Session, *, name: str = "Pending Product") -> Product:
    product = Product(name=name, vision="vision")
    session.add(product)
    session.commit()
    session.refresh(product)
    return product


def _write_spec(tmp_path: Path, content: str = "# Spec\n\nBuild the thing.") -> Path:
    spec_path = tmp_path / "spec.md"
    spec_path.write_text(content, encoding="utf-8")
    return spec_path


def _persist_authority(
    session: Session, *, spec_version_id: int
) -> CompiledSpecAuthority:
    authority = CompiledSpecAuthority(
        spec_version_id=spec_version_id,
        compiler_version="fake-compiler",
        prompt_hash="f" * 64,
        compiled_at=datetime.now(UTC),
        compiled_artifact_json='{"ok": true}',
        scope_themes='["Scope"]',
        invariants="[]",
        eligible_feature_ids="[]",
        rejected_features="[]",
        spec_gaps="[]",
    )
    session.add(authority)
    session.commit()
    session.refresh(authority)
    return authority


def test_pending_authority_public_contract_is_keyword_only() -> None:
    """The service seam should match the runner-facing public contract."""
    service = _pending_service()
    signature = inspect.signature(service.compile_pending_authority_for_project)

    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    result_hints = get_type_hints(service.PendingAuthorityResult)
    assert result_hints["spec_path"] is str


def test_compile_pending_authority_creates_artifact_without_acceptance(
    session: Session, tmp_path: Path
) -> None:
    """Pending setup should compile authority without accepting it."""
    service = _pending_service()
    product = _create_product(session)
    product_id = require_id(product.product_id, "product_id")
    spec_path = _write_spec(tmp_path)

    def compile_authority(
        spec_version_id: int,
        force_recompile: bool | None = None,
        tool_context: object | None = None,
        lease_guard: object | None = None,
        record_progress: object | None = None,
    ) -> dict[str, object]:
        del tool_context
        assert force_recompile is False
        if callable(lease_guard):
            assert lease_guard("compiled_authority_persisted") is True
        authority = _persist_authority(session, spec_version_id=spec_version_id)
        if callable(record_progress):
            assert record_progress("compiled_authority_persisted") is True
        return {
            "success": True,
            "authority_id": authority.authority_id,
            "spec_version_id": spec_version_id,
            "compiler_version": authority.compiler_version,
            "prompt_hash": authority.prompt_hash,
        }

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=compile_authority,
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is True
    assert result.spec_version_id is not None
    assert result.authority_id is not None

    session.expire_all()
    saved_product = session.get(Product, product_id)
    assert saved_product is not None
    assert saved_product.spec_file_path == str(spec_path.resolve())
    assert saved_product.spec_loaded_at is not None

    specs = session.exec(
        select(SpecRegistry).where(SpecRegistry.product_id == product_id)
    ).all()
    assert len(specs) == 1
    assert specs[0].status == "approved"
    assert specs[0].approved_by == "cli-project-create"
    assert specs[0].approval_notes == EXPECTED_APPROVAL_NOTES

    acceptances = session.exec(select(SpecAuthorityAcceptance)).all()
    assert acceptances == []


def test_compile_pending_authority_for_project_rejects_missing_spec_file(
    session: Session, tmp_path: Path
) -> None:
    """Missing spec files should fail before persistence."""
    service = _pending_service()
    product = _create_product(session)

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=require_id(product.product_id, "product_id"),
        spec_path=tmp_path / "missing.md",
        approved_by="cli-project-create",
        compile_authority=lambda **_: {"success": True},
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "SPEC_FILE_NOT_FOUND"


def test_compile_pending_authority_for_project_rejects_non_utf8_spec_file(
    session: Session, tmp_path: Path
) -> None:
    """Non-UTF-8 spec files should fail before persistence."""
    service = _pending_service()
    product = _create_product(session)
    spec_path = tmp_path / "bad.md"
    spec_path.write_bytes(b"\xff\xfe\x00")

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=require_id(product.product_id, "product_id"),
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=lambda **_: {"success": True},
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "SPEC_FILE_INVALID"


def test_compile_pending_authority_for_project_maps_compiler_failure(
    session: Session, tmp_path: Path
) -> None:
    """Compiler failure should return the pending spec version for recovery."""
    service = _pending_service()
    product = _create_product(session)
    spec_path = _write_spec(tmp_path)

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=require_id(product.product_id, "product_id"),
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=lambda **_: {"success": False, "error": "boom"},
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "SPEC_COMPILE_FAILED"
    assert result.spec_version_id is not None


def test_compile_pending_authority_for_project_removes_bad_acceptance_write(
    session: Session, engine: Engine, tmp_path: Path
) -> None:
    """A compiler seam must not be able to leave accepted authority behind."""
    service = _pending_service()
    product = _create_product(session)
    product_id = require_id(product.product_id, "product_id")
    spec_path = _write_spec(tmp_path)

    def bad_compiler(spec_version_id: int, **_: object) -> dict[str, object]:
        authority = _persist_authority(session, spec_version_id=spec_version_id)
        acceptance = SpecAuthorityAcceptance(
            product_id=product_id,
            spec_version_id=spec_version_id,
            status="accepted",
            policy="auto",
            decided_by="bad-seam",
            decided_at=datetime.now(UTC),
            rationale="should be removed",
            compiler_version=authority.compiler_version,
            prompt_hash=authority.prompt_hash,
            spec_hash="x" * 64,
        )
        session.add(acceptance)
        session.commit()
        return {
            "success": True,
            "authority_id": authority.authority_id,
            "compiler_version": authority.compiler_version,
            "prompt_hash": authority.prompt_hash,
        }

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=bad_compiler,
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "MUTATION_FAILED"
    assert result.spec_version_id is not None

    with Session(engine) as fresh_session:
        remaining = fresh_session.exec(
            select(SpecAuthorityAcceptance).where(
                SpecAuthorityAcceptance.product_id == product_id,
                SpecAuthorityAcceptance.spec_version_id == result.spec_version_id,
            )
        ).all()
    assert remaining == []


def test_compile_pending_authority_cleans_bad_acceptance_on_compiler_failure(
    session: Session, engine: Engine, tmp_path: Path
) -> None:
    """Compiler failures must not leave canonical acceptance rows behind."""
    service = _pending_service()
    product = _create_product(session)
    product_id = require_id(product.product_id, "product_id")
    spec_path = _write_spec(tmp_path)

    def bad_compiler(spec_version_id: int, **_: object) -> dict[str, object]:
        authority = _persist_authority(session, spec_version_id=spec_version_id)
        acceptance = SpecAuthorityAcceptance(
            product_id=product_id,
            spec_version_id=spec_version_id,
            status="accepted",
            policy="auto",
            decided_by="bad-seam",
            decided_at=datetime.now(UTC),
            rationale="should be removed",
            compiler_version=authority.compiler_version,
            prompt_hash=authority.prompt_hash,
            spec_hash="x" * 64,
        )
        session.add(acceptance)
        session.commit()
        return {"success": False, "error": "bad seam failed after acceptance"}

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=bad_compiler,
        lease_guard=lambda _boundary: True,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "MUTATION_FAILED"
    assert result.spec_version_id is not None

    with Session(engine) as fresh_session:
        remaining = fresh_session.exec(
            select(SpecAuthorityAcceptance).where(
                SpecAuthorityAcceptance.product_id == product_id,
                SpecAuthorityAcceptance.spec_version_id == result.spec_version_id,
            )
        ).all()
    assert remaining == []


@pytest.mark.parametrize(
    ("blocked_boundary", "expect_product_link", "expect_spec", "expect_approved"),
    [
        ("product_spec_linked", False, False, False),
        ("spec_registry_written", True, False, False),
        ("spec_marked_approved", True, True, False),
    ],
)
def test_compile_pending_authority_lease_loss_prevents_durable_write(  # noqa: PLR0913
    session: Session,
    tmp_path: Path,
    blocked_boundary: str,
    expect_product_link: bool,
    expect_spec: bool,
    expect_approved: bool,
) -> None:
    """A lost lease should stop the guarded durable write."""
    service = _pending_service()
    product = _create_product(session)
    product_id = require_id(product.product_id, "product_id")
    spec_path = _write_spec(tmp_path)

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=lambda **_: {"success": True},
        lease_guard=lambda boundary: boundary != blocked_boundary,
        record_progress=lambda _boundary: True,
    )

    assert result.ok is False
    assert result.error_code == "MUTATION_IN_PROGRESS"

    session.expire_all()
    saved_product = session.get(Product, product_id)
    assert saved_product is not None
    assert (saved_product.spec_file_path is not None) is expect_product_link

    specs = session.exec(
        select(SpecRegistry).where(SpecRegistry.product_id == product_id)
    ).all()
    assert bool(specs) is expect_spec
    assert any(spec.status == "approved" for spec in specs) is expect_approved


@pytest.mark.parametrize(
    ("failed_boundary", "mode"),
    [
        ("product_spec_linked", "false"),
        ("spec_registry_written", "false"),
        ("spec_marked_approved", "raise"),
    ],
)
def test_compile_pending_authority_for_project_record_progress_failure_after_write(
    session: Session, tmp_path: Path, failed_boundary: str, mode: str
) -> None:
    """Progress-record failures should report recovery with the boundary name."""
    service = _pending_service()
    product = _create_product(session)
    product_id = require_id(product.product_id, "product_id")
    spec_path = _write_spec(tmp_path)

    def record_progress(boundary: str) -> bool:
        if boundary != failed_boundary:
            return True
        if mode == "raise":
            message = f"record failed at {boundary}"
            raise RuntimeError(message)
        return False

    result = service.compile_pending_authority_for_project(
        session=session,
        product_id=product_id,
        spec_path=spec_path,
        approved_by="cli-project-create",
        compile_authority=lambda **_: {"success": True},
        lease_guard=lambda _boundary: True,
        record_progress=record_progress,
    )

    assert result.ok is False
    assert result.error_code == "MUTATION_RECOVERY_REQUIRED"
    assert result.error is not None
    assert failed_boundary in result.error

    session.expire_all()
    saved_product = session.get(Product, product_id)
    assert saved_product is not None
    assert saved_product.spec_file_path == str(spec_path.resolve())
