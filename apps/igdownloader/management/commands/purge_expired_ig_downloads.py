from django.core.management.base import BaseCommand
from igdownloader.services.cleanup_service import purge_expired_downloads


class Command(BaseCommand):
    help = 'Elimina descargas de Instagram y miniaturas en disco con más de 24 horas de antigüedad.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Horas de retención de las descargas (por defecto: 24).'
        )

    def handle(self, *args, **options):
        hours = options['hours']
        self.stdout.write(f"Iniciando purga de descargas con más de {hours} horas...")

        result = purge_expired_downloads(hours=hours)

        self.stdout.write(
            self.style.SUCCESS(
                f"Purga exitosa: {result['records_deleted']} registros eliminados, "
                f"{result['files_deleted']} miniaturas borradas (Cutoff: {result['cutoff']})."
            )
        )
