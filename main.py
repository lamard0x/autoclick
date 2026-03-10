"""Polymarket Auto-Claimer — Entry point.

Usage:
    1. Mở Chrome với: chrome.exe --remote-debugging-port=9222
    2. Login Polymarket, vào trang Portfolio
    3. Chạy: python main.py
"""

import time
import logging
import sys

from browser import connect_chrome, navigate_to_portfolio
from claimer import Claimer
from config import ClaimerConfig, SCAN_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def run() -> None:
    """Main loop: connect to Chrome, scan for claims, and auto-claim."""
    config = ClaimerConfig()

    logger.info("Đang kết nối Chrome...")
    try:
        driver = connect_chrome()
    except ConnectionError as e:
        logger.error(str(e))
        sys.exit(1)

    logger.info(f"Đã kết nối! Tab hiện tại: {driver.title}")

    # Navigate to portfolio if needed
    navigate_to_portfolio(driver)
    time.sleep(config.page_load_wait)

    claimer = Claimer(driver, config)
    claim_count = 0

    logger.info(f"Bắt đầu scan... (mỗi {SCAN_INTERVAL}s, Ctrl+C để dừng)")

    try:
        while True:
            # Refresh via JS (works when screen locked)
            try:
                driver.execute_script("location.reload()")
            except Exception:
                logger.warning("Không thể refresh, thử lại...")
                time.sleep(5)
                continue

            time.sleep(config.page_load_wait)

            success = claimer.claim_once()
            if success:
                claim_count += 1
                logger.info(f"Tổng claims: {claim_count}")

            time.sleep(config.scan_interval)

    except KeyboardInterrupt:
        logger.info(f"\nDừng lại. Tổng claims: {claim_count}")


if __name__ == "__main__":
    run()
