"""Tests for `ai_marketplace_monitor` module."""

from typing import Generator

import pytest

import ai_marketplace_monitor


@pytest.fixture
def version() -> Generator[str, None, None]:
    """Sample pytest fixture."""
    yield ai_marketplace_monitor.__version__


def test_version(version: str) -> None:
    """Sample pytest test function with the pytest fixture as an argument."""
    assert version == "0.6.1"
