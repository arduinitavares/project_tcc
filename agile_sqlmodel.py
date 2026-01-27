# pylint: disable=not-callable, no-member
# agile_sqlmodel.py

"""
Defines the Agile project management schema using SQLModel.

This script creates all 12 tables, including link models for
many-to-many relationships, and sets up a SQLite database.

This version fixes the 'utcnow' deprecation warning and the
'func.now' runtime error.
"""

import enum
from datetime import date, datetime, timezone  # Import timezone
from typing import List, Optional

from sqlalchemy import event, func
from sqlalchemy.engine import Engine
from sqlalchemy.schema import UniqueConstraint
from sqlalchemy.types import Date, Text
from sqlmodel import Field, Relationship, SQLModel, create_engine

# --- 1. Enums for Status Fields ---


class TeamRole(str, enum.Enum):
    """Roles for a member within a team."""

    DEVELOPER = "Developer"
    PRODUCT_OWNER = "Product Owner"
    DESIGNER = "Designer"
    QA = "QA"
    LEAD = "Lead"


class SprintStatus(str, enum.Enum):
    """Status of a sprint."""

    PLANNED = "Planned"
    ACTIVE = "Active"
    COMPLETED = "Completed"


class StoryStatus(str, enum.Enum):
    """Status of a user story."""

    TO_DO = "To Do"
    IN_PROGRESS = "In Progress"
    DONE = "Done"
    ACCEPTED = "Accepted"


class TaskStatus(str, enum.Enum):
    """Status of a task."""

    TO_DO = "To Do"
    IN_PROGRESS = "In Progress"
    DONE = "Done"


class StoryResolution(str, enum.Enum):
    """Resolution reason when story is marked DONE."""

    COMPLETED = "Completed"
    COMPLETED_WITH_CHANGES = "Completed with AC changes"
    PARTIAL = "Partial"
    WONT_DO = "Won't Do"


class WorkflowEventType(str, enum.Enum):
    """Types of workflow events for metrics tracking."""

    SPRINT_PLAN_DRAFT = "sprint_plan_draft"
    SPRINT_PLAN_REVIEW = "sprint_plan_review"
    SPRINT_PLAN_SAVED = "sprint_plan_saved"
    SPRINT_STARTED = "sprint_started"
    SPRINT_COMPLETED = "sprint_completed"
    TLX_PROMPT_TRIGGERED = "tlx_prompt_triggered"


class TimeFrame(str, enum.Enum):
    """Roadmap time frames for prioritization."""

    NOW = "Now"
    NEXT = "Next"
    LATER = "Later"


# --- 2. Link Models (for Many-to-Many Relationships) ---


class TeamMembership(SQLModel, table=True):
    """Link table for Team <-> TeamMember."""

    __tablename__ = "team_memberships"  # type: ignore
    team_id: int = Field(foreign_key="teams.team_id", primary_key=True)
    member_id: int = Field(foreign_key="team_members.member_id", primary_key=True)
    role: TeamRole = Field(default=TeamRole.DEVELOPER, nullable=False)


class ProductTeam(SQLModel, table=True):
    """Link table for Product <-> Team."""

    __tablename__ = "product_teams"  # type: ignore
    product_id: int = Field(foreign_key="products.product_id", primary_key=True)
    team_id: int = Field(foreign_key="teams.team_id", primary_key=True)


class SprintStory(SQLModel, table=True):
    """Link table for Sprint <-> UserStory."""

    __tablename__ = "sprint_stories"  # type: ignore
    sprint_id: int = Field(foreign_key="sprints.sprint_id", primary_key=True)
    story_id: int = Field(foreign_key="user_stories.story_id", primary_key=True)
    added_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )


# --- 3. Core Models ---


class ProductPersona(SQLModel, table=True):
    """Approved personas for a product."""

    __tablename__ = "product_personas"  # type: ignore

    persona_id: Optional[int] = Field(default=None, primary_key=True)
    product_id: int = Field(foreign_key="products.product_id")
    persona_name: str = Field(max_length=100, nullable=False)
    is_default: bool = Field(default=False)
    category: str = Field(max_length=50, default="primary_user")
    description: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )

    # Relationships
    product: "Product" = Relationship(back_populates="personas")

    # Constraints
    __table_args__ = (
        UniqueConstraint("product_id", "persona_name", name="unique_product_persona"),
    )


