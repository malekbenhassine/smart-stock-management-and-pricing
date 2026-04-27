import threading
import time

from app.core.config import settings
from app.services.scraping_service import ScrapingService


_scheduler_started = False


def start_scheduler() -> None:
    global _scheduler_started

    if _scheduler_started:
        return

    _scheduler_started = True

    def _worker():
        scraper = ScrapingService()

        while True:
            try:
                scraper.scrape_due_or_all()
            except Exception as exc:
                print(f"[scheduler] erreur: {exc}")

            time.sleep(settings.SCRAPING_INTERVAL_MINUTES * 60)

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()