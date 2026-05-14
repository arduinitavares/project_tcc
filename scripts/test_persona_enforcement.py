# ruff: noqa: E501
"""
Manual test script for persona enforcement.

Seeds a dummy Review-First product and generates test stories (with mocked LLM response).
"""

import asyncio
import importlib
import json
from collections.abc import Iterable, Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from sqlmodel import Session, select

from agile_sqlmodel import Product, create_db_and_tables, engine
from models.core import ProductPersona
from utils.cli_output import emit


def _load_story_pipeline_tools() -> Any:  # noqa: ANN401
    module_name = "orchestrator_agent.agent_tools.story_pipeline.tools"
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as exc:
        msg = (
            "The persona enforcement script targets legacy module "
            f"{module_name!r}, which is not present in this checkout."
        )
        raise RuntimeError(msg) from exc


_story_pipeline_tools = _load_story_pipeline_tools()
ProcessStoryInput = _story_pipeline_tools.ProcessStoryInput
process_single_story = _story_pipeline_tools.process_single_story


def _require_id(value: int | None, name: str) -> int:
    if value is None:
        msg = f"{name} was not generated"
        raise RuntimeError(msg)
    return value


# Mock Iterator for Runner
class AsyncIterator:
    """Test helper for async iterator."""

    def __init__(self, items: Iterable[object]) -> None:
        """Initialize the test helper."""
        self.items = items
        self._iter: Iterator[object] = iter(())

    def __aiter__(self) -> "AsyncIterator":
        """Implement __aiter__ for the test helper."""
        self._iter = iter(self.items)
        return self

    async def __anext__(self) -> object:
        """Implement __anext__ for the test helper."""
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


def _seed_default_personas(session: Session, product_id: int) -> None:
    personas_data = [
        ("automation engineer", True, "primary_user"),
        ("engineering qa reviewer", False, "primary_user"),
        ("it administrator", False, "admin"),
        ("ml engineer", False, "platform"),
    ]

    for name, is_default, category in personas_data:
        persona = ProductPersona(
            product_id=product_id,
            persona_name=name,
            is_default=is_default,
            category=category,
        )
        session.add(persona)


async def main() -> None:
    """Return main."""
    emit("Initializing Database...")
    create_db_and_tables()

    # Create test product
    with Session(engine) as session:
        # Check if exists
        product = session.exec(
            select(Product).where(Product.name == "Review-First P&ID Extraction (TEST)")
        ).first()
        if not product:
            product = Product(
                name="Review-First P&ID Extraction (TEST)",
                vision="AI-powered P&ID review tool for automation and control engineers",
            )
            session.add(product)
            session.commit()
            session.refresh(product)
            product_id = _require_id(product.product_id, "Product ID")

            _seed_default_personas(session, product_id)
            session.commit()
            emit(f"✅ Created test product: {product.name} (ID: {product.product_id})")
        else:
            emit(
                f"ℹ️  Using existing product: {product.name} (ID: {product.product_id})"  # noqa: RUF001
            )

        product_id = _require_id(product.product_id, "Product ID")

    # Test features that commonly cause drift
    test_features = [
        {
            "title": "Interactive P&ID annotation UI",
            "theme": "Review Workflow",
            "epic": "Annotation",
            "expected_drift": "frontend developer",
        },
        {
            "title": "Configure extraction rule templates",
            "theme": "Configuration",
            "epic": "Rules",
            "expected_drift": "software engineer",
        },
    ]

    emit(f"\n{'=' * 60}")
    emit("PERSONA ENFORCEMENT TEST (Mocked LLM)")
    emit(f"{'=' * 60}\n")

    # We patch the Runner and SessionService to simulate drift
    with (
        patch(
            "orchestrator_agent.agent_tools.story_pipeline.tools.Runner"
        ) as MockRunner,  # noqa: N806
        patch(
            "orchestrator_agent.agent_tools.story_pipeline.tools.InMemorySessionService"
        ) as MockService,  # noqa: N806
        patch(
            "orchestrator_agent.agent_tools.story_pipeline.tools.validate_feature_alignment"
        ) as mock_align,
    ):
        mock_align.return_value.is_aligned = True

        for i, feature in enumerate(test_features, 1):
            emit(f"Test {i}/{len(test_features)}: {feature['title']}")
            emit(f"  Expected drift risk: '{feature['expected_drift']}'")
            emit("  Required Persona: 'automation engineer'")

            # Setup mock to return DRIFTED story
            drifted_desc = (
                f"As a {feature['expected_drift']}, I want to use the feature..."
            )
            drifted_story = {
                "title": feature["title"],
                "description": drifted_desc,
                "acceptance_criteria": "- Works",
                "story_points": 5,
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
                "refinement_result": json.dumps(
                    {
                        "is_valid": True,
                        "refined_story": drifted_story,
                        "refinement_notes": "Validation passed (simulated drift)",
                    }
                ),
                "validation_result": json.dumps({"validation_score": 90}),
            }
            service_instance.get_session = AsyncMock(return_value=mock_final_session)

            story_input = ProcessStoryInput(
                product_id=product_id,
                product_name="Review-First P&ID Extraction (TEST)",
                product_vision="Vision...",
                feature_id=i,
                feature_title=feature["title"],
                theme=feature["theme"],
                epic=feature["epic"],
                user_persona="automation engineer",  # Always require this
                time_frame="Now",
                spec_version_id=1,  # TODO: set to a real compiled spec_version_id  # noqa: FIX002
            )

            try:
                result = await process_single_story(story_input)

                # Check result
                final_desc = result["story"]["description"]
                emit(f"  Result Description: {final_desc}")

                if (
                    "automation engineer" in final_desc
                    and feature["expected_drift"] not in final_desc
                ):
                    emit("  ✅ PASS - Persona enforced correctly (Auto-corrected)")
                else:
                    emit("  ❌ FAIL - Persona drift persisted!")

            except Exception as e:  # noqa: BLE001
                emit(f"  ❌ ERROR: {e}")

            emit()


if __name__ == "__main__":
    asyncio.run(main())
