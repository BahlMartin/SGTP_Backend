from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0006_dias_laborales_personal'),
    ]

    operations = [
        migrations.CreateModel(
            name='PlanificacionHorasExtras',
            fields=[
                ('id', models.AutoField(primary_key=True, serialize=False)),
                ('anio', models.SmallIntegerField(verbose_name='Año Calendario')),
                ('mes', models.SmallIntegerField(verbose_name='Mes Calendario (1-12)')),
                ('tipo_extension', models.CharField(choices=[
                    ('POST_TURNO', 'Post-Turno (Continuación)'),
                    ('PRE_TURNO', 'Pre-Turno (Anticipada)'),
                    ('GUARDIA', 'Guardia de Fin de Semana / Franco'),
                    ('PERSONALIZADA', 'Franja Personalizada')
                ], default='POST_TURNO', max_length=20)),
                ('hora_inicio', models.TimeField()),
                ('hora_fin', models.TimeField()),
                ('total_horas_mensual', models.DecimalField(decimal_places=2, default=0.0, max_digits=6, verbose_name='Total Horas Extras Computadas')),
                ('motivo', models.CharField(max_length=255)),
                ('activa', models.BooleanField(default=True)),
                ('fecha_creacion', models.DateTimeField(auto_now_add=True)),
                ('aprobado_por', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='planificaciones_otorgadas', to='app.personal')),
                ('personal', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='planificaciones_horas_extras', to='app.personal')),
            ],
            options={
                'verbose_name': 'Planificación Mensual de Horas Extras',
                'verbose_name_plural': 'Planificaciones Mensuales de Horas Extras',
                'db_table': 'sgtp_planificacion_horas_extras',
                'ordering': ['-anio', '-mes'],
            },
        ),
        migrations.AddConstraint(
            model_name='planificacionhorasextras',
            constraint=models.UniqueConstraint(fields=('personal', 'anio', 'mes'), name='unique_planificacion_personal_mes'),
        ),
        migrations.AddField(
            model_name='habilitacionhoraria',
            name='planificacion',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='habilitaciones_diarias', to='app.planificacionhorasextras'),
        ),
    ]
