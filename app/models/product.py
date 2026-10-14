import enum
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Enum,
    ForeignKey,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

CATEGORIAS = ["Wall panel", "Piso PVC", "Clips", "Pegamento", "Otro"]


class UnitKind(str, enum.Enum):
    BASE = "base"  # la unidad en la que se guarda el stock (pieza, unidad...)
    CAJA = "caja"  # N piezas por caja
    AREA = "area"  # m²; se convierte con Product.m2_por_pieza


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(primary_key=True)
    sku: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    nombre: Mapped[str] = mapped_column(String(150))
    categoria: Mapped[str] = mapped_column(String(40))
    unidad_base: Mapped[str] = mapped_column(String(30))
    costo: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))
    stock_minimo: Mapped[int] = mapped_column(default=0)
    # m² que cubre una pieza; solo para pisos y wall panels
    m2_por_pieza: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    controla_vencimiento: Mapped[bool] = mapped_column(Boolean, default=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)

    unidades: Mapped[list["ProductUnit"]] = relationship(
        back_populates="producto",
        cascade="all, delete-orphan",
        order_by="ProductUnit.id",
    )

    def unidad_de_tipo(self, tipo: UnitKind) -> "ProductUnit | None":
        return next((u for u in self.unidades if u.tipo == tipo), None)


class ProductUnit(Base):
    __tablename__ = "product_units"
    __table_args__ = (
        UniqueConstraint("product_id", "nombre", name="uq_unidad_producto_nombre"),
        CheckConstraint("piezas_por_unidad >= 1", name="ck_piezas_por_unidad"),
        CheckConstraint("precio_lista >= 0", name="ck_precio_lista"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"), index=True)
    nombre: Mapped[str] = mapped_column(String(30))
    tipo: Mapped[UnitKind] = mapped_column(Enum(UnitKind, native_enum=False, length=10))
    # Piezas base que contiene 1 de esta unidad (1 para BASE; N para CAJA).
    # No se usa en AREA: ahí manda Product.m2_por_pieza.
    piezas_por_unidad: Mapped[int] = mapped_column(default=1)
    precio_lista: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"))

    producto: Mapped[Product] = relationship(back_populates="unidades")
