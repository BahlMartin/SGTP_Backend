"""
Controlador de Endpoints para Autenticación, Cierre de Sesión y Desbloqueos de Emergencia.
"""
from django.urls import path
from django.contrib.auth import login, logout
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from drf_spectacular.utils import extend_schema

from app.schemas.user import (
    LoginSerializer,
    PersonalAuthSerializer,
    DesbloqueoManualSerializer,
    BloqueoManualSerializer,
    EmergencyUnlockSerializer,
)
from app.services.auth_service import AuthenticationService
from app.services.audit_service import AuditService
from app.models.audit import AccionAuditoria, ResultadoAuditoria


class LoginView(APIView):
    """
    Endpoint de inicio de sesión hospitalario.
    Evalúa credenciales, políticas de intentos fallidos (bloqueo al 3er fallo).
    """
    permission_classes = [AllowAny]
    serializer_class = LoginSerializer

    @extend_schema(request=LoginSerializer, responses={200: PersonalAuthSerializer})
    def post(self, request: Request) -> Response:
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        email = serializer.validated_data['email']
        password = serializer.validated_data['password']

        user, error = AuthenticationService.autenticar_personal(email, password)
        if error:
            status_code = status.HTTP_403_FORBIDDEN if "bloqueada" in error else status.HTTP_401_UNAUTHORIZED
            return Response({"error": "LOGIN_FAILED", "detail": error}, status=status_code)

        # Iniciar sesión de Django
        login(request, user)
        if not request.session.session_key:
            request.session.save()
        
        return Response({
            "mensaje": "Inicio de sesión exitoso.",
            "usuario": PersonalAuthSerializer(user).data,
            "token": request.session.session_key
        }, status=status.HTTP_200_OK)


class SessionMeView(APIView):
    """
    Permite a un usuario autenticado recuperar su perfil y token de sesión activo.
    Ideal para rehidratar el token de WebSocket tras recargas de página.
    """
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: PersonalAuthSerializer})
    def get(self, request: Request) -> Response:
        if not request.session.session_key:
            request.session.save()
        return Response({
            "usuario": PersonalAuthSerializer(request.user).data,
            "token": request.session.session_key
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Cierre de sesión de usuario y liberación de puestos asistenciales."""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request) -> Response:
        from app.services.triage_service import TriageService
        user = request.user
        AuditService.registrar_evento(
            accion=AccionAuditoria.LOGOUT,
            usuario=user,
            resultado=ResultadoAuditoria.EXITO,
            descripcion='Cierre voluntario de sesión',
            metadata={'rol': getattr(user, 'rol', '')},
            request=request
        )
        TriageService.liberar_boxes_de_personal(user)
        logout(request)
        return Response({"mensaje": "Sesión finalizada correctamente."}, status=status.HTTP_200_OK)


class DesbloqueoManualView(APIView):
    """
    Desbloquea una cuenta bloqueada por intentos fallidos.
    Exclusivo para roles: Jefa, Admin, Secretaria.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = DesbloqueoManualSerializer

    @extend_schema(request=DesbloqueoManualSerializer, responses={200: PersonalAuthSerializer})
    def post(self, request: Request) -> Response:
        serializer = DesbloqueoManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        personal_desbloqueado = AuthenticationService.desbloquear_cuenta(
            id_personal=serializer.validated_data['id_personal'],
            solicitante=request.user
        )

        return Response({
            "mensaje": f"La cuenta de {personal_desbloqueado.email} ha sido desbloqueada exitosamente.",
            "usuario": PersonalAuthSerializer(personal_desbloqueado).data
        }, status=status.HTTP_200_OK)

    @extend_schema(request=DesbloqueoManualSerializer, responses={200: PersonalAuthSerializer})
    def patch(self, request: Request) -> Response:
        return self.post(request)


class BloqueoManualView(APIView):
    """
    Bloquea manualmente una cuenta de personal e invalida su acceso asistencial.
    Exclusivo para roles: Jefa, Admin.
    """
    permission_classes = [IsAuthenticated]
    serializer_class = BloqueoManualSerializer

    @extend_schema(request=BloqueoManualSerializer, responses={200: PersonalAuthSerializer})
    def patch(self, request: Request) -> Response:
        serializer = BloqueoManualSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        personal_bloqueado = AuthenticationService.bloquear_cuenta(
            id_personal=serializer.validated_data['id_personal'],
            solicitante=request.user
        )

        return Response({
            "mensaje": f"La cuenta de {personal_bloqueado.email} ha sido bloqueada exitosamente.",
            "usuario": PersonalAuthSerializer(personal_bloqueado).data
        }, status=status.HTTP_200_OK)

    @extend_schema(request=BloqueoManualSerializer, responses={200: PersonalAuthSerializer})
    def post(self, request: Request) -> Response:
        return self.patch(request)


class EmergencyUnlockView(APIView):
    """
    Endpoint oculto y seguro para autodesbloqueo de emergencia de roles Admin y Jefa
    mediante token criptográfico configurado en .env.
    """
    permission_classes = [AllowAny]
    serializer_class = EmergencyUnlockSerializer

    @extend_schema(request=EmergencyUnlockSerializer)
    def post(self, request: Request) -> Response:
        serializer = EmergencyUnlockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = AuthenticationService.autodesbloqueo_emergencia(
            email=serializer.validated_data['email'],
            token_emergencia=serializer.validated_data['token_emergencia']
        )

        return Response({
            "mensaje": f"Autodesbloqueo de emergencia exitoso para {user.email}.",
            "rol": user.rol
        }, status=status.HTTP_200_OK)


app_name = 'auth_endpoints'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('session/', SessionMeView.as_view(), name='session-me'),
    path('desbloquear/', DesbloqueoManualView.as_view(), name='desbloqueo-manual'),
    path('bloquear/', BloqueoManualView.as_view(), name='bloqueo-manual'),
    path('emergency-unlock/', EmergencyUnlockView.as_view(), name='emergency-unlock'),
]

__all__ = [
    'LoginView',
    'LogoutView',
    'SessionMeView',
    'DesbloqueoManualView',
    'BloqueoManualView',
    'EmergencyUnlockView',
    'urlpatterns',
]
