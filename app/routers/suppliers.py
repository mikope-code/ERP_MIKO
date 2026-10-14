from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.config import settings
from app.db import get_db
from app.models import Supplier
from app.templating import templates

router = APIRouter(prefix="/proveedores")
DB = Annotated[Session, Depends(get_db)]


def _render(request: Request, user, db: Session, errores=None, status_code=200):
    proveedores = db.scalars(select(Supplier).order_by(Supplier.nombre)).all()
    return templates.TemplateResponse(
        request,
        "suppliers/list.html",
        {
            "app_name": settings.app_name,
            "user": user,
            "proveedores": proveedores,
            "errores": errores or [],
        },
        status_code=status_code,
    )


@router.get("", response_class=HTMLResponse)
def listar(request: Request, user: AdminUser, db: DB):
    return _render(request, user, db)


@router.post("", response_class=HTMLResponse)
def crear(
    request: Request,
    user: AdminUser,
    db: DB,
    nombre: Annotated[str, Form()],
    telefono: Annotated[str, Form()] = "",
):
    nombre = nombre.strip()
    errores = []
    if not nombre:
        errores.append("Nombre: obligatorio")
    elif db.scalar(
        select(Supplier).where(func.lower(Supplier.nombre) == nombre.lower())
    ):
        errores.append(f"Ya existe el proveedor '{nombre}'")
    if errores:
        return _render(request, user, db, errores, 422)
    db.add(Supplier(nombre=nombre, telefono=telefono.strip() or None))
    db.commit()
    return RedirectResponse("/proveedores", status_code=303)


@router.post("/{supplier_id}/estado")
def cambiar_estado(supplier_id: int, user: AdminUser, db: DB):
    proveedor = db.get(Supplier, supplier_id)
    if proveedor is not None:
        proveedor.activo = not proveedor.activo
        db.commit()
    return RedirectResponse("/proveedores", status_code=303)
