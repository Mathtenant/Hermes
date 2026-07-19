"""Async job queue for heavy passes (SQLite-backed).

Named ``jobqueue`` (not ``queue``) to avoid shadowing the stdlib ``queue``
module. Heavy critic reviews are enqueued and processed by a worker process so
they never block the interactive CLI on bandwidth-bound hardware.
"""
