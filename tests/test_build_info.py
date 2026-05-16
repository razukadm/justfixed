"""Tests for is_expired() in _build_info."""

from datetime import timedelta

from justfixed._build_info import EXPIRY_DATE, is_expired


def test_day_before_expiry_is_not_expired() -> None:
    assert is_expired(EXPIRY_DATE - timedelta(days=1)) is False


def test_expiry_date_itself_is_not_expired() -> None:
    assert is_expired(EXPIRY_DATE) is False


def test_day_after_expiry_is_expired() -> None:
    assert is_expired(EXPIRY_DATE + timedelta(days=1)) is True
