# Arquitectura de Reportes: Patrón Fachada (Facade Pattern) y Principio de Responsabilidad Única (SRP)

Este documento describe el refactor arquitectónico aplicado al subsistema de reportes diarios asistenciales del **SGTP Backend**, explicando el problema del antipatrón *God Object* y cómo el **Patrón Fachada (Facade)** junto con el **Principio de Responsabilidad Única (SRP)** resuelven este problema de forma elegante, mantenible y escalable.

---

## 1. Contexto y Diagnóstico del Problema

### El Antipatrón: *God Object* (Objeto Dios)
Anteriormente, la clase `ReportService` concentraba en un único archivo de más de 330 líneas tres responsabilidades arquitectónicamente disjuntas:

1. **Cálculo y Analítica Asistencial (Capa de Dominio / ORM):**
   - Filtrado de tickets por rango horario diario en UTC.
   - Cálculo de tiempos promedio de espera y tiempos promedio de atención.
   - Agregación estadística por clasificación de triage (`Guardia`, `Shockroom`, etc.).
   - Rendimiento por personal y conteo de prácticas médicas solicitadas.
2. **Presentación y Compilación Documental (Capa de Presentación / ReportLab):**
   - Configuración de márgenes, orientación y tamaños de página (`SimpleDocTemplate`).
   - Definición de estilos tipográficos (`ParagraphStyle`), jerarquía de títulos y paleta de colores corporativa.
   - Maquetado de tablas complejas (`Table`, `TableStyle`), fondos alternados y alineaciones.
   - Serialización de binarios en memoria (`io.BytesIO`).
3. **Comunicaciones de Infraestructura y Auditoría (Capa de Infraestructura / SMTP):**
   - Consulta de destinatarios autorizados con roles `Jefa` y `Secretaria`.
   - Composición del asunto y cuerpo multipart MIME con adjunto PDF.
   - Despacho mediante servidor SMTP (`django.core.mail.EmailMessage`).
   - Registro transaccional inalterable en `HistorialReporteDiario`.

### ¿Por qué era problemático?
- **Violación del Principio de Responsabilidad Única (SRP):** Había más de tres razones distintas para modificar la misma clase: si cambiaban los modelos de datos, si cambiaba el diseño visual del PDF, o si cambiaba el proveedor de correo/notificaciones.
- **Acoplamiento Fuerte:** La lógica de negocio dependía directamente de librerías visuales pesadas (`reportlab`), dificultando su reutilización o sustitución (por ejemplo, migrar a WeasyPrint o Typst en el futuro).
- **Testabilidad Deficiente:** Para probar el despacho de correo era obligatorio compilar un PDF real y consultar la base de datos completa. No se podían realizar pruebas unitarias aisladas de cada etapa sin *mocks* complejos y frágiles.

---

## 2. El Patrón Fachada (Facade Pattern)

### Definición (Gang of Four - GoF)
> *"Proporciona una interfaz unificada y simplificada para un conjunto de interfaces en un subsistema. Define una interfaz de nivel más alto que hace que el subsistema sea más fácil de usar."*

En lugar de exponer al resto de la aplicación la complejidad interna de consultar modelos, compilar el binario PDF con ReportLab y despachar el protocolo SMTP, la **Fachada (`ReportService`)** actúa como un punto de entrada de alto nivel que delega el trabajo real en subsistemas especializados.

### Diagrama de Arquitectura

```mermaid
graph TD
    subgraph Clientes Externos
        API["API Endpoints<br>(reports.py)"]
        Celery["Tareas Celery<br>(tasks.py)"]
        Tests["Suite de Tests<br>(test_reports_service.py)"]
    end

    subgraph Fachada
        Facade["ReportFacade<br>(report_facade.py)"]
    end

    subgraph Subsistemas Especializados (SRP)
        Metrics["ReportMetricsService<br>(metrics.py)<br>• Consultas ORM<br>• Promedios y tiempos"]
        PdfGen["ReportPdfGenerator<br>(pdf.py)<br>• ReportLab<br>• Estilos y tablas"]
        Email["ReportEmailService<br>(email.py)<br>• Django EmailMessage<br>• HistorialReporteDiario"]
    end

    API --> Facade
    Celery --> Facade
    Tests --> Facade

    Facade -->|1. consolidar| Metrics
    Facade -->|2. generar| PdfGen
    Facade -->|3. despachar| Email
```

---

## 3. Estructura Modular Implementada

