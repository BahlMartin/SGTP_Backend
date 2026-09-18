"""
Tests para Consolidación de Reportes Diarios, Generación de PDF y Despacho SMTP.
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core import mail

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.triage import Box, Ticket, AsignacionesBox, ClasificacionTriage, EstadoTicket
from app.services.reports_service import ReportService
from app.models.report import HistorialReporteDiario


class ReportsServiceTestCase(TestCase):
    def setUp(self):
        self.jefa = Personal.objects.create_user(
            email='jefa_reportes@hospital.local',
            password='Password123!',
            nombre='Marta',
            apellidos='Suarez',
            dni=21111222,
            rol=RolPersonal.JEFA
        )
        self.secretaria = Personal.objects.create_user(
            email='secretaria@hospital.local',
            password='Password123!',
            nombre='Lucia',
            apellidos='Navarro',
            dni=28888999,
            rol=RolPersonal.SECRETARIA
        )
        self.paciente = Paciente.objects.create(
            dni=45000111,
            num_obra_social='OSDE-5544',
            nombre='Gonzalo',
            apellidos='Morales'
        )
        self.box = Box.objects.create(numero=1, activo=True)

        # Crear ticket atendido
        self.ticket = Ticket.objects.create(
            num_totem='R-100',
            personal_admision=self.jefa,
            paciente=self.paciente,
            clasificacion_triage=ClasificacionTriage.GUARDIA,
            estado=EstadoTicket.FINALIZADO
        )
        # Asignación asociada
        self.asig = AsignacionesBox.objects.create(
            box=self.box,
            personal=self.jefa,
            ticket=self.ticket,
            fecha_hora_final=timezone.now()
        )

    def test_consolidacion_de_metricas(self):
        """Verifica el cálculo de métricas de flujo asistencial."""
        metricas = ReportService.consolidar_metricas_diarias(timezone.now().date())
        self.assertEqual(metricas['total_emitidos'], 1)
        self.assertEqual(metricas['total_atendidos'], 1)
        self.assertGreaterEqual(len(metricas['distribucion_triage']), 1)
        self.assertEqual(metricas['distribucion_triage'][0]['clasificacion_triage'], ClasificacionTriage.GUARDIA)

    def test_generacion_de_pdf_valido(self):
        """El reporte PDF debe compilarse en memoria y ser un archivo PDF binario válido."""
        metricas = ReportService.consolidar_metricas_diarias(timezone.now().date())
        pdf_bytes = ReportService.generar_pdf_reporte(metricas)

        self.assertIsInstance(pdf_bytes, bytes)
        self.assertGreater(len(pdf_bytes), 1000)
        # Todo PDF válido comienza con la firma mágica %PDF-
        self.assertTrue(pdf_bytes.startswith(b'%PDF-'))

    def test_despacho_por_correo_a_jefa_y_secretaria(self):
        """El reporte debe enviarse vía correo a las cuentas con rol Jefa y Secretaria."""
        historial = ReportService.enviar_reporte_diario_por_email(timezone.now().date())

        self.assertTrue(historial.exitoso)
        self.assertEqual(historial.total_pacientes_atendidos, 1)

        # Verificar correo en outbox de Django
        self.assertEqual(len(mail.outbox), 1)
        email_enviado = mail.outbox[0]
        self.assertIn('Reporte Asistencial Consolidado', email_enviado.subject)
        self.assertIn('jefa_reportes@hospital.local', email_enviado.to)
        self.assertIn('secretaria@hospital.local', email_enviado.to)
        self.assertEqual(len(email_enviado.attachments), 1)
        self.assertTrue(email_enviado.attachments[0][0].endswith('.pdf'))
