from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from django.test import TestCase

from app.models.reception import TurnoRecepcion, EstadoTurnoRecepcion
from app.services.reception_service import ReceptionService


class TestReceptionTotem(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_emitir_turno_secuencial_diario(self):
        """Verifica que los números de llamado se generen secuencialmente por prefijo."""
        t1 = ReceptionService.emitir_turno('38472910', 'Ext')
        self.assertEqual(t1.numero_llamado, 'Ext-01')
        self.assertEqual(t1.categoria_label, 'Extracción')
        self.assertEqual(t1.estado, EstadoTurnoRecepcion.PENDIENTE)

        t2 = ReceptionService.emitir_turno('38472911', 'Ext')
        self.assertEqual(t2.numero_llamado, 'Ext-02')

        # Prefijo diferente inicia su propia secuencia
        t3 = ReceptionService.emitir_turno('38472912', 'G')
        self.assertEqual(t3.numero_llamado, 'G-01')

    def test_totem_endpoint_publico(self):
        """El endpoint del tótem debe ser accesible sin autenticación."""
        response = self.client.post('/app/turnos-recepcion/totem/', {
            'dni': '39111222',
            'prefijo': 'Med'
        }, format='json')

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['numero_llamado'], 'Med-01')
        self.assertEqual(response.data['dni'], '39111222')

    def test_llamar_y_cancelar_turno(self):
        """Verifica los estados de convocatoria y cancelación."""
        turno = ReceptionService.emitir_turno('40123456', 'Csl')
        
        # Llamar paciente
        turno_llamado = ReceptionService.llamar_turno(turno.id)
        self.assertEqual(turno_llamado.estado, EstadoTurnoRecepcion.EN_ATENCION)

        # Cancelar paciente
        turno_cancelado = ReceptionService.cancelar_turno(turno.id, motivo='No respondió')
        self.assertEqual(turno_cancelado.estado, EstadoTurnoRecepcion.CANCELADO)
        self.assertEqual(turno_cancelado.motivo_cancelacion, 'No respondió')
