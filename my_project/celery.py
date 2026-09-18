import os
from celery import Celery
from celery.schedules import crontab

# Establecer configuración por defecto de Django para Celery
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

app = Celery('sgtp_backend')

# Carga la configuración desde settings de Django con namespace 'CELERY'
app.config_from_object('django.conf:settings', namespace='CELERY')

# Autodescubrimiento de tareas en apps registradas
app.autodiscover_tasks()

# Configuración de Celery Beat: Reporte Diario consolidado a las 23:59 UTC
app.conf.beat_schedule = {
    'generar-y-enviar-reporte-diario-2359-utc': {
        'task': 'app.tasks.tarea_consolidar_y_enviar_reporte_diario',
        'schedule': crontab(hour=23, minute=59),
    },
}
