import logging
import io
import sys


def setup_logger(name: str) -> logging.Logger:
    numeric_level = getattr(logging, "INFO", logging.INFO)

    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)

    if not logger.handlers:
        stream = sys.stdout
        if hasattr(sys.stdout, "buffer"):
            try:
                stream = io.TextIOWrapper(
                    sys.stdout.buffer,
                    encoding=(getattr(sys.stdout, "encoding", None) or "utf-8"),
                    errors="backslashreplace",
                    line_buffering=True,
                )
            except Exception:
                stream = sys.stdout

        handler = logging.StreamHandler(stream)
        handler.setLevel(numeric_level)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)

    # Avoid double-emitting via root handlers (which may use GBK stream)
    logger.propagate = False

    return logger
