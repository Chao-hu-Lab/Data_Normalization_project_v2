from __future__ import annotations

import logging

from metabolomics.gui.app import DataNormalizationApp, StreamToLogger


class _DummyLogger:
    def __init__(self):
        self.calls = []

    def log(self, level, message):
        self.calls.append((level, message))


class _DummyText:
    def __init__(self):
        self.insert_calls = []
        self.seen = []

    def insert(self, position, message, tag):
        self.insert_calls.append((position, message, tag))

    def see(self, position):
        self.seen.append(position)


def test_stream_to_logger_forwards_each_line_without_linebuf_state():
    logger = _DummyLogger()
    stream = StreamToLogger(logger, logging.WARNING)

    stream.write("first line\nsecond line\n")

    assert logger.calls == [
        (logging.WARNING, "first line"),
        (logging.WARNING, "second line"),
    ]
    assert not hasattr(stream, "linebuf")


def test_display_log_uses_record_message_and_error_tag():
    app = DataNormalizationApp.__new__(DataNormalizationApp)
    app.result_text = _DummyText()

    record = logging.makeLogRecord(
        {"levelno": logging.ERROR, "msg": "critical failure"}
    )

    app.display_log(record)

    assert app.result_text.insert_calls == [("end", "critical failure\n", "ERROR")]
    assert app.result_text.seen == ["end"]
