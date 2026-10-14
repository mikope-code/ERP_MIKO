from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="ERP_")

    # SQLite en desarrollo; en producción usar una URL de PostgreSQL
    # (postgresql+psycopg://usuario:clave@host/db)
    database_url: str = "sqlite:///./erp.db"
    secret_key: str = "cambiar-en-produccion"
    app_name: str = "ERP MIKO"
    # Poner en true cuando se publique con HTTPS
    cookie_secure: bool = False
    # Zona horaria con la que se muestran las fechas (se guardan en UTC)
    timezone: str = "America/Lima"
    # Días de anticipación para avisar de lotes por vencer
    dias_alerta_vencimiento: int = 30


settings = Settings()
