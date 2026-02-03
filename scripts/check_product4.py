"""Quick script to check product 4 and spec authority status."""
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agile_sqlmodel import get_engine, Product, SpecAuthorityAcceptance, SpecRegistry, CompiledSpecAuthority
from sqlmodel import Session, select


def main():
    with Session(get_engine()) as session:
        # Check product 4
        product = session.exec(select(Product).where(Product.product_id == 4)).first()
        if product:
            print(f"Product ID: {product.product_id}")
            print(f"Name: {product.name}")
            print(f"Vision: {product.vision[:200] if product.vision else 'N/A'}...")
        else:
            print("Product 4 not found!")
            return
        
        # Check spec versions for this product
        print("\n--- Spec Versions ---")
        spec_versions = session.exec(
            select(SpecRegistry).where(SpecRegistry.product_id == 4)
        ).all()
        for sv in spec_versions:
            print(f"  SpecVersion ID: {sv.spec_version_id}, path: {sv.content_ref}")
        
        # Check acceptance status
        print("\n--- Spec Authority Acceptances ---")
        acceptances = session.exec(
            select(SpecAuthorityAcceptance).where(SpecAuthorityAcceptance.product_id == 4)
        ).all()
        for acc in acceptances:
            print(f"  Acceptance: spec_version_id={acc.spec_version_id}, status={acc.status}")
        
        if not acceptances:
            print("  No acceptances found for product 4")
            
        # Check compiled spec authorities
        print("\n--- Compiled Spec Authorities ---")
        for sv in spec_versions:
            compiled = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == sv.spec_version_id
                )
            ).first()
            if compiled:
                has_artifact = compiled.compiled_artifact_json is not None
                artifact_len = len(compiled.compiled_artifact_json) if has_artifact else 0
                print(f"  spec_version_id={sv.spec_version_id}: has_artifact={has_artifact}, artifact_len={artifact_len}")
                if has_artifact:
                    # Try to validate it
                    from utils.schemes import SpecAuthorityCompilerOutput, SpecAuthorityCompilationFailure, SpecAuthorityCompilationSuccess
                    try:
                        parsed = SpecAuthorityCompilerOutput.model_validate_json(compiled.compiled_artifact_json)
                        if isinstance(parsed.root, SpecAuthorityCompilationFailure):
                            print(f"    -> FAILURE envelope: {parsed.root.error[:100]}...")
                        elif isinstance(parsed.root, SpecAuthorityCompilationSuccess):
                            print(f"    -> SUCCESS: {len(parsed.root.scope_themes)} themes, {len(parsed.root.invariants)} invariants")
                        else:
                            print(f"    -> UNKNOWN type: {type(parsed.root)}")
                    except Exception as e:
                        print(f"    -> VALIDATION ERROR: {e}")
                        print(f"    -> Raw artifact preview: {compiled.compiled_artifact_json[:500]}...")
            else:
                print(f"  spec_version_id={sv.spec_version_id}: NO COMPILED RECORD")
        
        # Test calling ensure_accepted_spec_authority directly
        print("\n--- Calling ensure_accepted_spec_authority directly ---")
        from tools.spec_tools import ensure_accepted_spec_authority
        try:
            spec_version_id = ensure_accepted_spec_authority(
                product_id=4,
                spec_content=None,
                content_ref=None,
                recompile=False,
                tool_context=None,
            )
            print(f"SUCCESS: returned spec_version_id={spec_version_id}")
        except RuntimeError as e:
            print(f"FAILED with RuntimeError: {e}")
        except Exception as e:
            print(f"FAILED with {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
