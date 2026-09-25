"""
Módulo de Esquemas y Serializadores de SGTP Backend.
"""
from app.schemas.user import (
    PersonalAuthSerializer,
    PersonalSerializer,
    UserSchema,
    LoginSerializer,
    LoginRequestSchema,
    EmergencyUnlockSerializer,
    EmergencyUnlockSchema,
    HabilitacionHorariaSerializer,
)

from app.schemas.studies import EstudiosSerializer, ItemSchema, CatalogItemSchema
from app.schemas.patient import PacienteSerializer, PatientSchema
from app.schemas.box import (
    BoxSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
)
from app.schemas.ticket import (
    TicketEstudiosSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
)
from app.schemas.report import HistorialReporteDiarioSerializer, ReportSchema
from app.schemas.ocr import OCRScanRequestSerializer, OCRScanResponseSerializer

__all__ = [
    'PersonalAuthSerializer',
    'PersonalSerializer',
    'UserSchema',
    'LoginSerializer',
    'LoginRequestSchema',
    'EmergencyUnlockSerializer',
    'EmergencyUnlockSchema',
    'HabilitacionHorariaSerializer',
    'EstudiosSerializer',
    'ItemSchema',
    'CatalogItemSchema',
    'PacienteSerializer',
    'PatientSchema',
    'BoxSerializer',
    'TicketEstudiosSerializer',
    'TicketCreateSerializer',
    'TicketDetailSerializer',
    'AsignacionesBoxSerializer',
    'CerrarAtencionSerializer',
    'HistorialReporteDiarioSerializer',
    'ReportSchema',
    'OCRScanRequestSerializer',
    'OCRScanResponseSerializer',
]

