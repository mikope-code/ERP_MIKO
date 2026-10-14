from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.config import settings
from app.db import get_db
from app.forms import leer_decimal
from app.models import (
    Customer,
    CustomerProductAdjustment,
    CustomerUnitPrice,
    Product,
    ProductUnit,
)
from app.services.pricing import calcular_precio
from app.templating import templates

router = APIRouter(prefix="/clientes")
DB = Annotated[Session, Depends(get_db)]


def _render(request: Request, user, name: str, status_code: int = 200, **ctx):
    return templates.TemplateResponse(
        request,
        name,
        {"app_name": settings.app_name, "user": user, **ctx},
        status_code=status_code,
    )


def _porcentaje(valor: str, campo: str, errores: list[str]) -> Decimal | None:
    pct = leer_decimal(valor, campo, errores, minimo=Decimal("-100"))
    if pct is not None and pct > 100:
        errores.append(f"{campo}: no puede ser mayor que 100")
        return None
    return pct


def _cliente(db: Session, customer_id: int) -> Customer:
    cliente = db.get(Customer, customer_id)
    if cliente is None:
        raise HTTPException(404, "Cliente no encontrado")
    return cliente


def _detalle(request, user, db, cliente, errores=None, status_code=200):
    productos = db.scalars(
        select(Product).where(Product.activo.is_(True)).order_by(Product.nombre)
    ).all()
    # Qué pagaría este cliente por cada unidad: sirve para revisar las reglas
    vista = [
        (p, u, calcular_precio(db, cliente, u))
        for p in productos
        for u in p.unidades
    ]
    return _render(
        request, user, "customers/detail.html", status_code,
        cliente=cliente, productos=productos, vista=vista, errores=errores or [],
    )


@router.get("", response_class=HTMLResponse)
def listar(request: Request, user: AdminUser, db: DB):
    clientes = db.scalars(select(Customer).order_by(Customer.nombre)).all()
    return _render(request, user, "customers/list.html", clientes=clientes, errores=[])


@router.post("", response_class=HTMLResponse)
def crear(
    request: Request,
    user: AdminUser,
    db: DB,
    nombre: Annotated[str, Form()],
    telefono: Annotated[str, Form()] = "",
    ajuste_pct_defecto: Annotated[str, Form()] = "0",
):
    errores: list[str] = []
    nombre = nombre.strip()
    if not nombre:
        errores.append("Nombre: obligatorio")
    elif db.scalar(select(Customer).where(func.lower(Customer.nombre) == nombre.lower())):
        errores.append(f"Ya existe el cliente '{nombre}'")
    pct = _porcentaje(ajuste_pct_defecto or "0", "Ajuste %", errores)
    if errores:
        clientes = db.scalars(select(Customer).order_by(Customer.nombre)).all()
        return _render(
            request, user, "customers/list.html", 422, clientes=clientes, errores=errores
        )
    cliente = Customer(
        nombre=nombre, telefono=telefono.strip() or None, ajuste_pct_defecto=pct
    )
    db.add(cliente)
    db.commit()
    return RedirectResponse(f"/clientes/{cliente.id}", status_code=303)


@router.get("/{customer_id}", response_class=HTMLResponse)
def detalle(request: Request, customer_id: int, user: AdminUser, db: DB):
    return _detalle(request, user, db, _cliente(db, customer_id))


