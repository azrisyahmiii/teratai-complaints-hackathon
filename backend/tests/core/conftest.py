"""Core tests never reach the model by accident: the investigator (C12) is off unless a test turns it on."""

from collections.abc import Iterator

import pytest

from teratai.llm import breaker


@pytest.fixture(autouse=True)
def _investigator_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATOR", "off")


@pytest.fixture(autouse=True)
def _breaker_closed() -> Iterator[None]:
    """The LLM circuit breaker is process-wide state: every test starts and ends with it closed."""
    breaker.reset()
    yield
    breaker.reset()
