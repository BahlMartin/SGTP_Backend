# SGTP Backend - Sistema de Gestión de Triage y Flujo de Pacientes

Backend asistencial hospitalario de alta concurrencia desarrollado en **Django** y **Django REST Framework (DRF)**. Diseñado para optimizar el flujo de atención en salas de espera y laboratorios mediante un sistema inteligente de asignación multibox, estricto cumplimiento normativo de protección de datos médicos, trazabilidad inmutable y automatización de reportes asistenciales.

---

## 📋 Tabla de Contenidos

1. [Características Principales](#-características-principales)
2. [Stack Tecnológico](#-stack-tecnológico)
3. [Arquitectura del Proyecto](#-arquitectura-del-proyecto)
4. [Requisitos Previos](#-requisitos-previos)
5. [Guía de Instalación y Configuración](#-guía-de-instalación-y-configuración)
   - [1. Clonar el repositorio](#1-clonar-el-repositorio)
   - [2. Crear y activar el entorno virtual](#2-crear-y-activar-el-entorno-virtual)
   - [3. Instalar dependencias](#3-instalar-dependencias)
   - [4. Configurar las variables de entorno](#4-configurar-las-variables-de-entorno)
   - [5. Generar claves criptográficas](#5-generar-claves-criptográficas)
   - [6. Ejecutar migraciones](#6-ejecutar-migraciones)
   - [7. Crear el superusuario inicial](#7-crear-el-superusuario-inicial)
6. [Ejecución del Sistema](#-ejecución-del-sistema)
   - [Servidor Web (API)](#servidor-web-api)
   - [Worker de Celery y Celery Beat](#worker-de-celery-y-celery-beat)
7. [Documentación de la API (Swagger / ReDoc)](#-documentación-de-la-api-swagger--redoc)
8. [Módulos y Endpoints Principales](#-módulos-y-endpoints-principales)
9. [Ejecución de Pruebas Automatizadas](#-ejecución-de-pruebas-automatizadas)
10. [Seguridad y Políticas Asistenciales](#-seguridad-y-políticas-asistenciales)

---

## 🚀 Características Principales

- **Gestión Dinámica de Triage y Boxes:** Clasificación de prioridades asistenciales y asignación automatizada de tickets a boxes de extracción/atención disponibles.
- **Seguridad Criptográfica Hospitalaria:**
  - **Field-Level Encryption (FLE):** Cifrado simétrico AES (Fernet) a nivel de campos sensibles de pacientes (DNI, historia clínica, etc.).
  - **Payload Encryption JWE (RFC 7516 A256GCM):** Middleware de descifrado punto a punto para cargas confidenciales.
  - **Hashing Robusto:** Implementación prioritaria de Argon2 + PBKDF2 para contraseñas de personal.
- **Control de Acceso Basado en Roles (RBAC) y Restricción de Turnos:**
  - Roles médicos y administrativos (`Admin`, `Jefa de Laboratorio`, `Bioquímico`, `Técnico/Extraccionista`, `Secretaría`).
  - `ShiftScheduleRestrictionMiddleware`: Restricción estricta de acceso al sistema fuera de la franja horaria habilitada para el turno de cada trabajador.
  - Mecanismo criptográfico de autodesbloqueo de emergencia para contingencias.
- **Auditoría Inmutable:** Registro de auditoría *append-only* mediante `django-auditlog` para garantizar la trazabilidad legal de cada acción clínica.
- **Automatización Asíncrona (Celery + Redis):** Consolidación diaria de atenciones a las 23:59 UTC, generación automática de reportes en PDF con `ReportLab` y despacho SMTP a directivos.
- **Integración OCR On-Premise LAN:** Compatibilidad con microservicios locales de lectura de órdenes médicas y coincidencia difusa de estudios mediante `RapidFuzz`.

---

## 🛠️ Stack Tecnológico

| Componente | Tecnología |
| :--- | :--- |
| **Lenguaje** | Python 3.10+ / 3.11+ / 3.12+ |
| **Framework Web** | Django 5.0+, Django REST Framework (DRF) |
| **Base de Datos** | PostgreSQL (Soporte nativo Supabase con SSL forzado `sslmode=require`) |
| **Cola de Tareas / Broker** | Celery 5.3+, Redis 5.0+ |
| **Criptografía** | Cryptography (Fernet), JWCrypto (JWE/JWT), Argon2-cffi |
| **Auditoría** | django-auditlog |
| **Generación de Reportes** | ReportLab (PDF) |
| **Documentación API** | drf-spectacular (OpenAPI 3.0 / Swagger UI / ReDoc) |
| **Matching de Texto** | RapidFuzz |

---

## 📂 Arquitectura del Proyecto

```text
SGTP Backend/
│
├── app/                              # Aplicación principal del dominio asistencial
│   ├── api/                          # Capa de presentación / Controladores REST
│   │   ├── endpoints/                # Endpoints modulares (auth, triage, patients, etc.)
│   │   └── urls.py                   # Enrutador central de la API
│   ├── core/                         # Utilidades transversales, seguridad y criptografía
│   ├── crud/                         # Consultas y operaciones de acceso a datos
│   ├── management/commands/          # Comandos personalizados de Django (init_superuser)
│   ├── middlewares/                  # Pipeline de middlewares (seguridad, turnos, logs)
│   ├── migrations/                   # Historial de migraciones del ORM
│   ├── models/                       # Modelos ORM (User, Patient, Triage, Item, Report)
│   ├── schemas/                      # Serializadores DRF y esquemas OpenAPI
│   ├── services/                     # Lógica de negocio desacoplada (triage, reportes, OCR)
│   └── tasks.py                      # Tareas asíncronas de Celery (Reporte diario PDF)
│
├── my_project/                       # Configuración general del proyecto Django
│   ├── settings/
│   │   └── base.py                   # Configuración centralizada Fail-Fast desde .env
│   ├── asgi.py                       # Interfaz ASGI
│   ├── urls.py                       # Enrutador raíz (URLs globales y Swagger)
│   └── wsgi.py                       # Interfaz WSGI
│
├── tests/                            # Suite completa de pruebas automatizadas
│   ├── test_authentication_rbac.py   # Pruebas de autenticación y permisos
│   ├── test_patients_encryption.py   # Pruebas de cifrado de pacientes (FLE)
│   ├── test_triage_service.py        # Pruebas de lógica de triage y asignación
│   ├── test_reports_service.py       # Pruebas de generación y consolidación PDF
│   └── test_ocr_integration.py       # Pruebas de integración con OCR
│
├── main.py                           # Punto de entrada unificado y ergonómico
├── manage.py                         # CLI estándar de Django
├── requirements.txt                  # Lista de dependencias del proyecto
├── .env.example                      # Plantilla de variables de entorno requeridas
└── README.md                         # Documentación general del sistema
```

---

## 📦 Requisitos Previos

Antes de comenzar, asegúrate de contar con los siguientes componentes instalados en tu entorno:

1. **Python**: Versión 3.10 o superior ([Descargar Python](https://www.python.org/downloads/)).
2. **PostgreSQL**: Instancia local de PostgreSQL o conexión a un proyecto en la nube (ej. **Supabase**).
3. **Redis**: Para el funcionamiento de Celery (Opcional si no se ejecutan tareas asíncronas en desarrollo local).
4. **Git**: Para el control de versiones.

---

## ⚙️ Guía de Instalación y Configuración

Sigue estos pasos en orden para levantar el entorno de desarrollo:

### 1. Clonar el repositorio

```bash
git clone <URL_DEL_REPOSITORIO>
cd "SGTP Backend"
```

### 2. Crear y activar el entorno virtual

Es fundamental aislar las dependencias del proyecto utilizando un entorno virtual.

- **En Windows (PowerShell):**
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```
  *(Si PowerShell restringe la ejecución de scripts, ejecuta antes: `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process`)*

- **En Windows (CMD):**
  ```cmd
  python -m venv venv
  .\venv\Scripts\activate.bat
  ```

- **En Linux / macOS:**
  ```bash
  python3 -m venv venv
  source venv/bin/activate
  ```

### 3. Instalar dependencias

Con el entorno virtual activo, instala todas las librerías necesarias:

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configurar las variables de entorno

El backend utiliza una arquitectura **Fail-Fast**: no iniciará si falta el archivo `.env` o si alguna variable crítica no está declarada.

Copia la plantilla `.env.example` para crear tu `.env`:

- **En Windows (PowerShell):**
  ```powershell
  Copy-Item .env.example .env
  ```
- **En Linux / macOS / Git Bash:**
  ```bash
  cp .env.example .env
  ```

Abre el archivo `.env` y completa los valores correspondientes. A continuación se detallan las configuraciones clave:

```ini
# Configuración básica
DJANGO_SECRET_KEY=clave_unica_y_aleatoria
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1

# Conexión a Base de Datos (PostgreSQL o Supabase con SSL)
DATABASE_URL=postgresql://usuario:password@host:5432/nombre_db
DB_SSL_MODE=require
```

### 5. Generar claves criptográficas

Para las variables de cifrado `FERNET_ENCRYPTION_KEY`, `JWE_SECRET_KEY` y `EMERGENCY_UNLOCK_SECRET_TOKEN`, puedes generar valores seguros ejecutando los siguientes comandos en tu terminal con Python activo:

- **Generar clave Fernet (FLE Pacientes - Base64 32 bytes):**
  ```bash
  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
  ```
  *Copia la salida y pégala en `FERNET_ENCRYPTION_KEY` en tu `.env`.*

- **Generar token de autodesbloqueo de emergencia:**
  ```bash
  python -c "import secrets; print(secrets.token_hex(32))"
  ```
  *Pégalo en `EMERGENCY_UNLOCK_SECRET_TOKEN` en tu `.env`.*

- **Clave JWE (Simétrica 32 caracteres):**
  ```bash
  python -c "import secrets; print(secrets.token_urlsafe(24)[:32])"
  ```
  *Pégala en `JWE_SECRET_KEY` en tu `.env`.*

### 6. Ejecutar migraciones

Aplica la estructura de datos a la base de datos PostgreSQL:

```bash
python manage.py migrate
```
*(O alternativamente: `python main.py migrate`)*

### 7. Crear el superusuario inicial

Puedes inicializar el administrador automáticamente utilizando las credenciales configuradas en tu `.env` mediante el comando de gestión incorporado:

```bash
python manage.py init_superuser
```

> **Nota:** Las credenciales por defecto se configuran en el `.env` bajo `DJANGO_SUPERUSER_EMAIL` y `DJANGO_SUPERUSER_PASSWORD`.
> Si prefieres crearlo interactivamente de forma manual, ejecuta `python manage.py createsuperuser`.

---

## 🚦 Ejecución del Sistema

### Servidor Web (API)

Para iniciar el servidor de desarrollo en `http://localhost:8000`:

```bash
# Método 1 (Ergonómico mediante main.py)
python main.py

# Método 2 (Estándar Django)
python manage.py runserver 0.0.0.0:8000
```

### Worker de Celery y Celery Beat

Si vas a procesar el reporte diario consolidado o tareas asíncronas en segundo plano, asegúrate de tener una instancia de Redis corriendo y ejecuta en terminales separadas:

1. **Iniciar Celery Worker:**
   ```bash
   celery -A my_project worker --loglevel=info
   ```
   *(En Windows, si experimentas problemas de concurrencia con multiprocessing en Celery, añade el pool solo: `celery -A my_project worker --loglevel=info -P solo`)*

2. **Iniciar Celery Beat (Planificador de tareas programadas - 23:59 UTC):**
   ```bash
   celery -A my_project beat --loglevel=info
   ```

---

## 📖 Documentación de la API (Swagger / ReDoc)

Una vez que el servidor esté en ejecución, puedes explorar y probar interactivamente todos los endpoints de la API:

- **Swagger UI (Interactivo):** [http://localhost:8000/api/docs/](http://localhost:8000/api/docs/)
- **ReDoc (Documentación técnica estructurada):** [http://localhost:8000/api/redoc/](http://localhost:8000/api/redoc/)
- **Esquema OpenAPI en formato JSON/YAML:** [http://localhost:8000/api/schema/](http://localhost:8000/api/schema/)

---

## 🔌 Módulos y Endpoints Principales

Todos los endpoints de la aplicación se agrupan bajo el prefijo `/app/`:

| Ruta Base | Módulo | Descripción |
| :--- | :--- | :--- |
| `/app/auth/` | **Autenticación** | Inicio de sesión, cierre de sesión y gestión de sesiones asistenciales. |
| `/app/users/` | **Usuarios y Turnos** | Gestión de personal, roles asistenciales y asignación de franjas horarias. |
| `/app/patients/` | **Pacientes** | Registro y consulta de pacientes con protección criptográfica FLE. |
| `/app/tickets/` | **Tickets y Espera** | Emisión de tickets en admisión, cola priorizada por triage y borrado lógico. |
| `/app/boxes/` | **Boxes y Atención** | Llamado de pacientes (algoritmo multibox), cierre de atención y pantallas de sala. |
| `/app/studies/` | **Catálogo de Estudios** | Catálogo de análisis clínicos, tipos de muestra y tiempos de procesamiento. |
| `/app/ocr/` | **Procesamiento OCR** | Recepción de órdenes médicas escaneadas y extracción difusa de prácticas. |
| `/app/reports/` | **Reportes Asistenciales**| Generación manual y consulta del historial de reportes diarios consolidados en PDF. |

---

## 🧪 Ejecución de Pruebas Automatizadas

El proyecto incluye un conjunto de pruebas unitarias y de integración que validan el comportamiento clínico, de seguridad y de persistencia:

```bash
# Ejecutar todas las pruebas
python main.py test

# O usando manage.py apuntando a la carpeta de tests
python manage.py test tests
```

### Pruebas Específicas:
```bash
# Probar autenticación y control de acceso (RBAC)
python manage.py test tests.test_authentication_rbac

# Probar cifrado de datos de pacientes (FLE Fernet)
python manage.py test tests.test_patients_encryption

# Probar el flujo del motor de triage y boxes
python manage.py test tests.test_triage_service

# Probar la generación de reportes diarios en PDF
python manage.py test tests.test_reports_service

# Probar la integración con el microservicio OCR
python manage.py test tests.test_ocr_integration
```

---

## 🔒 Seguridad y Políticas Asistenciales

1. **Gestión Estricta de Entorno (Fail-Fast):** Ningún secreto o credencial de base de datos se encuentra hardcodeado en el código fuente. La ausencia de configuración en `.env` detiene inmediatamente el proceso al arrancar.
2. **Cifrado de Datos en Reposo:** Los campos clínicos e identitarios de los pacientes no se almacenan en texto plano en la base de datos; se procesan mediante `Fernet` (cifrado simétrico autenticado).
3. **Control de Horario de Turnos:** El middleware `ShiftScheduleRestrictionMiddleware` evalúa si el personal que realiza solicitudes HTTP tiene un turno activo en el horario actual, bloqueando operaciones no autorizadas fuera de guardia o de turno asignado.
4. **Registro Legal Inmutable:** Cada modificación de registros sensibles es capturada por `auditlog`, guardando el usuario responsable, timestamp UTC y los valores previos y posteriores.

---

## 👥 Contribución y Soporte

Para reportar incidencias, proponer mejoras o solicitar nuevas funcionalidades para el flujo asistencial, por favor abre un *Issue* o envía un *Pull Request* siguiendo los estándares de codificación y asegurando que la suite de pruebas automatizadas finalice con éxito.
