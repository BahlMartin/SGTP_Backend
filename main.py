#!/usr/bin/env python
"""
Punto de Entrada Principal (Main Entry Point) - SGTP Backend.
Permite iniciar el servidor directamente o ejecutar comandos de gestión.

Uso:
    python main.py                    # Inicia el servidor de desarrollo en el puerto 8000
    python main.py runserver 8000     # Inicia el servidor explícitamente
    python main.py test               # Ejecuta la suite de pruebas
    python main.py migrate            # Ejecuta las migraciones pendientes
"""
import os
import sys
from pathlib import Path

# Añadir el directorio raíz al PYTHONPATH
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

def main():
    """Punto de inicio para el backend."""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "No se pudo importar Django. Asegúrate de que el entorno virtual esté activo "
            "y que las dependencias estén instaladas (pip install -r requirements.txt)."
        ) from exc

    # Si no se proveen argumentos adicionales, iniciar el servidor por defecto
    args = sys.argv
    if len(args) == 1:
        args = [args[0], 'runserver', '0.0.0.0:8000']

    execute_from_command_line(args)


if __name__ == '__main__':
    main()
