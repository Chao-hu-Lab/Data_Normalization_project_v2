"""Qt worker object for running one processor outside the GUI thread."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import TextIOBase
import sys
import threading
import traceback
from typing import Callable

from PySide6.QtCore import QObject, Signal, Slot

from metabolomics.utils.results import ProcessingResult


Processor = Callable[..., ProcessingResult]


class _SignalTextStream(TextIOBase):
    def __init__(
        self,
        fallback: TextIOBase,
        emit_line: Callable[[str], None],
        owner_thread_id: int,
    ) -> None:
        super().__init__()
        self._fallback = fallback
        self._emit_line = emit_line
        self._owner_thread_id = owner_thread_id
        self._buffer = ""

    def writable(self) -> bool:
        return True

    def write(self, text: str) -> int:
        if threading.get_ident() != self._owner_thread_id:
            return self._fallback.write(text)
        if not text:
            return 0
        self._buffer += text.replace("\r", "\n")
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line:
                self._emit_line(line)
        return len(text)

    def flush(self) -> None:
        if threading.get_ident() != self._owner_thread_id:
            self._fallback.flush()
            return
        if self._buffer:
            self._emit_line(self._buffer)
            self._buffer = ""


class ProcessorWorker(QObject):
    """Call one processor and communicate only through Qt signals."""

    log_line = Signal(str, str, str)
    finished = Signal(str, object)
    failed = Signal(str, str)

    def __init__(
        self,
        run_id: str,
        processor: Processor,
        kwargs: dict[str, object],
    ) -> None:
        super().__init__()
        self._run_id = run_id
        self._processor = processor
        self._kwargs = kwargs

    @Slot()
    def run(self) -> None:
        worker_thread_id = threading.get_ident()
        stdout = _SignalTextStream(
            sys.stdout,
            lambda line: self.log_line.emit(self._run_id, "info", line),
            worker_thread_id,
        )
        stderr = _SignalTextStream(
            sys.stderr,
            lambda line: self.log_line.emit(self._run_id, "error", line),
            worker_thread_id,
        )
        try:
            with redirect_stdout(stdout), redirect_stderr(stderr):
                result = self._processor(**self._kwargs)
            if not isinstance(result, ProcessingResult):
                raise TypeError("Processor must return ProcessingResult")
        except Exception:
            stdout.flush()
            stderr.flush()
            self.failed.emit(self._run_id, traceback.format_exc())
            return

        stdout.flush()
        stderr.flush()
        self.finished.emit(self._run_id, result)
