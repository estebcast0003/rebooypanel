from django.core.management.base import BaseCommand

from extractor.models import FacebookPage
from extractor.services.runner import start_extraction_job


class Command(BaseCommand):
    help = "Executes an immediate follower extraction update for all stored Facebook fanpages."

    def add_arguments(self, parser):
        parser.add_argument(
            "--async",
            dest="run_async",
            action="store_true",
            default=False,
            help="Run extraction in background thread without waiting for completion.",
        )
        parser.add_argument(
            "--proxy",
            type=str,
            default=None,
            help="Optional custom proxy URL override.",
        )

    def handle(self, *args, **options):
        run_async = options["run_async"]
        proxy_url = options["proxy"]

        pages = list(FacebookPage.objects.all().values_list("url", flat=True).distinct())
        if not pages:
            self.stdout.write(
                self.style.WARNING("No Facebook fanpages found in database. Nothing to update.")
            )
            return

        self.stdout.write(
            self.style.NOTICE(f"Starting update for {len(pages)} Facebook fanpages...")
        )

        job = start_extraction_job(
            urls=pages,
            raw_input="\n".join(pages),
            proxy_url=proxy_url,
            run_in_background=run_async,
        )

        if run_async:
            self.stdout.write(
                self.style.SUCCESS(f"Extraction job {job.id} launched in background.")
            )
        else:
            job.refresh_from_db()
            self.stdout.write(
                self.style.SUCCESS(
                    f"Extraction job {job.id} completed. Total: {job.total_urls} | "
                    f"Successful: {job.successful_urls} | Failed: {job.failed_urls}"
                )
            )
