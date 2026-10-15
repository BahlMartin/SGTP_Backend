"""
Pruebas Unitarias e Integración para Horas Extras Nocturnas y Revocación Masiva (Jefa).
Valida:
1. Desglose automático de extensiones nocturnas que cruzan la medianoche (2 tramos en ambos días).
2. Cálculo de horas diarias y total mensual en PlanificacionHorasExtrasSerializer con cruce de 00:00 hs.
3. Endpoint transaccional /api/v1/users/habilitaciones-horarias/revocar-lote/ en todas sus modalidades:
   - 'todas'
   - 'semana'
   - 'rango'
   - 'dia'
"""
from datetime import date, time, timedelta
from rest_framework import status
from rest_framework.test import APITestCase

from app.models.user import Personal, RolPersonal
from app.models.shifts import HabilitacionHoraria, PlanificacionHorasExtras, TipoExtensionChoices


class HorasExtrasNocturnasYRevocacionTests(APITestCase):
    def setUp(self):
        # Crear Jefa
        self.jefa = Personal.objects.create_user(
            email="jefa_test@sgtp.hospital.gob.ar",
            password="SeguridadHospital2026!",
            nombre="Laura",
            apellidos="Gómez",
            dni=30111222,
            rol=RolPersonal.JEFA,
            matricula="MN-8844",
            inicio_turno="08:00:00",
            fin_turno="16:00:00",
            activo=True
        )

        # Crear Personal asistencial de Box
        self.staff_box = Personal.objects.create_user(
            email="tecnico_box_test@sgtp.hospital.gob.ar",
            password="SeguridadHospital2026!",
            nombre="Carlos",
            apellidos="Benítez",
            dni=35333444,
            rol=RolPersonal.BOX,
            matricula="MN-5511",
            inicio_turno="08:00:00",
            fin_turno="16:00:00",
            activo=True
        )

        self.client.force_authenticate(user=self.jefa)

    def test_single_exception_overnight_splits_both_days(self):
        """
        Al autorizar una excepción de 22:00 a 02:00 (cruza medianoche),
        el backend debe desglosar en dos HabilitacionHoraria correlativas:
        - Tramo 1: Fecha D, 22:00:00 a 23:59:59
        - Tramo 2: Fecha D+1, 00:00:00 a 02:00:00
        """
        fecha_d1 = date(2026, 10, 20)
        url = "/app/users/habilitaciones-horarias/"
        payload = {
            "personal": self.staff_box.pk,
            "fecha": str(fecha_d1),
            "hora_inicio": "22:00:00",
            "hora_fin": "02:00:00",
            "motivo": "Refuerzo nocturno de guardia"
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn("tramos", response.data)
        self.assertEqual(len(response.data["tramos"]), 2)

        # Verificar en base de datos
        habs = HabilitacionHoraria.objects.filter(personal=self.staff_box, activa=True).order_by("fecha", "hora_inicio")
        self.assertEqual(habs.count(), 2)

        # Tramo 1
        self.assertEqual(habs[0].fecha, fecha_d1)
        self.assertEqual(habs[0].hora_inicio, time(22, 0))
        self.assertEqual(habs[0].hora_fin, time(23, 59, 59))

        # Tramo 2
        self.assertEqual(habs[1].fecha, fecha_d1 + timedelta(days=1))
        self.assertEqual(habs[1].hora_inicio, time(0, 0))
        self.assertEqual(habs[1].hora_fin, time(2, 0))

    def test_monthly_planning_overnight_computes_hours_and_splits_days(self):
        """
        Planificación mensual con franja nocturna (22:00 a 02:00, 4 hs diarias).
        Para 2 días seleccionados, debe computar 8.0 hs totales y crear 4 registros diarios.
        """
        dias = [date(2026, 10, 15), date(2026, 10, 22)]
        url = "/app/users/planificaciones-horas-extras/"
        payload = {
            "personal": self.staff_box.pk,
            "anio": 2026,
            "mes": 10,
            "tipo_extension": TipoExtensionChoices.POST_TURNO,
            "hora_inicio": "22:00:00",
            "hora_fin": "02:00:00",
            "motivo": "Guardia programada nocturna",
            "fechas_seleccionadas": [str(d) for d in dias]
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        plan = PlanificacionHorasExtras.objects.get(personal=self.staff_box, anio=2026, mes=10)
        # Duración: (24 - 22) + 2 = 4 hs diarias * 2 días = 8.0 hs
        self.assertEqual(float(plan.total_horas_mensual), 8.0)

        # 2 días * 2 tramos = 4 registros diarios
        habs = HabilitacionHoraria.objects.filter(planificacion=plan, activa=True)
        self.assertEqual(habs.count(), 4)

    def test_revocar_lote_alcance_todas(self):
        """Revoca todas las habilitaciones activas del mes para el personal."""
        # Crear 3 habilitaciones
        for d in range(1, 4):
            HabilitacionHoraria.objects.create(
                personal=self.staff_box,
                aprobado_por=self.jefa,
                fecha=date(2026, 10, d),
                hora_inicio=time(16, 0),
                hora_fin=time(20, 0),
                motivo="Test",
                activa=True
            )

        self.assertEqual(HabilitacionHoraria.objects.filter(personal=self.staff_box, activa=True).count(), 3)

        url = "/app/users/habilitaciones-horarias/revocar-lote/"
        payload = {
            "personal_id": self.staff_box.pk,
            "alcance": "todas",
            "anio": 2026,
            "mes": 10
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["revocadas_count"], 3)
        self.assertEqual(HabilitacionHoraria.objects.filter(personal=self.staff_box, activa=True).count(), 0)

    def test_revocar_lote_alcance_semana(self):
        """Revoca las habilitaciones de la semana asistencial de la fecha indicada."""
        # Lunes 12 de Octubre al Viernes 16 de Octubre 2026
        for d in [12, 14, 16]:
            HabilitacionHoraria.objects.create(
                personal=self.staff_box,
                aprobado_por=self.jefa,
                fecha=date(2026, 10, d),
                hora_inicio=time(16, 0),
                hora_fin=time(18, 0),
                motivo="Semana 1",
                activa=True
            )

        # Otra semana (20 de Octubre)
        HabilitacionHoraria.objects.create(
            personal=self.staff_box,
            aprobado_por=self.jefa,
            fecha=date(2026, 10, 20),
            hora_inicio=time(16, 0),
            hora_fin=time(18, 0),
            motivo="Semana 2",
            activa=True
        )

        url = "/app/users/habilitaciones-horarias/revocar-lote/"
        # Enviamos Miércoles 14 de Octubre
        payload = {
            "personal_id": self.staff_box.pk,
            "alcance": "semana",
            "fecha": "2026-10-14"
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["revocadas_count"], 3)

        # La de la semana 2 sigue activa
        self.assertEqual(HabilitacionHoraria.objects.filter(personal=self.staff_box, activa=True).count(), 1)
        self.assertTrue(HabilitacionHoraria.objects.filter(personal=self.staff_box, fecha=date(2026, 10, 20), activa=True).exists())

    def test_revocar_lote_alcance_rango(self):
        """Revoca dentro de un rango de fechas exacto."""
        for d in [5, 10, 15, 20]:
            HabilitacionHoraria.objects.create(
                personal=self.staff_box,
                aprobado_por=self.jefa,
                fecha=date(2026, 10, d),
                hora_inicio=time(16, 0),
                hora_fin=time(18, 0),
                motivo="Rango test",
                activa=True
            )

        url = "/app/users/habilitaciones-horarias/revocar-lote/"
        payload = {
            "personal_id": self.staff_box.pk,
            "alcance": "rango",
            "fecha_desde": "2026-10-08",
            "fecha_hasta": "2026-10-18"
        }

        response = self.client.post(url, payload, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Debe revocar días 10 y 15 (2 registros)
        self.assertEqual(response.data["revocadas_count"], 2)

        activas = HabilitacionHoraria.objects.filter(personal=self.staff_box, activa=True)
        self.assertEqual(activas.count(), 2)
        fechas_activas = set(activas.values_list("fecha", flat=True))
        self.assertEqual(fechas_activas, {date(2026, 10, 5), date(2026, 10, 20)})
