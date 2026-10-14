from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.product import Product, ProductUnit


class Customer(Base):
    __tablename__ = "customers"
    __table_args__ = (
        CheckConstraint(
            "ajuste_pct_defecto >= -100 AND ajuste_pct_defecto <= 100",
            name="ck_cliente_ajuste_rango",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120), index=True)
    telefono: Mapped[str | None] = mapped_column(String(30))
    # Positivo = descuento, negativo = recargo (a algunos clientes se les vende más caro)
    ajuste_pct_defecto: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=Decimal("0"))
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    precios_especiales: Mapped[list["CustomerUnitPrice"]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan"
    )
    ajustes_producto: Mapped[list["CustomerProductAdjustment"]] = relationship(
        back_populates="cliente", cascade="all, delete-orphan"
    )


class CustomerUnitPrice(Base):
    """Precio fijo para un cliente en una unidad de venta concreta (p. ej. la caja)."""

    __tablename__ = "customer_unit_prices"
    __table_args__ = (
        UniqueConstraint("customer_id", "unit_id", name="uq_precio_cliente_unidad"),
        CheckConstraint("precio >= 0", name="ck_precio_especial"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    unit_id: Mapped[int] = mapped_column(ForeignKey("product_units.id"), index=True)
    precio: Mapped[Decimal] = mapped_column(Numeric(12, 2))

    cliente: Mapped[Customer] = relationship(back_populates="precios_especiales")
    unidad: Mapped[ProductUnit] = relationship()


class CustomerProductAdjustment(Base):
    """Descuento (o recargo) % de un cliente para todas las unidades de un producto."""

    __tablename__ = "customer_product_adjustments"
    __table_args__ = (
        UniqueConstraint("customer_id", "product_id", name="uq_ajuste_cliente_producto"),
        CheckConstraint("ajuste_pct >= -100 AND ajuste_pct <= 100", name="ck_ajuste_producto_rango"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    ajuste_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2))

    cliente: Mapped[Customer] = relationship(back_populates="ajustes_producto")
    producto: Mapped[Product] = relationship()
