"""
Tests unitarios y de integración para el cálculo de fecha estimada de retiro
según demora en horas de los estudios y días hábiles (L-V), y gestión de demoras por Jefa.
"""
from datetime import timedelta, datetime, timezone as dt_tz
from rest_framework import status
from rest_framework.test import APITestCase

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.box import Box, EstadoBox, MotivoCierreBox
from app.models.studies import Estudios, Seccion, TipoMuestra
from app.models.ticket import Ticket, TicketEstudios, EstadoTicket, EstadoEstudio, ClasificacionTriage
from app.services.triage_service import TriageService


class DemoraEstudiosRetiroTestCase(APITestCase):
    def setUp(self):
        # Usuarios
        self.jefa = Personal.objects.create_user(
            email='jefa_demoras@sgtp.hospital.gob.ar',
            password='Password123!',
            nombre='Marta',
            apellidos='Gomez',
            dni=22334455,
            rol=RolPersonal.JEFA,
            activo=True
        )
        self.tecnico_box = Personal.objects.create_user(
            email='tecnico_box_demoras@sgtp.hospital.gob.ar',
            password='Password123!',
            nombre='Lucas',
            apellidos='Perez',
            dni=33445566,
            rol=RolPersonal.BOX,
            matricula='TEC-9921',
            activo=True
        )

        # Paciente
        self.paciente = Paciente.objects.create(
            nombre='Carlos',
            apellidos='Fernandez',
            dni=14556677,
            obra_social='IOMA'
        )

        # Estudios con diferentes demoras
        self.hemograma = Estudios.objects.create(
            codigo_practica='HEMO-01',
            nombre='Hemograma Completo',
            seccion=Seccion.HEMATOLOGIA,
            tipo_muestra=TipoMuestra.EDTA,
            demora_horas=24,
            activo=True
        )
        self.urocultivo = Estudios.objects.create(
            codigo_practica='UROC-01',
            nombre='Urocultivo con Antibiograma',
            seccion=Seccion.BACTEREOLOGIA,
            tipo_muestra=TipoMuestra.ORINA,
            demora_horas=72,
            activo=True
        )

        # Box
        self.box = Box.objects.create(
            numero=1,
            estado=EstadoBox.DISPONIBLE,
            personal_actual=self.tecnico_box
        )

    def test_calculo_demora_toma_maximo_estudio_efectivo(self):
        """Verifica que el cálculo tome el estudio con mayor demora entre los no cancelados."""
        ticket = Ticket.objects.create(
            num_totem='Ext-01',
            paciente=self.paciente,
            personal_admision=self.jefa,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        TicketEstudios.objects.create(ticket=ticket, estudio=self.hemograma, estado=EstadoEstudio.REALIZADO)
        TicketEstudios.objects.create(ticket=ticket, estudio=self.urocultivo, estado=EstadoEstudio.REALIZADO)

        # Base: un martes a las 10:00 (weekday = 1)
        # Martes 2026-10-27 10:00:00 UTC
        fecha_base = datetime(2026, 10, 27, 10, 0, 0, tzinfo=dt_tz.utc)
        fecha_entrega, max_horas, mayor = TriageService.calcular_fecha_estimada_entrega(ticket, fecha_base=fecha_base)

        self.assertEqual(max_horas, 72)
        self.assertEqual(mayor, 'Urocultivo con Antibiograma')
        # Martes 10:00 + 72hs = Viernes 10:00 (weekday = 4, día hábil)
        self.assertEqual(fecha_entrega, fecha_base + timedelta(hours=72))
        self.assertEqual(fecha_entrega.weekday(), 4)

    def test_calculo_demora_corre_al_lunes_si_cae_fin_de_semana(self):
        """Si la fecha de entrega cae sábado o domingo, debe posponerse al lunes siguiente."""
        ticket = Ticket.objects.create(
            num_totem='Ext-02',
            paciente=self.paciente,
            personal_admision=self.jefa,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        TicketEstudios.objects.create(ticket=ticket, estudio=self.hemograma, estado=EstadoEstudio.REALIZADO)

        # Base: Viernes a las 10:00 (2026-10-30 10:00:00 UTC, weekday = 4)
        fecha_base = datetime(2026, 10, 30, 10, 0, 0, tzinfo=dt_tz.utc)
        # 24 hs después cae sábado 2026-10-31 10:00 (weekday = 5)
        # Al correr a lunes -> Lunes 2026-11-02 10:00 (weekday = 0)
        fecha_entrega, max_horas, _ = TriageService.calcular_fecha_estimada_entrega(ticket, fecha_base=fecha_base)

        self.assertEqual(max_horas, 24)
        self.assertEqual(fecha_entrega.weekday(), 0) # Lunes
        self.assertEqual(fecha_entrega, datetime(2026, 11, 2, 10, 0, 0, tzinfo=dt_tz.utc))

    def test_cerrar_atencion_box_guarda_fecha_entrega_y_retorna_ticket(self):
        """Al cerrar atención en Box, se fija fecha_estimada_entrega y se devuelve el ticket en la respuesta."""
        self.client.force_authenticate(user=self.tecnico_box)

        # Llamar paciente
        ticket = Ticket.objects.create(
            num_totem='Ext-03',
            paciente=self.paciente,
            personal_admision=self.jefa,
            clasificacion_triage=ClasificacionTriage.EXTRACCION_CON_TURNO,
            estado=EstadoTicket.PENDIENTE
        )
        TicketEstudios.objects.create(ticket=ticket, estudio=self.urocultivo, estado=EstadoEstudio.SOLICITADO)

        TriageService.llamar_siguiente_paciente(box_id=self.box.id, personal=self.tecnico_box, ticket_id=ticket.pk)

        # Cerrar atención
        response = self.client.post(
            f'/app/boxes/{self.box.id}/cerrar-atencion/',
            {'motivo_cierre': MotivoCierreBox.FINALIZADO, 'observaciones_cierre': 'Extracción exitosa'}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('ticket', response.data)
        ticket_data = response.data['ticket']
        self.assertIsNotNone(ticket_data)
        self.assertIsNotNone(ticket_data['fecha_estimada_entrega'])
        self.assertEqual(ticket_data['demora_horas_max'], 72)
        self.assertEqual(ticket_data['estudio_mayor_demora'], 'Urocultivo con Antibiograma')

    def test_jefa_puede_actualizar_horas_demora_de_estudio(self):
        """La Jefa de Laboratorio puede modificar las horas de demora de un estudio del catálogo."""
        self.client.force_authenticate(user=self.jefa)

        response = self.client.patch(
            f'/app/studies/{self.urocultivo.id}/',
            {'demora_horas': 48}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.urocultivo.refresh_from_db()
        self.assertEqual(self.urocultivo.demora_horas, 48)

