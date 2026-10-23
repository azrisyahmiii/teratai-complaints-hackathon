"""Replay provider (`DEMO_MODE=cached`): reads only the disk cache, never touches the network."""

from __future__ import annotations

from typing import Any

from teratai.llm.base import BaseProvider, CacheMiss


class ReplayProvider(BaseProvider):
    def _call_api(self, request: dict[str, Any], key: str) -> dict[str, Any]:
        raise CacheMiss(key, str(request["model"]))
