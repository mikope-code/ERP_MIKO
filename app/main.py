from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import CurrentUser, LoginRequired
from app.config import settings
from app.routers import auth as auth_router
from app.routers import products as products_router
from app.routers import stock as stock_router
from app.routers import suppliers as suppliers_router
from app.templating import BASE_DIR, templates

app = FastAPI(title=settings.app_name)

# Cookie de sesión firmada. same_site=lax impide que otro sitio dispare
# POSTs con la sesión del usuario (protección CSRF básica).
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.secret_key,
    session_cookie="erp_session",
    max_age=60 * 60 * 8,
    same_site="lax",
    https_only=settings.cookie_secure,
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(auth_router.router)
app.include_router(products_router.router)
app.include_router(stock_router.router)
app.include_router(suppliers_router.router)


@app.exception_handler(LoginRequired)
def _login_required(request: Request, _exc: LoginRequired):
    return RedirectResponse("/login", status_code=303)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def home(request: Request, user: CurrentUser):
    return templates.TemplateResponse(
        request, "home.html", {"app_name": settings.app_name, "user": user}
    )
