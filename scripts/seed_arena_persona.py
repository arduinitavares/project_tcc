"""Seed the 'gestor da arena' persona for product ID 4."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select
from sqlmodel import Session
from agile_sqlmodel import engine, ProductPersona

def seed_arena_persona():
    """Add 'gestor da arena' persona to product ID 4."""
    with Session(engine) as session:
        # Check if persona already exists
        existing = session.exec(
            select(ProductPersona).where(
                ProductPersona.product_id == 4,
                ProductPersona.persona_name == "gestor da arena"
            )
        ).first()
        
        if existing:
            print("✓ Persona 'gestor da arena' already exists for product ID 4")
            return
        
        # Create new persona
        persona = ProductPersona(
            product_id=4,
            persona_name="gestor da arena",
            is_default=True,
            category="primary_user",
            description="Arena manager responsible for operational compliance and monitoring"
        )
        
        session.add(persona)
        session.commit()
        print("✓ Persona 'gestor da arena' added successfully for product ID 4")

if __name__ == "__main__":
    seed_arena_persona()
