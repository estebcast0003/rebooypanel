import logging
try:
    from celery import shared_task
    from extractor.services.runner import execute_job_sync
    from extractor.services.scheduler import scheduler

    logger = logging.getLogger(__name__)

    @shared_task(bind=True, name='extractor.run_extraction_job')
    def run_extraction_job_task(self, job_id: str, urls: list[str], proxy_url: str | None = None):
        logger.info(f'Celery task starting extraction job {job_id} ({len(urls)} URLs)')
        return execute_job_sync(job_id=job_id, urls=urls, proxy_url=proxy_url)

    @shared_task(name='extractor.scheduled_update_followers')
    def scheduled_update_followers_task():
        logger.info('Celery periodic task triggering scheduled update')
        return scheduler.trigger_now()
except ImportError:
    pass
