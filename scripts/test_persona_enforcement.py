"""
Manual test script for persona enforcement.
Seeds a dummy Review-First product and generates test stories (with mocked LLM response).
"""
import asyncio
import json
from unittest.mock import MagicMock, patch, AsyncMock
from sqlmodel import Session, select
from agile_sqlmodel import Product, ProductPersona, engine, create_db_and_tables
from orchestrator_agent.agent_tools.story_pipeline.tools import ProcessStoryInput, process_single_story

# Mock Iterator for Runner
class AsyncIterator:
    def __init__(self, items):
        self.items = items
    def __aiter__(self):
        self._iter = iter(self.items)
        return self
    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc

async def main():
    print("Initializing Database...")
    create_db_and_tables()

    # Create test product
    with Session(engine) as session:
        # Check if exists
        product = session.exec(select(Product).where(Product.name == "Review-First P&ID Extraction (TEST)")).first()
        if not product:
            product = Product(
                name="Review-First P&ID Extraction (TEST)",
                vision="AI-powered P&ID review tool for automation and control engineers"
            )
            session.add(product)
            session.commit()
            session.refresh(product)

            # Seed personas
            personas_data = [
                ("automation engineer", True, "primary_user"),
                ("engineering qa reviewer", False, "primary_user"),
                ("it administrator", False, "admin"),
                ("ml engineer", False, "platform"),
            ]

            for name, is_default, category in personas_data:
                persona = ProductPersona(
                    product_id=product.product_id,
                    persona_name=name,
                    is_default=is_default,
                    category=category
                )
                session.add(persona)
            session.commit()
            print(f"✅ Created test product: {product.name} (ID: {product.product_id})")
        else:
            print(f"ℹ️  Using existing product: {product.name} (ID: {product.product_id})")

        product_id = product.product_id

    # Test features that commonly cause drift
    test_features = [
        {
            "title": "Interactive P&ID annotation UI",
            "theme": "Review Workflow",
            "epic": "Annotation",
            "expected_drift": "frontend developer"
        },
        {
            "title": "Configure extraction rule templates",
            "theme": "Configuration",
            "epic": "Rules",
            "expected_drift": "software engineer"
        }
    ]

    print(f"\n{'='*60}")
    print("PERSONA ENFORCEMENT TEST (Mocked LLM)")
    print(f"{'='*60}\n")

    # We patch the Runner and SessionService to simulate drift
    with patch("orchestrator_agent.agent_tools.story_pipeline.tools.Runner") as MockRunner, \
         patch("orchestrator_agent.agent_tools.story_pipeline.tools.InMemorySessionService") as MockService, \
         patch("orchestrator_agent.agent_tools.story_pipeline.tools.validate_feature_alignment") as mock_align:

        mock_align.return_value.is_aligned = True

        for i, feature in enumerate(test_features, 1):
            print(f"Test {i}/{len(test_features)}: {feature['title']}")
            print(f"  Expected drift risk: '{feature['expected_drift']}'")
            print(f"  Required Persona: 'automation engineer'")

            # Setup mock to return DRIFTED story
            drifted_desc = f"As a {feature['expected_drift']}, I want to use the feature..."
            drifted_story = {
                "title": feature['title'],
                "description": drifted_desc,
                "acceptance_criteria": "- Works",
                "story_points": 5
            }

            # Mock Runner
            instance = MockRunner.return_value
            instance.run_async.return_value = AsyncIterator([])

            # Mock Service
            service_instance = MockService.return_value
            mock_session_obj = MagicMock()
            mock_session_obj.id = f"test_session_{i}"
            service_instance.create_session = AsyncMock(return_value=mock_session_obj)

            mock_final_session = MagicMock()
            mock_final_session.state = {
                "refinement_result": json.dumps({
                    "is_valid": True,
                    "refined_story": drifted_story,
                    "refinement_notes": "Validation passed (simulated drift)"
                }),
                "validation_result": json.dumps({"validation_score": 90})
            }
            service_instance.get_session = AsyncMock(return_value=mock_final_session)

            story_input = ProcessStoryInput(
                product_id=product_id,
                product_name="Review-First P&ID Extraction (TEST)",
                product_vision="Vision...",
                feature_id=i,
                feature_title=feature['title'],
                theme=feature['theme'],
                epic=feature['epic'],
                user_persona="automation engineer",  # Always require this
                time_frame="Now",
                    spec_version_id=1,  # TODO: set to a real compiled spec_version_id
            )

            try:
                result = await process_single_story(story_input)

                # Check result
                final_desc = result['story']['description']
                print(f"  Result Description: {final_desc}")

                if "automation engineer" in final_desc and feature['expected_drift'] not in final_desc:
                     print(f"  ✅ PASS - Persona enforced correctly (Auto-corrected)")
                else:
                     print(f"  ❌ FAIL - Persona drift persisted!")

            except Exception as e:
                print(f"  ❌ ERROR: {e}")

            print()

if __name__ == "__main__":
    asyncio.run(main())
