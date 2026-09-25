"""
Tests de Políticas de Autenticación, Bloqueo tras 3 Intentos, Jerarquía RBAC y Restricción Horaria.
"""
from datetime import time, timedelta
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from django.conf import settings

from app.models.user import Personal, RolPersonal, HabilitacionHoraria
from app.services.auth_service import AuthenticationService
from app.middlewares.security import ShiftScheduleRestrictionMiddleware
from django.http import HttpResponse


class AuthenticationRBACTestCase(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

        self.admin_user = Personal.objects.create_user(
            email='admin@hospital.local',
            password='AdminPassword123!',
            nombre='Admin',
            apellidos='General',
            dni=10101010,
            rol=RolPersonal.ADMIN
        )
        self.jefa_user = Personal.objects.create_user(
            email='jefa@hospital.local',
            password='JefaPassword123!',
            nombre='Elena',
            apellidos='Rios',
            dni=20202020,
            rol=RolPersonal.JEFA
        )
        self.admision_user = Personal.objects.create_user(
            email='operador@hospital.local',
            password='OperadorPass123!',
            nombre='Martin',
            apellidos='Silva',
            dni=30303030,
            rol=RolPersonal.ADMISION,
            inicio_turno=time(8, 0),
            fin_turno=time(16, 0)
        )

    def test_bloqueo_automatico_al_tercer_intento_fallido(self):
        """Al 3er fallo consecutivo, la cuenta debe quedar activo=False y bloqueada."""
        # Intento 1
        user, err = AuthenticationService.autenticar_personal(self.admision_user.email, 'clave_erronea_1')
        self.assertIsNone(user)
        self.admision_user.refresh_from_db()
        self.assertEqual(self.admision_user.cant_intentos, 1)
        self.assertTrue(self.admision_user.activo)

        # Intento 2
        user, err = AuthenticationService.autenticar_personal(self.admision_user.email, 'clave_erronea_2')
        self.assertIsNone(user)
        self.admision_user.refresh_from_db()
        self.assertEqual(self.admision_user.cant_intentos, 2)
        self.assertTrue(self.admision_user.activo)

        # Intento 3 -> Bloqueo
        user, err = AuthenticationService.autenticar_personal(self.admision_user.email, 'clave_erronea_3')
        self.assertIsNone(user)
        self.assertIn("ha sido bloqueada automáticamente", err)
        self.admision_user.refresh_from_db()
        self.assertEqual(self.admision_user.cant_intentos, 3)
        self.assertFalse(self.admision_user.activo)

        # Intento 4 con clave correcta -> Rechazado por cuenta inactiva
        user, err = AuthenticationService.autenticar_personal(self.admision_user.email, 'OperadorPass123!')
        self.assertIsNone(user)
        self.assertIn("Cuenta deshabilitada o bloqueada", err)

    def test_desbloqueo_manual_por_jefa_o_admin(self):
        """Jefa o Admin pueden desbloquear la cuenta."""
        # Forzar bloqueo
        self.admision_user.activo = False
        self.admision_user.cant_intentos = 3
        self.admision_user.save()

        # Desbloqueo por Jefa
        desbloqueado = AuthenticationService.desbloquear_cuenta(
            id_personal=self.admision_user.id_personal,
            solicitante=self.jefa_user
        )
        self.assertTrue(desbloqueado.activo)
        self.assertEqual(desbloqueado.cant_intentos, 0)

        # Ahora el login con clave correcta funciona
        user, err = AuthenticationService.autenticar_personal(self.admision_user.email, 'OperadorPass123!')
        self.assertIsNotNone(user)
        self.assertIsNone(err)

    def test_autodesbloqueo_emergencia_con_token(self):
        """Admin y Jefa pueden autodesbloquearse con token criptográfico configurado en .env."""
        self.jefa_user.activo = False
        self.jefa_user.cant_intentos = 3
        self.jefa_user.save()

        token_secreto = settings.EMERGENCY_UNLOCK_SECRET_TOKEN

        # Token erróneo -> Falla
        with self.assertRaises(PermissionDenied):
            AuthenticationService.autodesbloqueo_emergencia(
                email=self.jefa_user.email,
                token_emergencia='token_falso_invalido'
            )

        # Token correcto -> Éxito
        jefa_rescatada = AuthenticationService.autodesbloqueo_emergencia(
            email=self.jefa_user.email,
            token_emergencia=token_secreto
        )
        self.assertTrue(jefa_rescatada.activo)
        self.assertEqual(jefa_rescatada.cant_intentos, 0)

        # Rol no autorizado (Admisión) no puede usar el autodesbloqueo de emergencia
        self.admision_user.activo = False
        self.admision_user.save()
        with self.assertRaises(PermissionDenied):
            AuthenticationService.autodesbloqueo_emergencia(
                email=self.admision_user.email,
                token_emergencia=token_secreto
            )

    def test_jerarquia_de_creacion_de_usuarios(self):
        """Jefa puede crear roles asistenciales pero NO roles Jefa ni Admin."""
        # Jefa creando técnico de Box -> Permitido
        datos_box = {
            'email': 'nuevo_tecnico@hospital.local',
            'nombre': 'Lucas',
            'apellidos': 'Torres',
            'dni': 35444555,
            'rol': RolPersonal.BOX,
            'password': 'Password123!'
        }
        tecnico = AuthenticationService.crear_personal(datos_box, creador=self.jefa_user)
        self.assertIsNotNone(tecnico.pk)

        # Jefa intentando crear otra Jefa -> Prohibido
        datos_otra_jefa = {
            'email': 'otra_jefa@hospital.local',
            'nombre': 'Silvia',
            'apellidos': 'Mendez',
            'dni': 24999111,
            'rol': RolPersonal.JEFA,
            'password': 'Password123!'
        }
        with self.assertRaises(PermissionDenied):
            AuthenticationService.crear_personal(datos_otra_jefa, creador=self.jefa_user)

        # Jefa intentando crear Admin -> Prohibido
        datos_admin = {
            'email': 'otro_admin@hospital.local',
            'nombre': 'Pablo',
            'apellidos': 'Castro',
            'dni': 23888222,
            'rol': RolPersonal.ADMIN,
            'password': 'Password123!'
        }
        with self.assertRaises(PermissionDenied):
            AuthenticationService.crear_personal(datos_admin, creador=self.jefa_user)

        # Admin sí puede crear rol Jefa
        jefa_por_admin = AuthenticationService.crear_personal(datos_otra_jefa, creador=self.admin_user)
        self.assertIsNotNone(jefa_por_admin.pk)

    def test_middleware_restriccion_horaria(self):
        """Personal asistencial fuera de turno es bloqueado (403), salvo habilitación extraordinaria."""
        middleware = ShiftScheduleRestrictionMiddleware(lambda req: HttpResponse("OK", status=200))

        # Configurar usuario con turno de 02:00 a 04:00 (garantizado fuera de turno a las 12:00)
        usuario_turno = Personal.objects.create_user(
            email='nocturno@hospital.local',
            password='Password123!',
            nombre='Claudio',
            apellidos='Bravo',
            dni=38123987,
            rol=RolPersonal.BOX,
            inicio_turno=time(2, 0),
            fin_turno=time(4, 0)
        )

        request = self.factory.get('/app/boxes/')
        request.user = usuario_turno

        # Si la hora actual del test está fuera de 02:00 a 04:00
        now_time = timezone.localtime(timezone.now()).time()
        if not (time(2, 0) <= now_time <= time(4, 0)):
            response = middleware(request)
            self.assertEqual(response.status_code, 403)
            self.assertIn("ACCESO_FUERA_DE_TURNO", response.content.decode('utf-8'))

            # Otorgar habilitación horaria excepcional aprobada por Jefa
            HabilitacionHoraria.objects.create(
                personal=usuario_turno,
                aprobado_por=self.jefa_user,
                fecha=timezone.localtime(timezone.now()).date(),
                hora_inicio=time(0, 0),
                hora_fin=time(23, 59),
                motivo="Cobertura guardia extra de urgencia",
                activa=True
            )

            # Ahora debe permitir el acceso
            response_habilitado = middleware(request)
            self.assertEqual(response_habilitado.status_code, 200)
