from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from app.clock import hoy_local

from app.auth import AdminUser, CurrentUser
from app.config import settings
from app.db import get_db
from app.forms import leer_decimal, leer_entero, leer_fecha
from app.models import Product, ProductUnit, StockLot, StockMovement, Supplier, UnitKind
from app.services.stock import StockError, ajustar_lote, registrar_entrada
from app.services.units import CantidadInvalida
from app.templating import templates

router = APIRouter(prefix="/stock")
DB = Annotated[Session, Depends(get_db)]


def _render(request: Request, user, name: str, status_code: int = 200, **ctx):
    return templates.TemplateResponse(
        request,
        name,
        {"app_name": settings.app_name, "user": user, "hoy": hoy_local(), **ctx},
        status_code=status_code,
    )


def _opciones_entrada(db: Session) -> list[Product]:
    """Productos activos con sus unidades de entrada (base y caja; m² no)."""
    return list(
        db.scalars(
            select(Product).where(Product.activo.is_(True)).order_by(Product.nombre)
        ).all()
    )


def _form_entrada(request, user, db, status_code=200, errores=None, form=None):
    return _render(
        request, user, "stock/entrada.html", status_code,
        productos=_opciones_entrada(db),
        proveedores=db.scalars(
            select(Supplier).where(Supplier.activo.is_(True)).order_by(Supplier.nombre)
        ).all(),
        errores=errores or [], form=form or {},
        UnitKind=UnitKind,
    )


@router.get("", response_class=HTMLResponse)
def resumen(request: Request, user: CurrentUser, db: DB):
    hoy = hoy_local()
    limite = hoy + timedelta(days=settings.dias_alerta_vencimiento)
    productos = db.scalars(
        select(Product).where(Product.activo.is_(True)).order_by(Product.categoria, Product.nombre)
    ).all()

    totales = dict(
        db.execute(
            select(StockLot.product_id, func.sum(StockLot.cantidad_base)).group_by(StockLot.product_id)
        ).all()
    )
    vencidos = dict(
        db.execute(
            select(StockLot.product_id, func.sum(StockLot.cantidad_base))
            .where(StockLot.fecha_vencimiento < hoy, StockLot.cantidad_base > 0)
            .group_by(StockLot.product_id)
        ).all()
    )
    por_vencer = dict(
        db.execute(
            select(StockLot.product_id, func.min(StockLot.fecha_vencimiento))
            .where(
                StockLot.fecha_vencimiento >= hoy,
                StockLot.fecha_vencimiento <= limite,
                StockLot.cantidad_base > 0,
            )
            .group_by(StockLot.product_id)
        ).all()
    )
    filas = [
        {
            "producto": p,
            "stock": int(totales.get(p.id, 0)),
            "vencido": int(vencidos.get(p.id, 0)),
            "por_vencer": por_vencer.get(p.id),
            "bajo": int(totales.get(p.id, 0)) <= p.stock_minimo,
        }
        for p in productos
    ]
    return _render(request, user, "stock/list.html", filas=filas)


@router.get("/entrada", response_class=HTMLResponse)
def entrada_form(request: Request, user: CurrentUser, db: DB):
    return _form_entrada(request, user, db)


@router.post("/entrada", response_class=HTMLResponse)
def entrada(
    request: Request,
    user: CurrentUser,
    db: DB,
    unit_id: Annotated[str, Form()],
    cantidad: Annotated[str, Form()],
    vencimiento: Annotated[str, Form()] = "",
    supplier_id: Annotated[str, Form()] = "",
    costo: Annotated[str, Form()] = "",
    nota: Annotated[str, Form()] = "",
):
    errores: list[str] = []
    form = dict(unit_id=unit_id, cantidad=cantidad, vencimiento=vencimiento,
                supplier_id=supplier_id, costo=costo, nota=nota)

    unidad = db.get(ProductUnit, int(unit_id)) if unit_id.isdigit() else None
    if unidad is None:
        errores.append("Producto: elige un producto y unidad")
    producto = unidad.producto if unidad else None

    qty = leer_decimal(cantidad, "Cantidad", errores, minimo=0)
    fecha = leer_fecha(vencimiento, "Vencimiento", errores) if vencimiento.strip() else None
    proveedor = None
    if supplier_id.strip():
        proveedor = db.get(Supplier, int(supplier_id)) if supplier_id.isdigit() else None
        if proveedor is None:
            errores.append("Proveedor: no válido")
    # Solo el administrador maneja costos
    costo_d = None
    if user.rol.value == "admin" and costo.strip():
        costo_d = leer_decimal(costo, "Costo", errores)

    if not errores:
        try:
            registrar_entrada(
                db, producto, unidad, qty, user,
                vencimiento=fecha, proveedor=proveedor, costo_unidad=costo_d, nota=nota,
            )
            db.commit()
        except (StockError, CantidadInvalida) as e:
            db.rollback()
            errores.append(str(e))

    if errores:
        return _form_entrada(request, user, db, 422, errores, form)
    return RedirectResponse(f"/stock/{producto.id}", status_code=303)


def _detalle(request, product_id, user, db, errores=None, status_code=200):
    producto = db.get(Product, product_id)
    if producto is None:
        raise HTTPException(404, "Producto no encontrado")
    lotes = db.scalars(
        select(StockLot)
        .where(StockLot.product_id == product_id)
        .order_by(StockLot.fecha_vencimiento.is_(None), StockLot.fecha_vencimiento)
    ).all()
    movimientos = db.scalars(
        select(StockMovement)
        .where(StockMovement.product_id == product_id)
        .order_by(StockMovement.id.desc())
        .limit(100)
    ).all()
    return _render(
        request, user, "stock/detail.html", status_code,
        producto=producto, lotes=lotes, movimientos=movimientos,
        total=sum(l.cantidad_base for l in lotes), errores=errores or [],
    )


@router.get("/{product_id}", response_class=HTMLResponse)
def detalle(request: Request, product_id: int, user: CurrentUser, db: DB):
    return _detalle(request, product_id, user, db)

@router.post("/lotes/{lot_id}/ajuste")
def ajuste(
    request: Request,
    lot_id: int,
    user: AdminUser,
    db: DB,
    cantidad_contada: Annotated[str, Form()],
    nota: Annotated[str, Form()],
):
    lote = db.get(StockLot, lot_id)
    if lote is None:
        raise HTTPException(404, "Lote no encontrado")
    errores: list[str] = []
    contada = leer_entero(cantidad_contada, "Cantidad contada", errores)
    if contada is not None:
        try:
            ajustar_lote(db, lote, contada, user, nota)
            db.commit()
        except StockError as e:
            db.rollback()
            errores.append(str(e))
    if errores:
        return _detalle(request, lote.product_id, user, db, errores, 422)
    return RedirectResponse(f"/stock/{lote.product_id}", status_code=303)
