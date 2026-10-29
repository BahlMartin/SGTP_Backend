"""
Pruebas unitarias para Configuración de SLA de Triage y Tiempos Objetivos de Espera.
"""
from rest_framework import status
from rest_framework.test import APITestCase
from django.urls import reverse

from app.models.user import Personal, RolPersonal
from app.models.ticket import ConfiguracionSlaTriage


class SlaConfigurationTests(APITestCase):
    def setUp(self):
        # Crear usuarios para control de permisos
        self.jefa = Personal.objects.create_user(
            dni='11111111',
            email='jefa@hospital.com',
            nombre='Jefa',
            apellidos='Laboratorio',
            rol=RolPersonal.JEFA,
            password='Password123!',
            activo=True
        )
        self.tecnico = Personal.objects.create_user(
            dni='22222222',
            email='tecnico@hospital.com',
            nombre='Tecnico',
            apellidos='Box',
            rol=RolPersonal.BOX,
            password='Password123!',
            activo=True
        )

        # Poblar configuración por defecto
        ConfiguracionSlaTriage.get_or_seed_defaults()
        self.url = '/app/sla/'

    def test_seed_defaults_creates_all_categories(self):
        configs = ConfiguracionSlaTriage.objects.all()
        self.assertEqual(configs.count(), 7)
        guardia = configs.filter(clasificacion_triage='guardia').first()
        self.assertIsNotNone(guardia)
        self.assertEqual(guardia.tiempo_objetivo_minutos, 5)

    def test_list_sla_authenticated(self):
        self.client.force_authenticate(user=self.tecnico)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data if isinstance(response.data, list) else response.data.get('results', [])
        self.assertEqual(len(results), 7)
        self.assertIn('tiempo_objetivo_minutos', results[0])
        self.assertIn('nombre_display', results[0])

    def test_update_sla_as_jefa(self):
        self.client.force_authenticate(user=self.jefa)
        guardia = ConfiguracionSlaTriage.objects.get(clasificacion_triage='guardia')
        detail_url = f"{self.url}{guardia.id}/"

        response = self.client.patch(detail_url, {'tiempo_objetivo_minutos': 8})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        guardia.refresh_from_db()
        self.assertEqual(guardia.tiempo_objetivo_minutos, 8)

    def test_update_sla_forbidden_for_box_staff(self):
        self.client.force_authenticate(user=self.tecnico)
        guardia = ConfiguracionSlaTriage.objects.get(clasificacion_triage='guardia')
        detail_url = f"{self.url}{guardia.id}/"

        response = self.client.patch(detail_url, {'tiempo_objetivo_minutos': 10})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_update_sla_validation_range(self):
        self.client.force_authenticate(user=self.jefa)
        guardia = ConfiguracionSlaTriage.objects.get(clasificacion_triage='guardia')
        detail_url = f"{self.url}{guardia.id}/"

        response_zero = self.client.patch(detail_url, {'tiempo_objetivo_minutos': 0})
        self.assertEqual(response_zero.status_code, status.HTTP_400_BAD_REQUEST)

        response_too_big = self.client.patch(detail_url, {'tiempo_objetivo_minutos': 999})
        self.assertEqual(response_too_big.status_code, status.HTTP_400_BAD_REQUEST)
