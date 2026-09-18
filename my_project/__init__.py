"""
SGTP Backend - Package init
Asegura la carga de la app de Celery al iniciar Django.
"""
from .celery import app as celery_app

__all__ = ('celery_app',)
