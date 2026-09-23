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
    EmergencyUnlockSerializer,
)
from app.services.auth_service import AuthenticationService


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
        return Response({
            "mensaje": "Inicio de sesión exitoso.",
            "usuario": PersonalAuthSerializer(user).data
        }, status=status.HTTP_200_OK)


class LogoutView(APIView):
    """Cierre de sesión de usuario."""
    permission_classes = [IsAuthenticated]

    @extend_schema(request=None, responses={200: dict})
    def post(self, request: Request) -> Response:
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
    path('desbloquear/', DesbloqueoManualView.as_view(), name='desbloqueo-manual'),
    path('emergency-unlock/', EmergencyUnlockView.as_view(), name='emergency-unlock'),
]

__all__ = [
    'LoginView',
    'LogoutView',
    'DesbloqueoManualView',
    'EmergencyUnlockView',
    'urlpatterns',
]
