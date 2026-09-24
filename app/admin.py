"""
Configuración del Panel Administrativo de Django para SGTP.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from app.models import (
    Personal,
    HabilitacionHoraria,
    Estudios,
    Paciente,
    Box,
    Ticket,
    AsignacionesBox,
    TicketEstudios,
    HistorialReporteDiario,
)


@admin.register(Personal)
class PersonalAdmin(admin.ModelAdmin):
    list_display = ['email', 'nombre', 'apellidos', 'dni', 'rol', 'activo', 'cant_intentos']
    list_filter = ['rol', 'activo']
    search_fields = ['email', 'nombre', 'apellidos', 'dni']
    ordering = ['apellidos', 'nombre']


@admin.register(HabilitacionHoraria)
class HabilitacionHorariaAdmin(admin.ModelAdmin):
    list_display = ['personal', 'aprobado_por', 'fecha', 'hora_inicio', 'hora_fin', 'activa']
    list_filter = ['activa', 'fecha']
    search_fields = ['personal__email', 'motivo']


@admin.register(Estudios)
class EstudiosAdmin(admin.ModelAdmin):
    list_display = ['codigo_practica', 'nombre', 'seccion', 'tipo_muestra', 'activo']
    list_filter = ['seccion', 'tipo_muestra', 'activo']
    search_fields = ['codigo_practica', 'nombre']


@admin.register(Paciente)
class PacienteAdmin(admin.ModelAdmin):
    list_display = ['dni', 'nombre', 'apellidos', 'obra_social', 'num_obra_social', 'fecha_creacion', 'is_deleted']
    search_fields = ['dni', 'obra_social']
    list_filter = ['obra_social', 'is_deleted', 'fecha_creacion']


@admin.register(Box)
class BoxAdmin(admin.ModelAdmin):
    list_display = ['numero', 'estado', 'activo', 'discapacidad']
    list_filter = ['estado', 'activo', 'discapacidad']


class TicketEstudiosInline(admin.TabularInline):
    model = TicketEstudios
    extra = 0


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ['num_totem', 'clasificacion_triage', 'estado', 'box_actual', 'fecha_hora_admision', 'is_deleted']
    list_filter = ['clasificacion_triage', 'estado', 'is_deleted']
    search_fields = ['num_totem']
    inlines = [TicketEstudiosInline]


@admin.register(AsignacionesBox)
class AsignacionesBoxAdmin(admin.ModelAdmin):
    list_display = ['box', 'personal', 'ticket', 'motivo_cierre', 'fecha_hora_inicio', 'fecha_hora_final']
    list_filter = ['motivo_cierre']
    search_fields = ['box__numero', 'personal__email']


@admin.register(HistorialReporteDiario)
class HistorialReporteDiarioAdmin(admin.ModelAdmin):
    list_display = ['fecha_reporte', 'total_pacientes_atendidos', 'total_estudios_realizados', 'exitoso', 'fecha_hora_envio']
    list_filter = ['exitoso', 'fecha_reporte']
