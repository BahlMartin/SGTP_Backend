"""
Comando de gestión para descargar o actualizar la base de datos local DB-IP City Lite (.mmdb).
Licencia: Creative Commons Attribution 4.0 International (CC BY 4.0).
"""
import os
import gzip
import shutil
from datetime import datetime
from pathlib import Path
import requests
from django.core.management.base import BaseCommand
from django.conf import settings


class Command(BaseCommand):
    help = "Descarga y descomprime la base DB-IP City Lite en el directorio geoip/"

    def handle(self, *args, **options):
        dest_path = Path(getattr(settings, 'GEOIP_DB_PATH', settings.BASE_DIR / 'geoip' / 'dbip-city-lite.mmdb'))
        dest_dir = dest_path.parent
        dest_dir.mkdir(parents=True, exist_ok=True)

        now = datetime.now()
        # Probar mes actual y mes anterior si el del mes actual aún no fue publicado
        meses_a_probar = [
            now.strftime('%Y-%m'),
            datetime(now.year if now.month > 1 else now.year - 1, now.month - 1 if now.month > 1 else 12, 1).strftime('%Y-%m')
        ]

        descargado = False
        headers = {'User-Agent': 'SGTP-Hospital-Audit/1.0 (Hospital Publico Lab)'}

        for periodo in meses_a_probar:
            url = f"https://download.db-ip.com/free/dbip-city-lite-{periodo}.mmdb.gz"
            self.stdout.write(f"Intentando descargar DB-IP Lite ({periodo}) desde {url}...")
            try:
                resp = requests.get(url, stream=True, timeout=20, headers=headers)
                if resp.status_code == 200:
                    gz_tmp = dest_dir / f"dbip-tmp-{periodo}.mmdb.gz"
                    with open(gz_tmp, 'wb') as f_out:
                        shutil.copyfileobj(resp.raw, f_out)

                    # Descomprimir a destino final
                    with gzip.open(gz_tmp, 'rb') as f_in, open(dest_path, 'wb') as f_final:
                        shutil.copyfileobj(f_in, f_final)

                    # Eliminar archivo temporal comprimido
                    if os.path.exists(gz_tmp):
                        os.remove(gz_tmp)

                    self.stdout.write(self.style.SUCCESS(
                        f"Base GeoIP DB-IP ({periodo}) instalada con éxito en {dest_path} ({os.path.getsize(dest_path)} bytes)"
                    ))
                    descargado = True
                    break
                else:
                    self.stdout.write(self.style.WARNING(f"HTTP {resp.status_code} para {periodo}. Probando período anterior..."))
            except Exception as exc:
                self.stdout.write(self.style.WARNING(f"Error de conexión con DB-IP ({periodo}): {exc}"))

        if not descargado:
            if dest_path.exists():
                self.stdout.write(self.style.NOTICE("No se pudo actualizar DB-IP; se mantiene el archivo existente."))
            else:
                self.stdout.write(self.style.ERROR(
                    "No se pudo descargar la base DB-IP. La geolocalización IP funcionará con estado NO_DISPONIBLE."
                ))

