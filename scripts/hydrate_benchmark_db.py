#!/usr/bin/env python3
"""
Initialize and Hydrate Database for Benchmark.
Creates products, specs, compiled authorities, AND user stories.
"""

import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlmodel import Session, select

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from agile_sqlmodel import (
    CompiledSpecAuthority,
    Product,
    SpecAuthorityAcceptance,
    SpecRegistry,
    StoryStatus,
    UserStory,
    create_db_and_tables,
    get_engine,
)

# Define specifications
SPECS = {
    7: {
        "name": "Project Quadra",  # Using existing name/domain from p7-v8 in cases.jsonl
        "content": """# Project Quadra Specification

## Vision
A secure document review and attestation platform for regulated industries.

## Scope
### In Scope
- Document ingestion pipeline
- Review interface with annotation tools
- Attestation workflows (Accept/Decline)
- Audit logging of all actions
- Role-based access control (Reviewer, Admin)
- Export to PDF and JSON

### Out of Scope
- Real-time collaboration
- Public API access
- Mobile application
- Payment processing

## Invariants
- FORBIDDEN_CAPABILITY: Real-time collaboration
- FORBIDDEN_CAPABILITY: Public API
- FORBIDDEN_CAPABILITY: Payment processing
- REQUIRED_FIELD: Acceptance Criteria
- REQUIRED_FIELD: Story Points
- MAX_VALUE: Story Points <= 8

## Features
- Document Viewer: Pan, zoom, rotate
- Annotation: Bounding boxes, text labels
- Workflow: Assign, review, approve, reject
""",
        "spec_version_id": 8,
        "mock_invariants": [
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Real-time collaboration"},
            },
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Public API"},
            },
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Payment processing"},
            },
            {
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "Acceptance Criteria"},
            },
            {"type": "REQUIRED_FIELD", "parameters": {"field_name": "Story Points"}},
            {
                "type": "MAX_VALUE",
                "parameters": {"field_name": "Story Points", "max_value": 8},
            },
        ],
    },
    8: {
        "name": "Visionary Manufacturing",  # Based on p8-s62-v9 content
        "content": """# Visionary Manufacturing Specification (Phase 1)

## Vision
Offline dataset ingestion and 2D product segmentation system.

## Scope
### In Scope
- Offline Dataset Ingestion & Organization
- 2D Product Segmentation & Instance Extraction
- 2D Color-Based Defect Detection Algorithms
- Traceable CSV Export & Data Lineage

### Out of Scope
- Real-time line integration
- 3D Scanning
- Cloud connectivity

## Invariants
- FORBIDDEN_CAPABILITY: Cloud connectivity
- FORBIDDEN_CAPABILITY: Real-time integration
- REQUIRED_FIELD: Acceptance Criteria
- MAX_VALUE: Story Points <= 5

## Features
- CSV Export: instance and batch level
- File Ingestion: folder parsing
""",
        "spec_version_id": 9,  # Matching v9 from cases
        "mock_invariants": [
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Cloud connectivity"},
            },
            {
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "Acceptance Criteria"},
            },
            {
                "type": "MAX_VALUE",
                "parameters": {"field_name": "Story Points", "max_value": 5},
            },
        ],
    },
    9: {
        "name": "E-Commerce Platform",
        "content": """# E-Commerce Platform Specification

## Vision
A modern, scalable e-commerce platform for digital goods.

## Scope
### In Scope
- Product catalog management
- Shopping cart and checkout
- User authentication (OAuth2)
- Payment gateway integration (Stripe, PayPal)
- Order history and tracking
- Admin dashboard for sales analytics

### Out of Scope
- Physical inventory management
- Shipping logistics
- Auction bidding system
- Cryptocurrency payments

## Invariants
- FORBIDDEN_CAPABILITY: Physical inventory
- FORBIDDEN_CAPABILITY: Shipping
- FORBIDDEN_CAPABILITY: Cryptocurrency
- REQUIRED_FIELD: Acceptance Criteria
- REQUIRED_FIELD: API Endpoint
- MAX_VALUE: Story Points <= 5

## Features
- Catalog: Search, filter, sort
- Cart: Add, remove, update quantity
- Checkout: Guest and user checkout
""",
        "spec_version_id": 901,
        "mock_invariants": [
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Physical inventory"},
            },
            {"type": "FORBIDDEN_CAPABILITY", "parameters": {"capability": "Shipping"}},
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Cryptocurrency"},
            },
            {
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "Acceptance Criteria"},
            },
            {"type": "REQUIRED_FIELD", "parameters": {"field_name": "API Endpoint"}},
            {
                "type": "MAX_VALUE",
                "parameters": {"field_name": "Story Points", "max_value": 5},
            },
        ],
    },
    10: {
        "name": "IoT Home Controller",
        "content": """# IoT Home Controller Specification

## Vision
A centralized hub for managing smart home devices locally.

## Scope
### In Scope
- Device discovery (Zigbee, Z-Wave)
- Local control dashboard
- Automation rules engine
- Energy monitoring
- Secure local access (HTTPS)

### Out of Scope
- Cloud dependency (must work offline)
- Voice assistant integration (Alexa, Google Home)
- Video streaming storage
- Subscription services

## Invariants
- FORBIDDEN_CAPABILITY: Cloud dependency
- FORBIDDEN_CAPABILITY: Voice assistant
- FORBIDDEN_CAPABILITY: Video storage
- REQUIRED_FIELD: Acceptance Criteria
- REQUIRED_FIELD: Latency Requirement
- MAX_VALUE: Story Points <= 13

## Features
- Dashboard: Widget-based layout
- Devices: On/off, dimming, color control
- Automations: Time-based, event-based triggers
""",
        "spec_version_id": 1001,
        "mock_invariants": [
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Cloud dependency"},
            },
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Voice assistant"},
            },
            {
                "type": "FORBIDDEN_CAPABILITY",
                "parameters": {"capability": "Video storage"},
            },
            {
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "Acceptance Criteria"},
            },
            {
                "type": "REQUIRED_FIELD",
                "parameters": {"field_name": "Latency Requirement"},
            },
            {
                "type": "MAX_VALUE",
                "parameters": {"field_name": "Story Points", "max_value": 13},
            },
        ],
    },
}


