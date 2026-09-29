"""Console logging shared by future pipeline stages."""

import logging


def configure_logging(level: str = "INFO") -> None:
    """Configure a consistent process-wide console logger."""
    normalized = level.upper()
    if normalized not in logging.getLevelNamesMapping():
        raise ValueError(f"Unknown log level: {level}")
    logging.basicConfig(
        level=normalized,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S%z",
        force=True,
    )
