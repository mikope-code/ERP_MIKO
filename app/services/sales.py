"""Ventas: precio + conversión de unidades + descuento de stock en un solo paso.

`crear_venta` y `anular_venta` hacen `flush`, no `commit`. Si lanzan una
excepción, quien las llama debe hacer `rollback` (los movimientos de stock ya
generados se descartan con él).
"""

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Customer,
    MovementType,
    Product,
    ProductUnit,
    Role,
    Sale,
    SaleLine,
    SaleStatus,
    StockLot,
    StockMovement,
    UnitKind,
    User,
)
from app.services.pricing import PrecioCalculado, calcular_precio
from app.services.stock import StockError, registrar_salida, stock_vendible
from app.services.units import CantidadInvalida, a_piezas, m2_de_piezas

CENTAVO = Decimal("0.01")


class VentaError(ValueError):
    pass


@dataclass(frozen=True)
class LineaPedido:
    unit_id: int
    cantidad: Decimal | int | str
    precio_manual: Decimal | None = None  # solo el administrador puede fijarlo


@dataclass(frozen=True)
class LineaCalculada:
    unidad: ProductUnit
    producto: Product
    cantidad_pedida: Decimal
    piezas: int
    cantidad_cobrada: Decimal
    m2_entregados: Decimal | None
    precio: PrecioCalculado
    precio_unitario: Decimal
    precio_manual: bool
    subtotal: Decimal


def _calcular_linea(
    db: Session,
    user: User,
    cliente: Customer | None,
    pedido: LineaPedido,
    numero: int,
) -> LineaCalculada:
    unidad = db.get(ProductUnit, pedido.unit_id)
    if unidad is None:
        raise VentaError(f"Línea {numero}: producto o unidad no válidos")
    producto = unidad.producto
    if not producto.activo:
        raise VentaError(f"Línea {numero}: {producto.nombre} está inactivo")

    try:
        piezas = a_piezas(producto, unidad, pedido.cantidad)
    except CantidadInvalida as e:
        raise VentaError(f"Línea {numero} ({producto.nombre}): {e}") from e

    precio = calcular_precio(db, cliente, unidad)
    manual = pedido.precio_manual is not None
    if manual:
        if user.rol != Role.ADMIN:
            raise VentaError("Solo el administrador puede cambiar el precio")
        if pedido.precio_manual < 0:
            raise VentaError(f"Línea {numero}: el precio no puede ser negativo")
        unitario = Decimal(pedido.precio_manual).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    else:
        unitario = precio.precio_final

    if unidad.tipo is UnitKind.AREA:
        m2 = m2_de_piezas(producto, piezas)
        cobrada, m2_entregados = m2, m2
    else:
        cobrada, m2_entregados = Decimal(piezas // unidad.piezas_por_unidad), None

    subtotal = (cobrada * unitario).quantize(CENTAVO, rounding=ROUND_HALF_UP)
    return LineaCalculada(
        unidad=unidad,
        producto=producto,
        cantidad_pedida=Decimal(str(pedido.cantidad)),
        piezas=piezas,
        cantidad_cobrada=cobrada,
        m2_entregados=m2_entregados,
        precio=precio,
        precio_unitario=unitario,
        precio_manual=manual,
        subtotal=subtotal,
    )


def calcular_lineas(
    db: Session, user: User, cliente: Customer | None, pedido: list[LineaPedido]
) -> list[LineaCalculada]:
    """Precios y conversiones sin tocar el stock. Sirve para la vista previa."""
    if not pedido:
        raise VentaError("Agrega al menos un producto")
    if cliente is not None and not cliente.activo:
        raise VentaError(f"El cliente {cliente.nombre} está inactivo")
    return [
        _calcular_linea(db, user, cliente, p, i) for i, p in enumerate(pedido, start=1)
    ]


def faltantes(db: Session, lineas: list[LineaCalculada], hoy: date | None = None) -> list[str]:
    """Avisos de stock insuficiente, sumando todas las líneas de un mismo producto."""
    pedidas: dict[int, tuple[Product, int]] = {}
    for l in lineas:
        prod, total = pedidas.get(l.producto.id, (l.producto, 0))
        pedidas[l.producto.id] = (prod, total + l.piezas)
    avisos = []
    for prod, total in pedidas.values():
        disponible = stock_vendible(db, prod.id, hoy)
        if total > disponible:
            avisos.append(
                f"{prod.nombre}: se piden {total} {prod.unidad_base} y hay {disponible}"
            )
    return avisos


def crear_venta(
    db: Session,
    user: User,
    cliente: Customer | None,
    pedido: list[LineaPedido],
    *,
    nota: str | None = None,
    hoy: date | None = None,
) -> Sale:
    lineas = calcular_lineas(db, user, cliente, pedido)

    venta = Sale(
        customer_id=cliente.id if cliente else None,
        user_id=user.id,
        total=sum((l.subtotal for l in lineas), Decimal("0.00")),
        estado=SaleStatus.ACTIVA,
        nota=(nota or "").strip()[:255] or None,
    )
    db.add(venta)
    db.flush()  # necesitamos venta.id para marcar los movimientos del kardex

    for l in lineas:
        registrar_salida(
            db, l.producto, l.piezas, user, referencia=venta.referencia_stock, hoy=hoy
        )
        venta.lineas.append(
            SaleLine(
                product_id=l.producto.id,
                unit_id=l.unidad.id,
                cantidad_pedida=l.cantidad_pedida,
                cantidad_base=l.piezas,
                cantidad_cobrada=l.cantidad_cobrada,
                precio_lista=l.precio.precio_lista,
                ajuste_pct=_ajuste_efectivo(l),
                precio_unitario=l.precio_unitario,
                precio_manual=l.precio_manual,
                subtotal=l.subtotal,
            )
        )
    db.flush()
    return venta


def _ajuste_efectivo(l: LineaCalculada) -> Decimal:
    lista = l.precio.precio_lista
    if lista <= 0:
        return Decimal("0.00")
    return ((lista - l.precio_unitario) / lista * 100).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def anular_venta(db: Session, venta: Sale, user: User, motivo: str) -> list[StockMovement]:
    """Repone el stock en los mismos lotes de los que salió. No borra nada."""
    if user.rol != Role.ADMIN:
        raise VentaError("Solo el administrador puede anular ventas")
    if venta.estado is SaleStatus.ANULADA:
        raise VentaError("La venta ya está anulada")
    motivo = (motivo or "").strip()
    if not motivo:
        raise VentaError("La anulación requiere un motivo")

    salidas = db.scalars(
        select(StockMovement).where(
            StockMovement.referencia == venta.referencia_stock,
            StockMovement.tipo == MovementType.SALIDA,
        )
    ).all()
    if not salidas:
        raise StockError("La venta no tiene movimientos de stock que revertir")

    repuestos = []
    for s in salidas:
        lote = db.get(StockLot, s.lot_id)
        cantidad = -s.cantidad_base
        lote.cantidad_base += cantidad
        mov = StockMovement(
            product_id=s.product_id,
            lot_id=s.lot_id,
            tipo=MovementType.ANULACION,
            cantidad_base=cantidad,
            referencia=venta.referencia_stock,
            nota=motivo[:255],
            user_id=user.id,
        )
        db.add(mov)
        repuestos.append(mov)

    venta.estado = SaleStatus.ANULADA
    venta.anulada_por_id = user.id
    venta.anulada_en = datetime.now(timezone.utc).replace(tzinfo=None)
    venta.motivo_anulacion = motivo[:255]
    db.flush()
    return repuestos
