"""
Tests de Integración para los Endpoints REST Independientes de Tickets y Boxes.
Valida /app/tickets/, /app/boxes/ y la eliminación definitiva de /app/triage/.
"""
from django.test import TestCase
from django.urls import resolve, Resolver404
from rest_framework.test import APIClient
from rest_framework import status

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.studies import Estudios, TipoMuestra
from app.models.box import Box, EstadoBox, MotivoCierreBox
from app.models.ticket import Ticket, EstadoTicket, ClasificacionTriage


class TicketsBoxesEndpointsTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        # Usuario con rol JEFA (sin restricción horaria)
        self.jefa_user = Personal.objects.create_user(
            email='jefa_endpoints@hospital.local',
            password='Password123!',
            nombre='Mariana',
            apellidos='Lopez',
            dni=22334455,
            rol=RolPersonal.JEFA
        )

        self.box_user = Personal.objects.create_user(
            email='box_tecnico@hospital.local',
            password='Password123!',
            nombre='Lucas',
            apellidos='Benitez',
            dni=33445566,
            rol=RolPersonal.BOX
        )

        self.paciente = Paciente.objects.create(
            dni=12345678,
            obra_social='OSDE',
            num_obra_social='OS-998877',
            nombre='Juan',
            apellidos='Perez'
        )

        self.estudio = Estudios.objects.create(
            codigo_practica='HEMO-TEST',
            nombre='Hemograma Test',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )

        self.box1 = Box.objects.create(numero=1, discapacidad=True, estado=EstadoBox.DISPONIBLE)
        self.box2 = Box.objects.create(numero=2, discapacidad=False, estado=EstadoBox.DISPONIBLE)

    def test_rutas_antiguas_triage_no_existen(self):
        """Verifica que las rutas /app/triage/ ya no existen y fallan al resolver."""
        with self.assertRaises(Resolver404):
            resolve('/app/triage/boxes/')

        with self.assertRaises(Resolver404):
            resolve('/app/triage/tickets/')

    def test_rutas_nuevas_resuelven(self):
        """Verifica que las nuevas rutas independientes resuelven a sus ViewSets correspondientes."""
        match_tickets = resolve('/app/tickets/')
        self.assertEqual(match_tickets.func.cls.__name__, 'TicketViewSet')

        match_boxes = resolve('/app/boxes/')
        self.assertEqual(match_boxes.func.cls.__name__, 'BoxViewSet')

    def test_creacion_y_cola_tickets_endpoints(self):
        """Prueba creación de ticket y consulta de cola de espera en /app/tickets/."""
        self.client.force_authenticate(user=self.jefa_user)

        # 1. Crear ticket
        payload = {
            'num_totem': 'T-100',
            'paciente': self.paciente.pk,
            'clasificacion_triage': ClasificacionTriage.GUARDIA,
            'estudios_ids': [self.estudio.id],
        }
        create_resp = self.client.post('/app/tickets/', payload, format='json')
        self.assertEqual(create_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(create_resp.data['clasificacion_triage'], ClasificacionTriage.GUARDIA)

        ticket_id = create_resp.data['id_ticket']

        # 2. Consultar cola de espera
        cola_resp = self.client.get('/app/tickets/cola-espera/')
        self.assertEqual(cola_resp.status_code, status.HTTP_200_OK)
        ids_en_cola = [t['id_ticket'] for t in cola_resp.data]
        self.assertIn(ticket_id, ids_en_cola)

    def test_operativa_boxes_endpoints(self):
        """Prueba estado general, llamar siguiente y cerrar atención en /app/boxes/."""
        self.client.force_authenticate(user=self.jefa_user)

        # Crear un ticket en espera
        ticket = Ticket.objects.create(
            num_totem='T-200',
            paciente=self.paciente,
            personal_admision=self.jefa_user,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )

        # 1. Estado general
        estado_resp = self.client.get('/app/boxes/estado-general/')
        self.assertEqual(estado_resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(estado_resp.data), 2)

        # 2. Llamar siguiente paciente desde Box 2
        llamar_resp = self.client.post(f'/app/boxes/{self.box2.id}/llamar-siguiente/')
        self.assertEqual(llamar_resp.status_code, status.HTTP_200_OK)
        self.assertIsNotNone(llamar_resp.data['ticket'])
        self.assertEqual(llamar_resp.data['ticket']['id_ticket'], str(ticket.id_ticket))

        # 3. Cerrar atención
        cerrar_payload = {
            'motivo_cierre': MotivoCierreBox.FINALIZADO
        }
        cerrar_resp = self.client.post(f'/app/boxes/{self.box2.id}/cerrar-atencion/', cerrar_payload, format='json')
        self.assertEqual(cerrar_resp.status_code, status.HTTP_200_OK)

        # 4. Asignaciones históricas
        asig_resp = self.client.get('/app/boxes/asignaciones/')
        self.assertEqual(asig_resp.status_code, status.HTTP_200_OK)
        self.assertGreaterEqual(len(asig_resp.data), 1)

    def test_rendimiento_personal_endpoint(self):
        """Valida endpoint de rendimiento de personal con permisos exclusivos de Jefa/Admin."""
        # 1. Denegar a usuario no autenticado
        self.client.force_authenticate(user=None)
        resp_anon = self.client.get('/app/tickets/rendimiento-personal/')
        self.assertIn(resp_anon.status_code, [status.HTTP_401_UNAUTHORIZED, status.HTTP_403_FORBIDDEN])

        # 2. Denegar a usuario sin rol Jefa/Admin (rol BOX)
        self.client.force_authenticate(user=self.box_user)
        resp_forbid = self.client.get('/app/tickets/rendimiento-personal/')
        self.assertEqual(resp_forbid.status_code, status.HTTP_403_FORBIDDEN)

        # 3. Permitir a Jefa
        self.client.force_authenticate(user=self.jefa_user)
        # Emitir un ticket por jefa_user
        Ticket.objects.create(
            num_totem='T-501',
            paciente=self.paciente,
            personal_admision=self.jefa_user,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )

        resp_ok = self.client.get('/app/tickets/rendimiento-personal/')
        self.assertEqual(resp_ok.status_code, status.HTTP_200_OK)
        self.assertIn('fecha', resp_ok.data)
        self.assertIn('personal', resp_ok.data)
        self.assertIn('tickets_por_personal', resp_ok.data)
        # Comprobar que en tickets_por_personal jefa_user tenga al menos 1
        self.assertGreaterEqual(resp_ok.data['tickets_por_personal'].get(str(self.jefa_user.id_personal), 0), 1)

    def test_resumen_estudios_endpoint(self):
        """Valida endpoint de resumen de estudios con conteo, top y búsqueda por nombre."""
        # 1. Denegar sin rol Jefa
        self.client.force_authenticate(user=self.box_user)
        resp_forbid = self.client.get('/app/tickets/resumen-estudios/')
        self.assertEqual(resp_forbid.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Permitir con rol Jefa y verificar conteo
        self.client.force_authenticate(user=self.jefa_user)
        ticket = Ticket.objects.create(
            num_totem='T-601',
            paciente=self.paciente,
            personal_admision=self.jefa_user,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        from app.models.ticket import TicketEstudios
        TicketEstudios.objects.create(ticket=ticket, estudio=self.estudio)

        # Consulta general
        resp_ok = self.client.get('/app/tickets/resumen-estudios/')
        self.assertEqual(resp_ok.status_code, status.HTTP_200_OK)
        self.assertIn('estudios', resp_ok.data)
        self.assertGreaterEqual(resp_ok.data['total_estudios_realizados'], 1)

        # Búsqueda específica con parámetro search
        resp_search = self.client.get('/app/tickets/resumen-estudios/?search=Hemograma')
        self.assertEqual(resp_search.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_search.data['estudios']), 1)
        self.assertEqual(resp_search.data['estudios'][0]['nombre'], self.estudio.nombre)
        self.assertEqual(resp_search.data['estudios'][0]['total'], 1)

        # Búsqueda que no coincide
        resp_empty = self.client.get('/app/tickets/resumen-estudios/?search=EstudioInexistente999')
        self.assertEqual(resp_empty.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp_empty.data['estudios']), 0)

    def test_tickets_por_personal_endpoint(self):
        """Valida endpoint /app/tickets/personal/<id>/ para admisión y para técnico en box."""
        # 1. Denegar a usuario sin rol Jefa/Admin
        self.client.force_authenticate(user=self.box_user)
        resp_forbid = self.client.get(f'/app/tickets/personal/{self.jefa_user.id_personal}/')
        self.assertEqual(resp_forbid.status_code, status.HTTP_403_FORBIDDEN)

        # 2. Permitir con rol Jefa
        self.client.force_authenticate(user=self.jefa_user)

        # Crear operador de admisión
        admision_user = Personal.objects.create_user(
            email='admision_test@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Gomez',
            dni=44556677,
            rol=RolPersonal.ADMISION
        )

        ticket_adm1 = Ticket.objects.create(
            num_totem='T-701',
            paciente=self.paciente,
            personal_admision=admision_user,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        ticket_adm2 = Ticket.objects.create(
            num_totem='T-702',
            paciente=self.paciente,
            personal_admision=admision_user,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )

        # Consultar tickets del operador de admisión
        resp_adm = self.client.get(f'/app/tickets/personal/{admision_user.id_personal}/')
        self.assertEqual(resp_adm.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_adm.data['tipo'], 'admision')
        self.assertEqual(resp_adm.data['total'], 2)
        self.assertEqual(len(resp_adm.data['tickets']), 2)
        # Ordenado del último al menor (ticket_adm2 primero)
        self.assertEqual(resp_adm.data['tickets'][0]['num_totem'], 'T-702')
        self.assertEqual(resp_adm.data['tickets'][1]['num_totem'], 'T-701')

        # Crear atención en Box para el técnico box_user
        from app.models.box import AsignacionesBox
        asig_box = AsignacionesBox.objects.create(
            box=self.box1,
            personal=self.box_user,
            ticket=ticket_adm1
        )

        # Consultar tickets del técnico de box
        resp_box = self.client.get(f'/app/tickets/personal/{self.box_user.id_personal}/')
        self.assertEqual(resp_box.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_box.data['tipo'], 'box')
        self.assertGreaterEqual(resp_box.data['total'], 1)
        self.assertEqual(resp_box.data['tickets'][0]['num_totem'], 'T-701')

    def test_logout_libera_box_y_mantiene_estado_disponible(self):
        """
        Al cerrar sesión el usuario asignado al box:
        - Box.personal_actual pasa a None.
        - Box.estado permanece/pasa a 'Disponible'.
        - El endpoint GET /app/boxes/ retorna personal_actual=null y personal_actual_detalle=null.
        """
        # Asignar técnico al box 1
        self.box1.personal_actual = self.box_user
        self.box1.estado = EstadoBox.DISPONIBLE
        self.box1.save(update_fields=['personal_actual', 'estado'])

        self.client.force_authenticate(user=self.box_user)

        # Verificar que antes del logout el box tiene asignado al usuario
        resp_pre = self.client.get(f'/app/boxes/{self.box1.id}/')
        self.assertEqual(resp_pre.status_code, status.HTTP_200_OK)
        self.assertEqual(resp_pre.data['personal_actual'], self.box_user.id_personal)
        self.assertIsNotNone(resp_pre.data['personal_actual_detalle'])

        # Ejecutar logout
        resp_logout = self.client.post('/app/auth/logout/')
        self.assertEqual(resp_logout.status_code, status.HTTP_200_OK)

        # Refrescar box desde BD
        self.box1.refresh_from_db()
        self.assertIsNone(self.box1.personal_actual)
        self.assertEqual(self.box1.estado, EstadoBox.DISPONIBLE)

        # Verificar que el endpoint de boxes devuelve personal_actual en null
        self.client.force_authenticate(user=self.jefa_user)
        resp_post = self.client.get(f'/app/boxes/{self.box1.id}/')
        self.assertEqual(resp_post.status_code, status.HTTP_200_OK)
        self.assertIsNone(resp_post.data['personal_actual'])
        self.assertIsNone(resp_post.data['personal_actual_detalle'])
        self.assertEqual(resp_post.data['estado'], EstadoBox.DISPONIBLE)



