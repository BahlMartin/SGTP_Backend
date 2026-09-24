# Generated for adding obra_social to Paciente

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0004_estudios_seccion_alter_estudios_nombre_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='paciente',
            name='obra_social',
            field=models.CharField(
                default='Particular',
                max_length=150,
                verbose_name='Nombre de la Obra Social / Cobertura Médica'
            ),
            preserve_default=False,
        ),
    ]
