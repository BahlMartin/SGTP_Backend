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
        db_config['default']['CONN_MAX_AGE'] = env.int('DB_CONN_MAX_AGE', default=0)
        db_config['default']['CONN_HEALTH_CHECKS'] = True
        db_config['default']['DISABLE_SERVER_SIDE_CURSORS'] = True
        if (
            env.bool('DB_USE_TRANSACTION_POOLER', default=True)
            and str(db_config['default'].get('HOST', '')).endswith('.pooler.supabase.com')
            and str(db_config['default'].get('PORT', '')) == '5432'
        ):
            db_config['default']['PORT'] = 6543
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
