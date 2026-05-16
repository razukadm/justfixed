# This file is rewritten by build.py at build time.
# Do not edit by hand for releases — let the build script update it.

from datetime import date

VERSION     = "0.1.0"
BUILD_DATE  = date(2026, 5, 16)
EXPIRY_DATE = date(2026, 8, 31)


def is_expired(today: date | None = None) -> bool:
    """Return True if today is strictly after EXPIRY_DATE.

    EXPIRY_DATE is the last valid day — the app still runs on
    EXPIRY_DATE itself and refuses to launch on the day after.
    The `today` parameter exists for testing; production callers
    leave it None to use the real clock.
    """
    if today is None:
        today = date.today()
    return today > EXPIRY_DATE
