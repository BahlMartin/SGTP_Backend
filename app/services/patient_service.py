"""
Servicio de Integridad y Gestión Asistencial de Pacientes.
Centraliza la lógica de negocio y validación bidireccional entre DNI y Número de Afiliado (FLE).
"""
from typing import Any, Dict, Optional
from rest_framework.exceptions import ValidationError
from app.models.patient import Paciente


class PatientService:
    """
    Servicio de dominio para Pacientes.
    Garantiza la consistencia e integridad entre DNI y Número de Afiliado/Obra Social.
    """

    @classmethod
    def normalizar_num_afiliado(cls, valor: Optional[Any]) -> str:
        """Limpia y normaliza el número de afiliado."""
        if valor is None:
            return ""
        return str(valor).strip()

    @classmethod
    def validar_consistencia_afiliado_y_dni(
        cls,
        dni: int,
        num_obra_social: Optional[str] = None,
        exclude_paciente_id: Optional[int] = None,
        field_error_key: str = 'paciente_datos'
    ) -> None:
        """
        Valida bidireccionalmente la relación entre DNI y Número de Afiliado:
        1. Si el DNI ya existe, el número de afiliado no puede diferir del registrado.
        2. Si el número de afiliado está presente, no puede pertenecer a otro paciente activo con diferente DNI.
        """
        afiliado_ingresado = cls.normalizar_num_afiliado(num_obra_social)

        # 1. Verificar si el paciente con ese DNI ya existe
        paciente_query = Paciente.objects.filter(dni=dni, is_deleted=False)
        if exclude_paciente_id:
            paciente_query = paciente_query.exclude(id_paciente=exclude_paciente_id)

        paciente_existente = paciente_query.first()

        if paciente_existente:
            afiliado_existente = cls.normalizar_num_afiliado(paciente_existente.num_obra_social)
            # Regla 1: Mismo DNI no puede tener diferente número de afiliado
            if afiliado_existente and afiliado_ingresado and afiliado_existente != afiliado_ingresado:
                raise ValidationError({
                    field_error_key: (
                        f"Datos inválidos: El paciente con DNI {dni} ya se encuentra registrado "
                        f"con el número de afiliado '{afiliado_existente}'. "
                        f"No coincide con el número ingresado '{afiliado_ingresado}'."
                    )
                })

        # Regla 2: Número de afiliado duplicado en otro paciente (distinto DNI)
        if afiliado_ingresado:
            otros_pacientes = Paciente.objects.filter(is_deleted=False).exclude(dni=dni)
            if exclude_paciente_id:
                otros_pacientes = otros_pacientes.exclude(id_paciente=exclude_paciente_id)

            for otro in otros_pacientes:
                otro_afiliado = cls.normalizar_num_afiliado(otro.num_obra_social)
                if otro_afiliado and otro_afiliado == afiliado_ingresado:
                    raise ValidationError({
                        field_error_key: (
                            f"Datos inválidos: El número de afiliado '{afiliado_ingresado}' ya se encuentra "
                            f"registrado para otro paciente (DNI {otro.dni} - {otro.apellidos}, {otro.nombre})."
                        )
                    })

    @classmethod
    def resolver_o_crear_paciente_para_ticket(cls, paciente_datos: Dict[str, Any]) -> Paciente:
        """
        Resuelve un paciente preexistente o crea uno nuevo a partir del payload de ticket,
        aplicando validación estricta de consistencia de DNI y Afiliado.
        """
        dni_raw = paciente_datos.get('dni')
        if not dni_raw:
            raise ValidationError({
                'paciente_datos': "El campo 'dni' es requerido dentro de paciente_datos."
            })

        try:
            dni_val = int(str(dni_raw).replace('.', '').strip())
        except (ValueError, TypeError):
            raise ValidationError({
                'paciente_datos': "El DNI proporcionado debe ser numérico."
            })

        num_afiliado_ingresado = cls.normalizar_num_afiliado(paciente_datos.get('num_obra_social', ''))

        # Ejecutar validaciones de integridad
        cls.validar_consistencia_afiliado_y_dni(
            dni=dni_val,
            num_obra_social=num_afiliado_ingresado,
            field_error_key='paciente_datos'
        )

        paciente_existente = Paciente.objects.filter(dni=dni_val, is_deleted=False).first()
        if paciente_existente:
            return paciente_existente

        # Si no existe, crear el nuevo registro
        return Paciente.objects.create(
            dni=dni_val,
            nombre=str(paciente_datos.get('nombre', 'Sin Nombre')).strip(),
            apellidos=str(paciente_datos.get('apellidos', 'Sin Apellido')).strip(),
            obra_social=str(paciente_datos.get('obra_social', 'Particular')).strip(),
            num_obra_social=num_afiliado_ingresado
        )


__all__ = ['PatientService']
