"""Reglas de stock. Toda cantidad está en piezas (unidad base) y es entera.

Las funciones hacen `flush` pero no `commit`: quien las llama decide cuándo
confirmar, para que una venta o entrada completa sea una sola transacción.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session
from app.clock import hoy_local

from app.models import (
    MovementType,
    Product,
    ProductUnit,
    StockLot,
    StockMovement,
    Supplier,
    UnitKind,
    User,
)
from app.services.units import CantidadInvalida, a_piezas


class StockError(ValueError):
    pass


class StockInsuficiente(StockError):
    def __init__(self, producto: Product, pedido: int, disponible: int):
        self.disponible = disponible
        super().__init__(
            f"Stock insuficiente de {producto.nombre}: "
            f"pedido {pedido}, disponible {disponible}"
        )


def _lote(db: Session, product_id: int, vencimiento: date | None) -> StockLot:
    stmt = select(StockLot).where(StockLot.product_id == product_id)
    stmt = stmt.where(
        StockLot.fecha_vencimiento.is_(None)
        if vencimiento is None
        else StockLot.fecha_vencimiento == vencimiento
    )
    lote = db.scalar(stmt.with_for_update())
    if lote is None:
        lote = StockLot(product_id=product_id, cantidad_base=0, fecha_vencimiento=vencimiento)
        db.add(lote)
        db.flush()
    return lote


def costo_por_pieza(producto: Product, unidad: ProductUnit, costo_unidad: Decimal) -> Decimal:
    """Costo de una pieza a partir del costo de una unidad de compra."""
    if unidad.tipo is UnitKind.AREA:
        if not producto.m2_por_pieza:
            raise CantidadInvalida("El producto no tiene m² por pieza")
        return costo_unidad * Decimal(producto.m2_por_pieza)
    return costo_unidad / unidad.piezas_por_unidad


def registrar_entrada(
    db: Session,
    producto: Product,
    unidad: ProductUnit,
    cantidad,
    user: User,
    *,
    vencimiento: date | None = None,
    proveedor: Supplier | None = None,
    costo_unidad: Decimal | None = None,
    nota: str | None = None,
    hoy: date | None = None,
) -> StockMovement:
    if unidad.tipo is UnitKind.AREA:
        raise StockError("Las entradas se registran en piezas o cajas, no en m²")
    if not producto.activo:
        raise StockError(f"{producto.nombre} está inactivo")
    piezas = a_piezas(producto, unidad, cantidad)

    if producto.controla_vencimiento:
        if vencimiento is None:
            raise StockError(f"{producto.nombre} requiere fecha de vencimiento")
        if vencimiento < (hoy or hoy_local()):
            raise StockError("La fecha de vencimiento ya pasó")
    else:
        vencimiento = None

    lote = _lote(db, producto.id, vencimiento)
    lote.cantidad_base += piezas
    mov = StockMovement(
        product_id=producto.id,
        lot_id=lote.id,
        tipo=MovementType.ENTRADA,
        cantidad_base=piezas,
        user_id=user.id,
        supplier_id=proveedor.id if proveedor else None,
        costo_unitario=(
            costo_por_pieza(producto, unidad, costo_unidad)
            if costo_unidad is not None
            else None
        ),
        nota=(nota or None) and nota.strip()[:255],
    )
    db.add(mov)
    db.flush()
    return mov


def _lotes_vendibles(producto_id: int, hoy: date):
    return (
        select(StockLot)
        .where(
            StockLot.product_id == producto_id,
            StockLot.cantidad_base > 0,
            or_(StockLot.fecha_vencimiento.is_(None), StockLot.fecha_vencimiento >= hoy),
        )
    )


def stock_total(db: Session, product_id: int) -> int:
    """Todo lo que hay físicamente, vencido o no."""
    return db.scalar(
        select(func.coalesce(func.sum(StockLot.cantidad_base), 0)).where(
            StockLot.product_id == product_id
        )
    )


def stock_vendible(db: Session, product_id: int, hoy: date | None = None) -> int:
    """Lo que se puede vender: excluye lotes vencidos."""
    hoy = hoy or hoy_local()
    sub = _lotes_vendibles(product_id, hoy).subquery()
    return db.scalar(select(func.coalesce(func.sum(sub.c.cantidad_base), 0)))


def registrar_salida(
    db: Session,
    producto: Product,
    piezas: int,
    user: User,
    *,
    referencia: str | None = None,
    nota: str | None = None,
    hoy: date | None = None,
) -> list[StockMovement]:
    """Descarga `piezas` consumiendo primero el lote que vence antes (FEFO).

    Los lotes vencidos no se venden. Genera un movimiento por lote tocado.
    """
    if piezas <= 0:
        raise CantidadInvalida("La cantidad debe ser mayor que cero")
    hoy = hoy or hoy_local()

    lotes = db.scalars(
        _lotes_vendibles(producto.id, hoy)
        .order_by(StockLot.fecha_vencimiento.is_(None), StockLot.fecha_vencimiento, StockLot.id)
        .with_for_update()
    ).all()
    disponible = sum(l.cantidad_base for l in lotes)
    if disponible < piezas:
        raise StockInsuficiente(producto, piezas, disponible)

    movimientos: list[StockMovement] = []
    pendiente = piezas
    for lote in lotes:
        if pendiente == 0:
            break
        toma = min(lote.cantidad_base, pendiente)
        lote.cantidad_base -= toma
        pendiente -= toma
        mov = StockMovement(
            product_id=producto.id,
            lot_id=lote.id,
            tipo=MovementType.SALIDA,
            cantidad_base=-toma,
            referencia=referencia,
            nota=nota,
            user_id=user.id,
        )
        db.add(mov)
        movimientos.append(mov)
    db.flush()
    return movimientos


def ajustar_lote(
    db: Session, lote: StockLot, cantidad_contada: int, user: User, nota: str
) -> StockMovement | None:
    """Fija el lote en la cantidad realmente contada. Exige motivo."""
    if cantidad_contada < 0:
        raise StockError("La cantidad contada no puede ser negativa")
    nota = (nota or "").strip()
    if not nota:
        raise StockError("El ajuste requiere un motivo")
    delta = cantidad_contada - lote.cantidad_base
    if delta == 0:
        return None
    lote.cantidad_base = cantidad_contada
    mov = StockMovement(
        product_id=lote.product_id,
        lot_id=lote.id,
        tipo=MovementType.AJUSTE,
        cantidad_base=delta,
        nota=nota[:255],
        user_id=user.id,
    )
    db.add(mov)
    db.flush()
    return mov


def stock_segun_kardex(db: Session, product_id: int) -> int:
    """Suma de movimientos; debe coincidir siempre con stock_total."""
    return db.scalar(
        select(func.coalesce(func.sum(StockMovement.cantidad_base), 0)).where(
            StockMovement.product_id == product_id
        )
    )
