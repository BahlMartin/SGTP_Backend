"""
Módulo de Modelos ORM para SGTP Backend.
Centraliza las entidades del sistema: Usuarios, Items (Estudios), Pacientes, Triage y Reportes.
"""
from app.models.common import SoftDeleteModel
from app.models.user import Personal, User, RolPersonal, HabilitacionHoraria
from app.models.studies import Estudios, Item, CatalogItem, TipoMuestra, Seccion, SeccionEstudio
from app.models.patient import Paciente
from app.models.box import (
    Box,
    AsignacionesBox,
    EstadoBox,
    MotivoCierreBox,
)
from app.models.ticket import (
    Ticket,
    TicketEstudios,
    EstadoTicket,
    ClasificacionTriage,
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
    'Seccion',
    'SeccionEstudio',
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
