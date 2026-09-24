# Jerarquía de Modelos y Herencias del Backend (SGTP)

Este documento detalla todas las entidades de base de datos del sistema, su árbol de herencia, relaciones relacionales y la estrategia de borrado (lógico vs físico) adoptada en cada una.

---

## 1. Diagrama de Herencia de Modelos

```mermaid
classDiagram
    direction TB

    class Model["django.db.models.Model"] {
        <<Django Core>>
    }

    class AbstractBaseUser["django.contrib.auth.models.AbstractBaseUser"] {
        <<Django Auth Core>>
    }

    class SoftDeleteModel["SoftDeleteModel (Abstracto)"] {
        +BooleanField is_deleted
        +objects SoftDeleteManager
        +all_objects AllObjectsManager
        +delete()
        +hard_delete()
        +restore()
    }

    Model <|-- AbstractBaseUser
    Model <|-- SoftDeleteModel

    %% Modelos que heredan de SoftDeleteModel
    SoftDeleteModel <|-- Paciente : hereda borrado lógico
    SoftDeleteModel <|-- Ticket : hereda borrado lógico

    %% Modelos que heredan de AbstractBaseUser
    AbstractBaseUser <|-- Personal : usuario principal

    %% Modelos que heredan directamente de Model
    Model <|-- Estudios : catálogo de análisis
    Model <|-- Box : puesto de atención
    Model <|-- AsignacionesBox : historial box
    Model <|-- TicketEstudios : detalle N:M
    Model <|-- HabilitacionHoraria : excepciones turno
    Model <|-- HistorialReporteDiario : trazabilidad reportes
```

---

## 2. Mapa Consolidado de Modelos

| Modelo | Clase Padre / Herencia | Estrategia de Borrado | Auditoría (Auditlog) |
| :--- | :--- | :--- | :--- |
| **`SoftDeleteModel`** | `models.Model` *(Abstracto)* | Base del patrón Soft Delete (`is_deleted=True`) | N/A |
| **`Paciente`** | **`SoftDeleteModel`** | **Borrado Lógico** heredado (`is_deleted=True`) | ✅ Registrado |
| **`Ticket`** | **`SoftDeleteModel`** | **Borrado Lógico** heredado (`is_deleted=True`) | ✅ Registrado |
| **`Personal`** *(User)* | **`AbstractBaseUser`** | **Borrado Lógico Propio** (`activo=False`) | ✅ Registrado |
| **`HabilitacionHoraria`** | `models.Model` | **Borrado Lógico Propio** (`activa=False`) | ✅ Registrado |
| **`Estudios`** *(Item)* | `models.Model` | **Físico / Flag Operativo** (`activo=False`) | ✅ Registrado |
| **`Box`** | `models.Model` | Físico estándar | ✅ Registrado |
| **`AsignacionesBox`** | `models.Model` | Inmutable / Histórico | ✅ Registrado |
| **`TicketEstudios`** | `models.Model` | Cascada por Ticket (`CASCADE`) / Protegido por Estudio (`PROTECT`) | ✅ Registrado |
| **`HistorialReporteDiario`** | `models.Model` | Registro inmutable de logs Celery | ✅ Registrado |

---

## 3. Detalle por Modelo y Módulo

### 3.1. Módulo Común (`app/models/common.py`)

#### `SoftDeleteModel(models.Model)`
* **Tipo:** Modelo Abstracto (`abstract = True`).
* **Propósito:** Proporcionar infraestructura reutilizable de borrado lógico a modelos críticos asistenciales.
* **Campos añadidos:**
  * `is_deleted`: Booleano indexado (`db_index=True`, default=`False`).
* **Managers:**
  * `objects = SoftDeleteManager()`: Sobrescribe el manager por defecto para filtrar automáticamente y solo devolver registros vivos (`is_deleted=False`).
  * `all_objects = AllObjectsManager()`: Retorna todos los registros (incluyendo borrados) para fines administrativos y forenses.
