"""
Enrutador Principal de URLs para SGTP Backend.
"""
from django.urls import path, include
from django.views.generic import RedirectView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)

urlpatterns = [
    # Redirección raíz a la documentación Swagger
    path('', RedirectView.as_view(url='/api/docs/', permanent=False), name='root-redirect'),
    # Documentación OpenAPI / Swagger
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
    # Router modular centralizado
    path('app/', include('app.api.urls')),
]
