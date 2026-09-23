# Documentación Técnica: Modelo de Usuario y Personal (`app/models/user.py`)

Este documento describe en detalle la arquitectura, clases, atributos, métodos y justificación de negocio implementados en el archivo [`app/models/user.py`](file:///c:/Users/LENOVO%20i5/Desktop/SGTP/SGTP%20Backend/app/models/user.py), el cual constituye el núcleo de identidad, control de acceso, gestión de personal asistencial y excepciones horarias del SGTP.

---

## Índice

1. [Visión General](#visión-general)
2. [Clase `RolPersonal` (Enumeración de Roles)](#1-clase-rolpersonal)
3. [Clase `PersonalManager` (Gestor del Modelo)](#2-clase-personalmanager)
   - [`create_user`](#create_user)
   - [`create_superuser`](#create_superuser)
4. [Clase `Personal` (Modelo Principal de Usuario)](#3-clase-personal)
   - [Campos del Modelo](#campos-del-modelo-personal)
   - [Configuración de Autenticación de Django](#configuración-de-autenticación)
   - [Propiedades y Métodos](#métodos-del-modelo-personal)
     - [`__str__`](#__str__)
     - [`is_active`](#is_active)
     - [`registrar_intento_fallido`](#registrar_intento_fallido)
     - [`resetear_intentos`](#resetear_intentos)
     - [`desbloquear`](#desbloquear)
     - [`clean`](#clean)
5. [Clase `HabilitacionHoraria` (Excepciones de Turno y Justificación)](#4-clase-habilitacionhoraria)
   - [Contexto y Regla de Negocio Hospitalaria](#contexto-y-regla-de-negocio-hospitalaria)
   - [¿Por qué NO modificar directamente el turno del empleado en la base de datos?](#por-qué-no-se-debe-modificar-directamente-el-turno-del-empleado-en-la-base-de-datos)
   - [Campos del Modelo](#campos-del-modelo-habilitacionhoraria)
   - [Métodos](#métodos-del-modelo-habilitacionhoraria)
     - [`__str__`](#__str__-1)
     - [`clean`](#clean-1)
   - [Control de Acceso en Tiempo de Ejecución (`SecurityMiddleware`)](#control-de-acceso-en-tiempo-de-ejecución-securitymiddleware)
   - [¿Por qué es indispensable que sea un modelo (`models.Model`) en Django?](#por-qué-es-indispensable-que-sea-un-modelo-modelsmodel-en-django)
   - [Tabla Comparativa de Enfoques](#tabla-comparativa-de-enfoques)
6. [Auditoría, Alias y Exportaciones](#5-auditoría-alias-y-exportaciones)

---

## Visión General

El archivo centraliza dos entidades de base de datos interconectadas:
* **`Personal`:** Modelo de usuario personalizado que hereda de `AbstractBaseUser`. Sustituye al usuario por defecto de Django para implementar autenticación mediante correo institucional, roles hospitalarios específicos, control de intentos fallidos contra ataques de fuerza bruta y franja horaria contractual regular.
* **`HabilitacionHoraria`:** Registro de autorizaciones excepcionales que permiten a personal operativo ingresar al sistema fuera de su franja horaria asignada previa aprobación de una Jefa o Administrador.

---

## 1. Clase `RolPersonal`

```python
class RolPersonal(models.TextChoices):
```

Hereda de `models.TextChoices`. Define de forma tipada e inmutable los roles permitidos en el sistema hospitalario:

| Valor en BD | Etiqueta Descriptiva | Alcance / Responsabilidad |
| :--- | :--- | :--- |
| `'Admin'` | *Administrador General* | Gestión técnica, configuración global, desbloqueo de usuarios y auditorías. |
| `'Jefa'` | *Jefa de Laboratorio / Triage* | Supervisión médica, reclasificación de tickets, aprobación de habilitaciones horarias. |
| `'Admision'` | *Operador de Admisión* | Registro de pacientes y emisión de tickets de espera. |
| `'Box'` | *Técnico de Box* | Atención en boxes de extracción, carga de datos de triage y toma de muestras. |
| `'Secretaria'` | *Secretaría* | Consulta de estados, informes y soporte de recepción. |

---

## 2. Clase `PersonalManager`

```python
class PersonalManager(BaseUserManager):
```

Hereda de `BaseUserManager`. Es el administrador de la tabla en base de datos (`Personal.objects`) y provee la lógica segura para construir usuarios regulares y superusuarios.

### Métodos:

#### `create_user`
```python
def create_user(self, email: str, password: str | None = None, **extra_fields) -> 'Personal':
```
* **Propósito:** Construir y persistir un usuario estándar en la base de datos.
* **Flujo de ejecución:**
  1. Valida que el `email` no esté vacío; de lo contrario, lanza `ValueError("El email es un campo obligatorio.")`.
  2. Normaliza el correo electrónico (`self.normalize_email(email)`), convirtiendo el dominio a minúsculas para evitar duplicados por diferencias tipográficas.
  3. Instancia el modelo (`self.model(email=email, **extra_fields)`), inyectando dinámicamente los campos adicionales recibidos en `**extra_fields`.
  4. Gestiona la clave:
     - Si se proporciona `password`, la encripta con algoritmos robustos de derivación de claves mediante `user.set_password(password)`.
     - Si no se proporciona contraseña, llama a `user.set_unusable_password()` para que la cuenta no pueda autenticarse con contraseña vacía.
  5. Ejecuta `user.full_clean()` para forzar todas las validaciones de campos y de la función `clean()` antes de impactar en la BD.
  6. Guarda el registro (`user.save(using=self._db)`) y retorna la instancia creada.

---

#### `create_superuser`
```python
def create_superuser(self, email: str, password: str | None = None, **extra_fields) -> 'Personal':
```
* **Propósito:** Crear una cuenta con privilegios administrativos totales. Es el método que ejecuta internamente el comando CLI `python manage.py createsuperuser`.
* **Flujo de ejecución:**
  1. Fuerza que el rol sea `RolPersonal.ADMIN` y el estado sea `activo = True`.
  2. **Automatización segura por variables de entorno:**
     - Si no se pasó `nombre`, lo toma de `os.environ.get('DJANGO_SUPERUSER_NOMBRE', 'Administrador')`.
     - Si no se pasó `apellidos`, lo toma de `os.environ.get('DJANGO_SUPERUSER_APELLIDOS', 'General')`.
     - Si no se pasó `dni`, lo busca en `os.environ.get('DJANGO_SUPERUSER_DNI')`. Si no existe en el `.env` ni como argumento, lanza un `ValueError` descriptivo exigiendo el DNI.
  3. Delega la creación formal a `self.create_user(email, password, **extra_fields)`.

---

## 3. Clase `Personal`

```python
class Personal(AbstractBaseUser):
```

Modelo de usuario principal. Hereda de `AbstractBaseUser` para proveer almacenamiento seguro de credenciales (`password`, `last_login`) sin heredar campos innecesarios del usuario estándar de Django (como `first_name`, `last_name` o permisos por grupos auth).

### Campos del Modelo `Personal`:

| Campo | Tipo de Campo | Restricciones / Validadores | Descripción |
| :--- | :--- | :--- | :--- |
| `id_personal` | `AutoField` | `primary_key=True` | Identificador único interno autoincremental. |
| `email` | `EmailField` | `unique=True` | Correo institucional. Actúa como el identificador de inicio de sesión (`USERNAME_FIELD`). |
| `nombre` | `CharField(150)` | `validar_solo_letras_min2` | Nombre(s) de la persona. Obliga mínimo 2 letras y restringe símbolos/números. |
| `apellidos` | `CharField(150)` | `validar_solo_letras_min2` | Apellido(s) de la persona. Mismas restricciones alfabéticas. |
| `dni` | `IntegerField` | `unique=True` | Documento Nacional de Identidad único en el sistema. |
| `matricula` | `CharField(50)` | `blank=True, null=True` | Matrícula profesional médica o técnica (opcional). |
| `rol` | `CharField(20)` | `choices=RolPersonal.choices` | Rol del empleado, usado para control de acceso RBAC. |
| `activo` | `BooleanField` | `default=True` | Estado de habilitación. Se desactiva ante bloqueos o cese laboral. |
| `cant_intentos`| `IntegerField` | `default=0` | Contador de inicios de sesión fallidos consecutivos. |
| `inicio_turno` | `TimeField` | `blank=True, null=True` | Hora diaria regular de inicio de jornada (ej: `07:00:00`). |
| `fin_turno` | `TimeField` | `blank=True, null=True` | Hora diaria regular de fin de jornada (ej: `15:00:00`). |
| `fecha_creacion`| `DateTimeField` | `auto_now_add=True` | Marca temporal inmutable de cuándo se dio de alta al usuario. |

### Configuración de Autenticación:
* `objects = PersonalManager()`: Conecta el gestor personalizado.
* `USERNAME_FIELD = 'email'`: Declara el email como campo de inicio de sesión.
* `REQUIRED_FIELDS = ['nombre', 'apellidos', 'dni', 'rol']`: Campos solicitados obligatoriamente al crear superusuarios por consola.
* `class Meta`: Configura la tabla en base de datos como `sgtp_personal`, nombres descriptivos y orden por apellido y nombre.

---

### Métodos del Modelo `Personal`:

#### `__str__`
```python
def __str__(self) -> str:
```
* **Retorno:** Cadena legible del estilo: `"Pérez, Juan (Box) - DNI: 35123456"`.
* **Uso:** Utilizado en paneles de administración, logs y serializadores.

#### `is_active` (Propiedad `@property`)
```python
@property
def is_active(self) -> bool:
```
* **Retorno:** Retorna el valor booleano del campo `self.activo`.
* **Uso:** Requerimiento del subsistema de autenticación de Django para saber si un usuario puede iniciar sesión.

#### `registrar_intento_fallido`
```python
def registrar_intento_fallido(self) -> bool:
```
* **Propósito:** Mitigación de ataques de fuerza bruta al autenticar.
* **Comportamiento:**
  1. Incrementa `self.cant_intentos` en 1.
  2. Si `cant_intentos >= 3`:
     - Establece `self.activo = False` (bloquea la cuenta).
     - Marca la bandera `bloqueado = True`.
  3. Ejecuta `self.save(update_fields=['cant_intentos', 'activo'])` optimizando la consulta SQL para solo actualizar esas dos columnas.
  4. Retorna `True` si la cuenta resultó bloqueada en este intento exacto, o `False` en caso contrario.

#### `resetear_intentos`
```python
def resetear_intentos(self) -> None:
```
* **Propósito:** Limpieza tras inicio de sesión exitoso.
* **Comportamiento:** Si `self.cant_intentos > 0`, restablece el valor a `0` y ejecuta `self.save(update_fields=['cant_intentos'])`.

#### `desbloquear`
```python
def desbloquear(self) -> None:
```
* **Propósito:** Desbloqueo administrativo de cuentas.
* **Comportamiento:** Restablece `self.activo = True`, `self.cant_intentos = 0` y guarda ambos campos en la base de datos.

#### `clean`
```python
def clean(self) -> None:
```
* **Propósito:** Reglas de validación semántica antes de guardar.
* **Comportamiento:**
  1. Invoca `super().clean()`.
  2. Valida alfabéticamente el `nombre` mediante `validar_solo_letras_min2(self.nombre)`.
  3. Valida alfabéticamente los `apellidos` mediante `validar_solo_letras_min2(self.apellidos)`.
  4. Valida que el `dni` sea un número entero mayor a cero con `validar_dni_positivo(self.dni)`.

---

## 4. Clase `HabilitacionHoraria`

```python
class HabilitacionHoraria(models.Model):
```

Hereda de `models.Model`. Representa una **autorización transitoria desacoplada** de la jornada base para permitir que personal asistencial (`Admision`, `Box`, `Secretaria`) ingrese al sistema fuera de su franja habitual.

---

### Contexto y Regla de Negocio Hospitalaria

En el SGTP, el personal operativo tiene restricciones horarias de acceso por motivos de seguridad clínica y cumplimiento normativo. 
Los campos `inicio_turno` y `fin_turno` en `Personal` definen la jornada contractual regular del empleado (ej. `07:00 a 15:00`).

---

### ¿Por qué NO se debe modificar directamente el turno del empleado en la base de datos?

Si ante una necesidad excepcional (cubrir una guardia imprevista o realizar horas extras) se optara por actualizar simplemente `inicio_turno` y `fin_turno` en el registro de `Personal`, ocurrirían los siguientes problemas críticos:

| Problema | Impacto en el Sistema Hospitalario |
| :--- | :--- |
| **Pérdida del horario base contractual** | Al sobreescribir `inicio_turno` y `fin_turno`, se destruye el registro de la jornada habitual del trabajador. El administrador tendría que recordar revertirlo manualmente al día siguiente. |
| **Falta de temporalidad y fecha** | Los campos en `Personal` son horarios diarios recurrentes (`TimeField`), no tienen fecha (`DateField`). No permiten indicar que la excepción es válida *únicamente* hoy o en un día específico. |
| **Ausencia de autorización jerárquica** | En el flujo operativo, un operador no puede trabajar fuera de hora sin la venia de una **Jefa de Laboratorio** o **Administrador**. Modificar el usuario no registra quién autorizó la excepción. |
| **Ruptura de auditoría médica (Auditlog)** | No queda constancia del **motivo operativo** (ej: "Reemplazo de urgencia por baja médica") ni trazabilidad legal para auditorías de horas extraordinarias. |

---

### Campos del Modelo `HabilitacionHoraria`:

| Campo | Tipo de Campo | Restricciones / Relación | Descripción |
| :--- | :--- | :--- | :--- |
| `id` | `AutoField` | `primary_key=True` | Identificador autoincremental de la excepción. |
| `personal` | `ForeignKey(Personal)` | `on_delete=models.CASCADE` | Usuario beneficiario de la excepción. Si se elimina el personal, se eliminan sus habilitaciones en cascada. Relación inversa: `personal.habilitaciones_horarias`. |
| `aprobado_por` | `ForeignKey(Personal)` | `on_delete=models.PROTECT` | Usuario que autorizó la excepción. `PROTECT` impide borrar al autorizador para no destruir la evidencia de auditoría. Relación inversa: `aprobado_por.habilitaciones_otorgadas`. |
| `fecha` | `DateField` | `default=timezone.now` | Día específico para el cual tiene validez la excepción. |
| `hora_inicio` | `TimeField` | Obligatorio | Hora a partir de la cual se autoriza el ingreso (ej: `16:00:00`). |
| `hora_fin` | `TimeField` | Obligatorio | Hora hasta la cual se autoriza el ingreso (ej: `20:00:00`). |
| `motivo` | `CharField(255)` | Obligatorio | Justificación médica o administrativa (ej: `"Guardia de urgencias por reemplazo"`). |
| `activa` | `BooleanField` | `default=True` | Estado de vigencia de la habilitación. Permite revocarla de inmediato. |

---

### Métodos del Modelo `HabilitacionHoraria`:

#### `__str__`
```python
def __str__(self) -> str:
```
* **Retorno:** Cadena formateada para logs e inspección, por ejemplo:
  `"Excepción enfermero@hospital.com (2026-09-21 16:00:00-20:00:00)"`.

#### `clean`
```python
def clean(self) -> None:
```
* **Propósito:** Validaciones estrictas de coherencia jerárquica y temporal.
* **Comportamiento:**
  1. **Jerarquía médica:** Verifica que `self.aprobado_por.rol` pertenezca a `[RolPersonal.JEFA, RolPersonal.ADMIN]`. De lo contrario, lanza `ValidationError("Solo una usuaria con rol 'Jefa' o 'Admin' puede autorizar excepciones de turno.")`.
  2. **Coherencia horaria:** Verifica que `self.hora_inicio < self.hora_fin`. Si la hora de inicio es igual o posterior a la hora de fin, lanza `ValidationError("La hora de inicio debe ser estrictamente anterior a la hora de fin.")`.

---

### Control de Acceso en Tiempo de Ejecución (`SecurityMiddleware`)

El backend implementa un middleware de seguridad ([`app/middlewares/security.py`](file:///c:/Users/LENOVO%20i5/Desktop/SGTP/SGTP%20Backend/app/middlewares/security.py#L95)) que evalúa cada petición HTTP entrante:

1. Evalúa si el usuario operativo se encuentra dentro de su franja ordinaria (`inicio_turno <= ahora <= fin_turno`).
2. Si está **dentro de turno**, permite la solicitud con normalidad.
3. Si está **fuera de turno**, consulta la base de datos:
   ```python
   tiene_habilitacion = HabilitacionHoraria.objects.filter(
       personal=user,
       fecha=now_date,
       activa=True,
       hora_inicio__lte=now_time,
       hora_fin__gte=now_time
   ).exists()
   ```
4. Si existe una habilitación activa para ese momento y día, el acceso es concedido.
5. De lo contrario, se bloquea la solicitud retornando un error `HTTP 403 Forbidden`:
   ```json
   {
       "error": "ACCESO_FUERA_DE_TURNO",
       "detail": "Acceso bloqueado: Su usuario se encuentra fuera de su franja laboral asignada...",
       "hora_actual_servidor": "18:45:00"
   }
   ```

---

### ¿Por qué es indispensable que sea un modelo (`models.Model`) en Django?

En la arquitectura de Django, toda entidad persistida en base de datos que participe en la lógica del negocio debe declararse como una clase `Model`:

1. **Gestión de Esquema y Migraciones:** Permite que Django ORM cree, sincronice y mantenga la tabla (`sgtp_habilitacion_horaria`) en PostgreSQL/MySQL de forma automatizada y versionada mediante migraciones.
2. **Consultas Seguras mediante ORM:** Facilita filtros optimizados e indexados para el middleware (`.filter(...)`, `.exists()`), evitando consultas SQL manuales vulnerables a inyecciones.
3. **Exposición en API REST:** Permite asociar fácilmente serializadores (`HabilitacionHorariaSerializer`) y ViewSets (`HabilitacionHorariaViewSet`), habilitando al Frontend para que la Jefa pueda crear, listar y revocar habilitaciones desde la interfaz web.
4. **Auditoría inalterable:** Se encuentra registrado en `auditlog.register(HabilitacionHoraria)`, registrando automáticamente fecha, hora, IP y usuario responsable de cualquier alta, baja o modificación de una habilitación.

---

### Tabla Comparativa de Enfoques

| Enfoque | Mantiene Turno Base | Autorización Formal | Validez Temporal Automática | Auditoría Hospitalaria |
| :--- | :---: | :---: | :---: | :---: |
| **Modificar solo tabla `Personal`** | ❌ No (se sobreescribe) | ❌ No | ❌ No (requiere revertir a mano) | ❌ No |
| **Modelo `HabilitacionHoraria`** | ✅ Sí | ✅ Sí (Jefa/Admin) | ✅ Sí (por fecha y hora) | ✅ Sí (`auditlog`) |

---

## 5. Auditoría, Alias y Exportaciones

Al final del archivo se configuran las directivas globales del módulo:

### 1. Alias de Compatibilidad:
```python
User = Personal
```
Permite importar `User` indistintamente en módulos de infraestructura o librerías que requieran la convención de Django (`from app.models import User`).

### 2. Registro en `django-auditlog`:
```python
auditlog.register(Personal, exclude_fields=['password', 'last_login'])
auditlog.register(HabilitacionHoraria)
```
* Conecta ambos modelos al motor de auditoría inalterable.
* En `Personal`, excluye explícitamente los campos `password` y `last_login` para proteger la privacidad del hash y evitar saturar la tabla de auditoría con cada inicio de sesión.
* En `HabilitacionHoraria`, audita cada creación, cambio de estado (`activa`) o modificación de horas.

### 3. Símbolos Exportados (`__all__`):
```python
__all__ = [
    'RolPersonal',
    'PersonalManager',
    'Personal',
    'User',
    'HabilitacionHoraria',
]
```
Define la interfaz pública limpia del módulo, limitando las exportaciones a las entidades de modelo, gestor y roles de usuario (las funciones de validación residen ahora de forma desacoplada en `app.core.validators`).
