import logging

from app.logging_config import NoiseFilter


def record(name: str, message: str) -> logging.LogRecord:
    return logging.LogRecord(name, logging.INFO, __file__, 1, message, (), None)


def test_noise_filter_drops_known_funasr_internal_messages():
    noise_filter = NoiseFilter()

    assert noise_filter.filter(record("root", "Loading pretrained params from model.pt")) is False
    assert noise_filter.filter(record("root", "trust_remote_code: False")) is False
    assert noise_filter.filter(record("app.streaming", "stream.processor.warmup.complete")) is True
