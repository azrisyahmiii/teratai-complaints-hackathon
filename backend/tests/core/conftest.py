"""Core tests never reach the model by accident: the investigator (C12) is off unless a test turns it on."""

import pytest


@pytest.fixture(autouse=True)
def _investigator_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INVESTIGATOR", "off")
