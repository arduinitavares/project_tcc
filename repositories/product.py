from typing import List, Optional
from sqlmodel import Session, select
from agile_sqlmodel import Product, get_engine
import logging

logger = logging.getLogger(__name__)

class ProductRepository:
    """Repository handling database operations for the Product entity."""
    
    def __init__(self, session: Optional[Session] = None):
        # Allow passing an explicit session (for transactions), 
        # otherwise create one and close it immediately per call.
        self._session = session

    def _get_session(self) -> Session:
        return self._session if self._session else Session(get_engine())

    def get_all(self) -> List[Product]:
        """Fetch all products."""
        with self._get_session() as session:
            statement = select(Product)
            return list(session.exec(statement).all())

    def get_by_id(self, product_id: int) -> Optional[Product]:
        """Fetch a specific product by its ID."""
        with self._get_session() as session:
            return session.get(Product, product_id)

    def create(self, name: str, description: Optional[str] = None) -> Product:
        """Create a new product."""
        product = Product(name=name, description=description)
        # We must manage the transaction locally if we spawned the session
        session = self._get_session()
        try:
            session.add(product)
            session.commit()
            session.refresh(product)
            return product
        finally:
            if not self._session:
                session.close()

    def update_vision(self, product_id: int, vision: str) -> Optional[Product]:
        """Update the vision text for a product."""
        session = self._get_session()
        try:
            product = session.get(Product, product_id)
            if product:
                product.vision = vision
                session.add(product)
                session.commit()
                session.refresh(product)
            return product
        finally:
            if not self._session:
                session.close()

    def update_technical_spec(self, product_id: int, technical_spec: str) -> Optional[Product]:
        """Update the raw technical spec for a product."""
        session = self._get_session()
        try:
            product = session.get(Product, product_id)
            if product:
                product.technical_spec = technical_spec
                session.add(product)
                session.commit()
                session.refresh(product)
            return product
        finally:
            if not self._session:
                session.close()

    def update_compiled_authority(self, product_id: int, compiled_json: str) -> Optional[Product]:
        """Update the compiled authority JSON for a product."""
        session = self._get_session()
        try:
            product = session.get(Product, product_id)
            if product:
                product.compiled_authority_json = compiled_json
                session.add(product)
                session.commit()
                session.refresh(product)
            return product
        finally:
            if not self._session:
                session.close()
