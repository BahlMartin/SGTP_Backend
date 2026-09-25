"""
Tests para Consolidación de Reportes Diarios, Generación de PDF y Despacho SMTP.
"""
from datetime import timedelta
from django.test import TestCase
from django.utils import timezone
from django.core import mail

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.box import Box, AsignacionesBox
from app.models.ticket import Ticket, ClasificacionTriage, EstadoTicket
from app.services.reports.report_facade import ReportFacade, ReportService
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
            obra_social='OSDE',
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

    def test_validador_formato_fecha_unitario(self):
        """Valida que validar_formato_fecha maneje fechas válidas, nulas y formatos erróneos."""
        from datetime import date
        from rest_framework.exceptions import ValidationError as DRFValidationError
        from app.core.validators import validar_formato_fecha

        # Nulos o vacíos retornan None
        self.assertIsNone(validar_formato_fecha(None))
        self.assertIsNone(validar_formato_fecha(""))
        self.assertIsNone(validar_formato_fecha("   "))

        # Cadena válida
        self.assertEqual(validar_formato_fecha("2026-09-25"), date(2026, 9, 25))

        # Objeto date previo
        hoy = date.today()
        self.assertEqual(validar_formato_fecha(hoy), hoy)

        # Formato inválido lanza DRFValidationError con FECHA_INVALIDA
        with self.assertRaises(DRFValidationError) as ctx:
            validar_formato_fecha("25-09-2026")
        self.assertIn("FECHA_INVALIDA", str(ctx.exception))

    def test_endpoints_reportes_con_fecha_invalida(self):
        """Verifica que los endpoints de reportes respondan 400 con FECHA_INVALIDA ante fechas incorrectas."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.jefa)

        # 1. Metricas diarias
        res_metricas = client.get('/app/reports/metricas-diarias/?fecha=fecha-erronea')
        self.assertEqual(res_metricas.status_code, 400)
        self.assertEqual(res_metricas.data.get('error'), 'FECHA_INVALIDA')

        # 2. Descargar PDF
        res_pdf = client.get('/app/reports/descargar-pdf/?fecha=fecha-erronea')
        self.assertEqual(res_pdf.status_code, 400)
        self.assertEqual(res_pdf.data.get('error'), 'FECHA_INVALIDA')

        # 3. Disparar envío
        res_envio = client.post('/app/reports/disparar-envio/', {'fecha': 'fecha-erronea'}, format='json')
        self.assertEqual(res_envio.status_code, 400)
        self.assertEqual(res_envio.data.get('error'), 'FECHA_INVALIDA')
