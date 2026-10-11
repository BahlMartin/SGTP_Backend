"""
Pruebas Unitarias y de Integración para PatientService y Validación DNI vs. Afiliado.
"""
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework.exceptions import ValidationError

from app.models.user import Personal, RolPersonal
from app.models.patient import Paciente
from app.models.studies import Estudios, TipoMuestra
from app.services.patient_service import PatientService


class PatientServiceTestCase(TestCase):
    def setUp(self):
        self.paciente_existente = Paciente.objects.create(
            dni=12345678,
            obra_social='OSDE',
            num_obra_social='OS-998877',
            nombre='Juan',
            apellidos='Perez'
        )

        self.admision_user = Personal.objects.create_user(
            email='admision_test@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Gomez',
            dni=11223344,
            rol=RolPersonal.ADMISION
        )

        self.estudio = Estudios.objects.create(
            codigo_practica='TEST-01',
            nombre='Estudio General',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )

        self.client = APIClient()

    def test_mismo_dni_mismo_afiliado_retorna_paciente_existente(self):
        """Verifica que si coincide DNI y afiliado, no hay error y retorna la instancia existente."""
        paciente = PatientService.resolver_o_crear_paciente_para_ticket({
            'dni': 12345678,
            'num_obra_social': 'OS-998877',
            'nombre': 'Juan',
            'apellidos': 'Perez'
        })
        self.assertEqual(paciente.id_paciente, self.paciente_existente.id_paciente)

    def test_mismo_dni_distinto_afiliado_lanza_error(self):
        """Regla 1: Un paciente con el mismo DNI pero diferente afiliado debe arrojar ValidationError."""
        with self.assertRaises(ValidationError) as context:
            PatientService.resolver_o_crear_paciente_para_ticket({
                'dni': 12345678,
                'num_obra_social': 'OS-111111',  # Diferente al registrado OS-998877
                'nombre': 'Juan',
                'apellidos': 'Perez'
            })
        self.assertIn('paciente_datos', context.exception.detail)
        error_msg = str(context.exception.detail['paciente_datos'])
        self.assertIn("ya se encuentra registrado con el número de afiliado 'OS-998877'", error_msg)

    def test_distinto_dni_mismo_afiliado_lanza_error(self):
        """Regla 2: Un nuevo paciente no puede tener el mismo número de afiliado que otro paciente existente."""
        with self.assertRaises(ValidationError) as context:
            PatientService.resolver_o_crear_paciente_para_ticket({
                'dni': 87654321,  # Nuevo DNI
                'num_obra_social': 'OS-998877',  # Ya pertenece a Juan Perez (12345678)
                'nombre': 'Maria',
                'apellidos': 'Gomez'
            })
        self.assertIn('paciente_datos', context.exception.detail)
        error_msg = str(context.exception.detail['paciente_datos'])
        self.assertIn("ya se encuentra registrado para otro paciente", error_msg)

    def test_nuevo_dni_nuevo_afiliado_crea_paciente(self):
        """Verifica que datos nuevos y consistentes crean un nuevo paciente."""
        nuevo = PatientService.resolver_o_crear_paciente_para_ticket({
            'dni': 99887766,
            'num_obra_social': 'SWISS-445566',
            'nombre': 'Lucas',
            'apellidos': 'Diaz',
            'obra_social': 'Swiss Medical'
        })
        self.assertIsNotNone(nuevo.id_paciente)
        self.assertEqual(nuevo.dni, 99887766)
        self.assertEqual(nuevo.num_obra_social, 'SWISS-445566')

    def test_pacientes_particulares_sin_afiliado_no_colisionan(self):
        """Verifica que pacientes particulares con afiliado vacío no se bloqueen entre sí."""
        p1 = PatientService.resolver_o_crear_paciente_para_ticket({
            'dni': 11112222,
            'num_obra_social': '',
            'nombre': 'Ana',
            'apellidos': 'Ruiz',
            'obra_social': 'Particular'
        })
        p2 = PatientService.resolver_o_crear_paciente_para_ticket({
            'dni': 33334444,
            'num_obra_social': '',
            'nombre': 'Esteban',
            'apellidos': 'Quito',
            'obra_social': 'Particular'
        })
        self.assertNotEqual(p1.id_paciente, p2.id_paciente)

    def test_endpoint_crear_ticket_falla_si_hay_inconsistencia_afiliado(self):
        """Verifica vía POST /app/tickets/ que se rechace el ticket con 400 Bad Request ante inconsistencia."""
        self.client.force_authenticate(user=self.admision_user)

        payload = {
            'num_totem': 'T-999',
            'clasificacion_triage': 'extraccion sin turno',
            'estudios_ids': [self.estudio.id],
            'paciente_datos': {
                'dni': 12345678,
                'num_obra_social': 'OTRO-NUMERO',  # Inconsistente con OS-998877
                'nombre': 'Juan',
                'apellidos': 'Perez',
                'obra_social': 'OSDE'
            }
        }

        response = self.client.post('/app/tickets/', payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('paciente_datos', response.data)
