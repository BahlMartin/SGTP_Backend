from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0010_alter_ticketestudios_motivo_modificacion'),
    ]

    operations = [
        migrations.AddField(
            model_name='asignacionesbox',
            name='observaciones_cierre',
            field=models.CharField(
                blank=True,
                default='',
                max_length=255,
                null=True,
                verbose_name='Observaciones al cierre o cancelación de atención',
            ),
        ),
    ]

