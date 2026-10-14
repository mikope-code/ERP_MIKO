# ERP MIKO

Inventario y ventas para tienda de wall panels, pisos PVC, clips y pegamento. Ver `SPEC.md`.

## Puesta en marcha (Windows)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Abrir http://127.0.0.1:8000

## Comandos útiles

```powershell
.\.venv\Scripts\python.exe -m pytest                      # tests
.\.venv\Scripts\alembic.exe revision --autogenerate -m "mensaje"   # nueva migración
.\.venv\Scripts\alembic.exe upgrade head                  # aplicar migraciones
```

## Configuración

Variables de entorno con prefijo `ERP_` (o archivo `.env`):
`ERP_DATABASE_URL`, `ERP_SECRET_KEY`.
