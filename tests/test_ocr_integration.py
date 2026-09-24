"""
Tests de Integración OCR y Fuzzy Matching Léxico con RapidFuzz.
"""
import io
from unittest.mock import patch, MagicMock
from django.test import TestCase
from app.models.studies import Estudios, TipoMuestra
from app.services.ocr_service import OCRIntegrationService


class OCRIntegrationTestCase(TestCase):
    def setUp(self):
        # Crear catálogo de estudios de prueba
        self.estudio_hemo = Estudios.objects.create(
            codigo_practica='HEMO-01',
            nombre='Hemograma Completo Automatizado',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        self.estudio_glucemia = Estudios.objects.create(
            codigo_practica='GLUC-01',
            nombre='Glucemia Plasmática en Ayunas',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        self.estudio_orina = Estudios.objects.create(
            codigo_practica='ORI-01',
            nombre='Sedimento y Examen de Orina Completa',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True
        )
        self.estudio_inactivo = Estudios.objects.create(
            codigo_practica='INACT-99',
            nombre='Prueba Desactivada',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=False
        )

    @patch('requests.post')
    def test_procesamiento_en_memoria_y_fuzzy_matching(self, mock_post):
        """Simula respuesta del microservicio OCR y valida el Fuzzy Matching >= 80%."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        # Texto detectado por el OCR en la receta médica
        mock_response.json.return_value = {
            "textos": [
                "Hemograma Completo",      # Coincide con HEMO-01
                "Glucemia en ayunas",       # Coincide con GLUC-01
                "Texto irrelevante receta", # No coincide con nada del catálogo
            ]
        }
        mock_post.return_value = mock_response

        # Buffer volátil en memoria
        imagen_buffer = io.BytesIO(b"fake-image-binary-stream-in-memory")

        sugerencias = OCRIntegrationService.procesar_orden_medica_en_memoria(
            archivo_imagen=imagen_buffer,
            nombre_archivo="receta_paciente.jpg"
        )

        # Debe sugerir HEMO-01 y GLUC-01
        self.assertEqual(len(sugerencias), 2)

        codigos_sugeridos = [s['codigo_practica'] for s in sugerencias]
        self.assertIn('HEMO-01', codigos_sugeridos)
        self.assertIn('GLUC-01', codigos_sugeridos)

        # Todos los scores deben ser >= 80%
        for s in sugerencias:
            self.assertGreaterEqual(s['similitud_score'], 80.0)

        # Verificar que la llamada a requests.post fue realizada
        mock_post.assert_called_once()
