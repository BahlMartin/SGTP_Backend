"""
Django settings para el Sistema de Gestión de Triage y Flujo de Pacientes (SGTP).
Carga estricta y centralizada desde .env (Fail-Fast).
"""
import os
from pathlib import Path
import environ
from django.core.exceptions import ImproperlyConfigured

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

env = environ.Env()
env_file = BASE_DIR / '.env'

if env_file.exists():
    environ.Env.read_env(str(env_file))
elif not os.environ.get('DJANGO_SECRET_KEY'):
    # Fail-Fast si no existe el archivo .env ni variables de entorno cargadas
    raise ImproperlyConfigured(
        f"CRITICAL ERROR: No se encontró el archivo .env en {BASE_DIR} ni variables de entorno configuradas. "
        "Verifique la plantilla .env.example o configure las variables en el dashboard de despliegue."
    )

# ==============================================================================
# 1. CLAVES Y VARIABLES SENSIBLES (ESTRICTAMENTE DESDE .env - ZERO HARDCODED)
# ==============================================================================
SECRET_KEY = env('DJANGO_SECRET_KEY')
DEBUG = env.bool('DJANGO_DEBUG', default=False)
ALLOWED_HOSTS = env.list('DJANGO_ALLOWED_HOSTS')
CORS_ALLOWED_ORIGINS = env.list('DJANGO_CORS_ALLOWED_ORIGINS', default=[])
CORS_ALLOW_ALL_ORIGINS = DEBUG  # En modo debug local permite facilitar pruebas si CORS_ALLOWED_ORIGINS está vacío

# Criptografía: Field-Level Encryption (Fernet) para Pacientes
FERNET_ENCRYPTION_KEY = env('FERNET_ENCRYPTION_KEY')

# Criptografía: Payload Encryption JWE (RFC 7516 A256GCM)
JWE_SECRET_KEY = env('JWE_SECRET_KEY')
JWE_PAYLOAD_ENCRYPTION_ENABLED = env.bool('JWE_PAYLOAD_ENCRYPTION_ENABLED', default=False)

# Autodesbloqueo de emergencia con token criptográfico
EMERGENCY_UNLOCK_SECRET_TOKEN = env('EMERGENCY_UNLOCK_SECRET_TOKEN')

# Integración OCR On-Premise LAN
OCR_SERVICE_URL = env('OCR_SERVICE_URL')
OCR_SERVICE_TIMEOUT_SECONDS = env.int('OCR_SERVICE_TIMEOUT_SECONDS', default=15)
OCR_SIMILARITY_THRESHOLD = env.int('OCR_SIMILARITY_THRESHOLD', default=80)

# ==============================================================================
# 2. APLICACIONES REGISTRADAS
# ==============================================================================
DJANGO_APPS = [
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
]

THIRD_PARTY_APPS = [
    'rest_framework',
    'corsheaders',
    'auditlog',
    'drf_spectacular',
]

LOCAL_APPS = [
    'app.apps.AppConfig',
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

# Modelo de Usuario Personalizado
AUTH_USER_MODEL = 'app.Personal'

# ==============================================================================
# 3. MIDDLEWARE PIPELINE
# ==============================================================================
MIDDLEWARE = [
    'app.middlewares.trusted_hosts.TrustedHostsMiddleware',
    'app.middlewares.logging.RequestLoggingMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'app.middlewares.security.JWEDecryptionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'auditlog.middleware.AuditlogMiddleware',  # Registro inmutable append-only
    'app.middlewares.security.ShiftScheduleRestrictionMiddleware',  # Control horario de turnos
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'app.middlewares.error_handler.GlobalErrorHandlerMiddleware',
]


ROOT_URLCONF = 'my_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'my_project.wsgi.application'
ASGI_APPLICATION = 'my_project.asgi.application'

# ==============================================================================
# 4. BASE DE DATOS (POSTGRESQL / SUPABASE CON SSL)
# ==============================================================================
DATABASES = {
    'default': env.db('DATABASE_URL')
}
db_ssl_mode = env('DB_SSL_MODE', default='require')
if DATABASES['default']['ENGINE'] == 'django.db.backends.postgresql':
    DATABASES['default'].setdefault('OPTIONS', {})['sslmode'] = db_ssl_mode

# ==============================================================================
# 5. POLÍTICA DE HASHING DE CONTRASEÑAS (ARGON2 + PBKDF2)
# ==============================================================================
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.Argon2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    'django.contrib.auth.hashers.PBKDF2SHA1PasswordHasher',
]

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator', 'OPTIONS': {'min_length': 8}},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# ==============================================================================
# 6. INTERNACIONALIZACIÓN Y ZONA HORARIA
# ==============================================================================
LANGUAGE_CODE = 'es-ar'
TIME_ZONE = 'UTC'  # Estricto UTC para consistencia asistencial
USE_I18N = True
USE_TZ = True

# ==============================================================================
# 7. ARCHIVOS ESTÁTICOS
# ==============================================================================
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ==============================================================================
# 8. DJANGO REST FRAMEWORK & SPECTACULAR
# ==============================================================================
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.BasicAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 50,
}

SPECTACULAR_SETTINGS = {
    'TITLE': 'SGTP API - Sistema de Gestión de Triage y Flujo de Pacientes',
    'DESCRIPTION': 'API REST asistencial hospitalaria de alta concurrencia con triage multibox y seguridad FLE/JWE.',
    'VERSION': '1.0.0',
    'SERVE_INCLUDE_SCHEMA': False,
}

# ==============================================================================
# 9. CELERY & REDIS
# ==============================================================================
CELERY_BROKER_URL = env('CELERY_BROKER_URL')
CELERY_RESULT_BACKEND = env('CELERY_RESULT_BACKEND')
CELERY_ACCEPT_CONTENT = ['json']
CELERY_TASK_SERIALIZER = 'json'
CELERY_RESULT_SERIALIZER = 'json'
CELERY_TIMEZONE = 'UTC'

# ==============================================================================
# 10. NOTIFICACIONES Y SERVIDOR SMTP
# ==============================================================================
EMAIL_BACKEND = env('EMAIL_BACKEND', default='django.core.mail.backends.smtp.EmailBackend')
EMAIL_HOST = env('EMAIL_HOST')
EMAIL_PORT = env.int('EMAIL_PORT', default=587)
EMAIL_HOST_USER = env('EMAIL_HOST_USER')
EMAIL_HOST_PASSWORD = env('EMAIL_HOST_PASSWORD')
EMAIL_USE_TLS = env.bool('EMAIL_USE_TLS', default=True)
EMAIL_USE_SSL = env.bool('EMAIL_USE_SSL', default=False)
DEFAULT_FROM_EMAIL = env('DEFAULT_FROM_EMAIL')

# ==============================================================================
# 11. AUDITORÍA INALTERABLE (django-auditlog)
# ==============================================================================
AUDITLOG_ENABLED = env.bool('AUDITLOG_ENABLED', default=True)
