"""
Módulo CRUD: Operaciones y Consultas de Acceso a Datos.
"""
from app.crud.crud_user import crud_user, CRUDUser
from app.crud.crud_item import crud_item, CRUDItem
from app.crud.crud_patient import crud_patient, CRUDPatient
from app.crud.crud_triage import crud_triage, CRUDTriage
from app.crud.crud_report import crud_report, CRUDReport

__all__ = [
    'crud_user',
    'CRUDUser',
    'crud_item',
    'CRUDItem',
    'crud_patient',
    'CRUDPatient',
    'crud_triage',
    'CRUDTriage',
    'crud_report',
    'CRUDReport',
]
