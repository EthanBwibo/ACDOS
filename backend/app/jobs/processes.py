"""Waiting for another process to exit, by its PID (#51).

Solver processes use it to exit when the API process that started them dies
(worker.init). The tests and the smoke run use it to check that no solver
process outlives the API.

On Windows a PID can be reused as soon as its process exits, so the process
is held by a handle opened while it is alive: the handle stays tied to that
process, never to a later one with the same PID. Elsewhere, os.kill(pid, 0)
says whether the PID is in use; that could in principle be a reused PID, so
the solver processes there watch os.getppid() instead (worker._exit_with).
"""

import os
import time

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _SYNCHRONIZE = 0x00100000
    _WAIT_OBJECT_0 = 0
    _INFINITE = 0xFFFFFFFF


class Process:
    """A process to wait on, opened while it is known to be alive."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self._handle = None
        if os.name == "nt":
            self._handle = _kernel32.OpenProcess(_SYNCHRONIZE, False, pid)
            if not self._handle:
                raise OSError(ctypes.get_last_error(), f"cannot open process {pid}")

    def wait(self, timeout_sec: float | None = None) -> bool:
        """True once the process has exited; False if it is still running
        after timeout_sec (None: wait as long as it takes)."""
        if self._handle is not None:
            ms = _INFINITE if timeout_sec is None else int(timeout_sec * 1000)
            return _kernel32.WaitForSingleObject(self._handle, ms) == _WAIT_OBJECT_0
        deadline = None if timeout_sec is None else time.monotonic() + timeout_sec
        while True:
            try:
                os.kill(self.pid, 0)
            except ProcessLookupError:
                return True
            except PermissionError:
                pass  # in use, by a process we may not signal
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.2)