@router.post("/{customer_id}/editar")
def editar(
    request: Request,
    customer_id: int,
    user: AdminUser,
    db: DB,
    nombre: Annotated[str, Form()],
    ajuste_pct_defecto: Annotated[str, Form()],
    telefono: Annotated[str, Form()] = "",
    activo: Annotated[str | None, Form()] = None,
):
    cliente = _cliente(db, customer_id)
    errores: list[str] = []
    nombre = nombre.strip()
    if not nombre:
        errores.append("Nombre: obligatorio")
    else:
        otro = db.scalar(
            select(Customer).where(
                func.lower(Customer.nombre) == nombre.lower(), Customer.id != cliente.id
            )
        )
        if otro:
            errores.append(f"Ya existe el cliente '{nombre}'")
    pct = _porcentaje(ajuste_pct_defecto, "Ajuste %", errores)
    if errores:
        db.rollback()
        return _detalle(request, user, db, cliente, errores, 422)
    cliente.nombre = nombre
    cliente.telefono = telefono.strip() or None
    cliente.ajuste_pct_defecto = pct
    cliente.activo = bool(activo)
    db.commit()
    return RedirectResponse(f"/clientes/{cliente.id}", status_code=303)


@router.post("/{customer_id}/precios")
def guardar_precio_especial(
    request: Request,
    customer_id: int,
    user: AdminUser,
    db: DB,
    unit_id: Annotated[str, Form()],
    precio: Annotated[str, Form()],
):
    cliente = _cliente(db, customer_id)
    errores: list[str] = []
    unidad = db.get(ProductUnit, int(unit_id)) if unit_id.isdigit() else None
    if unidad is None:
        errores.append("Unidad: elige un producto y unidad")
    valor = leer_decimal(precio, "Precio", errores)
    if errores:
        return _detalle(request, user, db, cliente, errores, 422)

    existente = db.scalar(
        select(CustomerUnitPrice).where(
            CustomerUnitPrice.customer_id == cliente.id,
            CustomerUnitPrice.unit_id == unidad.id,
        )
    )
    if existente:
        existente.precio = valor
    else:
        db.add(CustomerUnitPrice(customer_id=cliente.id, unit_id=unidad.id, precio=valor))
    db.commit()
    return RedirectResponse(f"/clientes/{cliente.id}", status_code=303)


@router.post("/{customer_id}/precios/{price_id}/eliminar")
def quitar_precio_especial(customer_id: int, price_id: int, user: AdminUser, db: DB):
    _cliente(db, customer_id)
    fila = db.get(CustomerUnitPrice, price_id)
    if fila is None or fila.customer_id != customer_id:
        raise HTTPException(404, "Precio especial no encontrado")
    db.delete(fila)
    db.commit()
    return RedirectResponse(f"/clientes/{customer_id}", status_code=303)


@router.post("/{customer_id}/ajustes")
def guardar_ajuste_producto(
    request: Request,
    customer_id: int,
    user: AdminUser,
    db: DB,
    product_id: Annotated[str, Form()],
    ajuste_pct: Annotated[str, Form()],
):
    cliente = _cliente(db, customer_id)
    errores: list[str] = []
    producto = db.get(Product, int(product_id)) if product_id.isdigit() else None
    if producto is None:
        errores.append("Producto: elige un producto")
    pct = _porcentaje(ajuste_pct, "Ajuste %", errores)
    if errores:
        return _detalle(request, user, db, cliente, errores, 422)

    existente = db.scalar(
        select(CustomerProductAdjustment).where(
            CustomerProductAdjustment.customer_id == cliente.id,
            CustomerProductAdjustment.product_id == producto.id,
        )
    )
    if existente:
        existente.ajuste_pct = pct
    else:
        db.add(
            CustomerProductAdjustment(
                customer_id=cliente.id, product_id=producto.id, ajuste_pct=pct
            )
        )
    db.commit()
    return RedirectResponse(f"/clientes/{cliente.id}", status_code=303)


@router.post("/{customer_id}/ajustes/{adjustment_id}/eliminar")
def quitar_ajuste_producto(customer_id: int, adjustment_id: int, user: AdminUser, db: DB):
    _cliente(db, customer_id)
    fila = db.get(CustomerProductAdjustment, adjustment_id)
    if fila is None or fila.customer_id != customer_id:
        raise HTTPException(404, "Ajuste no encontrado")
    db.delete(fila)
    db.commit()
    return RedirectResponse(f"/clientes/{customer_id}", status_code=303)
