from decimal import Decimal
from itertools import zip_longest
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AdminUser, CurrentUser
from app.config import settings
from app.db import get_db
from app.forms import leer_decimal
from app.models import Customer, Product, Role, Sale, SaleStatus, User
from app.services.sales import (
    LineaPedido,
    VentaError,
    anular_venta,
    calcular_lineas,
    crear_venta,
    faltantes,
)
from app.services.stock import StockError
from app.services.units import CantidadInvalida
from app.templating import templates

router = APIRouter(prefix="/ventas")
DB = Annotated[Session, Depends(get_db)]
Lista = Annotated[list[str], Form()]


def _render(request: Request, user, name: str, status_code: int = 200, **ctx):
    return templates.TemplateResponse(
        request,
        name,
        {"app_name": settings.app_name, "user": user, **ctx},
        status_code=status_code,
    )


def _productos(db: Session) -> list[Product]:
    return list(
        db.scalars(
            select(Product).where(Product.activo.is_(True)).order_by(Product.nombre)
        ).all()
    )


def _clientes(db: Session) -> list[Customer]:
    return list(
        db.scalars(
            select(Customer).where(Customer.activo.is_(True)).order_by(Customer.nombre)
        ).all()
    )


def _leer_pedido(
    db: Session,
    user: User,
    cliente_id: str,
    unit_id: list[str],
    cantidad: list[str],
    precio: list[str],
) -> tuple[Customer | None, list[LineaPedido], list[str]]:
    errores: list[str] = []

    cliente = None
    if cliente_id.strip():
        cliente = db.get(Customer, int(cliente_id)) if cliente_id.isdigit() else None
        if cliente is None:
            errores.append("Cliente no válido")

    pedido: list[LineaPedido] = []
    filas = zip_longest(unit_id, cantidad, precio, fillvalue="")
    for n, (uid, qty, px) in enumerate(filas, start=1):
        if not uid.strip() and not qty.strip():
            continue  # fila vacía
        if not uid.strip() or not uid.isdigit():
            errores.append(f"Línea {n}: elige un producto")
            continue
        if not qty.strip():
            errores.append(f"Línea {n}: falta la cantidad")
            continue
        cantidad_d = leer_decimal(qty, f"Línea {n}: cantidad", errores, Decimal("0"))
        if cantidad_d is None:
            continue
        manual = None
        # El campo solo existe para el administrador; se ignora para los demás
        if user.rol == Role.ADMIN and px.strip():
            manual = leer_decimal(px, f"Línea {n}: precio", errores)
            if manual is None:
                continue
        pedido.append(LineaPedido(int(uid), cantidad_d, manual))
    return cliente, pedido, errores


@router.get("", response_class=HTMLResponse)
def historial(request: Request, user: CurrentUser, db: DB):
    ventas = db.scalars(select(Sale).order_by(Sale.id.desc()).limit(100)).all()
    return _render(request, user, "sales/list.html", ventas=ventas, SaleStatus=SaleStatus)


@router.get("/nueva", response_class=HTMLResponse)
def nueva(request: Request, user: CurrentUser, db: DB):
    return _render(
        request, user, "sales/new.html",
        productos=_productos(db), clientes=_clientes(db), errores=[], form={},
    )


@router.post("/linea", response_class=HTMLResponse)
def nueva_linea(request: Request, user: CurrentUser, db: DB):
    """Fila vacía para agregar otro producto a la venta (HTMX)."""
    return _render(request, user, "sales/_linea.html", productos=_productos(db))


@router.post("/previa", response_class=HTMLResponse)
def previa(
    request: Request,
    user: CurrentUser,
    db: DB,
    cliente_id: Annotated[str, Form()] = "",
    unit_id: Lista = [],
    cantidad: Lista = [],
    precio: Lista = [],
):
    """Precios y totales sin registrar nada (HTMX)."""
    cliente, pedido, errores = _leer_pedido(db, user, cliente_id, unit_id, cantidad, precio)
    lineas, avisos = [], []
    if not errores and pedido:
        try:
            lineas = calcular_lineas(db, user, cliente, pedido)
            avisos = faltantes(db, lineas)
        except VentaError as e:
            errores.append(str(e))
    total = sum((l.subtotal for l in lineas), Decimal("0.00"))
    return _render(
        request, user, "sales/_previa.html",
        lineas=lineas, total=total, errores=errores, avisos=avisos,
    )


@router.post("", response_class=HTMLResponse)
def registrar(
    request: Request,
    user: CurrentUser,
    db: DB,
    cliente_id: Annotated[str, Form()] = "",
    unit_id: Lista = [],
    cantidad: Lista = [],
    precio: Lista = [],
    nota: Annotated[str, Form()] = "",
):
    cliente, pedido, errores = _leer_pedido(db, user, cliente_id, unit_id, cantidad, precio)
    venta = None
    if not errores:
        try:
            venta = crear_venta(db, user, cliente, pedido, nota=nota)
            db.commit()
        except (VentaError, StockError, CantidadInvalida) as e:
            db.rollback()
            errores.append(str(e))

    if errores or venta is None:
        return _render(
            request, user, "sales/new.html", 422,
            productos=_productos(db), clientes=_clientes(db), errores=errores,
            form=dict(cliente_id=cliente_id, nota=nota),
        )
    return RedirectResponse(f"/ventas/{venta.id}", status_code=303)


@router.get("/{sale_id}", response_class=HTMLResponse)
def detalle(request: Request, sale_id: int, user: CurrentUser, db: DB):
    return _detalle(request, sale_id, user, db)


def _detalle(request, sale_id, user, db, errores=None, status_code=200):
    venta = db.get(Sale, sale_id)
    if venta is None:
        raise HTTPException(404, "Venta no encontrada")
    return _render(
        request, user, "sales/detail.html", status_code,
        venta=venta, errores=errores or [], SaleStatus=SaleStatus,
    )


@router.post("/{sale_id}/anular")
def anular(
    request: Request,
    sale_id: int,
    user: AdminUser,
    db: DB,
    motivo: Annotated[str, Form()],
):
    venta = db.get(Sale, sale_id)
    if venta is None:
        raise HTTPException(404, "Venta no encontrada")
    try:
        anular_venta(db, venta, user, motivo)
        db.commit()
    except (VentaError, StockError) as e:
        db.rollback()
        return _detalle(request, sale_id, user, db, [str(e)], 422)
    return RedirectResponse(f"/ventas/{sale_id}", status_code=303)
