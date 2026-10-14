# Los modelos se importan aquí para que Alembic los detecte.
from app.models.product import CATEGORIAS, Product, ProductUnit, UnitKind
from app.models.stock import MovementType, StockLot, StockMovement, Supplier
from app.models.user import Role, User

__all__ = [
    "CATEGORIAS",
    "MovementType",
    "Product",
    "ProductUnit",
    "Role",
    "StockLot",
    "StockMovement",
    "Supplier",
    "UnitKind",
    "User",
]
