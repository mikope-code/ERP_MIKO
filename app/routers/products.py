from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import AdminUser, CurrentUser
from app.config import settings
from app.db import get_db
from app.models import CATEGORIAS, Product, ProductUnit, UnitKind
from app.templating import templates

router = APIRouter(prefix="/productos")
DB = Annotated[Session, Depends(get_db)]


def _render(request: Request, user, name: str, status_code: int = 200, **ctx):
    return templates.TemplateResponse(
        request,
        name,
        {"app_name": settings.app_name, "user": user, "categorias": CATEGORIAS, **ctx},
        status_code=status_code,
    )


def _decimal(valor: str, campo: str, errores: list[str], minimo: Decimal = Decimal("0")):
    try:
        d = Decimal(valor.strip().replace(",", "."))
    except (InvalidOperation, AttributeError):
        errores.append(f"{campo}: número no válido")
        return None
    if not d.is_finite() or d < minimo:
        errores.append(f"{campo}: debe ser {minimo} o mayor")
        return None
    return d


def _entero(valor: str, campo: str, errores: list[str], minimo: int = 0):
    d = _decimal(valor, campo, errores, Decimal(minimo))
    if d is None:
        return None
    if d != d.to_integral_value():
        errores.append(f"{campo}: debe ser un número entero")
        return None
    return int(d)


def _get_product(db: Session, product_id: int) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise HTTPException(404, "Producto no encontrado")
    return product


@router.get("", response_class=HTMLResponse)
def listar(request: Request, user: CurrentUser, db: DB):
    productos = db.scalars(select(Product).order_by(Product.categoria, Product.nombre)).all()
    return _render(request, user, "products/list.html", productos=productos)


@router.get("/nuevo", response_class=HTMLResponse)
def nuevo_form(request: Request, user: AdminUser):
    return _render(request, user, "products/form.html", producto=None, errores=[], form={})


@router.post("", response_class=HTMLResponse)
def crear(
    request: Request,
    user: AdminUser,
    db: DB,
    sku: Annotated[str, Form()],
    nombre: Annotated[str, Form()],
    categoria: Annotated[str, Form()],
    unidad_base: Annotated[str, Form()],
    precio_base: Annotated[str, Form()],
    costo: Annotated[str, Form()] = "0",
    stock_minimo: Annotated[str, Form()] = "0",
    m2_por_pieza: Annotated[str, Form()] = "",
    controla_vencimiento: Annotated[str | None, Form()] = None,
):
    errores: list[str] = []
    sku = sku.strip().upper()
    nombre, unidad_base = nombre.strip(), unidad_base.strip()
    if not sku:
        errores.append("SKU: obligatorio")
    elif db.scalar(select(Product).where(Product.sku == sku)):
        errores.append(f"SKU: ya existe un producto con '{sku}'")
    if not nombre:
        errores.append("Nombre: obligatorio")
    if not unidad_base:
        errores.append("Unidad base: obligatoria")
    if categoria not in CATEGORIAS:
        errores.append("Categoría: no válida")
    precio = _decimal(precio_base, "Precio", errores)
    costo_d = _decimal(costo or "0", "Costo", errores)
    minimo = _entero(stock_minimo or "0", "Stock mínimo", errores)
    m2 = None
    if m2_por_pieza.strip():
        m2 = _decimal(m2_por_pieza, "m² por pieza", errores, Decimal("0.0001"))

    if errores:
        return _render(
            request, user, "products/form.html", status_code=422,
            producto=None, errores=errores, form=dict(
                sku=sku, nombre=nombre, categoria=categoria, unidad_base=unidad_base,
                precio_base=precio_base, costo=costo, stock_minimo=stock_minimo,
                m2_por_pieza=m2_por_pieza, controla_vencimiento=bool(controla_vencimiento),
            ),
        )

    producto = Product(
        sku=sku, nombre=nombre, categoria=categoria, unidad_base=unidad_base,
        costo=costo_d, stock_minimo=minimo, m2_por_pieza=m2,
        controla_vencimiento=bool(controla_vencimiento),
    )
    producto.unidades.append(
        ProductUnit(nombre=unidad_base, tipo=UnitKind.BASE, piezas_por_unidad=1, precio_lista=precio)
    )
    db.add(producto)
    db.commit()
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)


@router.get("/{product_id}", response_class=HTMLResponse)
def detalle(request: Request, product_id: int, user: CurrentUser, db: DB):
    return _render(
        request, user, "products/detail.html",
        producto=_get_product(db, product_id), errores=[],
    )


