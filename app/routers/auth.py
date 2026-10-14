from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.auth import SESSION_KEY, authenticate
from app.config import settings
from app.db import get_db
from app.templating import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if request.session.get(SESSION_KEY):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request, "login.html", {"app_name": settings.app_name, "error": None}
    )


@router.post("/login", response_class=HTMLResponse)
def login(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    usuario: Annotated[str, Form()],
    password: Annotated[str, Form()],
):
    user = authenticate(db, usuario, password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"app_name": settings.app_name, "error": "Usuario o contraseña incorrectos"},
            status_code=401,
        )
    request.session.clear()  # evita reutilizar una sesión previa
    request.session[SESSION_KEY] = user.id
    return RedirectResponse("/", status_code=303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)
