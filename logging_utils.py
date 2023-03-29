import json
import logging

import functools as ft

DEFAULT_LOG_LEVEL = logging.DEBUG


class JsonFormatter(logging.Formatter):
    """A JSON formatter can be used parse logs more easily."""

    def format(self, record):
        log_record = {
            "timestamp": record.created,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # If the record has exception information, add it to the log record
        if record.exc_info:
            log_record["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_record)


def make_logger(name, filepath=None, level=None):
    logger = logging.getLogger(name)

    filepath = filepath or f"{name}.log"
    file_handler = logging.FileHandler(filepath)
    # formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    formatter = JsonFormatter()
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    level = level or DEFAULT_LOG_LEVEL
    logger.setLevel(level)

    logger.info("Logger ready!")
    return logger


def log_exceptions(logger):
    def decorator(f):
        @ft.wraps(f)
        def wrapped_f(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                logger.exception(e, exc_info=e)
                raise e

        return wrapped_f

    return decorator
