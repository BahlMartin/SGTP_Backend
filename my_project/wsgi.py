"""
WSGI config for SGTP Backend project.
"""
import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'my_project.settings.base')

application = get_wsgi_application()
