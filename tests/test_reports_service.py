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
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    ClasificacionTriage,
    EstadoTicket,
    EstadoEstudio,
    OrigenEstudio,
)
from app.models.studies import Estudios, Seccion, TipoMuestra
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

    def test_franjas_horarias_y_sla_triage(self):
        """Verifica la segmentación por las 3 franjas horarias y el SLA de tiempos de espera."""
        metricas = ReportService.consolidar_metricas_diarias(timezone.now().date())

        self.assertIn('franjas_horarias', metricas)
        self.assertEqual(len(metricas['franjas_horarias']), 3)

        ids_franjas = [f['id'] for f in metricas['franjas_horarias']]
        self.assertEqual(ids_franjas, ['noche', 'manana', 'tarde'])

        # Verificar SLA de triage
        self.assertIn('sla_triage', metricas)
        self.assertGreaterEqual(len(metricas['sla_triage']), 1)
        guardia_sla = next((s for s in metricas['sla_triage'] if s['clasificacion_triage'] == ClasificacionTriage.GUARDIA), None)
        self.assertIsNotNone(guardia_sla)
        self.assertEqual(guardia_sla['total_pacientes'], 1)

    def test_estudios_secciones_y_todas_las_practicas(self):
        """Verifica el cálculo por sección bioquímica, detalle de todas las prácticas e insumos de tubos."""
        # Crear estudios
        est_glucosa = Estudios.objects.create(
            codigo_practica='GLUC-01',
            nombre='Glucemia en Ayunas',
            seccion=Seccion.QUIMICA,
            tipo_muestra=TipoMuestra.SUERO
        )
        est_hemograma = Estudios.objects.create(
            codigo_practica='HEMO-01',
            nombre='Hemograma Completo',
            seccion=Seccion.HEMATOLOGIA,
            tipo_muestra=TipoMuestra.EDTA
        )
        est_orina = Estudios.objects.create(
            codigo_practica='ORI-01',
            nombre='Sedimento Urinario',
            seccion=Seccion.ORINA,
            tipo_muestra=TipoMuestra.ORINA
        )

        # Asociar al ticket
        TicketEstudios.objects.create(
            ticket=self.ticket,
            estudio=est_glucosa,
            estado=EstadoEstudio.REALIZADO,
            origen=OrigenEstudio.ADMISION
        )
        TicketEstudios.objects.create(
            ticket=self.ticket,
            estudio=est_hemograma,
            estado=EstadoEstudio.REALIZADO,
            origen=OrigenEstudio.BOX
        )
        # Estudio cancelado en box
        TicketEstudios.objects.create(
            ticket=self.ticket,
            estudio=est_orina,
            estado=EstadoEstudio.CANCELADO,
            origen=OrigenEstudio.ADMISION,
            motivo_modificacion='Muestra insuficiente'
        )

        metricas = ReportService.consolidar_metricas_diarias(timezone.now().date())

        # El total de estudios realizados excluye el cancelado (2 estudios válidos)
        self.assertEqual(metricas['total_estudios'], 2)

        # Secciones
        self.assertIn('resumen_secciones', metricas)
        secciones_keys = [s['seccion_key'] for s in metricas['resumen_secciones']]
        self.assertIn(Seccion.QUIMICA, secciones_keys)
        self.assertIn(Seccion.HEMATOLOGIA, secciones_keys)

        # Verificar detalle de prácticas en química
        sec_quimica = next(s for s in metricas['resumen_secciones'] if s['seccion_key'] == Seccion.QUIMICA)
        self.assertEqual(len(sec_quimica['practicas']), 1)
        self.assertEqual(sec_quimica['practicas'][0]['codigo'], 'GLUC-01')
        self.assertEqual(sec_quimica['practicas'][0]['nombre'], 'Glucemia en Ayunas')

        # Insumos de tubos
        self.assertIn('insumos_tubos', metricas)
        tipos_tubos = [t['tipo_muestra'] for t in metricas['insumos_tubos']]
        self.assertIn(TipoMuestra.SUERO, tipos_tubos)
        self.assertIn(TipoMuestra.EDTA, tipos_tubos)

        # Auditoría de Box
        self.assertIn('auditoria_box', metricas)
        audit = metricas['auditoria_box']
        self.assertEqual(audit['total_cargados_admision'], 2)
        self.assertEqual(audit['total_agregados_box'], 1)
        self.assertEqual(audit['total_cancelados_box'], 1)
        self.assertEqual(len(audit['motivos_cancelacion']), 1)

    def test_rendimiento_personal_dividido_por_area(self):
        """Verifica la separación de rendimiento entre Admisión y Box de Extracción."""
        metricas = ReportService.consolidar_metricas_diarias(timezone.now().date())

        self.assertIn('rendimiento_admision', metricas)
        self.assertIn('rendimiento_box', metricas)

        # Admisión
        self.assertGreaterEqual(len(metricas['rendimiento_admision']), 1)
        adm = metricas['rendimiento_admision'][0]
        self.assertEqual(adm['personal_admision__id_personal'], self.jefa.id_personal)
        self.assertEqual(adm['pacientes_recepcionados'], 1)

        # Box
        self.assertGreaterEqual(len(metricas['rendimiento_box']), 1)
        bx = metricas['rendimiento_box'][0]
        self.assertEqual(bx['id_personal'], self.jefa.id_personal)
        self.assertEqual(bx['pacientes_atendidos'], 1)
        self.assertIn('promedio_atencion_minutos', bx)

    def test_despacho_por_correo_a_usuario_especificado(self):
        """El reporte debe enviarse vía correo exclusivamente al usuario especificado."""
        historial = ReportService.enviar_reporte_diario_por_email(
            timezone.now().date(),
            destinatarios=[self.jefa.email]
        )

        self.assertIsNotNone(historial)
        self.assertTrue(historial.exitoso)
        self.assertEqual(historial.total_pacientes_atendidos, 1)

        # Verificar correo en outbox de Django
        self.assertEqual(len(mail.outbox), 1)
        email_enviado = mail.outbox[0]
        self.assertIn('Reporte Asistencial Consolidado', email_enviado.subject)
        self.assertEqual([self.jefa.email], email_enviado.to)
        self.assertEqual(len(email_enviado.attachments), 1)
        self.assertTrue(email_enviado.attachments[0][0].endswith('.pdf'))

    def test_despacho_sin_destinatarios_retorna_none(self):
        """Si no se especifican destinatarios, no debe despachar correo y retorna None."""
        historial = ReportService.enviar_reporte_diario_por_email(timezone.now().date())
        self.assertIsNone(historial)
        self.assertEqual(len(mail.outbox), 0)

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

    def test_disparar_envio_exitoso_a_usuario_logeado(self):
        """Verifica que disparar-envio envíe el correo exclusivamente al email del usuario logeado."""
        from rest_framework.test import APIClient
        client = APIClient()
        client.force_authenticate(user=self.jefa)

        res = client.post('/app/reports/disparar-envio/', {}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [self.jefa.email])

    def test_disparar_envio_sin_email_retorna_401(self):
        """Verifica que si el usuario autenticado no tiene email, retorna 401 y no envía correo."""
        from rest_framework.test import APIClient
        client = APIClient()
        # Simular usuario sin email
        self.jefa.email = ''
        client.force_authenticate(user=self.jefa)

        res = client.post('/app/reports/disparar-envio/', {}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data.get('error'), 'EMAIL_NO_ENCONTRADO')
        self.assertEqual(len(mail.outbox), 0)
