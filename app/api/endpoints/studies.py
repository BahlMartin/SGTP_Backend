"""
Controlador de Endpoints para Catálogo de Estudios Médicos (Studies).
"""
from django.urls import path, include
from rest_framework import viewsets, filters, permissions
from rest_framework.routers import DefaultRouter
from rest_framework.permissions import IsAuthenticated
from rapidfuzz import fuzz

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from app.models.studies import Estudios, EstudioAliasAprendido, PerfilEstudioPatron
from app.schemas.studies import EstudiosSerializer
from app.core.permissions import IsJefaRole
from app.services.ocr_service import normalizar_texto_clinico, ALIAS_CLINICOS_MAP


class EstudiosViewSet(viewsets.ModelViewSet):
    """
    Gestión del catálogo maestro de estudios bioquímicos.
    Permite búsqueda por texto, código de práctica, alias aprendidos, diccionario clínico y baterías.
    """
    queryset = Estudios.objects.all().order_by('nombre')
    serializer_class = EstudiosSerializer
    filter_backends = [filters.SearchFilter]
    search_fields = ['codigo_practica', 'nombre']

    def filter_queryset(self, queryset):
        base_qs = super().filter_queryset(queryset)
        search_term = (self.request.query_params.get('search') or '').strip()
        if not search_term:
            return base_qs

        q_norm = normalizar_texto_clinico(search_term)
        if len(q_norm) < 2:
            return base_qs

        learned_ids = set()

        # 1. Alias aprendidos en EstudioAliasAprendido (substring o fuzzy)
        alias_qs = EstudioAliasAprendido.objects.filter(
            estado_revision__in=['APROBADO_AUTOMATICO', 'REVISADO_JEFA'],
            estudio__isnull=False,
        ).values_list('texto_patron', 'estudio_id')

        for patron, est_id in alias_qs:
            patron_norm = normalizar_texto_clinico(patron)
            if not patron_norm:
                continue
            if q_norm in patron_norm or patron_norm in q_norm:
                learned_ids.add(est_id)
            elif len(q_norm) >= 3 and len(patron_norm) >= 3:
                if max(fuzz.ratio(q_norm, patron_norm), fuzz.token_set_ratio(q_norm, patron_norm)) >= 82:
                    learned_ids.add(est_id)

        # 2. Diccionario clínico nuclear (ALIAS_CLINICOS_MAP) sobre nombres normalizados
        mapped_terms = set()
        for alias_key, target_term in ALIAS_CLINICOS_MAP.items():
            if q_norm == alias_key or (len(q_norm) >= 3 and (q_norm in alias_key or alias_key in q_norm)):
                mapped_terms.add(normalizar_texto_clinico(target_term))

        if mapped_terms:
            for est_id, est_nombre in queryset.values_list('id', 'nombre'):
                est_norm = normalizar_texto_clinico(est_nombre)
                if any(term in est_norm for term in mapped_terms):
                    learned_ids.add(est_id)

        # 3. Baterías / Combos aprendidos o configurados (PerfilEstudioPatron)
        for patron_perfil in PerfilEstudioPatron.objects.filter(activo=True):
            nombre_norm = normalizar_texto_clinico(patron_perfil.nombre_perfil)
            disps_norm = [normalizar_texto_clinico(d) for d in (patron_perfil.disparadores or [])]
            if q_norm in nombre_norm or any(q_norm in d or (len(d) >= 3 and d in q_norm) for d in disps_norm):
                for eid in (patron_perfil.estudios_ids or []):
                    if isinstance(eid, int):
                        learned_ids.add(eid)

        if not learned_ids:
            return base_qs

        base_ids = set(base_qs.values_list('id', flat=True))
        return queryset.filter(id__in=(base_ids | learned_ids)).order_by('nombre')

    def get_permissions(self):
        if self.request.method in permissions.SAFE_METHODS:
            return [IsAuthenticated()]
        return [IsJefaRole()]

    def perform_update(self, serializer):
        estudio = serializer.save()
        # Notificar al monitor operativo y laboratorio si se modifican demoras o datos del estudio
        channel_layer = get_channel_layer()
        if channel_layer:
            payload = {
                'type': 'broadcast_event',
                'payload': {
                    'event': 'LAB_STUDIES_UPDATED',
                    'action': 'STUDY_CONFIG_CHANGED',
                    'estudio_id': estudio.id,
                    'nombre': estudio.nombre,
                    'demora_horas': estudio.demora_horas,
                }
            }
            async_to_sync(channel_layer.group_send)('sgtp_lab_live', payload)
            async_to_sync(channel_layer.group_send)('sgtp_monitor_operativo', payload)


app_name = 'studies_endpoints'

router = DefaultRouter()
router.register(r'', EstudiosViewSet, basename='studies')

urlpatterns = [
    path('', include(router.urls)),
]

__all__ = [
    'EstudiosViewSet',
    'router',
    'urlpatterns',
]
