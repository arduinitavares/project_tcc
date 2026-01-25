# Fix for Foreign Key Constraint Error in `test_persona_field_population`

## Problem

The test fails with `sqlite3.IntegrityError: FOREIGN KEY constraint failed` because `UserStory` requires a valid `feature_id` that references the `Feature` table. The current fixture only creates `Product` and `ProductPersona`, but not the full hierarchy (`Theme` → `Epic` → `Feature`).

## Solution

Extend the `review_first_product` fixture to create the complete entity hierarchy:

```python
# tests/test_persona_enforcement_integration.py

@pytest.fixture
def review_first_product(session):
    """Create Review-First product with persona whitelist AND feature hierarchy."""
    from agile_sqlmodel import Product, ProductPersona, Theme, Epic, Feature
    
    # 1. Create Product
    product = Product(
        name="Review-First P&ID Extraction",
        vision="AI-powered P&ID review tool for automation engineers"
    )
    session.add(product)
    session.commit()
    session.refresh(product)

    # 2. Add approved personas
    personas = [
        ProductPersona(product_id=product.product_id, persona_name="automation engineer", is_default=True, category="primary_user"),
        ProductPersona(product_id=product.product_id, persona_name="engineering qa reviewer", is_default=False, category="primary_user"),
    ]
    for p in personas:
        session.add(p)
    session.commit()

    # 3. Create Theme -> Epic -> Feature hierarchy
    theme = Theme(
        name="Core Extraction",
        product_id=product.product_id,
        description="Core P&ID extraction features"
    )
    session.add(theme)
    session.commit()
    session.refresh(theme)

    epic = Epic(
        name="Review Workflow",
        theme_id=theme.theme_id,
        description="Review workflow features"
    )
    session.add(epic)
    session.commit()
    session.refresh(epic)

    feature = Feature(
        title="Interactive P&ID annotation UI",
        epic_id=epic.epic_id,
        description="Allow users to annotate P&ID diagrams"
    )
    session.add(feature)
    session.commit()
    session.refresh(feature)

    # Attach feature for test access
    product._test_feature = feature
    return product
```

Then in your test, use the feature from the fixture:

```python
@pytest.mark.asyncio
async def test_persona_field_population(review_first_product, session):
    """Verify UserStory.persona field is populated correctly."""
    feature = review_first_product._test_feature
    
    user_story = UserStory(
        title="Test Story",
        story_description="As an automation engineer, I want to review P&IDs...",
        product_id=review_first_product.product_id,
        feature_id=feature.feature_id,  # Valid FK reference
        persona="automation engineer",
    )
    session.add(user_story)
    session.commit()
    session.refresh(user_story)
    
    assert user_story.persona == "automation engineer"
```

## Why This Approach

- Reflects real-world data structure (stories belong to features)
- Other tests may need the feature hierarchy too
- Explicit about what data exists in the test database
- SQLModel enforces referential integrity, so parent entities must exist before children
