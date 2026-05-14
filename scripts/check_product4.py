"""Quick script to check product 4 and spec authority status."""

import sys
from pathlib import Path

from utils.cli_output import emit

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlmodel import Session, select  # noqa: E402

from agile_sqlmodel import (  # noqa: E402
    CompiledSpecAuthority,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
    get_engine,
)


def main() -> None:  # noqa: C901, PLR0912
    """Return main."""
    with Session(get_engine()) as session:
        # Check product 4
        product = session.exec(select(Product).where(Product.product_id == 4)).first()  # noqa: PLR2004
        if product:
            emit(f"Product ID: {product.product_id}")
            emit(f"Name: {product.name}")
            emit(f"Vision: {product.vision[:200] if product.vision else 'N/A'}...")
        else:
            emit("Product 4 not found!")
            return

        # Check spec versions for this product
        emit("\n--- Spec Versions ---")
        spec_versions = session.exec(
            select(SpecRegistry).where(SpecRegistry.product_id == 4)  # noqa: PLR2004
        ).all()
        for sv in spec_versions:
            emit(f"  SpecVersion ID: {sv.spec_version_id}, path: {sv.content_ref}")

        # Check acceptance status
        emit("\n--- Spec Authority Acceptances ---")
        acceptances = session.exec(
            select(SpecAuthorityAcceptance).where(
                SpecAuthorityAcceptance.product_id == 4  # noqa: PLR2004
            )
        ).all()
        for acc in acceptances:
            emit(
                f"  Acceptance: spec_version_id={acc.spec_version_id}, status={acc.status}"  # noqa: E501
            )

        if not acceptances:
            emit("  No acceptances found for product 4")

        # Check compiled spec authorities
        emit("\n--- Compiled Spec Authorities ---")
        for sv in spec_versions:
            compiled = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == sv.spec_version_id
                )
            ).first()
            if compiled:
                artifact_json = compiled.compiled_artifact_json
                has_artifact = artifact_json is not None
                artifact_len = len(artifact_json) if artifact_json is not None else 0
                emit(
                    f"  spec_version_id={sv.spec_version_id}: has_artifact={has_artifact}, artifact_len={artifact_len}"  # noqa: E501
                )
                if artifact_json is not None:
                    # Try to validate it
                    from utils.spec_schemas import (  # noqa: PLC0415
                        SpecAuthorityCompilationFailure,
                        SpecAuthorityCompilationSuccess,
                        SpecAuthorityCompilerOutput,
                    )

                    try:
                        parsed = SpecAuthorityCompilerOutput.model_validate_json(
                            artifact_json
                        )
                        if isinstance(parsed.root, SpecAuthorityCompilationFailure):
                            emit(
                                f"    -> FAILURE envelope: {parsed.root.error[:100]}..."
                            )
                        elif isinstance(parsed.root, SpecAuthorityCompilationSuccess):
                            emit(
                                f"    -> SUCCESS: {len(parsed.root.scope_themes)} themes, {len(parsed.root.invariants)} invariants"  # noqa: E501
                            )
                        else:
                            emit(f"    -> UNKNOWN type: {type(parsed.root)}")
                    except Exception as e:  # noqa: BLE001
                        emit(f"    -> VALIDATION ERROR: {e}")
                        emit(
                            f"    -> Raw artifact preview: {artifact_json[:500]}..."
                        )
            else:
                emit(f"  spec_version_id={sv.spec_version_id}: NO COMPILED RECORD")

        # Test calling ensure_accepted_spec_authority directly
        emit("\n--- Calling ensure_accepted_spec_authority directly ---")
        from tools.spec_tools import ensure_accepted_spec_authority  # noqa: PLC0415

        try:
            spec_version_id = ensure_accepted_spec_authority(
                product_id=4,
                spec_content=None,
                content_ref=None,
                recompile=False,
                tool_context=None,
            )
            emit(f"SUCCESS: returned spec_version_id={spec_version_id}")
        except RuntimeError as e:
            emit(f"FAILED with RuntimeError: {e}")
        except Exception as e:  # noqa: BLE001
            emit(f"FAILED with {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
