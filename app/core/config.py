"""
Configuración Global y Carga Estricta de Variables de Entorno (Fail-Fast).
Centraliza los parámetros del sistema basados en .env.
"""
from pathlib import Path
from typing import List
import environ
from django.core.exceptions import ImproperlyConfigured

# Directorio raíz del proyecto
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / '.env'

if env_file.exists():
    environ.Env.read_env(str(env_file))


class Settings:
    """Clase contenedora de configuración tipada para SGTP Backend."""

    BASE_DIR: Path = BASE_DIR

    # Claves y seguridad
    SECRET_KEY: str = env('DJANGO_SECRET_KEY')
    DEBUG: bool = env.bool('DJANGO_DEBUG', default=False)
    ALLOWED_HOSTS: List[str] = env.list('DJANGO_ALLOWED_HOSTS', default=['localhost', '127.0.0.1', '.onrender.com'])
    CORS_ALLOWED_ORIGINS: List[str] = env.list('DJANGO_CORS_ALLOWED_ORIGINS', default=[])
    CORS_ALLOW_ALL_ORIGINS: bool = DEBUG

    # Criptografía
    FERNET_ENCRYPTION_KEY: str = env('FERNET_ENCRYPTION_KEY')
    JWE_SECRET_KEY: str = env('JWE_SECRET_KEY')
    JWE_PAYLOAD_ENCRYPTION_ENABLED: bool = env.bool('JWE_PAYLOAD_ENCRYPTION_ENABLED', default=False)
    EMERGENCY_UNLOCK_SECRET_TOKEN: str = env('EMERGENCY_UNLOCK_SECRET_TOKEN')

    # OCR
    OCR_SERVICE_URL: str = env('OCR_SERVICE_URL')
    OCR_SERVICE_TIMEOUT_SECONDS: int = env.int('OCR_SERVICE_TIMEOUT_SECONDS', default=15)
    OCR_SIMILARITY_THRESHOLD: int = env.int('OCR_SIMILARITY_THRESHOLD', default=80)

    # Base de Datos
    DATABASE_URL: str = env('DATABASE_URL')
    DB_SSL_MODE: str = env('DB_SSL_MODE', default='require')

    # Celery & Redis
    CELERY_BROKER_URL: str = env('CELERY_BROKER_URL', default='redis://localhost:6379/0')
    CELERY_RESULT_BACKEND: str = env('CELERY_RESULT_BACKEND', default='redis://localhost:6379/0')


settings = Settings()
