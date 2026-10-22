"""Offline by default: tests run the template reply path unless a test opts into the LLM path (see core/test_reply.py)."""

import pytest


@pytest.fixture(autouse=True)
def _template_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REPLY_MODE", "template")
