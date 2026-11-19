"""
Tests de Integración OCR, Memoria Adaptativa, Combos por IDs y Coocurrencia.
"""
import base64
import io
import json
import cv2
import numpy as np
import requests
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from app.models.user import Personal, RolPersonal
from app.models.audit import EventoAuditoria, AccionAuditoria, ResultadoAuditoria
from app.models.studies import (
    Estudios,
    TipoMuestra,
    EstudioAliasAprendido,
    PerfilEstudioPatron,
    CoocurrenciaEstudio,
    RecorteImagenEstudio,
    RecorteEstudio,
    FeedbackComparacionTrazo,
    CalibracionComparadorVisual,
)
from app.services.ocr_service import OCRIntegrationService
from app.services.ocr_visual_matcher import VisualMatcherService


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

    def test_fragmentos_cursivos_esqueleto_y_siglas_multiples(self):
        """Valida matching de fragmentos cursivos ('costerel', 'cuotinim', 'pote ro') y siglas en un bloque ('HDL LDL tg')."""
        est_col = Estudios.objects.create(
            codigo_practica='COL-01',
            nombre='Colesterol Total',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_creat = Estudios.objects.create(
            codigo_practica='CREA-01',
            nombre='Creatinina Serica',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_hep = Estudios.objects.create(
            codigo_practica='HEP-01',
            nombre='Hepatograma Completo',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_tg = Estudios.objects.create(
            codigo_practica='TG-01',
            nombre='Trigliceridos',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )

        mapeo = OCRIntegrationService.mapear_textos_con_estudios([
            'costerel',
            'cuotinim',
            'pote ro',
            'HDL LDL tg',
        ])
        renglones = mapeo['renglones']
        self.assertEqual(len(renglones), 4)

        self.assertTrue(any(r['id_estudio'] == est_col.id for r in renglones[0]['recomendados']))
        self.assertTrue(any(r['id_estudio'] == est_creat.id for r in renglones[1]['recomendados']))
        self.assertTrue(any(r['id_estudio'] == est_hep.id for r in renglones[2]['recomendados']))
        ids_siglas = {r['id_estudio'] for r in renglones[3]['recomendados'] if r['preseleccionado']}
        self.assertIn(est_col.id, ids_siglas)
        self.assertIn(est_tg.id, ids_siglas)

    @override_settings(OCR_VISION_API_KEY='test-gemini-free-key', OCR_VISION_PROVIDER='gemini', OCR_VISION_MODEL='gemini-2.5-flash')
    @patch('requests.post')
    def test_asistente_vision_ia_resuelve_bloque_cursivo_dudoso(self, mock_post):
        """Valida que el conector opcional Gemini resuelva bloques dudosos con recorte sin romper el flujo local."""
        est_hep = Estudios.objects.create(
            codigo_practica='HEP-02',
            nombre='Hepatograma',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'resultados': [
                                {'indice': 1, 'texto': 'Hepatograma'}
                            ]
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        crop_webp = "data:image/webp;vhash=1234567890abcdef18;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        mapeo = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['Hemograma', '[Manuscrito a revisar]'],
            firmas_visuales=['', '1234567890abcdef18'],
            recortes_imagen=[crop_webp, crop_webp]
        )

        # Solo debió consultar por el bloque dudoso índice 1 (Hemograma ya tenía match 100%)
        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        self.assertIn('generativelanguage.googleapis.com', called_url)
        self.assertIn('gemini-2.5-flash', called_url)

        renglon_ai = mapeo['renglones'][1]
        self.assertEqual(renglon_ai['texto_renglon'], 'Hepatograma')
        self.assertTrue(any(
            r['id_estudio'] == est_hep.id and r['origen_deteccion'] == 'VISION_IA' and r['preseleccionado']
            for r in renglon_ai['recomendados']
        ))

    def test_cursiva_esqueleto_consonantico_subsegmentos_y_vhash_22(self):
        """Valida esqueleto consonántico cursivo, unión de palabras partidas, split 'HDL LDL tg' y vhash 22-hex."""
        est_colesterol = Estudios.objects.create(
            codigo_practica='COL-01',
            nombre='Colesterol Total',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_trigliceridos = Estudios.objects.create(
            codigo_practica='TG-01',
            nombre='Triglicéridos',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_hepato = Estudios.objects.create(
            codigo_practica='HEP-01',
            nombre='Hepatograma',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_creatinina = Estudios.objects.create(
            codigo_practica='CRE-01',
            nombre='Creatinina Sérica',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )

        # 1. Alias cursivos + unión de palabras partidas + esqueleto consonántico sin falso positivo
        self.assertEqual(
            OCRIntegrationService.calcular_similitud_estudio('costerel', est_colesterol.nombre, est_colesterol.codigo_practica),
            100.0
        )
        self.assertEqual(
            OCRIntegrationService.calcular_similitud_estudio('Hepato grama', est_hepato.nombre, est_hepato.codigo_practica),
            100.0
        )
        self.assertEqual(
            OCRIntegrationService.calcular_similitud_estudio('cuotinim', est_creatinina.nombre, est_creatinina.codigo_practica),
            100.0
        )
        # Deformación cursiva inédita (no en diccionario) resuelta por esqueleto consonántico
        score_skel_col = OCRIntegrationService.calcular_similitud_estudio(
            'clsterol', est_colesterol.nombre, est_colesterol.codigo_practica, min_score=75.0
        )
        self.assertGreaterEqual(score_skel_col, 75.0)
        score_skel_cre = OCRIntegrationService.calcular_similitud_estudio(
            'crtinina', est_creatinina.nombre, est_creatinina.codigo_practica, min_score=75.0
        )
        self.assertGreaterEqual(score_skel_cre, 75.0)

        # 2. Separación de múltiples siglas en el mismo renglón ("HDL LDL tg")
        subsegs = OCRIntegrationService._dividir_subsegmentos('HDL LDL tg')
        self.assertEqual(subsegs, ['hdl', 'ldl', 'tg'])

        mapeo = OCRIntegrationService.mapear_textos_con_estudios(['HDL LDL tg', 'Hepato grama', 'cuotinim'])
        presel_r0 = {r['id_estudio'] for r in mapeo['renglones'][0]['recomendados'] if r['preseleccionado']}
        self.assertIn(est_colesterol.id, presel_r0)
        self.assertIn(est_trigliceridos.id, presel_r0)

        presel_r1 = {r['id_estudio'] for r in mapeo['renglones'][1]['recomendados'] if r['preseleccionado']}
        self.assertIn(est_hepato.id, presel_r1)

        presel_r2 = {r['id_estudio'] for r in mapeo['renglones'][2]['recomendados'] if r['preseleccionado']}
        self.assertIn(est_creatinina.id, presel_r2)

        # 3. Huella visual 22 hex (dHash 16 + aspect 2 + morfología 4x4 4) con tolerancia a desplazamiento ±1 bit
        # Cada fila 0x54 (01010100) desplazada 1 bit a la derecha es 0x2a (00101010)
        vhash_base = '545454545454545428f3c1'
        vhash_shift = '2a2a2a2a2a2a2a2a28f3c1'
        vhash_distinto = 'ff00ff00ff00ff00900000'
        sim_shift = OCRIntegrationService.calcular_similitud_visual(vhash_base, vhash_shift)
        sim_distinto = OCRIntegrationService.calcular_similitud_visual(vhash_base, vhash_distinto)
        self.assertGreaterEqual(sim_shift, 95.0)
        self.assertLess(sim_distinto, 60.0)

    @override_settings(OCR_VISION_API_KEY='test-gemini-free-key', OCR_VISION_PROVIDER='gemini', OCR_VISION_MODEL='gemini-2.5-flash')
    @patch('requests.post')
    def test_endpoint_interpretar_recortes_bajo_demanda_y_memorizacion_posterior(self, mock_post):
        """Valida consulta grupal explícita /app/ocr/interpretar-recortes/ y memorización local al confirmar."""
        est_iono = Estudios.objects.create(
            codigo_practica='IONO-01',
            nombre='Ionograma Sérico',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_prot = Estudios.objects.create(
            codigo_practica='PROT-01',
            nombre='Proteinograma Electroforético',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        user = Personal.objects.create_user(
            email='admision_ocr@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Ruiz',
            dni=33445566,
            rol=RolPersonal.ADMISION
        )
        client = APIClient()
        client.force_authenticate(user=user)

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'resultados': [
                                {'indice': 1, 'texto': 'Ionograma Sérico'},
                                {'indice': 3, 'texto': 'Proteinograma Electroforético'}
                            ]
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        vhash_1 = '112233445566778820a5a5'
        vhash_3 = '887766554433221124f0f0'
        crop_1 = f"data:image/webp;vhash={vhash_1};base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        crop_3 = f"data:image/webp;vhash={vhash_3};base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="

        resp = client.post(
            '/app/ocr/interpretar-recortes/',
            {
                'recortes': [
                    {
                        'indice': 1,
                        'texto_ocr': 'iogr x',
                        'firma_visual': vhash_1,
                        'imagen_recorte': crop_1
                    },
                    {
                        'indice': 3,
                        'texto_ocr': '[Manuscrito a revisar]',
                        'firma_visual': vhash_3,
                        'imagen_recorte': crop_3
                    }
                ]
            },
            format='json'
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_post.assert_called_once()

        data = resp.json()
        self.assertEqual(data['total_procesados'], 2)
        por_idx = {r['indice']: r for r in data['resultados']}

        self.assertTrue(any(
            rec['id_estudio'] == est_iono.id and rec['origen_deteccion'] == 'VISION_IA' and rec['preseleccionado']
            for rec in por_idx[1]['recomendados']
        ))
        self.assertTrue(any(
            rec['id_estudio'] == est_prot.id and rec['origen_deteccion'] == 'VISION_IA' and rec['preseleccionado']
            for rec in por_idx[3]['recomendados']
        ))

        # Simular confirmación en Admisión enviando textoOriginalOcr + vhash para memorización local
        fb_resp = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {'texto': 'iogr x', 'estudios_ids': [est_iono.id], 'imagen_muestra': crop_1},
                {'texto': '[Manuscrito a revisar]', 'estudios_ids': [est_prot.id], 'imagen_muestra': crop_3},
            ]
        )
        self.assertTrue(fb_resp['success'])
        self.assertEqual(fb_resp['alias_procesados'], 2)

        # Resetear el mock y verificar que el siguiente escaneo SIN recortes_imagen lo resuelva 100% local sin llamar a Gemini
        mock_post.reset_mock()
        mapeo_local = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['iogr x', '[Manuscrito a revisar]'],
            firmas_visuales=[vhash_1, vhash_3]
        )
        mock_post.assert_not_called()

        self.assertTrue(any(
            r['id_estudio'] == est_iono.id and r['origen_deteccion'] == 'MEMORIA_APRENDIDA' and r['preseleccionado']
            for r in mapeo_local['renglones'][0]['recomendados']
        ))
        self.assertTrue(any(
            r['id_estudio'] == est_prot.id and r['origen_deteccion'] == 'MEMORIA_APRENDIDA' and r['preseleccionado']
            for r in mapeo_local['renglones'][1]['recomendados']
        ))

    def test_galeria_recortes_multiples_por_estudio_y_prioridad_trazado(self):
        """Valida galería M2M histórica por estudio (sin sobrescribir), 3 estudios por recorte y prioridad por trazado."""
        crop_hemo_1 = "data:image/webp;vhash=101010101010101020aaaa;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        crop_hemo_2 = "data:image/webp;vhash=020202020202020220bbbb;base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/BBB="

        # 1. Confirmar dos recetas distintas para Hemograma (ambas dicen "Hemograma" y otra "Hto"): debe acumular ambas imágenes
        r1 = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {'texto': 'Hemograma', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_hemo_1}
            ]
        )
        r2 = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {'texto': 'Hemograma', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_hemo_2}
            ]
        )
        r3 = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {'texto': 'Hto completo', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_hemo_2}
            ]
        )
        self.assertEqual(r1['recortes_guardados'], 1)
        self.assertEqual(r2['recortes_guardados'], 1)
        self.assertEqual(r3['recortes_guardados'], 1)
        # Hemograma acumula las 3 confirmaciones visuales históricas sin pisar la primera
        self.assertEqual(self.estudio_hemo.recortes_visuales.count(), 3)
        muestras_guardadas = set(self.estudio_hemo.recortes_visuales.values_list('imagen_muestra', flat=True))
        self.assertEqual(muestras_guardadas, {crop_hemo_1, crop_hemo_2})
        # Y conserva los textos patrón distintos asociados al estudio
        self.assertTrue(
            EstudioAliasAprendido.objects.filter(estudio=self.estudio_hemo, texto_patron='hemograma').exists()
        )
        self.assertTrue(
            EstudioAliasAprendido.objects.filter(estudio=self.estudio_hemo, texto_patron='hto completo').exists()
        )

        # 2. Confirmar 1 recorte seleccionando 3 estudios a la vez: referencia única M2M a los 3 + texto_patron en los 3
        vhash_multi = 'f0f0f0f0f0f0f0f02455aa'
        crop_multi = f"data:image/webp;vhash={vhash_multi};base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/CCC="
        resp_multi = OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {
                    'texto': 'Panel basal x3',
                    'estudios_ids': [self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id],
                    'imagen_muestra': crop_multi
                }
            ]
        )
        self.assertEqual(resp_multi['recortes_guardados'], 1)

        recorte_multi = RecorteImagenEstudio.objects.filter(firma_visual=vhash_multi).first()
        self.assertIsNotNone(recorte_multi)
        self.assertEqual(RecorteEstudio.objects.filter(recorte=recorte_multi).count(), 3)
        self.assertEqual(
            set(recorte_multi.estudios.values_list('id', flat=True)),
            {self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id}
        )
        for est in (self.estudio_hemo, self.estudio_glucemia, self.estudio_orina):
            self.assertTrue(
                EstudioAliasAprendido.objects.filter(estudio=est, texto_patron='panel basal x3').exists()
            )

        # 3. Escaneo posterior: prioridad 1 por trazado encuentra los 3 estudios asociados incluso con texto ilegible
        mapeo_trazo = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['garabato ilegible xyz'],
            firmas_visuales=[vhash_multi]
        )
        recs = mapeo_trazo['renglones'][0]['recomendados']
        ids_presel = {r['id_estudio'] for r in recs if r['preseleccionado']}
        self.assertEqual(ids_presel, {self.estudio_hemo.id, self.estudio_glucemia.id, self.estudio_orina.id})
        for r in recs:
            self.assertEqual(r['origen_deteccion'], 'MEMORIA_APRENDIDA')

    @override_settings(OCR_VISION_API_KEY='test-gemini-free-key', OCR_VISION_PROVIDER='gemini', OCR_VISION_MODEL='gemini-3.5-flash')
    @patch('requests.post')
    def test_descarte_visual_vhash_26_grafo_clinico_y_gemini_dual(self, mock_post):
        """Valida descarte por imagen (es_descarte=True), firma 26-hex, poda por grafo y respuesta dual Gemini."""
        vhash_26_a = 'a5a5a5a5a5a5a5a524f3c1aaaa'
        vhash_26_b = 'a5a5a5a5a5a5a5a524f3c15555'  # Mismo dHash y morfología, ascendentes vs descendentes opuestos (85.0 < 90.0)
        self.assertEqual(OCRIntegrationService.calcular_similitud_visual(vhash_26_a, vhash_26_a), 100.0)
        self.assertLess(OCRIntegrationService.calcular_similitud_visual(vhash_26_a, vhash_26_b), 90.0)

        # 1. Descarte por imagen: registrar una firma o sello como ruido visual (es_descarte=True)
        crop_sello = f"data:image/webp;vhash={vhash_26_a};base64,UklGRh4AAABXRUJQVlA4TBEAAAAvAAAAAAfQ//73v/+BiOh/AAA="
        fb_desc = OCRIntegrationService.registrar_retroalimentacion(
            recortes_descartados=[{'texto': 'Firma Dr. Perez', 'imagen_muestra': crop_sello}]
        )
        self.assertGreaterEqual(fb_desc['descartados_procesados'], 1)
        self.assertTrue(RecorteImagenEstudio.objects.filter(firma_visual=vhash_26_a, es_descarte=True).exists())

        # Aunque PaddleOCR lea otro texto distinto la próxima vez sobre la misma imagen de sello, debe descartarse
        mapeo_sello = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['Dr. Juan x'],
            firmas_visuales=[vhash_26_a]
        )
        self.assertTrue(mapeo_sello['renglones'][0]['es_ruido_aprendido'])
        self.assertEqual(mapeo_sello['renglones'][0]['recomendados'], [])

        # 2. Grafo clínico: Test de Embarazo (ancla) conectado con Hemograma, pero NO con Hepatitis B
        est_embarazo = Estudios.objects.create(
            codigo_practica='EMB-01',
            nombre='Test de Embarazo Subunidad Beta',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        est_hepb = Estudios.objects.create(
            codigo_practica='HEPB-01',
            nombre='Hepatitis B Antígeno Australiano',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True
        )
        CoocurrenciaEstudio.objects.create(
            estudio_a_id=est_embarazo.id,
            estudio_b_id=self.estudio_hemo.id,
            veces_juntos=5,
            indice_afinidad=0.80
        )

        # 'Hepatit' (< 80% OCR_DIRECTO) sobre Hepatitis B está desconectado de Test de Embarazo en el grafo -> se poda
        mapeo_grafo = OCRIntegrationService.mapear_textos_con_estudios([
            'Test de Embarazo Subunidad Beta',
            'Hematito'  # texto ambiguo ~60-74% sobre Hepatitis B vs Hemograma
        ])
        ids_r1 = [r['id_estudio'] for r in mapeo_grafo['renglones'][1]['recomendados']]
        self.assertNotIn(est_hepb.id, ids_r1)

        # 3. Gemini respuesta dual ('texto' literal + 'estudios_catalogo' exactos)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'resultados': [{
                                'indice': 0,
                                'texto': 'Control Prenatal',
                                'estudios_catalogo': [est_embarazo.nombre, self.estudio_hemo.nombre]
                            }]
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        res_ia = OCRIntegrationService.interpretar_recortes_seleccionados([
            {
                'indice': 0,
                'texto_ocr': '[Manuscrito a revisar]',
                'firma_visual': '',
                'imagen_recorte': crop_sello
            }
        ])
        ids_ia = {r['id_estudio'] for r in res_ia[0]['recomendados']}
        self.assertIn(est_embarazo.id, ids_ia)
        self.assertIn(self.estudio_hemo.id, ids_ia)

    @staticmethod
    def _build_handwritten_webp(
        text: str,
        *,
        thickness: int = 2,
        scale: float = 1.0,
        tilt: float = 0.0,
        sx: float = 1.0,
        vhash: str = '',
    ) -> str:
        """Genera un recorte WebP realista de texto manuscrito para pruebas OpenCV."""
        img = np.full((80, 420), 255, dtype=np.uint8)
        cv2.putText(img, text, (20, 55), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, scale, 0, thickness, cv2.LINE_AA)
        if tilt != 0.0 or sx != 1.0:
            mat = np.float32([[sx, tilt, 0.0], [0.0, 1.0, 0.0]])
            img = cv2.warpAffine(img, mat, (420, 80), borderValue=255)
        ok, buf = cv2.imencode('.webp', img)
        assert ok
        b64 = base64.b64encode(buf.tobytes()).decode('ascii')
        prefix = f"data:image/webp;vhash={vhash};base64," if vhash else "data:image/webp;base64,"
        return f"{prefix}{b64}"

    def test_comparador_opencv_precision_y_cero_falsos_positivos(self):
        """Valida que HOG + Chamfer + NCC reconozca variaciones reales y rechace palabras distintas aunque compartan vhash."""
        VisualMatcherService.limpiar_cache()

        same_vhash = 'a5a55a5a5a5a5a5a24f3c1aaaa'
        crop_gluc_base = self._build_handwritten_webp('Glucemia', thickness=2, scale=1.0, vhash=same_vhash)
        crop_gluc_var = self._build_handwritten_webp(
            'Glucemia', thickness=3, scale=1.05, tilt=0.08, sx=1.06, vhash='00000000000000000000000000'
        )
        crop_creatinina = self._build_handwritten_webp('Creatinina', thickness=2, scale=1.0, vhash=same_vhash)
        crop_hemograma = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0, vhash=same_vhash)
        crop_hepatograma = self._build_handwritten_webp('Hepatograma', thickness=2, scale=1.0, vhash=same_vhash)
        crop_tsh = self._build_handwritten_webp('TSH', thickness=2, scale=1.0, vhash=same_vhash)
        crop_hiv = self._build_handwritten_webp('HIV', thickness=2, scale=1.0, vhash=same_vhash)
        crop_urea = self._build_handwritten_webp('Urea', thickness=2, scale=1.0, vhash=same_vhash)

        prep_gluc_base = VisualMatcherService.preparar_recorte(crop_gluc_base)
        prep_gluc_var = VisualMatcherService.preparar_recorte(crop_gluc_var)
        prep_creat = VisualMatcherService.preparar_recorte(crop_creatinina)
        prep_hemo = VisualMatcherService.preparar_recorte(crop_hemograma)
        prep_hepa = VisualMatcherService.preparar_recorte(crop_hepatograma)
        prep_tsh = VisualMatcherService.preparar_recorte(crop_tsh)
        prep_hiv = VisualMatcherService.preparar_recorte(crop_hiv)
        prep_urea = VisualMatcherService.preparar_recorte(crop_urea)

        self.assertIsNotNone(prep_gluc_base)
        self.assertGreaterEqual(VisualMatcherService.comparar_preparados(prep_gluc_base, prep_gluc_var), 80.0)
        self.assertLess(VisualMatcherService.comparar_preparados(prep_gluc_base, prep_creat), 80.0)
        self.assertLess(VisualMatcherService.comparar_preparados(prep_hemo, prep_hepa), 80.0)
        self.assertLess(VisualMatcherService.comparar_preparados(prep_tsh, prep_hiv), 80.0)
        self.assertLess(VisualMatcherService.comparar_preparados(prep_urea, prep_tsh), 80.0)

        # Guardar Glucemia y un descarte real (firma/sello médico)
        crop_firma_desc = self._build_handwritten_webp('Dr Perez MP', thickness=2, scale=0.95)
        OCRIntegrationService.registrar_retroalimentacion(
            renglones_confirmados=[
                {
                    'texto': '[Manuscrito a revisar]',
                    'estudios_ids': [self.estudio_glucemia.id],
                    'imagen_muestra': crop_gluc_base,
                }
            ],
            recortes_descartados=[
                {'texto': 'Firma Medica', 'imagen_muestra': crop_firma_desc}
            ],
        )

        # Mismo trazo 'Glucemia' con variación debe recuperar Glucemia y su imagen histórica
        mapeo_ok = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['[Manuscrito a revisar]'],
            firmas_visuales=['00000000000000000000000000'],
            recortes_imagen=[crop_gluc_var],
            permitir_vision_ia=False,
        )
        r_ok = mapeo_ok['renglones'][0]
        self.assertFalse(r_ok['es_ruido_aprendido'])
        self.assertIn(self.estudio_glucemia.id, [rec['id_estudio'] for rec in r_ok['recomendados']])
        self.assertIn(crop_gluc_base, r_ok['imagenes_muestra_conocidas'])

        # 'Creatinina' aunque porte EXACTAMENTE el mismo vhash engañoso NO debe dar falso positivo con Glucemia
        mapeo_fp = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['[Manuscrito a revisar]'],
            firmas_visuales=[same_vhash],
            recortes_imagen=[crop_creatinina],
            permitir_vision_ia=False,
        )
        self.assertEqual(mapeo_fp['renglones'][0]['recomendados'], [])

        # El trazo descartado real debe filtrarse como ruido sin bloquear estudios válidos
        crop_firma_var = self._build_handwritten_webp('Dr Perez MP', thickness=3, scale=0.98, tilt=0.04)
        mapeo_desc = OCRIntegrationService.mapear_textos_con_estudios(
            textos_detectados=['[Manuscrito a revisar]', '[Manuscrito a revisar]'],
            recortes_imagen=[crop_firma_var, crop_gluc_var],
            permitir_vision_ia=False,
        )
        self.assertTrue(mapeo_desc['renglones'][0]['es_ruido_aprendido'])
        self.assertFalse(mapeo_desc['renglones'][1]['es_ruido_aprendido'])
        self.assertIn(self.estudio_glucemia.id, [rec['id_estudio'] for rec in mapeo_desc['renglones'][1]['recomendados']])

    @override_settings(OCR_VISION_API_KEY='fake-gemini-key')
    @patch('app.services.ocr_service.requests.post')
    def test_endpoint_escanear_con_recortes_usa_opencv_local_sin_llamar_gemini(self, mock_post):
        """Verifica que /app/ocr/escanear-receta/ compare recortes en Django y no envíe imágenes a Gemini por defecto."""
        VisualMatcherService.limpiar_cache()
        user = Personal.objects.create_user(
            email='admision_cv@hospital.local',
            password='Password123!',
            nombre='Carlos',
            apellidos='Ruiz',
            dni=33445566,
            rol=RolPersonal.ADMISION,
        )
        client = APIClient()
        client.force_authenticate(user=user)

        crop_gluc_base = self._build_handwritten_webp('Glucemia', thickness=2, scale=1.0)
        crop_gluc_query = self._build_handwritten_webp('Glucemia', thickness=3, scale=1.04, tilt=0.07, sx=1.04)
        crop_desconocido = self._build_handwritten_webp('Colesterol Total', thickness=2, scale=1.0)

        fb_resp = client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_glucemia.id],
                        'imagen_muestra': crop_gluc_base,
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(fb_resp.status_code, status.HTTP_200_OK)

        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]', '[Manuscrito a revisar]'],
                'firmas_visuales': ['', ''],
                'recortes_imagen': [crop_gluc_query, crop_desconocido],
            },
            format='json',
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        mock_post.assert_not_called()

        data = scan_resp.json()
        self.assertEqual(len(data['renglones']), 2)
        self.assertEqual(data['renglones'][0]['recomendados'][0]['id_estudio'], self.estudio_glucemia.id)
        self.assertIn(crop_gluc_base, data['renglones'][0]['imagenes_muestra_conocidas'])
        self.assertEqual(data['renglones'][1]['recomendados'], [])

    def _crear_cliente_ocr(self, email='admision_trazos@hospital.local', dni=99112233):
        user = Personal.objects.create_user(
            email=email,
            password='Password123!',
            nombre='Lucia',
            apellidos='Mendez',
            dni=dni,
            rol=RolPersonal.ADMISION,
        )
        client = APIClient()
        client.force_authenticate(user=user)
        return client

    def test_trazos_coincidentes_solo_recortes_historicos_y_metricas(self):
        """Valida que trazos_coincidentes incluya únicamente RecorteImagenEstudio del Paso 0 (nunca alias/combos)."""
        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='trazos_solo@hospital.local', dni=99110001)

        crop_orina_alias = self._build_handwritten_webp('Orina Completa', thickness=2, scale=1.0)
        crop_combo = self._build_handwritten_webp('Perfil Renal', thickness=2, scale=1.0)
        EstudioAliasAprendido.objects.create(
            texto_patron='orina alias especial',
            estudio=self.estudio_orina,
            veces_confirmado=2,
            confianza_score=100.0,
            estado_revision='APROBADO_AUTOMATICO',
            imagen_muestra=crop_orina_alias,
        )
        PerfilEstudioPatron.objects.create(
            nombre_perfil='Combo Renal Especial',
            disparadores=['perfil renal especial'],
            estudios_ids=[self.estudio_glucemia.id, self.estudio_orina.id],
            activo=True,
            imagen_muestra=crop_combo,
        )

        vhash_1 = '101010101010101020aaaa'
        vhash_2 = '101010101010101020bbbb'
        crop_hemo_1 = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0, vhash=vhash_1)
        crop_hemo_2 = self._build_handwritten_webp('Hemograma', thickness=3, scale=1.02, tilt=0.02, vhash=vhash_2)
        crop_hemo_query = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.03, tilt=0.04, sx=1.03)
        crop_descarte = self._build_handwritten_webp('Firma Dr Perez', thickness=2, scale=1.0)

        fb_resp = client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_hemo.id],
                        'imagen_muestra': crop_hemo_1,
                    },
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_hemo.id],
                        'imagen_muestra': crop_hemo_2,
                    },
                ],
                'recortes_descartados': [
                    {'texto': 'Firma Dr Perez', 'imagen_muestra': crop_descarte},
                ],
            },
            format='json',
        )
        self.assertEqual(fb_resp.status_code, status.HTTP_200_OK)

        recortes_validos = list(RecorteImagenEstudio.objects.filter(es_descarte=False).order_by('id'))
        self.assertEqual(len(recortes_validos), 2)
        rec_ids_esperados = {r.id for r in recortes_validos}

        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': [
                    '[Manuscrito a revisar]',
                    'orina alias especial',
                    'perfil renal especial',
                    '[Manuscrito a revisar]',
                ],
                'firmas_visuales': ['', '', '', ''],
                'recortes_imagen': [
                    crop_hemo_query,
                    crop_orina_alias,
                    crop_combo,
                    crop_descarte,
                ],
            },
            format='json',
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        renglones = scan_resp.json()['renglones']
        self.assertEqual(len(renglones), 4)

        # Renglón 0: solo los 2 RecorteImagenEstudio reales, ordenados por similitud_score desc, sin truncar
        trazos_0 = renglones[0]['trazos_coincidentes']
        self.assertEqual(len(trazos_0), 2)
        self.assertEqual({t['recorte_id'] for t in trazos_0}, rec_ids_esperados)
        self.assertGreaterEqual(trazos_0[0]['similitud_score'], trazos_0[1]['similitud_score'])
        for trazo in trazos_0:
            self.assertIn(trazo['imagen_muestra'], {crop_hemo_1, crop_hemo_2})
            self.assertNotIn(trazo['imagen_muestra'], {crop_orina_alias, crop_combo})
            self.assertEqual(trazo['estudios_ids'], [self.estudio_hemo.id])
            self.assertEqual(trazo['estudios_nombres'], [self.estudio_hemo.nombre])
            self.assertIsInstance(trazo['similitud_score'], float)
            self.assertIsInstance(trazo['score_base'], float)
            self.assertIsInstance(trazo['metricas'], dict)
            for metric_key in ('hog_cos', 'chamfer_sim', 'min_zone_chamfer', 'ncc_sim', 'ar_diff'):
                self.assertIn(metric_key, trazo['metricas'])
                self.assertIsInstance(trazo['metricas'][metric_key], float)

        # Renglón 1 (solo alias) y Renglón 2 (solo combo): trazos_coincidentes debe estar vacío
        self.assertFalse(renglones[1]['es_ruido_aprendido'])
        self.assertEqual(renglones[1]['trazos_coincidentes'], [])
        self.assertIn(crop_orina_alias, renglones[1]['imagenes_muestra_conocidas'])

        self.assertFalse(renglones[2]['es_ruido_aprendido'])
        self.assertEqual(renglones[2]['trazos_coincidentes'], [])

        # Renglón 3 (ruido descartado): es_ruido_aprendido=True y trazos_coincidentes=[]
        self.assertTrue(renglones[3]['es_ruido_aprendido'])
        self.assertEqual(renglones[3]['trazos_coincidentes'], [])

        # Fallback por vhash sin OpenCV (sin recortes_imagen): metricas debe ser {}
        scan_vhash = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]'],
                'firmas_visuales': [vhash_1],
            },
            format='json',
        )
        self.assertEqual(scan_vhash.status_code, status.HTTP_200_OK)
        trazos_vhash = scan_vhash.json()['renglones'][0]['trazos_coincidentes']
        self.assertGreaterEqual(len(trazos_vhash), 1)
        for trazo in trazos_vhash:
            self.assertEqual(trazo['metricas'], {})

    def test_reputacion_progresiva_bien_y_mal_sin_desactivar_recorte(self):
        """Valida reputación progresiva (+/-) y que muchos votos Mal nunca desactiven el recorte."""
        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='rep_prog@hospital.local', dni=99110002)

        crop_hemo_base = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0)
        crop_hemo_probe = self._build_handwritten_webp('Hemograma', thickness=3, scale=1.04, tilt=0.04, sx=1.03)
        crop_gluc_base = self._build_handwritten_webp('Glucemia', thickness=2, scale=1.0)
        crop_gluc_probe = self._build_handwritten_webp('Glucemia', thickness=3, scale=1.04, tilt=0.05, sx=1.04)

        client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_hemo.id],
                        'imagen_muestra': crop_hemo_base,
                    },
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_glucemia.id],
                        'imagen_muestra': crop_gluc_base,
                    },
                ]
            },
            format='json',
        )

        rec_hemo = RecorteImagenEstudio.objects.get(imagen_muestra=crop_hemo_base)
        rec_gluc = RecorteImagenEstudio.objects.get(imagen_muestra=crop_gluc_base)

        def _scan_score(crop_query, rec_id):
            resp = client.post(
                '/app/ocr/escanear-receta/',
                {
                    'textos': ['[Manuscrito a revisar]'],
                    'firmas_visuales': [''],
                    'recortes_imagen': [crop_query],
                },
                format='json',
            )
            self.assertEqual(resp.status_code, status.HTTP_200_OK)
            trazos = resp.json()['renglones'][0]['trazos_coincidentes']
            match = next((t for t in trazos if t['recorte_id'] == rec_id), None)
            return match

        # 1. Baseline y caída progresiva al votar Mal (sin imagen_consulta para aislar reputación pura)
        trazo_h0 = _scan_score(crop_hemo_probe, rec_hemo.id)
        self.assertIsNotNone(trazo_h0)
        score_h0 = trazo_h0['similitud_score']

        fb_mal_1 = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {
                        'recorte_id': rec_hemo.id,
                        'es_correcto': False,
                        'texto_consulta': '[Manuscrito a revisar]',
                        'imagen_consulta': '',
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(fb_mal_1.status_code, status.HTTP_200_OK)
        self.assertEqual(fb_mal_1.json()['trazos_evaluados_mal'], 1)
        self.assertEqual(fb_mal_1.json()['trazos_evaluados_bien'], 0)
        rec_hemo.refresh_from_db()
        self.assertEqual(rec_hemo.votos_negativos, 1)
        self.assertFalse(rec_hemo.es_descarte)

        trazo_h1 = _scan_score(crop_hemo_probe, rec_hemo.id)
        self.assertIsNotNone(trazo_h1)
        score_h1 = trazo_h1['similitud_score']
        self.assertLess(score_h1, score_h0)

        # Votar Mal 3 veces más (total 4 votos negativos) -> baja aún más
        fb_mal_3 = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {'recorte_id': rec_hemo.id, 'es_correcto': False, 'imagen_consulta': ''}
                    for _ in range(3)
                ]
            },
            format='json',
        )
        self.assertEqual(fb_mal_3.status_code, status.HTTP_200_OK)
        self.assertEqual(fb_mal_3.json()['trazos_evaluados_mal'], 3)
        rec_hemo.refresh_from_db()
        self.assertEqual(rec_hemo.votos_negativos, 4)
        self.assertFalse(rec_hemo.es_descarte)

        trazo_h4 = _scan_score(crop_hemo_probe, rec_hemo.id)
        self.assertIsNotNone(trazo_h4)
        self.assertLess(trazo_h4['similitud_score'], score_h1)

        # Muchos votos Mal adicionales (total 15) -> JAMÁS es_descarte=True ni desactivado
        fb_mal_11 = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {'recorte_id': rec_hemo.id, 'es_correcto': False, 'imagen_consulta': ''}
                    for _ in range(11)
                ]
            },
            format='json',
        )
        self.assertEqual(fb_mal_11.status_code, status.HTTP_200_OK)
        rec_hemo.refresh_from_db()
        self.assertEqual(rec_hemo.votos_negativos, 15)
        self.assertFalse(rec_hemo.es_descarte)

        # Sigue activo para su propio trazo genuino
        trazo_h_base = _scan_score(crop_hemo_base, rec_hemo.id)
        self.assertIsNotNone(trazo_h_base)
        self.assertGreaterEqual(trazo_h_base['similitud_score'], 80.0)

        # 2. Subida progresiva al votar Bien sobre Glucemia
        trazo_g0 = _scan_score(crop_gluc_probe, rec_gluc.id)
        self.assertIsNotNone(trazo_g0)
        score_g0 = trazo_g0['similitud_score']
        self.assertLess(score_g0, 98.0)

        fb_bien_1 = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {'recorte_id': rec_gluc.id, 'es_correcto': True, 'imagen_consulta': ''}
                ]
            },
            format='json',
        )
        self.assertEqual(fb_bien_1.status_code, status.HTTP_200_OK)
        self.assertEqual(fb_bien_1.json()['trazos_evaluados_bien'], 1)
        rec_gluc.refresh_from_db()
        self.assertEqual(rec_gluc.votos_positivos, 1)

        trazo_g1 = _scan_score(crop_gluc_probe, rec_gluc.id)
        self.assertIsNotNone(trazo_g1)
        score_g1 = trazo_g1['similitud_score']
        self.assertGreater(score_g1, score_g0)

        client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {'recorte_id': rec_gluc.id, 'es_correcto': True, 'imagen_consulta': ''}
                    for _ in range(4)
                ]
            },
            format='json',
        )
        rec_gluc.refresh_from_db()
        self.assertEqual(rec_gluc.votos_positivos, 5)

        trazo_g5 = _scan_score(crop_gluc_probe, rec_gluc.id)
        self.assertIsNotNone(trazo_g5)
        self.assertGreater(trazo_g5['similitud_score'], score_g1)

    def test_penalizacion_par_negativo_especifico_preserva_trazo_genuino(self):
        """Valida que marcar Mal un par (H, Q) penalice fuertemente Q' similar a Q, preservando el trazo genuino de H."""
        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='par_neg@hospital.local', dni=99110003)

        crop_h = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0)
        # Q coincide inicialmente cerca del borde (~87%) para que Q' sufra caída por par negativo
        # mientras que crop_h genuino (score_base=100) siga superando el umbral.
        crop_q = self._build_handwritten_webp('Hemograma', thickness=3, scale=1.05, tilt=0.28, sx=1.12)
        crop_q_prime = self._build_handwritten_webp('Hemograma', thickness=3, scale=1.05, tilt=0.285, sx=1.12)

        client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': '[Manuscrito a revisar]',
                        'estudios_ids': [self.estudio_hemo.id],
                        'imagen_muestra': crop_h,
                    }
                ]
            },
            format='json',
        )
        rec_h = RecorteImagenEstudio.objects.get(imagen_muestra=crop_h)

        # Escaneo previo de Q: H coincide inicialmente
        scan_q_before = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]'],
                'firmas_visuales': [''],
                'recortes_imagen': [crop_q],
            },
            format='json',
        )
        self.assertEqual(scan_q_before.status_code, status.HTTP_200_OK)
        trazos_q_before = scan_q_before.json()['renglones'][0]['trazos_coincidentes']
        self.assertEqual(len(trazos_q_before), 1)
        score_antes = trazos_q_before[0]['similitud_score']

        # Marcar Mal el par (H, Q)
        fb_mal = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {
                        'recorte_id': rec_h.id,
                        'es_correcto': False,
                        'texto_consulta': '[Manuscrito a revisar]',
                        'firma_visual_consulta': '',
                        'imagen_consulta': crop_q,
                        'estudios_confirmados_ids': [],
                        'score_base': trazos_q_before[0]['score_base'],
                        'metricas': trazos_q_before[0]['metricas'],
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(fb_mal.status_code, status.HTTP_200_OK)
        self.assertEqual(
            FeedbackComparacionTrazo.objects.filter(recorte_historico=rec_h, es_correcto=False).count(),
            1
        )

        # Re-escanear Q': debe quedar fuertemente penalizado (no alcanza umbral >= 80)
        scan_q_prime = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]'],
                'firmas_visuales': [''],
                'recortes_imagen': [crop_q_prime],
            },
            format='json',
        )
        self.assertEqual(scan_q_prime.status_code, status.HTTP_200_OK)
        renglon_q_prime = scan_q_prime.json()['renglones'][0]
        match_q_prime = next(
            (t for t in renglon_q_prime['trazos_coincidentes'] if t['recorte_id'] == rec_h.id),
            None
        )
        if match_q_prime is not None:
            self.assertLess(match_q_prime['similitud_score'], score_antes - 15.0)
        else:
            self.assertEqual(renglon_q_prime['trazos_coincidentes'], [])

        # Escanear el trazo genuino de H: sigue reconociendo a H y recomendando Hemograma
        scan_genuine = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]'],
                'firmas_visuales': [''],
                'recortes_imagen': [crop_h],
            },
            format='json',
        )
        self.assertEqual(scan_genuine.status_code, status.HTTP_200_OK)
        renglon_genuine = scan_genuine.json()['renglones'][0]
        self.assertTrue(any(t['recorte_id'] == rec_h.id for t in renglon_genuine['trazos_coincidentes']))
        self.assertTrue(any(
            r['id_estudio'] == self.estudio_hemo.id and r['preseleccionado']
            for r in renglon_genuine['recomendados']
        ))

    def test_consenso_ponderado_por_reputacion_hemograma_supera_aislado_penalizado(self):
        """Valida que varios trazos de Hemograma con buena reputación superen a un trazo aislado penalizado de otro estudio."""
        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='consenso_rep@hospital.local', dni=99110004)

        crop_h1 = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0)
        crop_h2 = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.01, tilt=0.01)
        crop_h3 = self._build_handwritten_webp('Hemograma', thickness=3, scale=1.02, sx=1.01)
        # Trazo aislado mal etiquetado históricamente como Orina
        crop_o1 = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0, tilt=0.015)
        crop_query = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.01, tilt=0.01)

        client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {'texto': '[Manuscrito a revisar]', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_h1},
                    {'texto': '[Manuscrito a revisar]', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_h2},
                    {'texto': '[Manuscrito a revisar]', 'estudios_ids': [self.estudio_hemo.id], 'imagen_muestra': crop_h3},
                    {'texto': '[Manuscrito a revisar]', 'estudios_ids': [self.estudio_orina.id], 'imagen_muestra': crop_o1},
                ]
            },
            format='json',
        )

        rec_h1 = RecorteImagenEstudio.objects.get(imagen_muestra=crop_h1)
        rec_h2 = RecorteImagenEstudio.objects.get(imagen_muestra=crop_h2)
        rec_h3 = RecorteImagenEstudio.objects.get(imagen_muestra=crop_h3)
        rec_o1 = RecorteImagenEstudio.objects.get(imagen_muestra=crop_o1)

        # Reforzar reputación positiva de Hemograma y penalizar el trazo aislado de Orina
        client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {'recorte_id': rec_h1.id, 'es_correcto': True, 'imagen_consulta': ''},
                    {'recorte_id': rec_h1.id, 'es_correcto': True, 'imagen_consulta': ''},
                    {'recorte_id': rec_h2.id, 'es_correcto': True, 'imagen_consulta': ''},
                    {'recorte_id': rec_h2.id, 'es_correcto': True, 'imagen_consulta': ''},
                    {'recorte_id': rec_h3.id, 'es_correcto': True, 'imagen_consulta': ''},
                    {'recorte_id': rec_o1.id, 'es_correcto': False, 'imagen_consulta': ''},
                    {'recorte_id': rec_o1.id, 'es_correcto': False, 'imagen_consulta': ''},
                ]
            },
            format='json',
        )

        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['[Manuscrito a revisar]'],
                'firmas_visuales': [''],
                'recortes_imagen': [crop_query],
            },
            format='json',
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        renglon = scan_resp.json()['renglones'][0]

        trazos = renglon['trazos_coincidentes']
        self.assertGreaterEqual(len(trazos), 3)
        # Los trazos positivos de Hemograma deben aparecer arriba del aislado penalizado
        self.assertEqual(trazos[0]['estudios_ids'], [self.estudio_hemo.id])

        recs = renglon['recomendados']
        self.assertGreaterEqual(len(recs), 1)
        self.assertEqual(recs[0]['id_estudio'], self.estudio_hemo.id)
        self.assertTrue(recs[0]['preseleccionado'])

        rec_orina = next((r for r in recs if r['id_estudio'] == self.estudio_orina.id), None)
        if rec_orina is not None:
            self.assertGreater(recs[0]['similitud_score'], rec_orina['similitud_score'])

    def test_calibracion_automatica_acotada_y_auditoria_metadata(self):
        """Valida calibración acotada [0.10, 0.55] con umbral >=12 (>=4 pos, >=4 neg) y metadata en AuditService."""
        client = self._crear_cliente_ocr(email='calibracion_ocr@hospital.local', dni=99110005)
        crop_cal = self._build_handwritten_webp('Hemograma', thickness=2, scale=1.0)
        rec_cal = RecorteImagenEstudio.objects.create(
            firma_visual='',
            texto_detectado='Hemograma',
            imagen_muestra=crop_cal,
        )
        RecorteEstudio.objects.create(recorte=rec_cal, estudio=self.estudio_hemo)

        # chamfer_sim discrimina fuertemente Bien vs Mal; hog_cos no discrimina (0.82 vs 0.82)
        metricas_bien = {
            'hog_cos': 0.82,
            'chamfer_sim': 0.96,
            'min_zone_chamfer': 0.86,
            'ncc_sim': 0.80,
            'ar_diff': 0.03,
        }
        metricas_mal = {
            'hog_cos': 0.82,
            'chamfer_sim': 0.35,
            'min_zone_chamfer': 0.72,
            'ncc_sim': 0.70,
            'ar_diff': 0.04,
        }

        def _eval_payload(es_correcto):
            return {
                'recorte_id': rec_cal.id,
                'es_correcto': es_correcto,
                'texto_consulta': '[Manuscrito a revisar]',
                'imagen_consulta': '',
                'estudios_confirmados_ids': [self.estudio_hemo.id] if es_correcto else [],
                'score_base': 88.0 if es_correcto else 82.0,
                'metricas': metricas_bien if es_correcto else metricas_mal,
            }

        # Paso 1: 5 Bien + 3 Mal = 8 votos (< 12 total y < 4 neg) -> NO calibra todavía
        with self.captureOnCommitCallbacks(execute=True):
            resp_1 = client.post(
                '/app/ocr/retroalimentar/',
                {
                    'evaluaciones_trazos': (
                        [_eval_payload(True) for _ in range(5)]
                        + [_eval_payload(False) for _ in range(3)]
                    )
                },
                format='json',
            )
        self.assertEqual(resp_1.status_code, status.HTTP_200_OK)
        d1 = resp_1.json()
        self.assertEqual(d1['trazos_evaluados_bien'], 5)
        self.assertEqual(d1['trazos_evaluados_mal'], 3)
        self.assertFalse(d1['pesos_calibrados'])

        cal = CalibracionComparadorVisual.objects.first()
        self.assertIsNotNone(cal)
        self.assertAlmostEqual(cal.peso_hog, 0.25, places=4)
        self.assertAlmostEqual(cal.peso_chamfer, 0.40, places=4)
        self.assertAlmostEqual(cal.peso_zonas, 0.15, places=4)
        self.assertAlmostEqual(cal.peso_ncc, 0.20, places=4)

        evento_1 = EventoAuditoria.objects.filter(accion=AccionAuditoria.OCR_CORREGIDO).first()
        self.assertIsNotNone(evento_1)
        self.assertEqual(evento_1.metadata.get('trazos_evaluados_bien'), 5)
        self.assertEqual(evento_1.metadata.get('trazos_evaluados_mal'), 3)
        self.assertFalse(evento_1.metadata.get('pesos_calibrados'))

        # Paso 2: +3 Bien -> 8 Bien + 3 Mal = 11 votos (aún bajo umbral)
        with self.captureOnCommitCallbacks(execute=True):
            resp_2 = client.post(
                '/app/ocr/retroalimentar/',
                {'evaluaciones_trazos': [_eval_payload(True) for _ in range(3)]},
                format='json',
            )
        self.assertEqual(resp_2.status_code, status.HTTP_200_OK)
        self.assertFalse(resp_2.json()['pesos_calibrados'])

        # Paso 3: +1 Mal -> 8 Bien + 4 Mal = 12 votos (>= 12 y >= 4 pos y >= 4 neg) -> CALIBRA
        with self.captureOnCommitCallbacks(execute=True):
            resp_3 = client.post(
                '/app/ocr/retroalimentar/',
                {'evaluaciones_trazos': [_eval_payload(False)]},
                format='json',
            )
        self.assertEqual(resp_3.status_code, status.HTTP_200_OK)
        d3 = resp_3.json()
        self.assertEqual(d3['trazos_evaluados_bien'], 0)
        self.assertEqual(d3['trazos_evaluados_mal'], 1)
        self.assertTrue(d3['pesos_calibrados'])

        cal.refresh_from_db()
        self.assertEqual(cal.total_votos_positivos, 8)
        self.assertEqual(cal.total_votos_negativos, 4)

        pesos = [cal.peso_hog, cal.peso_chamfer, cal.peso_zonas, cal.peso_ncc]
        for p in pesos:
            self.assertGreaterEqual(p, 0.10)
            self.assertLessEqual(p, 0.55)
        self.assertAlmostEqual(sum(pesos), 1.0, places=4)
        self.assertGreater(cal.peso_chamfer, cal.peso_hog)
        self.assertGreater(cal.peso_chamfer, 0.40)

        evento_3 = EventoAuditoria.objects.filter(accion=AccionAuditoria.OCR_CORREGIDO).first()
        self.assertIsNotNone(evento_3)
        self.assertEqual(evento_3.metadata.get('trazos_evaluados_bien'), 0)
        self.assertEqual(evento_3.metadata.get('trazos_evaluados_mal'), 1)
        self.assertTrue(evento_3.metadata.get('pesos_calibrados'))

    def test_alias_resuelto_a_recorte_historico_expone_trazos_coincidentes_votables(self):
        """Valida que coincidencias vía alias (Paso 2) resuelvan a RecorteImagenEstudio en trazos_coincidentes."""
        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='alias_trazo@hospital.local', dni=99110006)

        crop_gluc_saved = self._build_handwritten_webp('Glucemia Basal', thickness=2, scale=1.0)
        crop_gluc_other = self._build_handwritten_webp('Gluc', thickness=3, scale=1.15, tilt=0.22)

        fb_setup = client.post(
            '/app/ocr/retroalimentar/',
            {
                'renglones_confirmados': [
                    {
                        'texto': 'Glucemia',
                        'estudios_ids': [self.estudio_glucemia.id],
                        'imagen_muestra': crop_gluc_saved,
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(fb_setup.status_code, status.HTTP_200_OK)
        rec_saved = RecorteImagenEstudio.objects.get(imagen_muestra=crop_gluc_saved)

        # La imagen crop_gluc_other ('Gluc') es visualmente muy distinta (< 80% Paso 0),
        # pero el texto 'Glucemia' dispara el alias aprendido en el Paso 2.
        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {
                'textos': ['Glucemia'],
                'firmas_visuales': [''],
                'recortes_imagen': [crop_gluc_other],
            },
            format='json',
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        renglon = scan_resp.json()['renglones'][0]
        trazos = renglon['trazos_coincidentes']

        self.assertGreaterEqual(len(trazos), 1)
        trazo_resuelto = next((t for t in trazos if t['recorte_id'] == rec_saved.id), None)
        self.assertIsNotNone(trazo_resuelto)
        self.assertEqual(trazo_resuelto['estudios_ids'], [self.estudio_glucemia.id])
        self.assertEqual(trazo_resuelto['estudios_nombres'], [self.estudio_glucemia.nombre])
        self.assertIsInstance(trazo_resuelto['similitud_score'], float)
        self.assertIsInstance(trazo_resuelto['score_base'], float)
        self.assertIsInstance(trazo_resuelto['metricas'], dict)

        # Votar Mal usando el recorte_id devuelto en trazos_coincidentes
        fb_mal = client.post(
            '/app/ocr/retroalimentar/',
            {
                'evaluaciones_trazos': [
                    {
                        'recorte_id': trazo_resuelto['recorte_id'],
                        'es_correcto': False,
                        'texto_consulta': 'Glucemia',
                        'imagen_consulta': crop_gluc_other,
                        'estudios_confirmados_ids': [],
                        'score_base': trazo_resuelto['score_base'],
                        'metricas': trazo_resuelto['metricas'],
                    }
                ]
            },
            format='json',
        )
        self.assertEqual(fb_mal.status_code, status.HTTP_200_OK)
        self.assertEqual(fb_mal.json()['trazos_evaluados_mal'], 1)
        rec_saved.refresh_from_db()
        self.assertEqual(rec_saved.votos_negativos, 1)
        self.assertTrue(
            FeedbackComparacionTrazo.objects.filter(recorte_historico=rec_saved, es_correcto=False).exists()
        )

    def test_migracion_0021_backfill_recortes_historicos_idempotente(self):
        """Valida que la migración 0021 migre alias y combos legados a RecorteImagenEstudio sin duplicar."""
        import importlib
        from django.apps import apps

        VisualMatcherService.limpiar_cache()
        client = self._crear_cliente_ocr(email='backfill_0021@hospital.local', dni=99110007)

        crop_legacy_alias = self._build_handwritten_webp('Orina Especial X1', thickness=2, scale=1.0)
        crop_legacy_combo = self._build_handwritten_webp('Chequeo Prequirurgico Z2', thickness=2, scale=1.0)

        EstudioAliasAprendido.objects.create(
            texto_patron='orina especial x1',
            estudio=self.estudio_orina,
            veces_confirmado=2,
            confianza_score=100.0,
            estado_revision='APROBADO_AUTOMATICO',
            imagen_muestra=crop_legacy_alias,
        )
        PerfilEstudioPatron.objects.create(
            nombre_perfil='Chequeo Prequirurgico Z2',
            disparadores=['chequeo prequirurgico z2'],
            estudios_ids=[self.estudio_hemo.id, self.estudio_glucemia.id],
            activo=True,
            imagen_muestra=crop_legacy_combo,
        )
        self.assertEqual(RecorteImagenEstudio.objects.count(), 0)

        mig_0021 = importlib.import_module('app.migrations.0021_backfill_recortes_historicos')
        mig_0021.backfill_recortes_historicos(apps, None)
        self.assertEqual(RecorteImagenEstudio.objects.count(), 2)

        # Ejecutar una segunda vez debe ser 100% idempotente
        mig_0021.backfill_recortes_historicos(apps, None)
        self.assertEqual(RecorteImagenEstudio.objects.count(), 2)

        rec_alias = RecorteImagenEstudio.objects.get(imagen_muestra=crop_legacy_alias)
        rec_combo = RecorteImagenEstudio.objects.get(imagen_muestra=crop_legacy_combo)
        self.assertEqual(
            list(RecorteEstudio.objects.filter(recorte=rec_alias).values_list('estudio_id', flat=True)),
            [self.estudio_orina.id],
        )
        self.assertEqual(
            set(RecorteEstudio.objects.filter(recorte=rec_combo).values_list('estudio_id', flat=True)),
            {self.estudio_hemo.id, self.estudio_glucemia.id},
        )

        # Escanear luego del backfill debe devolver ambos trazos en trazos_coincidentes
        scan_resp = client.post(
            '/app/ocr/escanear-receta/',
            {'textos': ['orina especial x1', 'chequeo prequirurgico z2']},
            format='json',
        )
        self.assertEqual(scan_resp.status_code, status.HTTP_200_OK)
        renglones = scan_resp.json()['renglones']
        self.assertEqual(len(renglones[0]['trazos_coincidentes']), 1)
        self.assertEqual(renglones[0]['trazos_coincidentes'][0]['recorte_id'], rec_alias.id)
        self.assertEqual(len(renglones[1]['trazos_coincidentes']), 1)
        self.assertEqual(renglones[1]['trazos_coincidentes'][0]['recorte_id'], rec_combo.id)

    def test_receta_manuscrita_9_estudios_dos_columnas_completa(self):
        """Valida detección completa de los 9 estudios de la receta manuscrita a 2 columnas sin falsos positivos."""
        Estudios.objects.all().update(activo=False)

        nombres_objetivo = [
            'HEMOGRAMA CON FORMULA',
            'HEPATOGRAMA',
            'Glucemia',
            'Urea',
            'Creatinina en suero',
            'Lipidograma',
            'Orina Completa',
            'Hemoglobina glicosilada',
            'RAC (relación albu/cre) ó CAC (cociente alb/cre) (orina asilada)',
        ]
        estudios_objetivo = {}
        for idx, nombre in enumerate(nombres_objetivo, start=1):
            est = Estudios.objects.create(
                codigo_practica=f'REC9-{idx:02d}',
                nombre=nombre,
                tipo_muestra=(
                    TipoMuestra.ORINA
                    if 'orina' in nombre.lower() or 'rac' in nombre.lower()
                    else TipoMuestra.SANGRE
                ),
                activo=True,
            )
            estudios_objetivo[nombre] = est

        est_prot_tot = Estudios.objects.create(
            codigo_practica='DIST-01',
            nombre='Proteínas totales',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )
        est_creat_orina = Estudios.objects.create(
            codigo_practica='DIST-02',
            nombre='Creatinina en orina aislada',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        est_calcio_orina = Estudios.objects.create(
            codigo_practica='DIST-03',
            nombre='Calcio Orina Aislada',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )

        variantes_lectura = [
            [
                'Ycllte', 'covtemel', 'tpots Rom', 'HDL', 'Humi',
                'HA1C', 'VAT', 'Wotmm', 'Otintopi', 'Wuite Aisiat', '9my',
            ],
            [
                '4CLL6r6', 'Covtemel', 'itpote Som', 'H D P', 'Wcmw',
                'HA1C', 'VAT', 'Wotmim', 'Crin Goepi', 'Cuite Aislaet', '9my',
            ],
        ]

        ids_esperados = {est.id for est in estudios_objetivo.values()}
        ids_distractores_prohibidos = {est_prot_tot.id, est_creat_orina.id, est_calcio_orina.id}

        for lectura in variantes_lectura:
            resultado = OCRIntegrationService.mapear_textos_con_estudios(
                lectura,
                permitir_vision_ia=False,
            )
            ids_sugeridos = {s['id_estudio'] for s in resultado['sugerencias']}
            for nombre_est, est_obj in estudios_objetivo.items():
                self.assertIn(
                    est_obj.id,
                    ids_sugeridos,
                    f"Faltó detectar '{nombre_est}' en lectura {lectura}",
                )
            self.assertTrue(ids_esperados.issubset(ids_sugeridos))
            self.assertNotIn(est_prot_tot.id, ids_sugeridos)
            self.assertNotIn(est_creat_orina.id, ids_sugeridos)

            ids_preseleccionados = {
                rec['id_estudio']
                for renglon in resultado['renglones']
                for rec in renglon.get('recomendados', [])
                if rec.get('preseleccionado')
            }
            self.assertTrue(ids_esperados.issubset(ids_preseleccionados))
            for dist_id in ids_distractores_prohibidos:
                self.assertNotIn(dist_id, ids_preseleccionados)

    def test_proteinuria_y_estudios_orina_baja_masa_nefronal(self):
        """Valida mapeo de proteinuria (incluso variantes OCR), albuminuria, creatininuria e ionograma sin falsos positivos séricos."""
        Estudios.objects.all().update(activo=False)

        est_prot_orina = Estudios.objects.create(
            codigo_practica='767',
            nombre='Proteínas en orina de 24hs',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        est_microalb = Estudios.objects.create(
            codigo_practica='1308',
            nombre='MICROALBUMINURIA (orina DE 24hs)',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        est_creatinuria = Estudios.objects.create(
            codigo_practica='1941',
            nombre='CREATINURIA',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        est_iono = Estudios.objects.create(
            codigo_practica='IONO-02',
            nombre='Ionograma',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )
        est_iono_orina = Estudios.objects.create(
            codigo_practica='1304',
            nombre='Ionograma en orina de 24HS',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )

        # Distractores proteicos en suero que antes opacaban a 'proteinuria'
        est_pcr = Estudios.objects.create(
            codigo_practica='PCR-01',
            nombre='Proteina C Reactiva',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )
        est_prot_tot = Estudios.objects.create(
            codigo_practica='PROT-TOT',
            nombre='Proteínas totales',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )
        est_proteinograma = Estudios.objects.create(
            codigo_practica='PRG-01',
            nombre='PROTEINOGRAMA',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )
        est_afp = Estudios.objects.create(
            codigo_practica='AFP-01',
            nombre='Alfa feto proteína (AFP)',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )

        for texto_prot in ('proteinuria', 'poternuma', 'ptenunia', 'proternumn'):
            score_orina = OCRIntegrationService.calcular_similitud_estudio(
                texto_prot,
                est_prot_orina.nombre,
                est_prot_orina.codigo_practica,
            )
            self.assertGreaterEqual(score_orina, 95.0, f"Falló score para '{texto_prot}'")
            for dist in (est_pcr, est_prot_tot, est_proteinograma, est_afp):
                score_dist = OCRIntegrationService.calcular_similitud_estudio(
                    texto_prot,
                    dist.nombre,
                    dist.codigo_practica,
                )
                self.assertEqual(score_dist, 0.0, f"Falso positivo '{dist.nombre}' con '{texto_prot}'")

        mapeo = OCRIntegrationService.mapear_textos_con_estudios(
            ['ptenunia', 'albumimua', 'ceahmimua', 'ionograma'],
            permitir_vision_ia=False,
        )
        ids_sug = {s['id_estudio'] for s in mapeo['sugerencias']}
        self.assertIn(est_prot_orina.id, ids_sug)
        self.assertIn(est_microalb.id, ids_sug)
        self.assertIn(est_creatinuria.id, ids_sug)
        self.assertTrue(est_iono.id in ids_sug or est_iono_orina.id in ids_sug)
        for dist in (est_pcr, est_prot_tot, est_proteinograma, est_afp):
            self.assertNotIn(dist.id, ids_sug)

    @override_settings(
        OCR_VISION_API_KEY='test-gemini-36-key',
        OCR_VISION_PROVIDER='gemini',
        OCR_VISION_MODEL='gemini-3.6-flash',
    )
    @patch('app.services.ocr_service.requests.post')
    def test_gemini_solo_llama_gemini_3_6_flash_sin_fallback(self, mock_post):
        """Valida que Gemini llame exclusivamente a gemini-3.6-flash una sola vez y devuelva aviso claro sin fallback."""
        self.assertEqual(OCRIntegrationService._resolver_modelo_gemini(), 'gemini-3.6-flash')
        crop_ctx = self._build_handwritten_webp('proteinuria', thickness=2, scale=1.0)

        for status_code, texto_esperado in ((429, '429'), (503, '503'), (404, '404')):
            mock_post.reset_mock()
            resp_err = MagicMock()
            resp_err.status_code = status_code
            mock_post.return_value = resp_err

            res = OCRIntegrationService.interpretar_receta_contextual(
                imagen_contextual=crop_ctx,
                contexto_renglones=[{'indice': 0, 'texto_ocr': 'ptenunia'}],
            )
            self.assertEqual(mock_post.call_count, 1)
            called_url = mock_post.call_args[0][0]
            self.assertIn('models/gemini-3.6-flash:generateContent', called_url)
            self.assertEqual(res['modelo_usado'], 'gemini-3.6-flash')
            self.assertIn(texto_esperado, res['error_ia'])
            self.assertEqual(res['resultados'], [])
            self.assertEqual(res['renglones_nuevos'], [])

        mock_post.reset_mock()
        mock_post.side_effect = requests.exceptions.Timeout('read timeout')
        res_timeout = OCRIntegrationService.interpretar_receta_contextual(imagen_contextual=crop_ctx)
        self.assertEqual(mock_post.call_count, 1)
        self.assertEqual(res_timeout['modelo_usado'], 'gemini-3.6-flash')
        self.assertIn('Tiempo de espera', res_timeout['error_ia'])

    @override_settings(
        OCR_VISION_API_KEY='test-gemini-36-key',
        OCR_VISION_PROVIDER='gemini',
        OCR_VISION_MODEL='gemini-3.6-flash',
    )
    @patch('app.services.ocr_service.requests.post')
    def test_endpoint_interpretar_receta_contextual_catalogo_completo_y_renglones_nuevos(self, mock_post):
        """Valida lectura contextual única, catálogo >200 sin truncar, renglones nuevos y auditoría."""
        est_prot_orina = Estudios.objects.create(
            codigo_practica='767',
            nombre='Proteínas en orina de 24hs',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        est_microalb = Estudios.objects.create(
            codigo_practica='1308',
            nombre='MICROALBUMINURIA (orina DE 24hs)',
            tipo_muestra=TipoMuestra.ORINA,
            activo=True,
        )
        Estudios.objects.bulk_create([
            Estudios(
                codigo_practica=f'EXTRA-{i:03d}',
                nombre=f'Estudio Extra Catálogo {i:03d}',
                tipo_muestra=TipoMuestra.SANGRE,
                activo=True,
            )
            for i in range(1, 206)
        ])
        Estudios.objects.create(
            codigo_practica='ZZZ-299',
            nombre='Zzz Vitamina Especial Final',
            tipo_muestra=TipoMuestra.SANGRE,
            activo=True,
        )

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            'candidates': [{
                'content': {
                    'parts': [{
                        'text': json.dumps({
                            'diagnostico_detectado': 'baja masa nefronal',
                            'notas_muestra': 'orina muestra aislada',
                            'estudios': [
                                {
                                    'indice_renglon': None,
                                    'texto_manuscrito': 'proteinuria',
                                    'estudios_catalogo': ['Proteínas en orina de 24hs'],
                                },
                                {
                                    'indice_renglon': 0,
                                    'texto_manuscrito': 'albuminuria',
                                    'estudios_catalogo': ['MICROALBUMINURIA (orina DE 24hs)'],
                                },
                            ],
                        })
                    }]
                }
            }]
        }
        mock_post.return_value = mock_resp

        client = self._crear_cliente_ocr(email='contextual_ia@hospital.local', dni=99110088)
        crop_ctx = self._build_handwritten_webp('proteinuria albuminuria', thickness=2, scale=1.0)
        with self.captureOnCommitCallbacks(execute=True):
            resp = client.post(
                '/app/ocr/interpretar-recortes/',
                {
                    'imagen_contextual': crop_ctx,
                    'contexto_renglones': [
                        {'indice': 0, 'texto_ocr': 'albummna'},
                    ],
                },
                format='json',
            )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        mock_post.assert_called_once()
        called_url = mock_post.call_args[0][0]
        self.assertIn('models/gemini-3.6-flash:generateContent', called_url)

        sent_prompt = mock_post.call_args[1]['json']['contents'][0]['parts'][0]['text']
        self.assertIn('Zzz Vitamina Especial Final', sent_prompt)

        payload = resp.json()
        self.assertEqual(payload['error_ia'], '')
        self.assertEqual(payload['modelo_usado'], 'gemini-3.6-flash')
        self.assertEqual(payload['diagnostico_detectado'], 'baja masa nefronal')
        self.assertEqual(payload['notas_muestra'], 'orina muestra aislada')
        self.assertEqual(len(payload['resultados']), 1)
        self.assertEqual(payload['resultados'][0]['indice'], 0)
        self.assertEqual(payload['resultados'][0]['recomendados'][0]['id_estudio'], est_microalb.id)
        self.assertEqual(payload['resultados'][0]['recomendados'][0]['origen_deteccion'], 'VISION_IA')
        self.assertFalse(payload['resultados'][0]['recomendados'][0]['preseleccionado'])

        self.assertEqual(len(payload['renglones_nuevos']), 1)
        self.assertEqual(payload['renglones_nuevos'][0]['texto_transcrito_ia'], 'proteinuria')
        self.assertEqual(payload['renglones_nuevos'][0]['recomendados'][0]['id_estudio'], est_prot_orina.id)
        self.assertEqual(payload['renglones_nuevos'][0]['recomendados'][0]['origen_deteccion'], 'VISION_IA')
        self.assertFalse(payload['renglones_nuevos'][0]['recomendados'][0]['preseleccionado'])

        audit = EventoAuditoria.objects.filter(accion=AccionAuditoria.RECETA_ESCANEADA).order_by('-id').first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.resultado, ResultadoAuditoria.EXITO)
        self.assertEqual(audit.metadata.get('modo'), 'receta_contextual_ia')
        self.assertEqual(audit.metadata.get('motor_ia'), 'gemini-3.6-flash')








