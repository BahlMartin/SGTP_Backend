"""
Pruebas integrales de la suite de Auditoría Operacional, Visibilidad RBAC y Geolocalización (SGTP).
"""
from datetime import timedelta
from django.test import TestCase, RequestFactory
from django.utils import timezone
from django.core.exceptions import PermissionDenied
from rest_framework.test import APIClient

from app.models.user import Personal, RolPersonal
from app.models.audit import (
    EventoAuditoria,
    CategoriaAuditoria,
    ResultadoAuditoria,
    AccionAuditoria
)
from app.services.audit_service import (
    AuditService,
    haversine_km,
    es_ip_privada,
    resolver_geo_ip,
)
from app.core.audit_context import (
    resolver_ip_cliente,
    sintetizar_dispositivo
)


class AuditoriaIntegrationTestCase(TestCase):
    def setUp(self):
        self.rf = RequestFactory()
        self.client = APIClient()

        self.admin_user = Personal.objects.create_superuser(
            email='admin.audit@hospital.gob.ar',
            password='Password123!',
            nombre='Admin',
            apellidos='General',
            dni='11111111',
            rol=RolPersonal.ADMIN
        )

        self.jefa_user = Personal.objects.create_user(
            email='jefa.audit@hospital.gob.ar',
            password='Password123!',
            nombre='Jefa',
            apellidos='Laboratorio',
            dni='22222222',
            rol=RolPersonal.JEFA
        )

        self.box_user = Personal.objects.create_user(
            email='box.audit@hospital.gob.ar',
            password='Password123!',
            nombre='Tecnico',
            apellidos='Box',
            dni='33333333',
            rol=RolPersonal.BOX
        )

        self.admision_user = Personal.objects.create_user(
            email='admision.audit@hospital.gob.ar',
            password='Password123!',
            nombre='Operador',
            apellidos='Admision',
            dni='44444444',
            rol=RolPersonal.ADMISION
        )

    def test_ip_cliente_cadena_valida_dos_saltos(self):
        req = self.rf.get('/app/auth/session/', HTTP_X_FORWARDED_FOR='190.12.34.56, 76.76.21.21, 10.0.0.1')
        ip, cadena, confiable = resolver_ip_cliente(req)
        self.assertTrue(confiable)
        self.assertEqual(ip, '76.76.21.21')
        self.assertIn('190.12.34.56', cadena)

    def test_ip_cliente_acceso_directo_local(self):
        req = self.rf.get('/app/auth/session/', REMOTE_ADDR='127.0.0.1')
        ip, cadena, confiable = resolver_ip_cliente(req)
        self.assertEqual(ip, '127.0.0.1')
        self.assertTrue(confiable)

    def test_ip_cliente_un_solo_salto_marca_no_confiable(self):
        req = self.rf.get('/app/auth/session/', HTTP_X_FORWARDED_FOR='190.12.34.56')
        ip, cadena, confiable = resolver_ip_cliente(req)
        self.assertEqual(ip, '190.12.34.56')
        self.assertFalse(confiable)

    def test_sintesis_dispositivo_user_agent(self):
        ua_chrome_win = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36"
        disp = sintetizar_dispositivo(ua_chrome_win)
        self.assertIn("Chrome", disp)
        self.assertIn("Windows", disp)

        ua_edge_mac = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Edg/130.0.0.0"
        disp_mac = sintetizar_dispositivo(ua_edge_mac)
        self.assertIn("Edge", disp_mac)
        self.assertIn("macOS", disp_mac)

    def test_inmutabilidad_bloquea_modificar_campos_protegidos(self):
        ev = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            rol_usuario=self.admin_user.rol,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            resultado=ResultadoAuditoria.EXITO,
            descripcion='Test login',
            ip='127.0.0.1'
        )
        ev.descripcion = 'Intento de adulteración de auditoría'
        with self.assertRaises(PermissionDenied):
            ev.save()

    def test_inmutabilidad_permite_actualizar_geolocalizacion_navegador(self):
        ev = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            rol_usuario=self.admin_user.rol,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            resultado=ResultadoAuditoria.EXITO,
            descripcion='Test login',
            ip='127.0.0.1'
        )
        ev.geo_nav_lat = -31.4201
        ev.geo_nav_lon = -64.1888
        ev.geo_nav_precision_m = 25.0
        ev.geo_nav_estado = 'CONCEDIDA'
        ev.save(update_fields=['geo_nav_lat', 'geo_nav_lon', 'geo_nav_precision_m', 'geo_nav_estado'])
        ev.refresh_from_db()
        self.assertEqual(ev.geo_nav_lat, -31.4201)

    def test_inmutabilidad_bloquea_delete_individual(self):
        ev = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            descripcion='Test login'
        )
        with self.assertRaises(PermissionDenied):
            ev.delete()

    def test_admin_ve_todos_los_eventos(self):
        EventoAuditoria.objects.create(usuario=self.admin_user, rol_usuario=RolPersonal.ADMIN, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Admin login')
        EventoAuditoria.objects.create(usuario=self.jefa_user, rol_usuario=RolPersonal.JEFA, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Jefa login')
        EventoAuditoria.objects.create(usuario=self.box_user, rol_usuario=RolPersonal.BOX, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Box login')

        qs = AuditService.queryset_visible_para(self.admin_user)
        self.assertEqual(qs.count(), 3)

    def test_jefa_ve_empleados_pero_nunca_a_admin(self):
        EventoAuditoria.objects.create(usuario=self.admin_user, rol_usuario=RolPersonal.ADMIN, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Admin login')
        EventoAuditoria.objects.create(usuario=self.jefa_user, rol_usuario=RolPersonal.JEFA, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Jefa login')
        EventoAuditoria.objects.create(usuario=self.box_user, rol_usuario=RolPersonal.BOX, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Box login')
        EventoAuditoria.objects.create(usuario=self.admision_user, rol_usuario=RolPersonal.ADMISION, accion=AccionAuditoria.LOGIN_EXITOSO, descripcion='Admision login')

        qs = AuditService.queryset_visible_para(self.jefa_user)
        self.assertEqual(qs.count(), 3)
        self.assertFalse(qs.filter(rol_usuario=RolPersonal.ADMIN).exists())

    def test_endpoints_bloquean_a_roles_no_autorizados(self):
        self.client.force_authenticate(user=self.box_user)
        resp = self.client.get('/app/auditoria/eventos/')
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(user=self.admision_user)
        resp = self.client.get('/app/auditoria/eventos/')
        self.assertEqual(resp.status_code, 403)

    def test_almacenamiento_endpoint_exclusivo_admin(self):
        self.client.force_authenticate(user=self.jefa_user)
        resp = self.client.get('/app/auditoria/almacenamiento/')
        self.assertEqual(resp.status_code, 403)

        self.client.force_authenticate(user=self.admin_user)
        resp = self.client.get('/app/auditoria/almacenamiento/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('usado_mb', resp.data)
        self.assertEqual(resp.data['limite_mb'], 500)

    def test_haversine_calculo_distancia(self):
        dist = haversine_km(-31.4167, -64.1833, -34.6037, -58.3816)
        self.assertTrue(640 <= dist <= 660)

    def test_ip_privada_detectada_correctamente(self):
        self.assertTrue(es_ip_privada('127.0.0.1'))
        self.assertTrue(es_ip_privada('10.0.1.5'))
        self.assertTrue(es_ip_privada('192.168.1.50'))
        self.assertTrue(es_ip_privada('172.16.0.1'))
        self.assertFalse(es_ip_privada('181.45.200.11'))

    def test_reportar_ubicacion_propio_login_exitoso(self):
        self.client.force_authenticate(user=self.box_user)
        ev_login = EventoAuditoria.objects.create(
            usuario=self.box_user,
            rol_usuario=self.box_user.rol,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            resultado=ResultadoAuditoria.EXITO,
            descripcion='Inicio de sesión',
            ip='127.0.0.1',
            fecha=timezone.now()
        )

        resp = self.client.post('/app/auditoria/ubicacion/', {
            'lat': -31.4167,
            'lon': -64.1833,
            'precision_m': 30.5,
            'denegada': False
        }, format='json')

        self.assertEqual(resp.status_code, 200)
        ev_login.refresh_from_db()
        self.assertEqual(ev_login.geo_nav_estado, 'CONCEDIDA')
        self.assertEqual(ev_login.geo_nav_lat, -31.4167)
        self.assertEqual(ev_login.geo_nav_precision_m, 30.5)

    def test_purga_elimina_registros_mas_viejos_de_un_ano(self):
        hace_400_dias = timezone.now() - timedelta(days=400)
        hace_10_dias = timezone.now() - timedelta(days=10)

        ev_antiguo = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            descripcion='Login muy viejo',
            fecha=hace_400_dias
        )
        ev_reciente = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            descripcion='Login reciente',
            fecha=hace_10_dias
        )

        res = AuditService.purgar_retencion(dias=365, forzar=True)
        self.assertGreaterEqual(res['eventos_eliminados'], 1)
        self.assertFalse(EventoAuditoria.objects.filter(pk=ev_antiguo.pk).exists())
        self.assertTrue(EventoAuditoria.objects.filter(pk=ev_reciente.pk).exists())


    def test_websocket_notifica_con_filtro_rbac(self):
        from unittest.mock import patch
        from app.services.websocket_notifier import notificar_evento_auditoria

        ev_admin = EventoAuditoria.objects.create(
            usuario=self.admin_user,
            rol_usuario=RolPersonal.ADMIN,
            accion=AccionAuditoria.LOGIN_EXITOSO,
            descripcion='Login Admin'
        )
        ev_box = EventoAuditoria.objects.create(
            usuario=self.box_user,
            rol_usuario=RolPersonal.BOX,
            accion=AccionAuditoria.PACIENTE_LLAMADO,
            descripcion='Paciente llamado a Box'
        )

        with patch('app.services.websocket_notifier.emitir_evento_ws') as mock_emitir:
            notificar_evento_auditoria(ev_admin)
            # Solo debe emitirse a admin, NUNCA a jefa
            grupos_llamados = [call[0][0] for call in mock_emitir.call_args_list]
            self.assertIn('sgtp_auditoria_admin', grupos_llamados)
            self.assertNotIn('sgtp_auditoria_jefa', grupos_llamados)

        with patch('app.services.websocket_notifier.emitir_evento_ws') as mock_emitir:
            notificar_evento_auditoria(ev_box)
            # Debe emitirse tanto a admin como a jefa
            grupos_llamados = [call[0][0] for call in mock_emitir.call_args_list]
            self.assertIn('sgtp_auditoria_admin', grupos_llamados)
            self.assertIn('sgtp_auditoria_jefa', grupos_llamados)
