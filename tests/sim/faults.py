"""Fault injection toolkit for edge-case simulations (tests/sim).

Low-level, dependency-free primitives shared by every simulation test:

* Thread control — a :class:`threading.Barrier`-synchronised runner
  (``run_barrier_synced``) that releases every worker at the same instant to
  maximise the odds of exercising a genuine race, plus a plain thread-pool
  runner (``run_concurrent``) for high-volume "N concurrent ops" load.
* On-disk corruption — ``corrupt_wal``, ``truncate_file``, ``plant_stale_lock``
  simulate the artefacts a crashed/killed process leaves behind.
* ``flaky`` — wraps a callable so its Nth call raises, for simulating a batch
  write that fails partway through.
* ``raw_conn`` — an independent SQLite connection that bypasses any
  application-level ``RLock``, standing in for "a second process/connection
  opens this file directly".
"""

from __future__ import annotations

import contextlib
import os
import random
import sqlite3
import threading
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

# --------------------------------------------------------------------------- #
# Thread synchronisation
# --------------------------------------------------------------------------- #


def run_barrier_synced(
    fns: list[Callable[[], Any]], *, timeout: float = 10.0
) -> list[tuple[Any, BaseException | None]]:
    """Run every callable in *fns* in its own thread, released simultaneously.

    A :class:`threading.Barrier` sized to ``len(fns)`` holds every thread at
    the start line; once all threads have called ``barrier.wait()`` they are
    released in the same instant. This is what turns "threads that merely
    start close together" into a real, reproducible race between two
    independent connections/operations racing on the same underlying state.

    Returns one ``(result, exception)`` pair per input callable, in the same
    order as *fns*. Exactly one element of each pair is ``None``.
    """
    n = len(fns)
    barrier = threading.Barrier(n)
    results: list[Any] = [None] * n
    errors: list[BaseException | None] = [None] * n

    def _runner(i: int, fn: Callable[[], Any]) -> None:
        try:
            barrier.wait(timeout=timeout)
        except threading.BrokenBarrierError as exc:
            errors[i] = exc
            return
        try:
            results[i] = fn()
        except BaseException as exc:  # noqa: BLE001 - captured for the caller
            errors[i] = exc

    threads = [threading.Thread(target=_runner, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=timeout + 5)
    return list(zip(results, errors, strict=True))


def run_concurrent(
    fn: Callable[[int], Any],
    n: int,
    *,
    max_workers: int | None = None,
    timeout: float = 30.0,
) -> list[tuple[Any, BaseException | None]]:
    """Run ``fn(i)`` for ``i in range(n)`` concurrently via a thread pool.

    Unlike :func:`run_barrier_synced`, threads are *not* released
    simultaneously — this is for high-volume "N concurrent ops" style load
    (hundreds/thousands of writers), where a shared start line adds no value
    and a bare thread pool is both simpler and faster to spin up.

    Returns one ``(result, exception)`` pair per ``i``, in order.
    """
    results: list[Any] = [None] * n
    errors: list[BaseException | None] = [None] * n

    def _runner(i: int) -> None:
        try:
            results[i] = fn(i)
        except BaseException as exc:  # noqa: BLE001 - captured for the caller
            errors[i] = exc

    with ThreadPoolExecutor(max_workers=max_workers or min(n, 64)) as pool:
        futures = [pool.submit(_runner, i) for i in range(n)]
        for f in futures:
            f.result(timeout=timeout)
    return list(zip(results, errors, strict=True))


# --------------------------------------------------------------------------- #
# On-disk corruption
# --------------------------------------------------------------------------- #


def corrupt_wal(db_path: str | Path) -> bool:
    """Flip bytes in the back half of an existing ``-wal`` sidecar file.

    Simulates a crash mid-write-ahead-log-flush: the WAL file exists but some
    of its frames no longer match their own checksums. The 32-byte WAL header
    is left untouched so SQLite still recognises the file *as* a WAL (rather
    than rejecting it outright) — this is what makes the corruption "silent"
    until a frame is actually replayed on next open.

    Returns ``True`` if a non-empty WAL sidecar was found and corrupted,
    ``False`` if the db has no WAL sidecar (never written to, or already
    checkpointed away).
    """
    wal_path = Path(f"{db_path}-wal")
    if not wal_path.exists() or wal_path.stat().st_size == 0:
        return False
    data = bytearray(wal_path.read_bytes())
    rng = random.Random(1234)  # deterministic corruption pattern
    start = max(32, len(data) // 2)
    for i in range(start, len(data)):
        if rng.random() < 0.3:
            data[i] ^= 0xFF
    wal_path.write_bytes(bytes(data))
    return True


def truncate_file(path: str | Path, *, keep_bytes: int = 0) -> int:
    """Truncate *path* to ``keep_bytes``, simulating a partial/interrupted write.

    Returns the file's original size in bytes.
    """
    p = Path(path)
    original_size = p.stat().st_size
    with p.open("r+b") as fh:
        fh.truncate(keep_bytes)
    return original_size


def plant_stale_lock(db_path: str | Path) -> Path:
    """Plant a stale/corrupt WAL shared-memory index (``-shm``) file.

    In WAL mode the ``-shm`` file is SQLite's mmap'd index of reader/writer
    lock slots and WAL frame offsets. A process killed mid-write (``kill
    -9``) can leave a stale or torn ``-shm`` behind, holding lock-slot state
    that no longer corresponds to any live process. SQLite detects the salt
    mismatch against the current ``-wal`` header and rebuilds the ``-shm`` on
    next open — this plants that crash artefact so recovery can be verified.

    Returns the path to the planted file.
    """
    shm_path = Path(f"{db_path}-shm")
    shm_path.write_bytes(os.urandom(32 * 1024))
    return shm_path


# --------------------------------------------------------------------------- #
# Flaky callables
# --------------------------------------------------------------------------- #


class InjectedFailureError(RuntimeError):
    """Raised by :func:`flaky`-wrapped callables on their designated call."""


def flaky(
    fn: Callable[..., T],
    *,
    fail_on_call: int,
    exc: type[BaseException] = InjectedFailureError,
    message: str = "injected failure",
) -> Callable[..., T]:
    """Wrap *fn* so its ``fail_on_call``-th invocation (1-indexed) raises.

    Every other call passes through to *fn* unchanged. Call counting is
    thread-safe and shared across every caller of the wrapped callable —
    useful for simulating a batch import that fails partway through (S5):
    wrap the underlying write step so item *k* raises mid-batch and assert
    the surrounding transaction/rollback behaviour.
    """
    call_count = 0
    lock = threading.Lock()

    def wrapper(*args: Any, **kwargs: Any) -> T:
        nonlocal call_count
        with lock:
            call_count += 1
            current = call_count
        if current == fail_on_call:
            raise exc(message)
        return fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------- #
# Out-of-band inspection
# --------------------------------------------------------------------------- #


@contextlib.contextmanager
def raw_conn(
    db_path: str | Path, *, read_only: bool = True
) -> Iterator[sqlite3.Connection]:
    """Open an independent SQLite connection to *db_path*.

    Bypasses any application-level ``RLock`` entirely — this is exactly the
    scenario S1/S4 exist to test: a second, uncoordinated connection (a
    different process, or a crash-recovery reader) touching the same file.
    ``read_only=True`` (the default) opens via a ``file:`` URI in ``mode=ro``
    so inspection can never itself corrupt or write to the database under
    test.
    """
    path = str(db_path)
    if read_only:
        uri = f"file:{path}?mode=ro"
        conn = sqlite3.connect(uri, uri=True, timeout=5)
    else:
        conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()
