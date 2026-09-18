"""
Middlewares de seguridad específicos de SGTP:
- JWEDecryptionMiddleware: Descifrado transparente de payloads JWE RFC 7516.
- ShiftScheduleRestrictionMiddleware: Control estricto de horarios y turnos de personal.
"""
import json
import logging
from typing import Callable, Any
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.conf import settings
from django.utils import timezone

from app.core.jwe import decrypt_payload_jwe
from app.models.user import RolPersonal, HabilitacionHoraria

logger = logging.getLogger(__name__)


class JWEDecryptionMiddleware:
    """
    Interpreta peticiones con el encabezado 'X-Payload-Encrypted: JWE' o 'Content-Type: application/jose'.
    Desencripta el cuerpo JWE compacto utilizando la clave simétrica centralizada en .env
    y sustituye el body con el JSON plano original para que DRF lo procese normalmente.
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        is_jwe_header = request.headers.get('X-Payload-Encrypted') == 'JWE'
        is_jose_type = request.content_type == 'application/jose'

        if is_jwe_header or is_jose_type:
            try:
                raw_body = request.body.decode('utf-8').strip()
                if raw_body.startswith('"') and raw_body.endswith('"'):
                    raw_body = json.loads(raw_body)

                # Desencriptación JWE RFC 7516
                payload_dict = decrypt_payload_jwe(raw_body)

                # Reemplazar el payload del request con el JSON desencriptado
                new_body = json.dumps(payload_dict).encode('utf-8')
                request._body = new_body
                request.META['CONTENT_TYPE'] = 'application/json'
            except Exception as exc:
                logger.error("Error al desencriptar payload JWE entrante: %s", exc)
                return JsonResponse(
                    {
                        "error": "JWE_DECRYPTION_FAILED",
                        "detail": "El payload proporcionado no pudo ser autenticado o descifrado.",
                        "reason": str(exc)
                    },
                    status=400
                )

        return self.get_response(request)


class ShiftScheduleRestrictionMiddleware:
    """
    Controla el acceso asistencial de acuerdo a la franja horaria asignada al personal.
    Si el personal intenta operar fuera de su turno sin habilitación aprobada,
    se bloquea la petición con HTTP 403 Forbidden.
    """

    EXEMPT_PATHS = [
        '/app/auth/login/',
        '/app/auth/emergency-unlock/',
        '/api/schema/',
        '/api/docs/',
        '/static/',
        '/admin/',
    ]

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        # Permitir rutas públicas de autenticación y documentación
        if any(request.path.startswith(path) for path in self.EXEMPT_PATHS):
            return self.get_response(request)

        user = getattr(request, 'user', None)

        # Si no está autenticado, pasa a las capas de permisos de DRF
        if not user or not user.is_authenticated:
            return self.get_response(request)

        # Roles exentos de restricción horaria
        if user.rol in [RolPersonal.ADMIN, RolPersonal.JEFA]:
            return self.get_response(request)

        # Para Admision, Box y Secretaria, verificar franja laboral
        if user.rol in [RolPersonal.ADMISION, RolPersonal.BOX, RolPersonal.SECRETARIA]:
            now_dt = timezone.localtime(timezone.now())
            now_time = now_dt.time()
            now_date = now_dt.date()

            dentro_de_turno = False

            if user.inicio_turno and user.fin_turno:
                if user.inicio_turno <= user.fin_turno:
                    # Turno ordinario diurno (ej. 07:00 a 15:00)
                    dentro_de_turno = user.inicio_turno <= now_time <= user.fin_turno
                else:
                    # Turno que cruza la medianoche (ej. 22:00 a 06:00)
                    dentro_de_turno = now_time >= user.inicio_turno or now_time <= user.fin_turno
            else:
                # Si no tiene turno configurado explícitamente, se permite acceso o requiere habilitación
                dentro_de_turno = True

            if not dentro_de_turno:
                # Verificar si existe habilitación excepcional activa para hoy otorgada por Jefa/Admin
                tiene_habilitacion = HabilitacionHoraria.objects.filter(
                    personal=user,
                    fecha=now_date,
                    activa=True,
                    hora_inicio__lte=now_time,
                    hora_fin__gte=now_time
                ).exists()

                if not tiene_habilitacion:
                    return JsonResponse(
                        {
                            "error": "ACCESO_FUERA_DE_TURNO",
                            "detail": (
                                f"Acceso bloqueado: Su usuario ({user.email} - Rol {user.rol}) "
                                f"se encuentra fuera de su franja laboral asignada ({user.inicio_turno} a {user.fin_turno}). "
                                "Requiere una habilitación de horario excepcional autorizada por la Jefa de Laboratorio."
                            ),
                            "hora_actual_servidor": str(now_time),
                        },
                        status=403
                    )

        return self.get_response(request)


__all__ = [
    'JWEDecryptionMiddleware',
    'ShiftScheduleRestrictionMiddleware',
]
