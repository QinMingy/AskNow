import logging
import os
from contextvars import ContextVar


request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


class NoiseFilter(logging.Filter):
    noisy_root_prefixes = (
        "download models from model hub:",
        "Loading pretrained params from ",
        "ckpt:",
        "scope_map:",
        "excludes:",
        "Loading ckpt:",
        "trust_remote_code:",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        if record.name == "root" and record.getMessage().startswith(self.noisy_root_prefixes):
            return False
        return True


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    handler = logging.StreamHandler()
    handler.addFilter(RequestIdFilter())
    handler.addFilter(NoiseFilter())
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s | %(levelname)s | %(name)s | process=%(process)d | "
            "request=%(request_id)s | %(message)s"
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    external_level_name = os.getenv("THIRD_PARTY_LOG_LEVEL", "WARNING").upper()
    external_level = getattr(logging, external_level_name, logging.WARNING)
    for logger_name in (
        "httpcore",
        "httpx",
        "modelscope",
        "urllib3",
        "filelock",
        "multipart",
        "litellm",
        "LiteLLM",
        "uvicorn.access",
    ):
        logging.getLogger(logger_name).setLevel(external_level)
