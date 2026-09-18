"""
Tests Unitarios e Integración para el Motor de Triage, Cola Multibox y Ventana de 24 Horas.
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.item import Estudios, TipoMuestra
from app.models.triage import (
    Box,
    Ticket,
    TicketEstudios,
    AsignacionesBox,
    EstadoBox,
    EstadoTicket,
    ClasificacionTriage,
    MotivoCierreBox,
)
from app.services.triage_service import TriageService, TicketService


class TriageServiceTestCase(TestCase):
    def setUp(self):
        # Crear personal asistencial
        self.personal_admision = Personal.objects.create_user(
            email='admision1@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Gomez',
            dni=30111222,
            rol=RolPersonal.ADMISION
        )
        self.tecnico_box = Personal.objects.create_user(
            email='box1@hospital.local',
            password='Password123!',
            nombre='Mariana',
            apellidos='Lopez',
            dni=32333444,
            rol=RolPersonal.BOX
        )
        self.jefa = Personal.objects.create_user(
            email='jefa@hospital.local',
            password='Password123!',
            nombre='Beatriz',
            apellidos='Fernandez',
            dni=25555666,
            rol=RolPersonal.JEFA
        )

        # Crear boxes
        # Box 1: Discapacidad / Movilidad reducida
        self.box_1_discapacidad = Box.objects.create(
            numero=1,
            estado=EstadoBox.DISPONIBLE,
            activo=True,
            discapacidad=True
        )
        # Box 2: Box Estándar
        self.box_2_estandar = Box.objects.create(
            numero=2,
            estado=EstadoBox.DISPONIBLE,
            activo=True,
            discapacidad=False
        )

        # Crear pacientes
        self.paciente_1 = Paciente.objects.create(
            dni=10000001,
            num_obra_social='OS-998877',
            nombre='Juan',
            apellidos='Perez'
        )
        self.paciente_2 = Paciente.objects.create(
            dni=10000002,
            num_obra_social='OS-112233',
            nombre='Ana',
            apellidos='Garcia'
        )
        self.paciente_3 = Paciente.objects.create(
            dni=10000003,
            num_obra_social='OS-445566',
            nombre='Esteban',
            apellidos='Quito'
        )

    def test_box_1_prioriza_estrictamente_discapacidad(self):
        """Box 1 debe atender primero tickets de discapacidad antes que Guardia o cola general."""
        ahora = timezone.now()

        # Ticket general de Guardia (Prioridad médica 1 general)
        ticket_guardia = Ticket.objects.create(
            num_totem='G-001',
            personal_admision=self.personal_admision,
            paciente=self.paciente_1,
            clasificacion_triage=ClasificacionTriage.GUARDIA,
            estado=EstadoTicket.PENDIENTE
        )
        # Ticket de Discapacidad (Prioridad médica 3 general)
        ticket_discapacidad = Ticket.objects.create(
            num_totem='D-001',
            personal_admision=self.personal_admision,
            paciente=self.paciente_2,
            clasificacion_triage=ClasificacionTriage.DISCAPACIDAD,
            estado=EstadoTicket.PENDIENTE
        )

        ticket_llamado, asig = TriageService.llamar_siguiente_paciente(
            box_id=self.box_1_discapacidad.id,
            personal=self.tecnico_box
        )

        self.assertIsNotNone(ticket_llamado)
        self.assertEqual(ticket_llamado.id_ticket, ticket_discapacidad.id_ticket)
        self.assertEqual(ticket_llamado.clasificacion_triage, ClasificacionTriage.DISCAPACIDAD)
        self.assertEqual(ticket_llamado.estado, EstadoTicket.EN_ATENCION)
        self.assertEqual(ticket_llamado.box_actual, self.box_1_discapacidad)

    def test_box_1_atiende_cola_general_si_no_hay_discapacidad(self):
        """Si la cola de discapacidad está vacía, Box 1 atiende la cola general respetando prioridades."""
        ticket_guardia = Ticket.objects.create(
            num_totem='G-002',
            personal_admision=self.personal_admision,
            paciente=self.paciente_1,
            clasificacion_triage=ClasificacionTriage.GUARDIA,
            estado=EstadoTicket.PENDIENTE
        )
        ticket_otro = Ticket.objects.create(
            num_totem='O-001',
            personal_admision=self.personal_admision,
            paciente=self.paciente_2,
            clasificacion_triage=ClasificacionTriage.OTRO,
            justificacion_otro='Urgencia administrativa',
            estado=EstadoTicket.PENDIENTE
        )

        ticket_llamado, asig = TriageService.llamar_siguiente_paciente(
            box_id=self.box_1_discapacidad.id,
            personal=self.tecnico_box
        )

        self.assertIsNotNone(ticket_llamado)
        self.assertEqual(ticket_llamado.id_ticket, ticket_guardia.id_ticket)

    def test_box_estandar_excluye_estrictamente_discapacidad(self):
        """Boxes 2..N (discapacidad=False) nunca deben llamar a pacientes con discapacidad."""
        ticket_discapacidad = Ticket.objects.create(
            num_totem='D-002',
            personal_admision=self.personal_admision,
            paciente=self.paciente_2,
            clasificacion_triage=ClasificacionTriage.DISCAPACIDAD,
            estado=EstadoTicket.PENDIENTE
        )

        ticket_llamado, asig = TriageService.llamar_siguiente_paciente(
            box_id=self.box_2_estandar.id,
            personal=self.tecnico_box
        )

        # No debe llamar al ticket de discapacidad
        self.assertIsNone(ticket_llamado)
        self.assertIsNone(asig)

    def test_prioridad_general_y_desempate_fifo(self):
        """Verifica orden médico Guardia > Médicos > Oncología > ... y desempate FIFO por fecha de llegada."""
        ahora = timezone.now()

        # Ticket Oncología llegado a las 10:00
        ticket_onco = Ticket.objects.create(
            num_totem='ONCO-01',
            personal_admision=self.personal_admision,
            paciente=self.paciente_1,
            clasificacion_triage=ClasificacionTriage.ONCOLOGIA,
            estado=EstadoTicket.PENDIENTE
        )
        Ticket.objects.filter(pk=ticket_onco.pk).update(fecha_hora_admision=ahora - timedelta(minutes=30))

        # Ticket Guardia llegado a las 10:20 (llegó después pero tiene mayor peso médico)
        ticket_guardia = Ticket.objects.create(
            num_totem='GUARDIA-01',
            personal_admision=self.personal_admision,
            paciente=self.paciente_2,
            clasificacion_triage=ClasificacionTriage.GUARDIA,
            estado=EstadoTicket.PENDIENTE
        )
        Ticket.objects.filter(pk=ticket_guardia.pk).update(fecha_hora_admision=ahora - timedelta(minutes=10))

        # Box estándar llama
        ticket_1, _ = TriageService.llamar_siguiente_paciente(box_id=self.box_2_estandar.id, personal=self.tecnico_box)
        self.assertEqual(ticket_1.id_ticket, ticket_guardia.id_ticket)

        # Cierra atención y llama siguiente
        TriageService.cerrar_atencion(box_id=self.box_2_estandar.id, personal=self.tecnico_box)

        ticket_2, _ = TriageService.llamar_siguiente_paciente(box_id=self.box_2_estandar.id, personal=self.tecnico_box)
        self.assertEqual(ticket_2.id_ticket, ticket_onco.id_ticket)

    def test_ciclo_completo_cerrar_atencion(self):
        """Verifica la finalización de atención, actualización de estados e historial de asignaciones."""
        ticket = Ticket.objects.create(
            num_totem='E-001',
            personal_admision=self.personal_admision,
            paciente=self.paciente_1,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )

        ticket_llamado, asig = TriageService.llamar_siguiente_paciente(
            box_id=self.box_2_estandar.id,
            personal=self.tecnico_box
        )
        self.assertEqual(asig.box, self.box_2_estandar)
        self.assertIsNone(asig.fecha_hora_final)

        # Cerrar atención
        asig_cerrada = TriageService.cerrar_atencion(
            box_id=self.box_2_estandar.id,
            personal=self.tecnico_box,
            motivo_cierre=MotivoCierreBox.FINALIZADO
        )
        self.assertIsNotNone(asig_cerrada.fecha_hora_final)
        self.assertEqual(asig_cerrada.motivo_cierre, MotivoCierreBox.FINALIZADO)

        # Verificar estados
        self.box_2_estandar.refresh_from_db()
        ticket.refresh_from_db()
        self.assertEqual(self.box_2_estandar.estado, EstadoBox.DISPONIBLE)
        self.assertEqual(ticket.estado, EstadoTicket.FINALIZADO)
        self.assertIsNone(ticket.box_actual)

    def test_ventana_de_24_horas_inmutabilidad(self):
        """Verifica que un ticket mayor a 24h es inmutable y que solo Jefa puede editar dentro de 24h."""
        ticket = Ticket.objects.create(
            num_totem='T-24H',
            personal_admision=self.personal_admision,
            paciente=self.paciente_1,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )

        # Edición dentro de 24h por Admisión -> debe fallar (PermissionDenied)
        with self.assertRaises(PermissionDenied):
            TicketService.actualizar_ticket(
                ticket_id=ticket.pk,
                usuario=self.personal_admision,
                datos={'num_totem': 'T-MODIFICADO'}
            )

        # Edición dentro de 24h por Jefa -> debe tener éxito
        ticket_editado = TicketService.actualizar_ticket(
            ticket_id=ticket.pk,
            usuario=self.jefa,
            datos={'num_totem': 'T-JEFA-OK'}
        )
        self.assertEqual(ticket_editado.num_totem, 'T-JEFA-OK')

        # Simular ticket emitido hace 25 horas
        hace_25h = timezone.now() - timedelta(hours=25)
        Ticket.objects.filter(pk=ticket.pk).update(fecha_hora_admision=hace_25h)
        ticket.refresh_from_db()

        # Edición posterior a 24 horas por Jefa -> debe rechazar por inmutabilidad
        with self.assertRaises(ValidationError) as exc:
            TicketService.actualizar_ticket(
                ticket_id=ticket.pk,
                usuario=self.jefa,
                datos={'num_totem': 'T-INTENTO-TARDIO'}
            )
        self.assertIn("superado la ventana límite de 24 horas", str(exc.exception))
