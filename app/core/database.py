"""
Módulo de Conexión y Gestión de Base de Datos para SGTP.
Configuración del motor de conexión (PostgreSQL / Supabase) y verificación de conectividad.
"""
from typing import Dict, Any
from django.db import connection, connections
from django.db.utils import OperationalError
from app.core.config import env, settings


def get_database_config() -> Dict[str, Any]:
    """Genera la configuración de base de datos para Django a partir de DATABASE_URL."""
    db_config = {
        'default': env.db('DATABASE_URL')
    }
    if db_config['default']['ENGINE'] == 'django.db.backends.postgresql':
        db_config['default'].setdefault('OPTIONS', {})['sslmode'] = settings.DB_SSL_MODE
    return db_config


def check_database_health() -> bool:
    """Verifica si la base de datos responde correctamente."""
    try:
        connection.ensure_connection()
        return True
    except OperationalError:
        return False


def get_db():
    """Generador / Context manager para obtener la conexión activa a la base de datos."""
    yield connection
