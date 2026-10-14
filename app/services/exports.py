"""Datos de cada exportación: (encabezados, filas). No generan el CSV."""

from collections.abc import Iterator
from datetime import date, datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.clock import hoy_local, rango_utc_del_dia
from app.config import settings
from app.models import (
    Product,
    Sale,
    SaleLine,
    StockLot,
    StockMovement,
    UnitKind,
)

_tz = ZoneInfo(settings.timezone)

Filas = tuple[list[str], Iterator[list[object]]]

_CENTAVOS = Decimal("0.01")
_DIEZ_MILESIMAS = Decimal("0.0001")


def _d2(valor: Decimal | None) -> Decimal | None:
    """Importes siempre con 2 decimales, vengan como vengan de la base."""
    return None if valor is None else Decimal(valor).quantize(_CENTAVOS)


def _d4(valor: Decimal | None) -> Decimal | None:
    return None if valor is None else Decimal(valor).quantize(_DIEZ_MILESIMAS)


def _local(valor: datetime | None) -> datetime | None:
    """Los datetimes se guardan en UTC sin zona; el CSV los lleva a hora local."""
    if valor is None:
        return None
    return valor.replace(tzinfo=timezone.utc).astimezone(_tz).replace(tzinfo=None)


def _rango(desde: date | None, hasta: date | None):
    """Condiciones [desde, hasta] inclusivo, en días locales, sobre UTC."""
    inicio = rango_utc_del_dia(desde)[0] if desde else None
    fin = rango_utc_del_dia(hasta)[1] if hasta else None
    return inicio, fin


def productos(db: Session) -> Filas:
    """Una fila por unidad de venta de cada producto."""
    encabezados = [
        "sku", "producto", "categoria", "unidad_base", "costo_por_unidad_base",
        "stock_minimo", "m2_por_pieza", "controla_vencimiento", "activo",
        "unidad_venta", "tipo_unidad", "piezas_por_unidad", "precio_lista",
    ]
    prods = db.scalars(select(Product).order_by(Product.categoria, Product.nombre)).all()

    def filas():
        for p in prods:
            for u in p.unidades:
                yield [
                    p.sku, p.nombre, p.categoria, p.unidad_base, _d2(p.costo),
                    p.stock_minimo, _d4(p.m2_por_pieza), p.controla_vencimiento, p.activo,
                    u.nombre, u.tipo.value,
                    None if u.tipo is UnitKind.AREA else u.piezas_por_unidad,
                    _d2(u.precio_lista),
                ]

    return encabezados, filas()


def stock(db: Session, hoy: date | None = None) -> Filas:
    """Una fila por lote. Los productos sin existencias salen con cantidad 0."""
    hoy = hoy or hoy_local()
    encabezados = [
        "sku", "producto", "categoria", "unidad_base", "vencimiento",
        "cantidad", "estado", "stock_minimo",
    ]
    prods = db.scalars(
        select(Product).where(Product.activo.is_(True)).order_by(Product.categoria, Product.nombre)
    ).all()
    lotes = db.scalars(
        select(StockLot).order_by(StockLot.fecha_vencimiento.is_(None), StockLot.fecha_vencimiento)
    ).all()
    por_producto: dict[int, list[StockLot]] = {}
    for l in lotes:
        por_producto.setdefault(l.product_id, []).append(l)

    def estado(l: StockLot) -> str:
        if l.fecha_vencimiento is None:
            return "sin vencimiento"
        return "vencido" if l.fecha_vencimiento < hoy else "vigente"

    def filas():
        for p in prods:
            propios = por_producto.get(p.id) or []
            if not propios:
                yield [p.sku, p.nombre, p.categoria, p.unidad_base, None, 0, "sin stock", p.stock_minimo]
            for l in propios:
                yield [
                    p.sku, p.nombre, p.categoria, p.unidad_base,
                    l.fecha_vencimiento, l.cantidad_base, estado(l), p.stock_minimo,
                ]

    return encabezados, filas()


def ventas(db: Session, desde: date | None = None, hasta: date | None = None) -> Filas:
    """Una fila por línea de venta (las anuladas incluyen su estado)."""
    encabezados = [
        "venta", "fecha", "estado", "cliente", "vendedor", "sku", "producto",
        "unidad", "cantidad_pedida", "piezas", "cantidad_cobrada", "precio_lista",
        "ajuste_pct", "precio_unitario", "precio_manual", "subtotal", "nota",
    ]
    inicio, fin = _rango(desde, hasta)
    stmt = select(Sale).order_by(Sale.id)
    if inicio:
        stmt = stmt.where(Sale.fecha >= inicio)
    if fin:
        stmt = stmt.where(Sale.fecha < fin)
    ventas_ = db.scalars(stmt).all()

    def filas():
        for v in ventas_:
            for l in v.lineas:
                yield [
                    v.id, _local(v.fecha), v.estado.value,
                    v.cliente.nombre if v.cliente else "Mostrador",
                    v.usuario.nombre, l.producto.sku, l.producto.nombre, l.unidad.nombre,
                    l.cantidad_pedida.normalize(), l.cantidad_base,
                    l.cantidad_cobrada.normalize(), _d2(l.precio_lista), _d2(l.ajuste_pct),
                    _d2(l.precio_unitario), l.precio_manual, _d2(l.subtotal), v.nota,
                ]

    return encabezados, filas()


def kardex(db: Session, desde: date | None = None, hasta: date | None = None) -> Filas:
    encabezados = [
        "fecha", "sku", "producto", "tipo", "cantidad", "vencimiento_lote",
        "usuario", "proveedor", "referencia", "nota", "costo_unitario",
    ]
    inicio, fin = _rango(desde, hasta)
    stmt = select(StockMovement).order_by(StockMovement.id)
    if inicio:
        stmt = stmt.where(StockMovement.fecha >= inicio)
    if fin:
        stmt = stmt.where(StockMovement.fecha < fin)
    movs = db.scalars(stmt).all()

    def filas():
        for m in movs:
            yield [
                _local(m.fecha), m.producto.sku, m.producto.nombre, m.tipo.value,
                m.cantidad_base, m.lote.fecha_vencimiento, m.usuario.nombre,
                m.proveedor.nombre if m.proveedor else None, m.referencia, m.nota,
                _d4(m.costo_unitario),
            ]

    return encabezados, filas()
