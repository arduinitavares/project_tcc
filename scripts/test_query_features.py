"""
Quick test to verify query_features_for_stories returns validated Pydantic schema with theme/epic.
"""

from orchestrator_agent.agent_tools.product_user_story_tool.tools import (
    query_features_for_stories,
    QueryFeaturesInput,
)

def main() -> None:
    """Run a manual query test.

    Note: this script performs database access and must not execute during pytest collection.
    """

    # Test with product ID 3 (from the logs)
    result = query_features_for_stories(QueryFeaturesInput(product_id=3))

    print("Query Result Type:", type(result))
    print("Result is dict:", isinstance(result, dict))

    if result["success"]:
        print(f"\n✅ Success: {result['message']}")
        print(f"Product: {result['product_name']} (ID: {result['product_id']})")
        print(f"Total Features: {result['total_features']}")

        print(f"\n{'='*60}")
        print("SCHEMA VALIDATION TEST - Features with Theme/Epic:")
        print(f"{'='*60}")

        for i, feat in enumerate(result["features_flat"][:5], 1):  # Show first 5
            print(f"\n{i}. {feat['feature_title'][:60]}")
            print(f"   Theme: '{feat['theme']}' (type: {type(feat['theme']).__name__})")
            print(f"   Epic: '{feat['epic']}' (type: {type(feat['epic']).__name__})")
            print(f"   Feature ID: {feat['feature_id']}")

            # Verify required fields are NOT None or "Unknown"
            assert feat["theme"], f"FAIL: Theme is empty for feature {feat['feature_id']}"
            assert feat["epic"], f"FAIL: Epic is empty for feature {feat['feature_id']}"
            assert feat["theme"] != "Unknown", f"FAIL: Theme is 'Unknown' for feature {feat['feature_id']}"
            assert feat["epic"] != "Unknown", f"FAIL: Epic is 'Unknown' for feature {feat['feature_id']}"

        print(f"\n{'='*60}")
        print("✅ ALL SCHEMA VALIDATIONS PASSED!")
        print(f"{'='*60}")
        print("\nPydantic enforces (internally):")
        print("  - theme: str (min_length=1, REQUIRED)")
        print("  - epic: str (min_length=1, REQUIRED)")
        print("  - No None or empty strings allowed")
    else:
        print(f"❌ Query failed: {result.get('error', result)}")


if __name__ == "__main__":
    main()

