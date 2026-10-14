import enum
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.customer import Customer
from app.models.product import Product, ProductUnit
from app.models.user import User


def _ahora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SaleStatus(str, enum.Enum):
    ACTIVA = "activa"
    ANULADA = "anulada"


class Sale(Base):
    __tablename__ = "sales"

    id: Mapped[int] = mapped_column(primary_key=True)
    # NULL = cliente de mostrador
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fecha: Mapped[datetime] = mapped_column(DateTime, default=_ahora_utc, index=True)
    total: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    estado: Mapped[SaleStatus] = mapped_column(
        Enum(SaleStatus, native_enum=False, length=10), default=SaleStatus.ACTIVA
    )
    nota: Mapped[str | None] = mapped_column(String(255))

    anulada_por_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    anulada_en: Mapped[datetime | None] = mapped_column(DateTime)
    motivo_anulacion: Mapped[str | None] = mapped_column(String(255))

    cliente: Mapped[Customer | None] = relationship()
    usuario: Mapped[User] = relationship(foreign_keys=[user_id])
    anulada_por: Mapped[User | None] = relationship(foreign_keys=[anulada_por_id])
    lineas: Mapped[list["SaleLine"]] = relationship(
        back_populates="venta", cascade="all, delete-orphan", order_by="SaleLine.id"
    )

    @property
    def referencia_stock(self) -> str:
        """Texto con el que sus movimientos quedan marcados en el kardex."""
        return f"venta-{self.id}"


class SaleLine(Base):
    """Foto de lo vendido: guarda lo cobrado, no se recalcula con precios nuevos."""

    __tablename__ = "sale_lines"
    __table_args__ = (
        CheckConstraint("cantidad_base > 0", name="ck_linea_cantidad_positiva"),
        CheckConstraint("precio_unitario >= 0", name="ck_linea_precio"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    sale_id: Mapped[int] = mapped_column(ForeignKey("sales.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"))

    # Lo que pidió el cliente, en la unidad elegida (7 m², 2 cajas...)
    cantidad_pedida: Mapped[Decimal] = mapped_column(Numeric(12, 4))
    # Piezas que salen del stock
    cantidad_base: Mapped[int]
    # Lo que se cobra, en la unidad elegida. En m² son los m² realmente entregados.
    cantidad_cobrada: Mapped[Decimal] = mapped_column(Numeric(12, 4))

    precio_lista: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    ajuste_pct: Mapped[Decimal] = mapped_column(Numeric(6, 2), default=Decimal("0"))
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    precio_manual: Mapped[bool] = mapped_column(Boolean, default=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    venta: Mapped[Sale] = relationship(back_populates="lineas")
    producto: Mapped[Product] = relationship()
    unidad: Mapped[ProductUnit] = relationship()
