"""Configuration constants for Polymarket Auto-Claimer."""

from dataclasses import dataclass

# Browser
CHROME_DEBUG_PORT = 9222
CHROME_DEBUG_URL = f"http://localhost:{CHROME_DEBUG_PORT}"
POLYMARKET_PORTFOLIO_URL = "https://polymarket.com/portfolio"

# Timing (seconds)
SCAN_INTERVAL = 240
PAGE_LOAD_WAIT = 3
POPUP_WAIT = 3
POST_CLAIM_WAIT = 2

# Selectors
CLAIM_BUTTON_SELECTOR = 'button[data-testid="claim-button"]'
CLAIM_BUTTON_TEXT = "Claim"
CONFIRM_CLAIM_TEXT = "Claim $"

# Retry
MAX_RETRIES = 3
RETRY_DELAY = 2


@dataclass(frozen=True)
class ClaimerConfig:
    """Immutable configuration for the claimer."""

    scan_interval: int = SCAN_INTERVAL
    page_load_wait: int = PAGE_LOAD_WAIT
    popup_wait: int = POPUP_WAIT
    post_claim_wait: int = POST_CLAIM_WAIT
    max_retries: int = MAX_RETRIES
