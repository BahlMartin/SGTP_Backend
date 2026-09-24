"""
Operaciones CRUD para Pacientes.
"""
from typing import Optional, List
from app.models.patient import Paciente


class CRUDPatient:
    """Capa de acceso a datos para Pacientes."""

    @staticmethod
    def get_by_id(paciente_id: int) -> Optional[Paciente]:
        return Paciente.objects.filter(id_paciente=paciente_id, is_deleted=False).first()

    @staticmethod
    def get_by_dni(dni: int) -> Optional[Paciente]:
        return Paciente.objects.filter(dni=dni, is_deleted=False).first()

    @staticmethod
    def get_all_active() -> List[Paciente]:
        return list(Paciente.objects.filter(is_deleted=False).order_by('-fecha_creacion'))

    @staticmethod
    def create_patient(dni: int, nombre: str, apellidos: str, num_obra_social: str, obra_social: str = "Particular") -> Paciente:
        return Paciente.objects.create(
            dni=dni,
            nombre=nombre,
            apellidos=apellidos,
            obra_social=obra_social,
            num_obra_social=num_obra_social
        )


crud_patient = CRUDPatient()