@router.post("/{product_id}/editar")
def editar(
    request: Request,
    product_id: int,
    user: AdminUser,
    db: DB,
    nombre: Annotated[str, Form()],
    categoria: Annotated[str, Form()],
    costo: Annotated[str, Form()],
    stock_minimo: Annotated[str, Form()],
    m2_por_pieza: Annotated[str, Form()] = "",
    controla_vencimiento: Annotated[str | None, Form()] = None,
    activo: Annotated[str | None, Form()] = None,
):
    producto = _get_product(db, product_id)
    errores: list[str] = []
    if not nombre.strip():
        errores.append("Nombre: obligatorio")
    if categoria not in CATEGORIAS:
        errores.append("Categoría: no válida")
    costo_d = _decimal(costo, "Costo", errores)
    minimo = _entero(stock_minimo, "Stock mínimo", errores)
    m2 = None
    if m2_por_pieza.strip():
        m2 = _decimal(m2_por_pieza, "m² por pieza", errores, Decimal("0.0001"))
    elif producto.unidad_de_tipo(UnitKind.AREA):
        errores.append("m² por pieza: es obligatorio mientras exista la unidad m²")

    if errores:
        return _render(
            request, user, "products/detail.html", status_code=422,
            producto=producto, errores=errores,
        )

    producto.nombre = nombre.strip()
    producto.categoria = categoria
    producto.costo = costo_d
    producto.stock_minimo = minimo
    producto.m2_por_pieza = m2
    producto.controla_vencimiento = bool(controla_vencimiento)
    producto.activo = bool(activo)
    db.commit()
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)


@router.post("/{product_id}/unidades")
def agregar_unidad(
    request: Request,
    product_id: int,
    user: AdminUser,
    db: DB,
    tipo: Annotated[str, Form()],
    precio: Annotated[str, Form()],
    nombre: Annotated[str, Form()] = "",
    piezas_por_unidad: Annotated[str, Form()] = "",
):
    producto = _get_product(db, product_id)
    errores: list[str] = []
    precio_d = _decimal(precio, "Precio", errores)

    if tipo == UnitKind.CAJA.value:
        nombre = nombre.strip() or "caja"
        piezas = _entero(piezas_por_unidad, "Piezas por caja", errores, minimo=1)
        kind = UnitKind.CAJA
    elif tipo == UnitKind.AREA.value:
        nombre, piezas, kind = "m²", 1, UnitKind.AREA
        if not producto.m2_por_pieza:
            errores.append("Define primero los m² por pieza del producto")
    else:
        errores.append("Tipo de unidad no válido")
        kind, piezas = None, None

    if any(u.nombre.lower() == nombre.lower() for u in producto.unidades):
        errores.append(f"Ya existe una unidad llamada '{nombre}'")
    if kind is UnitKind.AREA and producto.unidad_de_tipo(UnitKind.AREA):
        errores.append("El producto ya tiene unidad m²")

    if errores:
        return _render(
            request, user, "products/detail.html", status_code=422,
            producto=producto, errores=errores,
        )

    producto.unidades.append(
        ProductUnit(nombre=nombre, tipo=kind, piezas_por_unidad=piezas, precio_lista=precio_d)
    )
    db.commit()
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)


@router.post("/{product_id}/unidades/{unit_id}/precio")
def actualizar_precio(
    request: Request,
    product_id: int,
    unit_id: int,
    user: AdminUser,
    db: DB,
    precio: Annotated[str, Form()],
):
    producto = _get_product(db, product_id)
    unidad = next((u for u in producto.unidades if u.id == unit_id), None)
    if unidad is None:
        raise HTTPException(404, "Unidad no encontrada")
    errores: list[str] = []
    precio_d = _decimal(precio, "Precio", errores)
    if errores:
        return _render(
            request, user, "products/detail.html", status_code=422,
            producto=producto, errores=errores,
        )
    unidad.precio_lista = precio_d
    db.commit()
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)


@router.post("/{product_id}/unidades/{unit_id}/eliminar")
def eliminar_unidad(product_id: int, unit_id: int, user: AdminUser, db: DB):
    producto = _get_product(db, product_id)
    unidad = next((u for u in producto.unidades if u.id == unit_id), None)
    if unidad is None:
        raise HTTPException(404, "Unidad no encontrada")
    if unidad.tipo is UnitKind.BASE:
        raise HTTPException(400, "La unidad base no se puede eliminar")
    producto.unidades.remove(unidad)
    db.commit()
    return RedirectResponse(f"/productos/{producto.id}", status_code=303)
