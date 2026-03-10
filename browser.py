"""Browser connection and utilities for Chrome DevTools."""

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException

from config import CHROME_DEBUG_URL, POLYMARKET_PORTFOLIO_URL


def connect_chrome(debug_url: str = CHROME_DEBUG_URL) -> webdriver.Chrome:
    """Attach to an existing Chrome instance with remote debugging enabled.

    Chrome must be started with: --remote-debugging-port=9222
    """
    options = Options()
    options.add_experimental_option("debuggerAddress", f"localhost:9222")

    try:
        driver = webdriver.Chrome(options=options)
    except WebDriverException as e:
        raise ConnectionError(
            "Không thể kết nối Chrome. Hãy chắc chắn Chrome đang chạy với:\n"
            '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
            "--remote-debugging-port=9222"
        ) from e

    return driver


def navigate_to_portfolio(driver: webdriver.Chrome) -> None:
    """Navigate to Polymarket portfolio page if not already there."""
    current = driver.current_url
    if POLYMARKET_PORTFOLIO_URL not in current:
        driver.get(POLYMARKET_PORTFOLIO_URL)


def is_page_ready(driver: webdriver.Chrome) -> bool:
    """Check if the page has finished loading."""
    try:
        state = driver.execute_script("return document.readyState")
        return state == "complete"
    except WebDriverException:
        return False
