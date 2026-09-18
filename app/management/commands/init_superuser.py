"""
Comando de gestión para inicializar o actualizar el Superusuario a partir de las variables en .env.
Uso: python manage.py init_superuser
"""
import os
from django.core.management.base import BaseCommand, CommandError
from app.models.user import Personal, RolPersonal


class Command(BaseCommand):
    help = "Crea o actualiza el superusuario inicial del sistema utilizando las variables configuradas en .env."

    def handle(self, *args, **options):
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL')
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD')
        nombre = os.environ.get('DJANGO_SUPERUSER_NOMBRE', 'Administrador')
        apellidos = os.environ.get('DJANGO_SUPERUSER_APELLIDOS', 'General')
        dni_raw = os.environ.get('DJANGO_SUPERUSER_DNI', '10000000')

        if not email or not password:
            raise CommandError(
                "DJANGO_SUPERUSER_EMAIL y DJANGO_SUPERUSER_PASSWORD son obligatorios en el archivo .env."
            )

        try:
            dni = int(dni_raw)
        except ValueError:
            raise CommandError("DJANGO_SUPERUSER_DNI en .env debe ser un número entero.")

        user, created = Personal.objects.get_or_create(
            email=email.strip().lower(),
            defaults={
                'nombre': nombre.strip(),
                'apellidos': apellidos.strip(),
                'dni': dni,
                'rol': RolPersonal.ADMIN,
                'activo': True,
            }
        )

        # Actualizar contraseña y atributos de administrador
        user.set_password(password)
        user.nombre = nombre.strip()
        user.apellidos = apellidos.strip()
        user.dni = dni
        user.rol = RolPersonal.ADMIN
        user.activo = True
        user.cant_intentos = 0
        user.save()

        action = "creado exitosamente" if created else "actualizado exitosamente"
        self.stdout.write(
            self.style.SUCCESS(f"Superusuario [{user.email}] {action} con credenciales de .env.")
        )
