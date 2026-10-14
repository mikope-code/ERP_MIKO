import enum
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.product import Product
from app.models.user import User


class MovementType(str, enum.Enum):
    ENTRADA = "entrada"
    SALIDA = "salida"
    AJUSTE = "ajuste"
    ANULACION = "anulacion"


class Supplier(Base):
    __tablename__ = "suppliers"

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), unique=True)
    telefono: Mapped[str | None] = mapped_column(String(30))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)


class StockLot(Base):
    """Existencias de un producto con una misma fecha de vencimiento.

    Los productos sin vencimiento tienen un único lote (fecha_vencimiento NULL).
    """

    __tablename__ = "stock_lots"
    __table_args__ = (
        CheckConstraint("cantidad_base >= 0", name="ck_lote_cantidad_no_negativa"),
        UniqueConstraint("product_id", "fecha_vencimiento", name="uq_lote_producto_venc"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    cantidad_base: Mapped[int] = mapped_column(default=0)
    fecha_vencimiento: Mapped[date | None] = mapped_column(Date)

    producto: Mapped[Product] = relationship()


class StockMovement(Base):
    """Kardex. Solo se insertan filas: nunca se modifican ni se borran."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        CheckConstraint("cantidad_base != 0", name="ck_movimiento_no_nulo"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    lot_id: Mapped[int] = mapped_column(ForeignKey("stock_lots.id"), index=True)
    tipo: Mapped[MovementType] = mapped_column(
        Enum(MovementType, native_enum=False, length=15)
    )
    # Con signo: positivo suma al stock, negativo resta (en unidad base)
    cantidad_base: Mapped[int]
    referencia: Mapped[str | None] = mapped_column(String(50))
    nota: Mapped[str | None] = mapped_column(String(255))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    # Costo por unidad base; solo en entradas, y solo lo ve el administrador
    costo_unitario: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    fecha: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None)
    )

    producto: Mapped[Product] = relationship()
    lote: Mapped[StockLot] = relationship()
    usuario: Mapped[User] = relationship()
    proveedor: Mapped[Supplier | None] = relationship()


@event.listens_for(StockMovement, "before_update")
@event.listens_for(StockMovement, "before_delete")
def _kardex_inmutable(_mapper, _connection, _target):
    raise ValueError("Los movimientos de stock no se modifican ni se borran")
