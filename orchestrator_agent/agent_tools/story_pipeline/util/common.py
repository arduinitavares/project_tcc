"""Shared helpers for story pipeline tools."""

from sqlmodel import Session, select

from agile_sqlmodel import (
    CompiledSpecAuthority,
    SpecAuthorityAcceptance,
    SpecRegistry,
)


def load_compiled_authority(
    session: Session,
    product_id: int,
    spec_version_id: int,
) -> tuple[SpecRegistry, CompiledSpecAuthority, str]:
    """Load compiled authority and spec content for a pinned spec version."""
    spec_version = session.get(SpecRegistry, spec_version_id)
    if not spec_version:
        raise ValueError(f"Spec version {spec_version_id} not found")
    if spec_version.product_id != product_id:
        raise ValueError(
            f"Spec version {spec_version_id} does not belong to product {product_id}"
        )
    compiled_authority = session.exec(
        select(CompiledSpecAuthority).where(
            CompiledSpecAuthority.spec_version_id == spec_version_id
        )
    ).first()
    if not compiled_authority:
        raise ValueError(f"spec_version_id {spec_version_id} is not compiled")
    acceptance = session.exec(
        select(SpecAuthorityAcceptance).where(
            SpecAuthorityAcceptance.spec_version_id == spec_version_id,
            SpecAuthorityAcceptance.status == "accepted",
        )
    ).first()
    if not acceptance:
        raise ValueError(
            f"spec_version_id {spec_version_id} authority not accepted"
        )
    technical_spec = spec_version.content or ""
    return spec_version, compiled_authority, technical_spec
