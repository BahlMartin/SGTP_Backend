"""
Comando de gestión para actualizar los tiempos de demora estimados (en horas)
del catálogo de Estudios según estándares internacionales de laboratorio clínico bioquímico.
Uso: python manage.py seed_demora_estudios
"""
from django.core.management.base import BaseCommand
from app.models.studies import Estudios, Seccion


class Command(BaseCommand):
    help = "Actualiza las horas de demora de los estudios clínicos según estándares de laboratorio bioquímico."

    def handle(self, *args, **options):
        # 1. Tiempos base por Sección (en horas)
        # 24 hs = 1 día hábil, 48 hs = 2 días, 72 hs = 3 días, 96 hs = 4 días, 120 hs = 5 días hábiles (1 semana)
        tiempos_por_seccion = {
            Seccion.HEMATOLOGIA: 24,       # Hemogramas, frotis, coagulogramas: 24 hs
            Seccion.QUIMICA: 24,            # Glucosa, urea, creatinina, ionograma, hepatograma: 24 hs
            Seccion.ORINA: 24,              # Orina completa, sedimento: 24 hs
            Seccion.PARASITOLOGIA: 72,      # Parasitológico seriado, Graham: 72 hs (3 días)
            Seccion.BACTEREOLOGIA: 72,      # Cultivos estándar (urocultivo, fauces): 72 hs (3 días)
            Seccion.ENDOCRINOLOGIA: 48,     # Perfil tiroideo, hormonas: 48 hs (2 días)
            Seccion.SEROLOGIA: 48,          # VDRL, anticuerpos básicos: 48 hs (2 días)
            Seccion.IAC: 48,                # Infecciones asociadas al cuidado / serologías: 48 hs (2 días)
            Seccion.MARCADORES_ONCOLOGICOS: 72, # PSA, CA-125, CEA: 72 hs (3 días)
            Seccion.DETERMINACIONES_ESPECIALES: 72, # Vitamina D, B12, PTH: 72 hs (3 días)
            Seccion.TOXICOLOGIA: 48,        # Screening de drogas: 48 hs (2 días)
            Seccion.VARIOS: 24,
        }

        # Aplicar base por sección
        for seccion, horas in tiempos_por_seccion.items():
            Estudios.objects.filter(seccion=seccion).update(demora_horas=horas)

        # 2. Reglas específicas por nombre o código de práctica (estándar clínico internacional)
        # Estudios rápidos / urgencias (2 a 12 horas)
        rapidos = [
            'GUARDIA', 'COAGULOGRAMA GUARDIA', 'AC LACTICO', 'CARBOXI HEMOGLOBINA',
            'TROPONINA US', 'PROCALCITONINA', 'CPK / CKMB', 'TEST DE EMBARAZO'
        ]
        for term in rapidos:
            Estudios.objects.filter(nombre__icontains=term).update(demora_horas=12)

        # Cultivos prolongados y microbiología compleja (96 a 120 horas / 4 a 5 días hábiles)
        cultivos_largos = [
            'COPROCULTIVO', 'HEMOCULTIVO', 'RETROCULTIVO', 'PUNTA DE CATETER',
            'LIQUIDO DE PUNCION', 'CLOSTRIDIUM', 'WESTERN BLOT', 'SCL-70', 'JO-1',
            'TRANSGLUTAMINASA', 'ENDOMISIO', 'GLIADINA', 'CITRULINA', 'ANCA', 'PR3', 'MPO'
        ]
        for term in cultivos_largos:
            Estudios.objects.filter(nombre__icontains=term).update(demora_horas=120)

        # Cultivo de Koch (tuberculosis / micobacterias): incubación prolongada (mínimo 15 días / 360 horas)
        Estudios.objects.filter(nombre__icontains='KOCH').update(demora_horas=360)

        # Urocultivo y exudados estándar: 72 horas (3 días hábiles)
        Estudios.objects.filter(nombre__icontains='UROCULTIVO').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='FAUCES').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='URETRAL').update(demora_horas=72)

        # Orinas de 24 horas y clearance: 48 horas (2 días hábiles)
        Estudios.objects.filter(nombre__icontains='24HS').update(demora_horas=48)
        Estudios.objects.filter(nombre__icontains='24 HS').update(demora_horas=48)
        Estudios.objects.filter(nombre__icontains='CLEARENCE').update(demora_horas=48)

        # Marcadores oncológicos y hormonas complejas (72 a 96 horas)
        Estudios.objects.filter(nombre__icontains='ANTIMULLERIANA').update(demora_horas=96)
        Estudios.objects.filter(nombre__icontains='TIROGLOBULINA').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='VITAMINA D').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='VITAMINA B12').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='ACIDO FOLICO').update(demora_horas=72)
        Estudios.objects.filter(nombre__icontains='PSA').update(demora_horas=48)

        # Perfiles ambulatorios agrupados (48 horas)
        Estudios.objects.filter(nombre__icontains='PREQUIRURGICO').update(demora_horas=48)
        Estudios.objects.filter(nombre__icontains='CONTROL').update(demora_horas=48)
        Estudios.objects.filter(nombre__icontains='NEFRO').update(demora_horas=48)

        total = Estudios.objects.count()
        ejemplos = Estudios.objects.filter(activo=True).order_by('-demora_horas')[:10]
        self.stdout.write(self.style.SUCCESS(f"Se actualizaron exitosamente las demoras estimadas de {total} estudios."))
        for e in ejemplos:
            dias = round(e.demora_horas / 24, 1)
            self.stdout.write(f" - [{e.codigo_practica}] {e.nombre}: {e.demora_horas} hs (~{dias} días hábiles)")

