# Generated manually for idempotent backfill of historical OCR crops

import re
from django.db import migrations


_VHASH_RE = re.compile(r'vhash=([0-9a-fA-F]{16,32})')


def _clean_img(img):
    if not isinstance(img, str):
        return ''
    limpia = img.strip()
    if limpia.startswith('data:image/') and len(limpia) <= 100_000:
        return limpia
    return ''


def _extract_vhash(img):
    match = _VHASH_RE.search(img or '')
    return match.group(1).lower() if match else ''


def backfill_recortes_historicos(apps, schema_editor):
    Estudios = apps.get_model('app', 'Estudios')
    EstudioAliasAprendido = apps.get_model('app', 'EstudioAliasAprendido')
    PerfilEstudioPatron = apps.get_model('app', 'PerfilEstudioPatron')
    RecorteImagenEstudio = apps.get_model('app', 'RecorteImagenEstudio')
    RecorteEstudio = apps.get_model('app', 'RecorteEstudio')

    estudios_activos_ids = set(
        Estudios.objects.filter(activo=True).values_list('id', flat=True)
    )

    recortes_por_img = {}
    for rec in RecorteImagenEstudio.objects.filter(es_descarte=False).order_by('-fecha_registro', '-id'):
        img_limpia = _clean_img(rec.imagen_muestra)
        if img_limpia and img_limpia not in recortes_por_img:
            recortes_por_img[img_limpia] = rec

    aliases = (
        EstudioAliasAprendido.objects
        .exclude(estado_revision='DESCARTADO')
        .filter(estudio_id__isnull=False)
        .exclude(imagen_muestra='')
        .exclude(imagen_muestra__isnull=True)
    )
    for alias in aliases:
        if alias.estudio_id not in estudios_activos_ids:
            continue
        img = _clean_img(alias.imagen_muestra)
        if not img:
            continue
        rec = recortes_por_img.get(img)
        if rec is None:
            rec = RecorteImagenEstudio.objects.create(
                firma_visual=_extract_vhash(img),
                texto_detectado=(alias.texto_patron or '')[:255],
                imagen_muestra=img,
                es_descarte=False,
            )
            recortes_por_img[img] = rec
        RecorteEstudio.objects.get_or_create(recorte=rec, estudio_id=alias.estudio_id)

    patrones = (
        PerfilEstudioPatron.objects
        .filter(activo=True)
        .exclude(imagen_muestra='')
        .exclude(imagen_muestra__isnull=True)
    )
    for patron in patrones:
        img = _clean_img(patron.imagen_muestra)
        if not img:
            continue
        eids = [
            int(e) for e in (patron.estudios_ids or [])
            if str(e).isdigit() and int(e) in estudios_activos_ids
        ]
        if not eids:
            continue
        rec = recortes_por_img.get(img)
        if rec is None:
            rec = RecorteImagenEstudio.objects.create(
                firma_visual=_extract_vhash(img),
                texto_detectado=(patron.nombre_perfil or '')[:255],
                imagen_muestra=img,
                es_descarte=False,
            )
            recortes_por_img[img] = rec
        for eid in dict.fromkeys(eids):
            RecorteEstudio.objects.get_or_create(recorte=rec, estudio_id=eid)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0020_calibracioncomparadorvisual_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_recortes_historicos, migrations.RunPython.noop),
    ]