El código fue desglosado en el paquete `app/services/reports/`:

```
app/services/
└── reports/
    ├── __init__.py         # Exporta subsistemas y la fachada
    ├── metrics.py          # ReportMetricsService: Cálculos y ORM
    ├── pdf.py              # ReportPdfGenerator: Maquetado ReportLab
    ├── email.py            # ReportEmailService: Despacho SMTP y auditoría
    └── report_facade.py    # ReportFacade: Fachada orquestadora
```

### Detalle de Componentes

#### 1. `ReportMetricsService` (`app/services/reports/metrics.py`)
- **Responsabilidad:** Extraer del ORM y calcular todas las métricas de la jornada seleccionada (00:00 a 23:59 UTC).
- **Entrada:** `fecha_consulta: Optional[date]`.
- **Salida:** `Dict[str, Any]` (diccionario estructurado y desacoplado de la base de datos).

#### 2. `ReportPdfGenerator` (`app/services/reports/pdf.py`)
- **Responsabilidad:** Transformar el diccionario de métricas en un documento binario PDF oficial.
- **Entrada:** `metricas: Dict[str, Any]`.
- **Salida:** `bytes` (flujo binario en memoria del PDF listo para descargar o adjuntar).
- **Ventaja:** Si mañana se rediseña el membrete, la paleta de colores o se cambia ReportLab, ningún otro módulo se ve afectado.

#### 3. `ReportEmailService` (`app/services/reports/email.py`)
- **Responsabilidad:** Buscar destinatarios autorizados (`Jefa`, `Secretaria`), armar el mensaje MIME, adjuntar el archivo y persistir la auditoría en `HistorialReporteDiario`.
- **Entrada:** `metricas: Dict[str, Any], pdf_bytes: bytes`.
- **Salida:** `HistorialReporteDiario` (registro de auditoría).

#### 4. `ReportFacade` (`app/services/reports/report_facade.py`)
- **Responsabilidad:** Orquestar el flujo end-to-end de manera explícita y prolija:
  - `consolidar_metricas_diarias(fecha)` $\rightarrow$ delega a `ReportMetricsService.consolidar(fecha)`
  - `generar_pdf_reporte(metricas)` $\rightarrow$ delega a `ReportPdfGenerator.generar(metricas)`
  - `enviar_reporte_diario_por_email(fecha)` $\rightarrow$ coordina las tres etapas y devuelve el historial.

---

## 4. Beneficios Obtenidos

| Criterio | Antes (God Object) | Después (Patrón Fachada + SRP) |
| :--- | :--- | :--- |
| **Líneas por archivo** | ~335 líneas en un solo archivo | Módulos pequeños y enfocados (~60-120 líneas) |
| **Responsabilidades** | 3 mezcladas (BD + PDF + Email) | 1 por cada subsistema |
| **Acoplamiento** | Alto (ReportLab ligado al servicio) | Débil (los subsistemas operan por contratos de datos simples) |
| **Testabilidad** | Difícil de mockear y probar por partes | Pruebas unitarias directas e independientes por cada capa |
| **Retrocompatibilidad** | N/A | **100% compatible**, no rompe endpoints ni tareas programadas |

---

## 5. Guía de Uso en el Código

### A. Uso a través de la Fachada (Recomendado para Endpoints y Celery)
```python
from app.services.reports.report_facade import ReportFacade

# 1. Obtener métricas consolidadas
metricas = ReportFacade.consolidar_metricas_diarias(fecha)

# 2. Generar PDF para descarga directa
pdf_bytes = ReportFacade.generar_pdf_reporte(metricas)

# 3. Flujo completo nocturno / bajo demanda (Celery)
historial = ReportFacade.enviar_reporte_diario_por_email(fecha)
```

### B. Uso Directo de Subsistemas (Ideal para Pruebas Unitarias o Personalizaciones)
```python
from app.services.reports import ReportMetricsService, ReportPdfGenerator, ReportEmailService

# Probar solo el generador de PDF con datos ficticios sin tocar la base de datos
metricas_mock = {
    'fecha': '2026-09-25',
    'total_emitidos': 10,
    'total_atendidos': 9,
    'promedio_espera_minutos': 12.5,
    'promedio_atencion_minutos': 20.0,
    'total_estudios': 3,
    'distribucion_triage': [],
    'rendimiento_personal': []
}
pdf_bytes = ReportPdfGenerator.generar(metricas_mock)
assert pdf_bytes.startswith(b'%PDF-')
```