* **Métodos principales:**
  * `delete()`: Ejecuta `self.is_deleted = True` y guarda únicamente ese campo.
  * `restore()`: Reactiva el registro seteando `self.is_deleted = False`.
  * `hard_delete()`: Ejecuta el `DELETE FROM` físico definitivo si se requiere mantenimiento técnico.

---

### 3.2. Módulo de Pacientes (`app/models/patient.py`)

#### `Paciente(SoftDeleteModel)`
* **Herencia:** [`SoftDeleteModel`](file:///c:/Users/LENOVO%20i5/Desktop/SGTP/SGTP%20Backend/app/models/common.py#L42) ➔ `models.Model`.
* **Propósito:** Registro central de pacientes del hospital.
* **Seguridad (FLE):** Cifrado a nivel de campo en reposo (*Field-Level Encryption* con Fernet AES-128-CBC) para datos sensibles de salud (PHI).
* **Campos destacados:**
  * `id_paciente`: Clave primaria autoincremental.
  * `dni`: Entero único e indexado (`unique=True, db_index=True`).
  * `obra_social`: `CharField` (nombre de la cobertura/prepaga para filtros y reportes).
  * `num_obra_social`, `nombre`, `apellidos`: `FernetEncryptedCharField` (cifrados FLE).
  * `fecha_creacion`: Timestamp automático.
  * `is_deleted`: Heredado de `SoftDeleteModel`.

---

### 3.3. Módulo de Triage y Box (`app/models/triage.py`)

#### `Ticket(SoftDeleteModel)`
* **Herencia:** [`SoftDeleteModel`](file:///c:/Users/LENOVO%20i5/Desktop/SGTP/SGTP%20Backend/app/models/common.py#L42) ➔ `models.Model`.
* **Propósito:** Turno y solicitud asistencial generada en el tótem / admisión.
* **Relaciones:**
  * `paciente`: `ForeignKey(Paciente, on_delete=models.PROTECT)`.
  * `operador_admision`: `ForeignKey(Personal, on_delete=models.PROTECT)`.
  * `box_asignado`: `ForeignKey(Box, null=True, on_delete=models.PROTECT)`.
* **Campos destacados:**
  * `num_totem`: Entero no secuencial para llamado público.
  * `estado`: Enum `EstadoTicket` (Esperando_Llamado, En_Atencion, Atendido, Cancelado).
  * `clasificacion_triage`: Enum `ClasificacionTriage` (Guardia, Medicos, Discapacidad, Oncologia, Extraccion_con_Turno, etc.).
  * `is_deleted`: Heredado de `SoftDeleteModel`.

#### `Box(models.Model)`
* **Herencia:** `models.Model` directo.
* **Propósito:** Box físico de atención o extracción de muestras.
* **Campos destacados:** `numero` (único), `estado` (`EstadoBox`: Libre, Ocupado, Inactivo), `discapacidad` (booleano de prioridad).

#### `AsignacionesBox(models.Model)`
* **Herencia:** `models.Model` directo.
* **Propósito:** Bitácora inmutable de qué enfermero/técnico utilizó qué box y en qué franja horaria.
* **Relaciones:** `box` (`ForeignKey(Box, PROTECT)`), `personal` (`ForeignKey(Personal, PROTECT)`).
* **Campos destacados:** `fecha_hora_inicio`, `fecha_hora_final`, `motivo_cierre` (`MotivoCierreBox`).

#### `TicketEstudios(models.Model)`
* **Herencia:** `models.Model` directo.
* **Propósito:** Tabla de relación N:M entre una orden/ticket y las prácticas clínicas prescritas.
* **Relaciones:**
  * `ticket`: `ForeignKey(Ticket, CASCADE)`.
  * `estudio`: `ForeignKey(Estudios, PROTECT)` *(impide borrar físicamente un estudio si ya fue pedido)*.
* **Campos:** `estado` (Solicitado, En Proceso, Completado), `observaciones`.

---

### 3.4. Módulo de Estudios Médicos (`app/models/studies.py`)

#### `Estudios(models.Model)`
* **Herencia:** `models.Model` directo.
* **Aliases arquitectónicos:** `Item = Estudios`, `CatalogItem = Estudios`.
* **Propósito:** Catálogo maestro y nomenclador de análisis bioquímicos.
* **Uso OCR:** Consumido por el microservicio OCR mediante coincidencia léxica difusa (*Fuzzy Matching* con `RapidFuzz`).
* **Campos:**
  * `codigo_practica`: Código único de la práctica (ej: "HEMO01").
  * `nombre`: Denominación del estudio.
  * `seccion`: Enum `Seccion` (Química, Hematología, Serología, etc.).
  * `tipo_muestra`: Enum `TipoMuestra` (EDTA/Sangre, Suero, Orina, etc.).
  * `activo`: Booleano para habilitar/deshabilitar la práctica sin eliminarla.

---

### 3.5. Módulo de Usuarios y Autenticación (`app/models/user.py`)

#### `Personal(AbstractBaseUser)`
* **Herencia:** `django.contrib.auth.models.AbstractBaseUser` ➔ `models.Model`.
* **Alias:** `User = Personal`.
* **Propósito:** Usuario personalizado del hospital con login vía email institucional.
* **Mecanismos de Seguridad:**
  * `cant_intentos`: Contador anti-fuerza bruta (bloqueo automático al 3er intento fallido).
  * `inicio_turno` / `fin_turno`: Franja horaria contractual validada por el middleware de seguridad.
  * `delete()` / `restore()` personalizados: Implementan borrado lógico mediante el atributo `activo = False`.

#### `HabilitacionHoraria(models.Model)`
* **Herencia:** `models.Model` directo.
* **Propósito:** Registro de autorizaciones excepcionales fuera de franja horaria.
* **Relaciones:**
  * `personal`: `ForeignKey(Personal, CASCADE)`.
  * `aprobado_por`: `ForeignKey(Personal, PROTECT)` *(debe ser rol Jefa o Admin)*.
* **Control:** Posee su propio `delete()` / `restore()` lógico mediante `activa = False`.

---

### 3.6. Módulo de Reportes (`app/models/report.py`)

#### `HistorialReporteDiario(models.Model)`
* **Herencia:** `models.Model` directo.
* **Propósito:** Registro de auditoría de los reportes diarios consolidados generados por tareas asíncronas de Celery (23:59 UTC).
* **Campos:** `fecha_reporte`, `total_pacientes_atendidos`, `total_estudios_realizados`, `destinatarios_notificados`, `fecha_hora_envio`, `exitoso`, `error_detalle`.

---

## 4. Enumeraciones del Sistema (`models.TextChoices`)

| Enumeración | Archivo | Valores principales |
| :--- | :--- | :--- |
| **`RolPersonal`** | `user.py` | `Admin`, `Jefa`, `Admision`, `Box`, `Secretaria` |
| **`EstadoTicket`** | `triage.py` | `Esperando Llamado`, `En Atencion`, `Atendido`, `Cancelado` |
| **`ClasificacionTriage`** | `triage.py` | `Guardia`, `Medicos`, `discapacidad`, `Oncologia`, `Extraccion con Turno`, `Extraccion sin Turno`, `Otro` |
| **`EstadoBox`** | `triage.py` | `Libre`, `Ocupado`, `Inactivo` |
| **`MotivoCierreBox`** | `triage.py` | `Finalizado`, `Derivado`, `Cancelado`, `Reasignado` |
| **`TipoMuestra`** | `studies.py` | `edta` *(sangre)*, `citrato`, `heparina`, `orina`, `suero`, `otro` |
| **`Seccion`** | `studies.py` | `Hematología`, `Química`, `Serología`, `Orina`, `Bactereología`, `Toxicología`, etc. |
