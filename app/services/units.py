"""Conversión entre unidades de venta y la unidad base (piezas).

El stock se guarda siempre en piezas enteras. Aquí vive la única lógica que
traduce "2 cajas", "7 m²" o "5 piezas" a piezas.
"""

from decimal import ROUND_CEILING, Decimal

from app.models import Product, ProductUnit, UnitKind


class CantidadInvalida(ValueError):
    """La cantidad o la configuración de la unidad no permite convertir."""


def _a_decimal(cantidad: Decimal | int | float | str) -> Decimal:
    try:
        # str() evita arrastrar el error binario de los float (0.1 → 0.1000000000000000055)
        return Decimal(str(cantidad))
    except Exception as exc:
        raise CantidadInvalida(f"Cantidad no válida: {cantidad!r}") from exc


def a_piezas(
    producto: Product, unidad: ProductUnit, cantidad: Decimal | int | float | str
) -> int:
    """Convierte `cantidad` de `unidad` a piezas enteras de la unidad base.

    - Piezas y cajas deben ser enteras (no se venden fracciones).
    - En m² se redondea hacia arriba a piezas completas.
    """
    if unidad.product_id is not None and unidad.product_id != producto.id:
        raise CantidadInvalida("La unidad no pertenece al producto")

    qty = _a_decimal(cantidad)
    if not qty.is_finite() or qty <= 0:
        raise CantidadInvalida("La cantidad debe ser mayor que cero")

    if unidad.tipo in (UnitKind.BASE, UnitKind.CAJA):
        if qty != qty.to_integral_value():
            raise CantidadInvalida(f"No se venden fracciones de {unidad.nombre}")
        return int(qty) * unidad.piezas_por_unidad

    if unidad.tipo is UnitKind.AREA:
        m2 = producto.m2_por_pieza
        if not m2 or m2 <= 0:
            raise CantidadInvalida(
                f"{producto.nombre} no tiene definidos los m² por pieza"
            )
        return int((qty / Decimal(m2)).to_integral_value(rounding=ROUND_CEILING))

    raise CantidadInvalida(f"Tipo de unidad desconocido: {unidad.tipo}")


def m2_de_piezas(producto: Product, piezas: int) -> Decimal:
    """m² reales que cubren `piezas` (los que se entregan al cliente)."""
    if not producto.m2_por_pieza:
        raise CantidadInvalida(f"{producto.nombre} no tiene definidos los m² por pieza")
    return Decimal(piezas) * Decimal(producto.m2_por_pieza)


def desglosar_en_cajas(piezas: int, piezas_por_caja: int) -> tuple[int, int]:
    """(cajas completas, piezas sueltas) — para mostrar el stock de forma legible."""
    if piezas_por_caja < 1:
        raise CantidadInvalida("Piezas por caja inválidas")
    return divmod(piezas, piezas_por_caja)
