# Los modelos se importan aquí para que Alembic los detecte.
from app.models.product import CATEGORIAS, Product, ProductUnit, UnitKind
from app.models.user import Role, User

__all__ = [
    "CATEGORIAS",
    "Product",
    "ProductUnit",
    "Role",
    "UnitKind",
    "User",
]
