"""Service-level tests for orchestrator read/query extraction."""

from __future__ import annotations

from datetime import date

from agile_sqlmodel import Product, Sprint, SprintStatus, SprintStory, StoryStatus, UserStory
from models.core import Team


def test_services_use_orchestrator_query_service_boundary() -> None:
    """Workflow and sprint-input services should no longer import tool-layer queries."""
    from services import sprint_input, workflow

    assert (
        sprint_input.fetch_sprint_candidates.__module__
        == "services.orchestrator_query_service"
    )
    assert (
        workflow.get_real_business_state.__module__
        == "services.orchestrator_query_service"
    )


def test_query_service_fetch_sprint_candidates_filters_open_sprints(session) -> None:
    """Query service should expose only refined TODO stories not already in open sprints."""
    from services.orchestrator_query_service import fetch_sprint_candidates

    product = Product(name="Query Product", vision="Vision", description="Desc")
    team = Team(name="Query Team")
    session.add(product)
    session.add(team)
    session.commit()
    session.refresh(product)
    session.refresh(team)

    stories = {
        "planned": UserStory(
            product_id=product.product_id,
            title="Planned story",
            story_description="Assigned to a planned sprint",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=True,
            rank="1",
        ),
        "active": UserStory(
            product_id=product.product_id,
            title="Active story",
            story_description="Assigned to an active sprint",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=True,
            rank="2",
        ),
        "completed_only": UserStory(
            product_id=product.product_id,
            title="Completed-only story",
            story_description="Assigned only to a completed sprint",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=True,
            rank="3",
        ),
        "eligible": UserStory(
            product_id=product.product_id,
            title="Eligible story",
            story_description="Not assigned to any open sprint",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=True,
            rank="4",
        ),
        "non_refined": UserStory(
            product_id=product.product_id,
            title="Needs refinement",
            story_description="Still rough",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=False,
            rank="5",
        ),
        "superseded": UserStory(
            product_id=product.product_id,
            title="Superseded story",
            story_description="Replaced by another story",
            acceptance_criteria="- AC",
            status=StoryStatus.TO_DO,
            is_refined=True,
            is_superseded=True,
            rank="6",
        ),
    }
    session.add_all(stories.values())
    session.flush()

    planned_sprint = Sprint(
        goal="Planned",
        start_date=date(2026, 2, 1),
        end_date=date(2026, 2, 14),
        status=SprintStatus.PLANNED,
        product_id=product.product_id,
        team_id=team.team_id,
    )
    active_sprint = Sprint(
        goal="Active",
        start_date=date(2026, 2, 15),
        end_date=date(2026, 2, 28),
        status=SprintStatus.ACTIVE,
        product_id=product.product_id,
        team_id=team.team_id,
    )
    completed_sprint = Sprint(
        goal="Completed",
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 14),
        status=SprintStatus.COMPLETED,
        product_id=product.product_id,
        team_id=team.team_id,
    )
    session.add_all([planned_sprint, active_sprint, completed_sprint])
    session.flush()

    session.add_all(
        [
            SprintStory(
                sprint_id=planned_sprint.sprint_id,
                story_id=stories["planned"].story_id,
            ),
            SprintStory(
                sprint_id=active_sprint.sprint_id,
                story_id=stories["active"].story_id,
            ),
            SprintStory(
                sprint_id=completed_sprint.sprint_id,
                story_id=stories["completed_only"].story_id,
            ),
        ]
    )
    session.commit()

    result = fetch_sprint_candidates(product.product_id)

    assert result["success"] is True
    assert [story["story_title"] for story in result["stories"]] == [
        "Completed-only story",
        "Eligible story",
    ]
    assert result["excluded_counts"] == {
        "non_refined": 1,
        "superseded": 1,
        "open_sprint": 2,
    }


def test_query_service_get_real_business_state_returns_idle_snapshot(session) -> None:
    """Query service should build the initial workflow state from project summaries."""
    from services.orchestrator_query_service import get_real_business_state

    team = Team(name="State Team")
    alpha = Product(name="Alpha", vision="Alpha vision", description="Desc")
    beta = Product(name="Beta", vision=None, description="Beta desc")
    session.add_all([team, alpha, beta])
    session.commit()
    session.refresh(team)
    session.refresh(alpha)
    session.refresh(beta)

    session.add(
        UserStory(
            product_id=alpha.product_id,
            title="Alpha story",
            status=StoryStatus.TO_DO,
            rank="1",
        )
    )
    session.add(
        Sprint(
            goal="Alpha sprint",
            start_date=date(2026, 3, 1),
            end_date=date(2026, 3, 14),
            status=SprintStatus.PLANNED,
            product_id=alpha.product_id,
            team_id=team.team_id,
        )
    )
    session.commit()

    result = get_real_business_state()

    assert result["projects_summary"] == 2
    assert result["current_context"] == "idle"
    assert result["active_project"] is None
    assert "projects_last_refreshed_utc" in result

    by_name = {project["name"]: project for project in result["projects_list"]}
    assert by_name["Alpha"]["user_stories_count"] == 1
    assert by_name["Alpha"]["sprint_count"] == 1
    assert by_name["Alpha"]["vision"] == "Alpha vision"
    assert by_name["Beta"]["user_stories_count"] == 0
    assert by_name["Beta"]["sprint_count"] == 0
    assert by_name["Beta"]["vision"] == "(No vision set)"
