"""
Tests de Integración y Reglas de Negocio para Modificación de Estudios en Box de Atención.
Valida:
1. Cancelación auditada de estudios en Box.
2. Adición de nuevos estudios solicitados con origen='box'.
3. Sustitución simultánea (cancelar y agregar).
4. Exclusión de estudios cancelados en métricas de Jefa (obtener_resumen_estudios).
5. Validaciones de estado del Box, permisos y regla de integridad (mínimo 1 estudio activo).
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from django.utils import timezone

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.studies import Estudios, TipoMuestra
from app.models.box import Box, EstadoBox
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    EstadoTicket,
    ClasificacionTriage,
    OrigenEstudio,
    EstadoEstudio,
)
from app.services.triage_service import TriageService
from app.services.ticket_service import TicketService


class ModificarEstudiosBoxTestCase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.tecnico1 = Personal.objects.create_user(
            email='tecnico1@hospital.local',
            password='Password123!',
            nombre='Lucas',
            apellidos='Benitez',
            matricula='TEC-1001',
            dni=30111222,
            rol=RolPersonal.BOX
        )

        self.tecnico2 = Personal.objects.create_user(
            email='tecnico2@hospital.local',
            password='Password123!',
            nombre='Ana',
            apellidos='Gomez',
            matricula='TEC-1002',
            dni=30222333,
            rol=RolPersonal.BOX
        )

        self.jefa = Personal.objects.create_user(
            email='jefa@hospital.local',
            password='Password123!',
            nombre='Mariana',
            apellidos='Lopez',
            matricula='BIO-5000',
            dni=22334455,
            rol=RolPersonal.JEFA
        )

        self.admision = Personal.objects.create_user(
            email='admision@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Ruiz',
            dni=25000111,
            rol=RolPersonal.ADMISION
        )

        self.paciente = Paciente.objects.create(
            dni=12345678,
            obra_social='OSDE',
            num_obra_social='OS-998877',
            nombre='Juan',
            apellidos='Perez'
        )

        self.estudio_hemo = Estudios.objects.create(
            codigo_practica='HEM-01',
            nombre='Hemograma Completo',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )

        self.estudio_urea = Estudios.objects.create(
            codigo_practica='BIO-02',
            nombre='Urea',
            tipo_muestra=TipoMuestra.SUERO,
            activo=True
        )

        self.estudio_glucemia = Estudios.objects.create(
            codigo_practica='BIO-01',
            nombre='Glucemia',
            tipo_muestra=TipoMuestra.SUERO,
            activo=True
        )

        self.box2 = Box.objects.create(
            numero=2,
            discapacidad=False,
            estado=EstadoBox.DISPONIBLE
        )

    def _crear_ticket_y_llamar(self):
        """Helper para emitir un ticket con Hemograma y Urea, y llamarlo en Box 2 por tecnico1."""
        ticket = Ticket.objects.create(
            num_totem='Ext-01',
            personal_admision=self.admision,
            paciente=self.paciente,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        TicketEstudios.objects.create(
            ticket=ticket,
            estudio=self.estudio_hemo,
            estado=EstadoEstudio.SOLICITADO,
            origen=OrigenEstudio.ADMISION
        )
        TicketEstudios.objects.create(
            ticket=ticket,
            estudio=self.estudio_urea,
            estado=EstadoEstudio.SOLICITADO,
            origen=OrigenEstudio.ADMISION
        )

        # Llamar en Box 2
        ticket_llamado, asignacion = TriageService.llamar_siguiente_paciente(
            box_id=self.box2.id,
            personal=self.tecnico1
        )
        self.box2.refresh_from_db()
        return ticket_llamado, asignacion

    def test_cancelar_estudio_y_agregar_nuevo_en_box(self):
        """Cancela Urea y agrega Glucemia: verifica auditoría completa y origen."""
        ticket, asignacion = self._crear_ticket_y_llamar()

        ticket_modificado = TriageService.modificar_estudios_atencion(
            box_id=self.box2.id,
            personal=self.tecnico1,
            cancelar_estudios=[
                {"estudio_id": self.estudio_urea.id, "motivo": "No figura en la orden médica"}
            ],
            agregar_estudios=[
                {"estudio_id": self.estudio_glucemia.id, "motivo": "Presente en orden médica física"}
            ]
        )

        estudios_ticket = ticket_modificado.estudios.all()
        self.assertEqual(estudios_ticket.count(), 3)

        # Urea: Cancelado, modificado por tecnico1, asignacion_box vinculada
        te_urea = estudios_ticket.get(estudio=self.estudio_urea)
        self.assertEqual(te_urea.estado, EstadoEstudio.CANCELADO)
        self.assertEqual(te_urea.origen, OrigenEstudio.ADMISION)
        self.assertEqual(te_urea.asignacion_box, asignacion)
        self.assertEqual(te_urea.modificado_por, self.tecnico1)
        self.assertEqual(te_urea.motivo_modificacion, "No figura en la orden médica")
        self.assertIsNotNone(te_urea.fecha_hora_modificacion)

        # Glucemia: Solicitado, origen='box', modificado por tecnico1
        te_glucemia = estudios_ticket.get(estudio=self.estudio_glucemia)
        self.assertEqual(te_glucemia.estado, EstadoEstudio.SOLICITADO)
        self.assertEqual(te_glucemia.origen, OrigenEstudio.BOX)
        self.assertEqual(te_glucemia.asignacion_box, asignacion)
        self.assertEqual(te_glucemia.modificado_por, self.tecnico1)
        self.assertEqual(te_glucemia.motivo_modificacion, "Presente en orden médica física")

        # Hemograma: Intacto
        te_hemo = estudios_ticket.get(estudio=self.estudio_hemo)
        self.assertEqual(te_hemo.estado, EstadoEstudio.SOLICITADO)
        self.assertEqual(te_hemo.origen, OrigenEstudio.ADMISION)

    def test_exclusion_estudios_cancelados_en_metricas_jefa(self):
        """Los estudios con estado='Cancelado' NO deben sumarse en obtener_resumen_estudios."""
        ticket, _ = self._crear_ticket_y_llamar()

        # Antes de cancelar: 2 estudios realizados en la jornada
        resumen_previo = TicketService.obtener_resumen_estudios(fecha_consulta=timezone.now().date())
        self.assertEqual(resumen_previo['total_estudios_realizados'], 2)

        # Cancelar Urea
        TriageService.modificar_estudios_atencion(
            box_id=self.box2.id,
            personal=self.tecnico1,
            cancelar_estudios=[{"estudio_id": self.estudio_urea.id, "motivo": "Error de tipeo"}]
        )

        # Después de cancelar: solo 1 estudio activo (Hemograma)
        resumen_post = TicketService.obtener_resumen_estudios(fecha_consulta=timezone.now().date())
        self.assertEqual(resumen_post['total_estudios_realizados'], 1)

        # Verificar que Urea no aparece en el desglose de prácticas de Jefa
        estudios_nombres = [item['nombre'] for item in resumen_post['estudios']]
        self.assertIn('Hemograma Completo', estudios_nombres)
        self.assertNotIn('Urea', estudios_nombres)

    def test_endpoint_modificar_estudios_api(self):
        """Prueba el endpoint REST POST /app/boxes/{id}/modificar-estudios/."""
        ticket, _ = self._crear_ticket_y_llamar()

        self.client.force_authenticate(user=self.tecnico1)
        url = f"/app/boxes/{self.box2.id}/modificar-estudios/"

        payload = {
            "cancelar_estudios": [
                {"estudio_id": self.estudio_urea.id, "motivo": "No solicitado"}
            ],
            "agregar_estudios": [
                {"estudio_id": self.estudio_glucemia.id, "motivo": "Agregado por orden"}
            ]
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertIn("Estudios del ticket actualizados", data["mensaje"])

        estudios_data = data["ticket"]["estudios"]
        urea_data = next(e for e in estudios_data if e["estudio"] == self.estudio_urea.id)
        self.assertEqual(urea_data["estado"], EstadoEstudio.CANCELADO)
        self.assertEqual(urea_data["motivo_modificacion"], "No solicitado")
        self.assertEqual(urea_data["modificado_por_nombre"], "Benitez, Lucas")

    def test_rechazo_si_se_intentan_cancelar_todos_los_estudios(self):
        """Un ticket no puede quedar con 0 estudios activos."""
        ticket, _ = self._crear_ticket_y_llamar()

        self.client.force_authenticate(user=self.tecnico1)
        url = f"/app/boxes/{self.box2.id}/modificar-estudios/"

        # Intentar cancelar tanto Hemograma como Urea sin agregar ninguno
        payload = {
            "cancelar_estudios": [
                {"estudio_id": self.estudio_hemo.id, "motivo": "Cancelado"},
                {"estudio_id": self.estudio_urea.id, "motivo": "Cancelado"}
            ]
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("debe conservar al menos un estudio", str(response.data))

    def test_rechazo_si_tecnico_ajeno_intenta_modificar_box(self):
        """Un técnico distinto al asignado al Box recibe HTTP 403 Forbidden."""
        ticket, _ = self._crear_ticket_y_llamar()

        # tecnico2 intenta modificar box2 que está asignado a tecnico1
        self.client.force_authenticate(user=self.tecnico2)
        url = f"/app/boxes/{self.box2.id}/modificar-estudios/"

        payload = {
            "cancelar_estudios": [
                {"estudio_id": self.estudio_urea.id, "motivo": "Intruso"}
            ]
        }

        response = self.client.post(url, data=payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