def _render_invariant_str(inv):
    t = inv["type"]
    p = inv["parameters"]
    if t == "FORBIDDEN_CAPABILITY":
        return f"FORBIDDEN_CAPABILITY:{p.get('capability')}"
    if t == "REQUIRED_FIELD":
        return f"REQUIRED_FIELD:{p.get('field_name')}"
    if t == "MAX_VALUE":
        return f"MAX_VALUE:{p.get('field_name')}<= {p.get('max_value')}"
    return f"INVARIANT:{t}"


def create_mock_authority(session, spec_version_id, mock_invariants):
    print(f"Creating mock authority for spec {spec_version_id}...")

    invariants_list = []
    for i, inv in enumerate(mock_invariants):
        invariants_list.append(
            {
                "id": f"inv-{spec_version_id}-{i}",
                "type": inv["type"],
                "parameters": inv["parameters"],
                "description": f"Mock invariant {i}",
                "source_text": "Mock source",
            }
        )

    # Render string summaries for column
    invariant_strs = [_render_invariant_str(inv) for inv in mock_invariants]

    artifact = {
        "scope_themes": ["Mock Theme 1", "Mock Theme 2"],
        "invariants": invariants_list,
        "gaps": [],
    }

    authority = CompiledSpecAuthority(
        spec_version_id=spec_version_id,
        compiler_version="mock-1.0",
        prompt_hash="mock-hash",
        compiled_at=datetime.now(UTC),
        compiled_artifact_json=json.dumps(artifact),
        scope_themes=json.dumps(artifact["scope_themes"]),
        invariants=json.dumps(invariant_strs),
        eligible_feature_ids=json.dumps([]),
        rejected_features=json.dumps([]),
        spec_gaps=json.dumps([]),
    )
    session.add(authority)
    session.commit()
    session.refresh(authority)
    print(f"Mock authority created: {authority.authority_id}")

    # Auto-accept
    acceptance = SpecAuthorityAcceptance(
        product_id=session.get(SpecRegistry, spec_version_id).product_id,
        spec_version_id=spec_version_id,
        status="accepted",
        policy="auto",
        decided_by="mock_script",
        decided_at=datetime.now(UTC),
        rationale="Mock hydration",
        compiler_version="mock-1.0",
        prompt_hash="mock-hash",
        spec_hash="mock-spec-hash",
    )
    session.add(acceptance)
    session.commit()
    print("Mock authority accepted.")


def hydrate_db():
    print("Creating tables...")
    create_db_and_tables()
    engine = get_engine()

    with Session(engine) as session:
        # 1. Products, Specs, Authorities
        for pid, spec_data in SPECS.items():
            print(f"Hydrating Product {pid}: {spec_data['name']}")

            # Product
            product = session.get(Product, pid)
            if not product:
                product = Product(
                    product_id=pid,
                    name=spec_data["name"],
                    description=spec_data["content"].split("\n")[2],
                    technical_spec=spec_data["content"],
                )
                session.add(product)
                session.commit()

            # Spec
            spec_version_id = spec_data["spec_version_id"]
            spec = session.get(SpecRegistry, spec_version_id)
            if not spec:
                spec = SpecRegistry(
                    spec_version_id=spec_version_id,
                    product_id=pid,
                    spec_hash=hashlib.sha256(spec_data["content"].encode()).hexdigest(),
                    content=spec_data["content"],
                    status="approved",
                    approved_at=datetime.now(UTC),
                    approved_by="system",
                )
                session.add(spec)
                session.commit()

            # Authority
            existing_auth = session.exec(
                select(CompiledSpecAuthority).where(
                    CompiledSpecAuthority.spec_version_id == spec_version_id
                )
            ).first()

            if existing_auth:
                print(f"Authority already exists: {existing_auth.authority_id}")
            else:
                try:
                    # Attempt mock first to save time/tokens if API is flaky
                    create_mock_authority(
                        session, spec_version_id, spec_data["mock_invariants"]
                    )
                except Exception as e:
                    print(f"Error creating authority: {e}")

        # 2. Stories
        stories_file = Path("artifacts/validation_benchmark/synthetic_stories.jsonl")
        if stories_file.exists():
            print("Hydrating user stories from synthetic_stories.jsonl...")
            with open(stories_file) as f:
                for line in f:
                    if not line.strip():
                        continue
                    s_data = json.loads(line)

                    # Upsert: update existing or insert new
                    story = session.get(UserStory, s_data["story_id"])
                    if story:
                        story.title = s_data["title"]
                        story.story_description = s_data["description"]
                        story.acceptance_criteria = s_data["acceptance_criteria"]
                        story.product_id = s_data["product_id"]
                        session.add(story)
                    else:
                        story = UserStory(
                            story_id=s_data["story_id"],
                            product_id=s_data["product_id"],
                            title=s_data["title"],
                            story_description=s_data["description"],
                            acceptance_criteria=s_data["acceptance_criteria"],
                            status=StoryStatus.TO_DO,
                        )
                        session.add(story)
            session.commit()
            print("Stories hydrated.")
        else:
            print("Warning: synthetic_stories.jsonl not found.")

    print("Hydration complete.")


if __name__ == "__main__":
    hydrate_db()
