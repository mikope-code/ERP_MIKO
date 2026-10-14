# Los modelos se importan aquí para que Alembic los detecte.
from app.models.customer import Customer, CustomerProductAdjustment, CustomerUnitPrice
from app.models.product import CATEGORIAS, Product, ProductUnit, UnitKind
from app.models.sale import Sale, SaleLine, SaleStatus
from app.models.stock import MovementType, StockLot, StockMovement, Supplier
from app.models.user import Role, User

__all__ = [
    "CATEGORIAS",
    "Customer",
    "CustomerProductAdjustment",
    "CustomerUnitPrice",
    "MovementType",
    "Product",
    "ProductUnit",
    "Role",
    "Sale",
    "SaleLine",
    "SaleStatus",
    "StockLot",
    "StockMovement",
    "Supplier",
    "UnitKind",
    "User",
]
