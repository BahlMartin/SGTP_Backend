"""
Comando de gestión para ejecutar la purga por retención de registros de auditoría (> 365 días).
Purga tanto EventoAuditoria como el histórico técnico de auditlog_logentry.
"""
from django.core.management.base import BaseCommand
from app.services.audit_service import AuditService


class Command(BaseCommand):
    help = "Purga eventos de auditoría y logs técnicos anteriores al período de retención configurado"

    def add_arguments(self, parser):
        parser.add_argument(
            '--dias',
            type=int,
            default=None,
            help='Días de retención (por defecto lee AUDITORIA_RETENCION_DIAS o 365)'
        )
        parser.add_argument(
            '--forzar',
            action='store_true',
            help='Ignora el throttling de 24 horas y ejecuta la purga de inmediato'
        )

    def handle(self, *args, **options):
        dias = options.get('dias')
        forzar = options.get('forzar', False)

        resultado = AuditService.purgar_retencion(dias=dias, forzar=forzar)

        if resultado.get('throttled'):
            self.stdout.write(self.style.NOTICE(
                "La purga ya fue ejecutada en las últimas 24 horas. Use --forzar para omitir el límite."
            ))
        else:
            eventos = resultado.get('eventos_eliminados', 0)
            auditlog = resultado.get('auditlog_eliminados', 0)
            self.stdout.write(self.style.SUCCESS(
                f"Purga completada exitosamente: {eventos} eventos operacionales y {auditlog} registros de auditlog eliminados."
            ))