class Product(SQLModel, table=True):
    """A top-level product container."""

    __tablename__ = "products"  # type: ignore
    product_id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    description: Optional[str] = Field(default=None, sa_type=Text)
    vision: Optional[str] = Field(default=None, sa_type=Text)
    roadmap: Optional[str] = Field(default=None, sa_type=Text)

    # NEW: Specification persistence fields
    technical_spec: Optional[str] = Field(
        default=None,
        sa_type=Text  # Use Text for large content (>65KB)
    )
    spec_file_path: Optional[str] = Field(
        default=None,
        description="Path to original spec file or generated backup file"
    )
    spec_loaded_at: Optional[datetime] = Field(
        default=None,
        description="When the specification was saved to this product"
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Relationships
    teams: List["Team"] = Relationship(
        back_populates="products", link_model=ProductTeam
    )
    themes: List["Theme"] = Relationship(back_populates="product")
    stories: List["UserStory"] = Relationship(back_populates="product")
    sprints: List["Sprint"] = Relationship(back_populates="product")
    personas: List["ProductPersona"] = Relationship(back_populates="product")


class Team(SQLModel, table=True):
    """A stable group of members."""

    __tablename__ = "teams"  # type: ignore
    team_id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(index=True, unique=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Relationships
    products: List["Product"] = Relationship(
        back_populates="teams", link_model=ProductTeam
    )
    members: List["TeamMember"] = Relationship(
        back_populates="teams", link_model=TeamMembership
    )
    sprints: List["Sprint"] = Relationship(back_populates="team")


class TeamMember(SQLModel, table=True):
    """An individual member of a team."""

    __tablename__ = "team_members"  # type: ignore
    member_id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    email: str = Field(unique=True, index=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Relationships
    teams: List["Team"] = Relationship(
        back_populates="members", link_model=TeamMembership
    )
    tasks: List["Task"] = Relationship(back_populates="assignee")


class Theme(SQLModel, table=True):
    """A high-level strategic goal."""

    __tablename__ = "themes"  # type: ignore
    __table_args__ = (UniqueConstraint("product_id", "title"),)

    theme_id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = Field(default=None, sa_type=Text)
    # NEW: Roadmap time frame for prioritization (Now/Next/Later)
    time_frame: Optional[TimeFrame] = Field(default=None)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Foreign Key
    product_id: int = Field(foreign_key="products.product_id")

    # Relationships
    product: "Product" = Relationship(back_populates="themes")
    epics: List["Epic"] = Relationship(back_populates="theme")


class Epic(SQLModel, table=True):
    """A large body of work (project) contributing to a theme."""

    __tablename__ = "epics"  # type: ignore
    epic_id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    summary: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Foreign Key
    theme_id: int = Field(foreign_key="themes.theme_id")

    # Relationships
    theme: "Theme" = Relationship(back_populates="epics")
    features: List["Feature"] = Relationship(back_populates="epic")


class Feature(SQLModel, table=True):
    """A component or part of an epic."""

    __tablename__ = "features"  # type: ignore
    feature_id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    description: Optional[str] = Field(default=None, sa_type=Text)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Foreign Key
    epic_id: int = Field(foreign_key="epics.epic_id")

    # Relationships
    epic: "Epic" = Relationship(back_populates="features")
    stories: List["UserStory"] = Relationship(back_populates="feature")


class Sprint(SQLModel, table=True):
    """A time-boxed iteration of work for a team."""

    __tablename__ = "sprints"  # type: ignore
    sprint_id: Optional[int] = Field(default=None, primary_key=True)
    goal: Optional[str] = Field(default=None, sa_type=Text)
    start_date: date = Field(sa_type=Date)
    end_date: date = Field(sa_type=Date)
    status: SprintStatus = Field(default=SprintStatus.PLANNED, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Foreign Keys
    product_id: int = Field(foreign_key="products.product_id")
    team_id: int = Field(foreign_key="teams.team_id")

    # Relationships
    product: "Product" = Relationship(back_populates="sprints")
    team: "Team" = Relationship(back_populates="sprints")
    stories: List["UserStory"] = Relationship(
        back_populates="sprints", link_model=SprintStory
    )


class UserStory(SQLModel, table=True):
    """A single item in the product backlog."""

    __tablename__ = "user_stories"  # type: ignore
    story_id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    story_description: Optional[str] = Field(default=None, sa_type=Text)
    acceptance_criteria: Optional[str] = Field(default=None, sa_type=Text)
    status: StoryStatus = Field(default=StoryStatus.TO_DO, nullable=False)
    story_points: Optional[int] = Field(default=None)
    rank: Optional[str] = Field(default=None, index=True)  # For ordering

    # NEW: Persona field (auto-extracted from description)
    persona: Optional[str] = Field(
        default=None,
        max_length=100,
        index=True,
        description="Extracted from 'As a [persona], I want...' format",
    )

    # Completion tracking fields
    resolution: Optional[StoryResolution] = Field(default=None)
    completion_notes: Optional[str] = Field(default=None, sa_type=Text)
    evidence_links: Optional[str] = Field(default=None, sa_type=Text)
    completed_at: Optional[datetime] = Field(default=None)
    # AC change tracking
    original_acceptance_criteria: Optional[str] = Field(default=None, sa_type=Text)
    ac_updated_at: Optional[datetime] = Field(default=None)
    ac_update_reason: Optional[str] = Field(default=None, sa_type=Text)

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # --- Foreign Keys for "Orphan Story" ---
    # 1. Must belong to a product (for the backlog)
    product_id: int = Field(foreign_key="products.product_id")
    # 2. Can optionally belong to a feature
    feature_id: Optional[int] = Field(default=None, foreign_key="features.feature_id")

    # Relationships
    product: "Product" = Relationship(back_populates="stories")
    feature: Optional["Feature"] = Relationship(back_populates="stories")
    sprints: List["Sprint"] = Relationship(
        back_populates="stories", link_model=SprintStory
    )
    tasks: List["Task"] = Relationship(
        back_populates="story", sa_relationship_kwargs={"cascade": "all, delete"}
    )


class Task(SQLModel, table=True):
    """A granular sub-task for a user story."""

    __tablename__ = "tasks"  # type: ignore
    task_id: Optional[int] = Field(default=None, primary_key=True)
    description: str = Field(sa_type=Text)
    status: TaskStatus = Field(default=TaskStatus.TO_DO, nullable=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={"server_default": func.now()},  # FIX 2
        nullable=False,
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),  # FIX 1
        sa_column_kwargs={
            "server_default": func.now(),
            "onupdate": func.now(),
        },  # FIX 2
        nullable=False,
    )

    # Foreign Keys
    story_id: int = Field(foreign_key="user_stories.story_id")
    assigned_to_member_id: Optional[int] = Field(
        default=None, foreign_key="team_members.member_id"
    )

    # Relationships
    story: "UserStory" = Relationship(back_populates="tasks")
    assignee: Optional["TeamMember"] = Relationship(back_populates="tasks")


class StoryCompletionLog(SQLModel, table=True):
    """Audit trail for story status changes."""

    __tablename__ = "story_completion_logs"  # type: ignore

    log_id: Optional[int] = Field(default=None, primary_key=True)
    story_id: int = Field(foreign_key="user_stories.story_id", index=True)
    old_status: StoryStatus
    new_status: StoryStatus
    resolution: Optional[StoryResolution] = Field(default=None)
    delivered: Optional[str] = Field(default=None, sa_type=Text)
    evidence: Optional[str] = Field(default=None, sa_type=Text)
    known_gaps: Optional[str] = Field(default=None, sa_type=Text)
    follow_ups_created: Optional[str] = Field(default=None, sa_type=Text)
    changed_by: Optional[str] = Field(default=None)
    changed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )


class WorkflowEvent(SQLModel, table=True):
    """
    Tracks workflow events for TCC metrics (cycle time, lead time, planning effort).

    Each event captures:
    - What happened (event_type)
    - When it happened (timestamp)
    - How long it took (duration_seconds for timed activities)
    - Context (product_id, sprint_id, session_id)
    - Interaction metrics (turn_count for conversation-based activities)
    """

    __tablename__ = "workflow_events"  # type: ignore
    event_id: Optional[int] = Field(default=None, primary_key=True)
    event_type: WorkflowEventType = Field(nullable=False, index=True)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column_kwargs={"server_default": func.now()},
        nullable=False,
    )
    # Optional timing metrics
    duration_seconds: Optional[float] = Field(default=None)
    turn_count: Optional[int] = Field(default=None)
    # Context references
    product_id: Optional[int] = Field(default=None, foreign_key="products.product_id")
    sprint_id: Optional[int] = Field(default=None, foreign_key="sprints.sprint_id")
    session_id: Optional[str] = Field(default=None, index=True)
    # Extra data (JSON string for flexibility) - named event_metadata to avoid SQLAlchemy reserved name
    event_metadata: Optional[str] = Field(default=None, sa_type=Text)


# --- 4. Database Engine and Main Function ---

# Define the SQLite database URL
DB_URL = "sqlite:///./agile_simple.db"

# Create the engine
engine = create_engine(DB_URL, echo=True)


@event.listens_for(Engine, "connect")
def set_sqlite_pragma(dbapi_connection, _connection_record):
    """Enforce foreign key constraints on SQLite."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_and_tables():
    """Create the database and all tables."""
    print("Creating tables...")
    SQLModel.metadata.create_all(engine)
    print("Tables created successfully.")


if __name__ == "__main__":
    # This makes the script runnable
    # It will create the 'agile_simple.db' file in your directory
    create_db_and_tables()
