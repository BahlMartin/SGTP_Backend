"""
Router Principal de Rutas de la API.
Agrupa de forma modular todos los controladores de endpoints.
"""
from django.urls import path, include

app_name = 'api'

urlpatterns = [
    path('auth/', include('app.api.endpoints.auth')),
    path('users/', include('app.api.endpoints.users')),
    path('items/', include('app.api.endpoints.items')),
    path('patients/', include('app.api.endpoints.patients')),
    path('triage/', include('app.api.endpoints.triage')),
    path('reports/', include('app.api.endpoints.reports')),
    path('ocr/', include('app.api.endpoints.ocr')),
]
