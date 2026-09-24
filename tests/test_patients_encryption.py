"""
Tests de Field-Level Encryption (FLE) con Fernet y Borrado Lógico en Pacientes.
"""
from django.test import TestCase
from django.db import connection
from django.core.exceptions import ValidationError
from app.models.patient import Paciente


class PatientsFLETestCase(TestCase):
    def setUp(self):
        self.paciente = Paciente.objects.create(
            dni=40123456,
            obra_social='Swiss Medical',
            num_obra_social='SWISS-889900',
            nombre='Valentina',
            apellidos='Alvarez'
        )

    def test_cifrado_en_reposo_y_descifrado_transparente(self):
        """Verifica que en la base de datos reside ciphertext Fernet y el ORM descifra en plano."""
        # Consulta en bruto directa a SQL para verificar lo almacenado físicamente en la BD
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT num_obra_social, nombre, apellidos FROM sgtp_paciente WHERE id_paciente = %s",
                [self.paciente.id_paciente]
            )
            raw_os, raw_nom, raw_ape = cursor.fetchone()

        # En la base de datos NO debe existir el texto plano
        self.assertNotEqual(raw_os, 'SWISS-889900')
        self.assertNotEqual(raw_nom, 'Valentina')
        self.assertNotEqual(raw_ape, 'Alvarez')

        # Los tokens de Fernet inician típicamente con 'gAAAAA'
        self.assertTrue(raw_os.startswith('gAAAAA'))
        self.assertTrue(raw_nom.startswith('gAAAAA'))
        self.assertTrue(raw_ape.startswith('gAAAAA'))

        # A través del ORM de Django se recupera descifrado de manera transparente
        paciente_recuperado = Paciente.objects.get(id_paciente=self.paciente.id_paciente)
        self.assertEqual(paciente_recuperado.obra_social, 'Swiss Medical')
        self.assertEqual(paciente_recuperado.num_obra_social, 'SWISS-889900')
        self.assertEqual(paciente_recuperado.nombre, 'Valentina')
        self.assertEqual(paciente_recuperado.apellidos, 'Alvarez')

    def test_validacion_nombres_sin_numeros_ni_simbolos(self):
        """No debe permitir nombres o apellidos con números o símbolos especiales."""
        p_invalido = Paciente(
            dni=40999888,
            obra_social='OSDE',
            num_obra_social='OS-001',
            nombre='Juan123',
            apellidos='Perez'
        )
        with self.assertRaises(ValidationError):
            p_invalido.full_clean()

        p_invalido_simbolo = Paciente(
            dni=40999889,
            obra_social='OSDE',
            num_obra_social='OS-002',
            nombre='Juan',
            apellidos='Perez@#$%^'
        )
        with self.assertRaises(ValidationError):
            p_invalido_simbolo.full_clean()

    def test_validacion_longitud_minima(self):
        """El nombre y apellido deben tener al menos 2 caracteres alfabéticos."""
        p_corto = Paciente(
            dni=40999890,
            obra_social='OSDE',
            num_obra_social='OS-003',
            nombre='A',
            apellidos='Perez'
        )
        with self.assertRaises(ValidationError):
            p_corto.full_clean()

    def test_borrado_logico_soft_delete(self):
        """El borrado debe marcar is_deleted=True sin destruir físicamente el registro."""
        paciente_id = self.paciente.id_paciente
        self.paciente.delete()

        # No debe aparecer en el manager habitual
        self.assertFalse(Paciente.objects.filter(id_paciente=paciente_id).exists())

        # Debe conservarse en all_objects con is_deleted=True
        paciente_eliminado = Paciente.all_objects.get(id_paciente=paciente_id)
        self.assertTrue(paciente_eliminado.is_deleted)

        # Restaurar
        paciente_eliminado.restore()
        self.assertTrue(Paciente.objects.filter(id_paciente=paciente_id).exists())
