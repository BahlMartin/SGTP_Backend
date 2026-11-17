"""
Tests de Integración OCR, Memoria Adaptativa, Combos por IDs y Coocurrencia.
"""
import io
import json
from unittest.mock import patch, MagicMock
from django.test import TestCase, override_settings
from rest_framework.test import APIClient
from rest_framework import status

from app.models.user import Personal, RolPersonal
from app.models.studies import (
    Estudios,
    TipoMuestra,
    EstudioAliasAprendido,
    PerfilEstudioPatron,
    CoocurrenciaEstudio,
    RecorteImagenEstudio,
    RecorteEstudio
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



