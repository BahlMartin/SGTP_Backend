from django.db import migrations, models
import django.db.models.deletion


def poblar_dias_laborales_por_defecto(apps, schema_editor):
    Personal = apps.get_model('app', 'Personal')
    DiaLaboralPersonal = apps.get_model('app', 'DiaLaboralPersonal')
    # Por defecto, asignar Lunes a Viernes (0 a 4) a todo el personal preexistente
    for p in Personal.objects.all():
        for d in range(5):
            DiaLaboralPersonal.objects.get_or_create(personal=p, dia_semana=d)


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0005_paciente_obra_social'),
    ]

    operations = [
        migrations.CreateModel(
            name='DiaLaboralPersonal',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('dia_semana', models.SmallIntegerField(choices=[
                    (0, 'Lunes'), (1, 'Martes'), (2, 'Miércoles'),
                    (3, 'Jueves'), (4, 'Viernes'), (5, 'Sábado'), (6, 'Domingo')
                ], verbose_name='Día de la Semana')),
                ('personal', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='dias_laborales',
                    to='app.personal'
                )),
            ],
            options={
                'verbose_name': 'Día Laboral de Personal',
                'verbose_name_plural': 'Días Laborales de Personal',
                'db_table': 'sgtp_personal_dias_laborales',
                'ordering': ['dia_semana'],
            },
        ),
        migrations.AddConstraint(
            model_name='dialaboralpersonal',
            constraint=models.UniqueConstraint(fields=('personal', 'dia_semana'), name='unique_personal_dia_laboral'),
        ),
        migrations.AddIndex(
            model_name='habilitacionhoraria',
            index=models.Index(fields=['personal', 'fecha', 'activa', 'hora_inicio', 'hora_fin'], name='sgtp_hab_idx'),
        ),
        migrations.RunPython(poblar_dias_laborales_por_defecto, reverse_code=migrations.RunPython.noop),
    ]
