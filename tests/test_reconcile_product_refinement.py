from sqlmodel import Session, SQLModel, create_engine, select

from agile_sqlmodel import Product, UserStory
from scripts.reconcile_product_refinement import reconcile_product


def test_reconcile_marks_duplicates_superseded(monkeypatch):
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        "scripts.reconcile_product_refinement.get_engine",
        lambda: engine,
    )

    with Session(engine) as session:
        session.add(Product(product_id=11, name="P11"))
        session.commit()
        session.add(
            UserStory(
                product_id=11,
                title="A",
                story_description="As a user, I want A, so that A.",
                acceptance_criteria="- Verify A",
                is_superseded=False,
            )
        )
        session.add(
            UserStory(
                product_id=11,
                title="A",
                story_description="As a user, I want A, so that A.",
                acceptance_criteria="- Verify A",
                is_superseded=False,
            )
        )
        session.commit()

    summary = reconcile_product(11)
    assert summary.superseded_story_ids

    with Session(engine) as session:
        rows = session.exec(select(UserStory).where(UserStory.product_id == 11)).all()
        superseded = [r for r in rows if r.is_superseded]
        assert len(superseded) == 1
        assert superseded[0].superseded_by_story_id is not None


def test_reconcile_reports_unresolved_placeholders(monkeypatch):
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(
        "scripts.reconcile_product_refinement.get_engine",
        lambda: engine,
    )

    with Session(engine) as session:
        session.add(Product(product_id=11, name="P11"))
        session.commit()
        session.add(
            UserStory(
                product_id=11,
                title="Placeholder requirement",
                story_description="backlog seed",
                acceptance_criteria=None,
                is_superseded=False,
            )
        )
        session.commit()

    summary = reconcile_product(11)
    assert summary.unresolved_story_ids
