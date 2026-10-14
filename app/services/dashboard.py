from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.clock import hoy_local, rango_utc_del_dia
from app.config import settings
from app.models import Product, Sale, SaleStatus, StockLot


@dataclass(frozen=True)
class StockBajo:
    producto: Product
    stock: int


@dataclass(frozen=True)
class LoteAlerta:
    producto: Product
    vencimiento: date
    cantidad: int
    dias: int  # negativo = ya venció hace |dias|


@dataclass(frozen=True)
class VentasDelDia:
    cantidad: int
    total: Decimal
    anuladas: int


@dataclass(frozen=True)
class Resumen:
    hoy: date
    stock_bajo: list[StockBajo]
    vencidos: list[LoteAlerta]
    por_vencer: list[LoteAlerta]
    ventas: VentasDelDia


def _lotes_con_vencimiento(db: Session, *condiciones, orden):
    return db.execute(
        select(StockLot, Product)
        .join(Product, Product.id == StockLot.product_id)
        .where(
            StockLot.cantidad_base > 0,
            StockLot.fecha_vencimiento.is_not(None),
            Product.activo.is_(True),
            *condiciones,
        )
        .order_by(orden, Product.nombre)
    ).all()


def resumen(db: Session, hoy: date | None = None) -> Resumen:
    hoy = hoy or hoy_local()
    limite = hoy + timedelta(days=settings.dias_alerta_vencimiento)

    # Stock bajo: mismo criterio que la pantalla de stock (stock <= mínimo)
    totales = dict(
        db.execute(
            select(StockLot.product_id, func.sum(StockLot.cantidad_base)).group_by(
                StockLot.product_id
            )
        ).all()
    )
    productos = db.scalars(
        select(Product).where(Product.activo.is_(True)).order_by(Product.nombre)
    ).all()
    bajos = [
        StockBajo(p, int(totales.get(p.id, 0)))
        for p in productos
        if int(totales.get(p.id, 0)) <= p.stock_minimo
    ]
    bajos.sort(key=lambda b: (b.stock - b.producto.stock_minimo, b.producto.nombre))

    def alertas(filas):
        return [
            LoteAlerta(p, l.fecha_vencimiento, l.cantidad_base, (l.fecha_vencimiento - hoy).days)
            for l, p in filas
        ]

    vencidos = alertas(
        _lotes_con_vencimiento(
            db, StockLot.fecha_vencimiento < hoy, orden=StockLot.fecha_vencimiento
        )
    )
    por_vencer = alertas(
        _lotes_con_vencimiento(
            db,
            StockLot.fecha_vencimiento >= hoy,
            StockLot.fecha_vencimiento <= limite,
            orden=StockLot.fecha_vencimiento,
        )
    )

    inicio, fin = rango_utc_del_dia(hoy)
    en_dia = (Sale.fecha >= inicio, Sale.fecha < fin)
    cantidad, total = db.execute(
        select(func.count(Sale.id), func.coalesce(func.sum(Sale.total), 0)).where(
            *en_dia, Sale.estado == SaleStatus.ACTIVA
        )
    ).one()
    anuladas = db.scalar(
        select(func.count(Sale.id)).where(*en_dia, Sale.estado == SaleStatus.ANULADA)
    )

    return Resumen(
        hoy=hoy,
        stock_bajo=bajos,
        vencidos=vencidos,
        por_vencer=por_vencer,
        ventas=VentasDelDia(int(cantidad), Decimal(str(total)), int(anuladas)),
    )
