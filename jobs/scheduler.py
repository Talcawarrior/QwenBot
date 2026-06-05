"""Zamanlayıcı ve bağımsız iş tetikleyici mekanizması."""

import logging
from datetime import datetime

logger = logging.getLogger("JOBS_SCHEDULER")


def job_wrapper(job_name: str, func):
    """Sarmalayıcı sayesinde bir iş çökerse diğer işlerin çalışması durmaz."""
    async def wrapped(*args, **kwargs):
        logger.info("=" * 50)
        logger.info("JOB BAŞLADI: %s @ %s", job_name, datetime.utcnow())
        try:
            result = await func(*args, **kwargs)
            logger.info("JOB TAMAMLANDI: %s -> %s", job_name, result)
            return result
        except Exception as e:
            logger.error("JOB HATA ALDI: %s -> %s", job_name, e, exc_info=True)
        logger.info("=" * 50)
    return wrapped
