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

from app.schemas.item import EstudiosSerializer, ItemSchema, CatalogItemSchema
from app.schemas.patient import PacienteSerializer, PatientSchema
from app.schemas.triage import (
    BoxSerializer,
    TicketEstudiosSerializer,
    TicketCreateSerializer,
    TicketDetailSerializer,
    AsignacionesBoxSerializer,
    CerrarAtencionSerializer,
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

