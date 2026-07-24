from celery import shared_task
import logging

logger = logging.getLogger(__name__)

@shared_task(bind=True, max_retries=3)
def process_ptc_task(self, ptc_data, user_id, custom_message="PTC processed successfully"):
    """
    Background task to process PTC data after API success.
    """
    try:
        # Your background processing logic here
        logger.info(f"[PTC Task] {custom_message} | User: {user_id} | Data: {ptc_data}")
        
        # Add your actual processing code here
        # e.g., send emails, update database, call external services, etc.
        
    except Exception as exc:
        logger.error(f"[PTC Task] Failed: {exc}")
        raise self.retry(exc=exc, countdown=60)