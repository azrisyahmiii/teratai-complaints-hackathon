"""Ops service (docs/dev/tasks/ops-platform.md): login, two-tier approval, fraud steps, audit log and case trail.

A separate FastAPI app with its own SQLite. It reads and acts on cases only through the frozen core HTTP API.
"""
