import logging, sys

LEVEL = logging.INFO

def configure_logging() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    root = logging.getLogger()
    root.setLevel(LEVEL)
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
