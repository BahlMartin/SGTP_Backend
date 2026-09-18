"""
Módulo de Modelos ORM para SGTP Backend.
Centraliza las entidades del sistema: Usuarios, Items (Estudios), Pacientes, Triage y Reportes.
"""
from app.models.common import SoftDeleteModel
from app.models.user import Personal, User, RolPersonal, HabilitacionHoraria
from app.models.item import Estudios, Item, CatalogItem, TipoMuestra
from app.models.patient import Paciente
from app.models.triage import (
    Box,
    Ticket,
    AsignacionesBox,
    EstadoBox,
    EstadoTicket,
    ClasificacionTriage,
    MotivoCierreBox,
)
from app.models.report import HistorialReporteDiario

__all__ = [
    'SoftDeleteModel',
    'Personal',
    'User',
    'RolPersonal',
    'HabilitacionHoraria',
    'Estudios',
    'Item',
    'CatalogItem',
    'TipoMuestra',
    'Paciente',
    'Box',
    'Ticket',
    'AsignacionesBox',
    'EstadoBox',
    'EstadoTicket',
    'ClasificacionTriage',
    'MotivoCierreBox',
    'HistorialReporteDiario',
]
