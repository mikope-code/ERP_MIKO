"""Precio de una unidad de venta para un cliente.

Prioridad (la primera que exista gana):
  1. precio especial del cliente para esa unidad
  2. ajuste % del cliente para ese producto
  3. ajuste % por defecto del cliente
  4. precio de lista

Un ajuste positivo es descuento; uno negativo es recargo.
"""

import enum
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    CustomerProductAdjustment,
    CustomerUnitPrice,
    ProductUnit,
)

CENTAVO = Decimal("0.01")


class Origen(str, enum.Enum):
    LISTA = "lista"
    PRECIO_ESPECIAL = "precio_especial"
    AJUSTE_PRODUCTO = "ajuste_producto"
    AJUSTE_CLIENTE = "ajuste_cliente"


ETIQUETAS = {
    Origen.LISTA: "Precio de lista",
    Origen.PRECIO_ESPECIAL: "Precio especial",
    Origen.AJUSTE_PRODUCTO: "Ajuste del producto",
    Origen.AJUSTE_CLIENTE: "Ajuste general del cliente",
}


@dataclass(frozen=True)
class PrecioCalculado:
    precio_lista: Decimal
    precio_final: Decimal
    origen: Origen
    ajuste_pct: Decimal  # % efectivo sobre la lista: positivo descuento, negativo recargo

    @property
    def etiqueta(self) -> str:
        return ETIQUETAS[self.origen]


def _redondear(valor: Decimal) -> Decimal:
    return valor.quantize(CENTAVO, rounding=ROUND_HALF_UP)


def resolver_precio(
    precio_lista: Decimal,
    *,
    precio_especial: Decimal | None = None,
    ajuste_producto: Decimal | None = None,
    ajuste_cliente: Decimal | None = None,
) -> PrecioCalculado:
    """Aplica la prioridad. Función pura: no toca la base de datos."""
    lista = _redondear(Decimal(precio_lista))

    if precio_especial is not None:
        final = _redondear(Decimal(precio_especial))
        origen = Origen.PRECIO_ESPECIAL
    elif ajuste_producto is not None:
        final = _redondear(lista * (Decimal(100) - Decimal(ajuste_producto)) / 100)
        origen = Origen.AJUSTE_PRODUCTO
    elif ajuste_cliente is not None and Decimal(ajuste_cliente) != 0:
        final = _redondear(lista * (Decimal(100) - Decimal(ajuste_cliente)) / 100)
        origen = Origen.AJUSTE_CLIENTE
    else:
        final, origen = lista, Origen.LISTA

    if lista > 0:
        pct = _redondear((lista - final) / lista * 100)
    else:
        pct = Decimal("0.00")
    return PrecioCalculado(lista, final, origen, pct)


def calcular_precio(
    db: Session, cliente: Customer | None, unidad: ProductUnit
) -> PrecioCalculado:
    """Precio de `unidad` para `cliente` (None = cliente de mostrador, sin ajustes)."""
    if cliente is None:
        return resolver_precio(unidad.precio_lista)

    especial = db.scalar(
        select(CustomerUnitPrice.precio).where(
            CustomerUnitPrice.customer_id == cliente.id,
            CustomerUnitPrice.unit_id == unidad.id,
        )
    )
    ajuste_producto = db.scalar(
        select(CustomerProductAdjustment.ajuste_pct).where(
            CustomerProductAdjustment.customer_id == cliente.id,
            CustomerProductAdjustment.product_id == unidad.product_id,
        )
    )
    return resolver_precio(
        unidad.precio_lista,
        precio_especial=especial,
        ajuste_producto=ajuste_producto,
        ajuste_cliente=cliente.ajuste_pct_defecto,
    )
