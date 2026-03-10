"""Core logic for scanning and claiming rewards on Polymarket.

Uses pure JavaScript for finding/clicking elements so it works
even when the screen is locked (Chrome throttles rendering but JS still runs).
"""

import time
import logging

from selenium import webdriver
from selenium.common.exceptions import WebDriverException

from config import (
    ClaimerConfig,
    CLAIM_BUTTON_TEXT,
    CONFIRM_CLAIM_TEXT,
)

logger = logging.getLogger(__name__)

JS_FIND_AND_CLICK_CLAIM = """
var buttons = document.querySelectorAll('button');
for (var i = 0; i < buttons.length; i++) {
    var text = buttons[i].innerText.trim();
    if (text === arguments[0] && !buttons[i].disabled) {
        buttons[i].click();
        return text;
    }
}
return null;
"""

JS_FIND_AND_CLICK_CONFIRM = """
var buttons = document.querySelectorAll('button');
for (var i = 0; i < buttons.length; i++) {
    var text = buttons[i].innerText.trim();
    if (text.startsWith(arguments[0]) && !buttons[i].disabled) {
        buttons[i].click();
        return text;
    }
}
return null;
"""


class Claimer:
    """Scans Polymarket portfolio for claimable rewards and auto-claims them."""

    def __init__(self, driver: webdriver.Chrome, config: ClaimerConfig = ClaimerConfig()) -> None:
        self._driver = driver
        self._config = config

    def _js_click(self, script: str, arg: str, max_wait: int = 0) -> str | None:
        """Run JS to find and click a button. Retries up to max_wait seconds."""
        deadline = time.time() + max_wait
        while True:
            try:
                result = self._driver.execute_script(script, arg)
                if result:
                    return result
            except WebDriverException as e:
                logger.warning(f"JS error: {e}")
            if time.time() >= deadline:
                return None
            time.sleep(0.5)

    def claim_once(self) -> bool:
        """Execute one full claim cycle: find Claim → click → find Confirm → click.

        All done via JavaScript so it works with locked screen.
        """
        # Step 1: Find and click "Claim"
        result = self._js_click(JS_FIND_AND_CLICK_CLAIM, CLAIM_BUTTON_TEXT)
        if not result:
            return False

        logger.info("Bước 1: Click nút Claim — OK")

        # Step 2: Wait for popup, find and click "Claim $X.XX"
        time.sleep(1)
        result = self._js_click(JS_FIND_AND_CLICK_CONFIRM, CONFIRM_CLAIM_TEXT, max_wait=self._config.popup_wait)
        if not result:
            logger.error("Không tìm thấy nút Confirm trong popup.")
            return False

        logger.info(f"Bước 2: Click '{result}' — OK")
        logger.info("Claim thành công!")
        time.sleep(self._config.post_claim_wait)
        return True
