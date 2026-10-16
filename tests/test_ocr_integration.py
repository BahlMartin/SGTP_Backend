"""
Tests de Integración OCR, Memoria Adaptativa, Combos por IDs y Coocurrencia.
"""
import io
from unittest.mock import patch, MagicMock
from django.test import TestCase
from app.models.studies import (
    Estudios,
    TipoMuestra,
    EstudioAliasAprendido,
    PerfilEstudioPatron,
    CoocurrenciaEstudio
)
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
        """Simula respuesta del microservicio OCR y valida el Fuzzy Matching."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "textos": [
                "Hemograma Completo",
                "Glucemia en ayunas",
                "Texto irrelevante receta",
            ]
        }
        mock_post.return_value = mock_response

        imagen_buffer = io.BytesIO(b"fake-image-binary-stream-in-memory")
        sugerencias = OCRIntegrationService.procesar_orden_medica_en_memoria(
            archivo_imagen=imagen_buffer,
            nombre_archivo="receta_paciente.jpg"
        )

        self.assertEqual(len(sugerencias), 2)
        codigos_sugeridos = [s['codigo_practica'] for s in sugerencias]
        self.assertIn('HEMO-01', codigos_sugeridos)
        self.assertIn('GLUC-01', codigos_sugeridos)
        mock_post.assert_called_once()

    def test_mapeo_textos_con_abreviaturas_clinicas(self):
        """Valida que textos con abreviaturas médicas (Hto, Orina comp) mapeen a prácticas correctas sin requests.post."""
        textos = [
            "Hto y fórmula",
            "Glucemia en ayunas",
            "Orina comp",
            "Dr. Juan Pérez MN 12345"
        ]
        resultado = OCRIntegrationService.mapear_textos_con_estudios(textos)
        sugerencias = resultado['sugerencias']
        self.assertEqual(len(sugerencias), 3)
        codigos = [s['codigo_practica'] for s in sugerencias]
        self.assertIn('HEMO-01', codigos)
        self.assertIn('GLUC-01', codigos)
        self.assertIn('ORI-01', codigos)

    def test_deteccion_combo_rutina_por_ids(self):
        """Valida que una frase como 'Rutina completa' active el combo y retorne todos sus estudios_ids."""
        PerfilEstudioPatron.objects.create(
            nombre_perfil="Batería de Rutina Básica",
            disparadores=["rutina completa", "laboratorio de rutina"],
            estudios_ids=[self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id],
            activo=True
        )

        resultado = OCRIntegrationService.mapear_textos_con_estudios(["Solicito rutina completa para control"])
        self.assertEqual(resultado['combo_detectado'], "Batería de Rutina Básica")
        self.assertEqual(len(resultado['sugerencias']), 3)

        ids_detectados = [s['id_estudio'] for s in resultado['sugerencias']]
        self.assertIn(self.estudio_hemo.id, ids_detectados)
        self.assertIn(self.estudio_glucemia.id, ids_detectados)
        self.assertIn(self.estudio_orina.id, ids_detectados)
        for s in resultado['sugerencias']:
            self.assertEqual(s['origen_deteccion'], 'COMBO_RUTINA')
            self.assertEqual(s['similitud_score'], 100.0)

    def test_memoria_adaptativa_alias_aprendido(self):
        """Valida que una abreviatura previamente aprendida en EstudioAliasAprendido se reconozca al 100%."""
        EstudioAliasAprendido.objects.create(
            texto_patron="formula roja y blanca",
            estudio=self.estudio_hemo,
            veces_confirmado=3,
            confianza_score=100.0,
            estado_revision='APROBADO_AUTOMATICO'
        )

        resultado = OCRIntegrationService.mapear_textos_con_estudios(["Formula roja y blanca"])
        sugerencias = resultado['sugerencias']
        self.assertEqual(len(sugerencias), 1)
        self.assertEqual(sugerencias[0]['id_estudio'], self.estudio_hemo.id)
        self.assertEqual(sugerencias[0]['origen_deteccion'], 'MEMORIA_APRENDIDA')

    def test_retroalimentacion_guarda_alias_y_coocurrencia(self):
        """Valida que registrar_retroalimentacion actualice la memoria y la matriz de afinidad."""
        payload_feedback = {
            'lineas_origen': ["Hto y plaq", "Glucemia"],
            'estudios_confirmados_ids': [self.estudio_hemo.id, self.estudio_glucemia.id],
            'asociaciones_directas': [
                {'texto': "Hto y plaq", 'estudio_id': self.estudio_hemo.id}
            ]
        }

        resp = OCRIntegrationService.registrar_retroalimentacion(
            lineas_origen=payload_feedback['lineas_origen'],
            estudios_confirmados_ids=payload_feedback['estudios_confirmados_ids'],
            asociaciones_directas=payload_feedback['asociaciones_directas']
        )
        self.assertTrue(resp['success'])

        # Verificar que se creó el alias aprendido
        alias = EstudioAliasAprendido.objects.filter(texto_patron="hto y plaq").first()
        self.assertNotNull = self.assertIsNotNone(alias)
        self.assertEqual(alias.estudio_id, self.estudio_hemo.id)

        # Verificar que se creó coocurrencia
        cooc = CoocurrenciaEstudio.objects.filter(
            estudio_a_id=self.estudio_hemo.id,
            estudio_b_id=self.estudio_glucemia.id
        ).first()
        self.assertIsNotNone(cooc)
        self.assertEqual(cooc.veces_juntos, 1)
