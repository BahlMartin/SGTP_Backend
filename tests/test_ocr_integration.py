"""
Tests de Integración OCR, Memoria Adaptativa, Combos por IDs y Coocurrencia.
"""
import io
from unittest.mock import patch, MagicMock
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework import status

from app.models.user import Personal, RolPersonal
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

    def test_desglose_renglon_por_renglon(self):
        """Valida que mapear_textos_con_estudios retorne el desglose estructurado renglón por renglón."""
        resultado = OCRIntegrationService.mapear_textos_con_estudios([
            "Hemograma - Glucemia",
            "Orina comp",
            "Texto sin coincidencia"
        ])

        self.assertIn('renglones', resultado)
        renglones = resultado['renglones']
        self.assertEqual(len(renglones), 3)

        ids_renglon_0 = {r['id_estudio'] for r in renglones[0]['recomendados'] if r['preseleccionado']}
        self.assertIn(self.estudio_hemo.id, ids_renglon_0)
        self.assertIn(self.estudio_glucemia.id, ids_renglon_0)

        ids_renglon_1 = {r['id_estudio'] for r in renglones[1]['recomendados'] if r['preseleccionado']}
        self.assertIn(self.estudio_orina.id, ids_renglon_1)

        self.assertEqual(renglones[2]['recomendados'], [])

    def test_aprendizaje_renglon_individual_con_imagen_y_fuzzy(self):
        """Valida que confirmar 1 estudio en un renglón guarde imagen_muestra y se recupere con fuzzy matching."""
        crop_webp = "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        resp = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {
                    'texto': 'Citolgico completo',
                    'estudios_ids': [self.estudio_hemo.id],
                    'imagen_muestra': crop_webp
                }
            ]
        )
        self.assertTrue(resp['success'])
        self.assertEqual(resp['alias_procesados'], 1)

        alias = EstudioAliasAprendido.objects.filter(
            texto_patron='citolgico completo',
            estudio=self.estudio_hemo
        ).first()
        self.assertIsNotNone(alias)
        self.assertEqual(alias.imagen_muestra, crop_webp)

        # Buscar con un texto levemente distinto leído por OCR para validar fuzzy sobre memoria
        mapeo = OCRIntegrationService.mapear_textos_con_estudios(["Citolgico complet"])
        recs = mapeo['renglones'][0]['recomendados']
        self.assertTrue(any(
            r['id_estudio'] == self.estudio_hemo.id and r['origen_deteccion'] == 'MEMORIA_APRENDIDA' and r['preseleccionado']
            for r in recs
        ))

    def test_aprendizaje_renglon_multiple_crea_bateria_con_imagen(self):
        """Valida que confirmar múltiples estudios en un mismo renglón cree/refuerce una batería con imagen_muestra."""
        crop_webp = "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        resp = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {
                    'texto': 'Control metabólico básico',
                    'estudios_ids': [self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id],
                    'imagen_muestra': crop_webp
                }
            ]
        )
        self.assertTrue(resp['success'])
        self.assertEqual(resp['baterias_procesadas'], 1)

        patron = PerfilEstudioPatron.objects.filter(
            nombre_perfil__icontains='Control Metabolico Basico'
        ).first()
        self.assertIsNotNone(patron)
        self.assertEqual(sorted(patron.estudios_ids), sorted([self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id]))
        self.assertEqual(patron.imagen_muestra, crop_webp)

        # Al volver a escanear esa frase, debe detectar la batería completa automáticamente
        mapeo = OCRIntegrationService.mapear_textos_con_estudios(["Control metabólico básico"])
        self.assertIsNotNone(mapeo['combo_detectado'])
        ids_detectados = {s['id_estudio'] for s in mapeo['sugerencias']}
        self.assertEqual(ids_detectados, {self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id})

    def test_renglones_descartados_se_filtran_en_futuros_escaneos(self):
        """Valida que los renglones descartados como ruido queden marcados y se filtren en próximos escaneos."""
        EstudioAliasAprendido.objects.create(
            texto_patron="obs obra social ioma",
            estudio=self.estudio_orina,
            estado_revision='APROBADO_AUTOMATICO'
        )

        resp = OCRIntegrationService.registrar_retroalimentacion(
            lineas_descartadas=["Obs: Obra Social IOMA"]
        )
        self.assertTrue(resp['success'])
        self.assertEqual(resp['descartados_procesados'], 1)

        # El alias previo automático debe quedar penalizado como DESCARTADO
        alias_prev = EstudioAliasAprendido.objects.get(texto_patron="obs obra social ioma", estudio=self.estudio_orina)
        self.assertEqual(alias_prev.estado_revision, 'DESCARTADO')

        # Al volver a escanear, el renglón debe marcarse es_ruido_aprendido=True sin sugerencias
        mapeo = OCRIntegrationService.mapear_textos_con_estudios(["Obs: Obra Social IOMA"])
        self.assertTrue(mapeo['renglones'][0]['es_ruido_aprendido'])
        self.assertEqual(mapeo['renglones'][0]['recomendados'], [])
        self.assertEqual(mapeo['total_sugerencias'], 0)

    def test_busqueda_manual_encuentra_estudios_por_alias_aprendido_y_api(self):
        """Valida que GET /app/studies/?search=... y /app/ocr/ usen los alias aprendidos y baterías."""
        user = Personal.objects.create_user(
            email='jefa_ocr@hospital.local',
            password='Password123!',
            nombre='Ana',
            apellidos='Gomez',
            dni=44556677,
            rol=RolPersonal.JEFA
        )
        client = APIClient()
        client.force_authenticate(user=user)

        crop_webp = "data:image/webp;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        feedback_resp = client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': 'Curva de azucar basal',
                        'estudios_ids': [self.estudio_glucemia.id],
                        'imagen_muestra': crop_webp
                    }
                ]
            },
            format='json'
        )
        self.assertEqual(feedback_resp.status_code, status.HTTP_200_OK)

        # Buscar manualmente por el alias aprendido "curva de azucar"
        search_resp = client.get('/app/studies/?search=curva%20de%20azucar')
        self.assertEqual(search_resp.status_code, status.HTTP_200_OK)
        data = search_resp.json()
        results = data if isinstance(data, list) else data.get('results', [])
        ids_encontrados = [item['id'] for item in results]
        self.assertIn(self.estudio_glucemia.id, ids_encontrados)

        # Validar respuesta del endpoint de escaneo con renglones
        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {'textos': ['Curva de azucar basal']},
            format='json'
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        scan_data = scan_resp.json()
        self.assertIn('renglones', scan_data)
        self.assertEqual(len(scan_data['renglones']), 1)
        self.assertEqual(scan_data['renglones'][0]['recomendados'][0]['id_estudio'], self.estudio_glucemia.id)
        self.assertEqual(scan_data['renglones'][0]['recomendados'][0]['imagen_muestra'], crop_webp)

    def test_huella_visual_y_manuscrito_sin_texto(self):
        """Valida aprendizaje y recuperación por huella visual (;vhash=...;) aunque el texto sea '[Manuscrito a revisar]'."""
        crop_con_vhash = "data:image/webp;vhash=a5a55a5af0f00f0f28;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="

        resp = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {
                    'texto': '[Manuscrito a revisar]',
                    'estudios_ids': [self.estudio_hemo.id],
                    'imagen_muestra': crop_con_vhash
                }
            ],
            lineas_descartadas=['[Manuscrito a revisar]']
        )
        self.assertTrue(resp['success'])
        self.assertEqual(resp['alias_procesados'], 1)
        # El placeholder genérico nunca debe marcarse como ruido global
        self.assertEqual(resp['descartados_procesados'], 0)

        # Al re-escanear otro bloque sin texto legible con huella visual casi idéntica (1 bit distinto)
        mapeo = OCRIntegrationService.mapear_textos_con_estudios(
            ['[Manuscrito a revisar]'],
            firmas_visuales=['a5a55a5af0f00f0e28']
        )
        renglon = mapeo['renglones'][0]
        self.assertFalse(renglon['es_ruido_aprendido'])
        self.assertTrue(any(
            r['id_estudio'] == self.estudio_hemo.id and r['origen_deteccion'] == 'MEMORIA_APRENDIDA'
            for r in renglon['recomendados']
        ))
