import logging

logging.basicConfig(level=logging.ERROR, format="%(name)s [%(levelname)s] %(message)s")


class PywitnessBase:
    def __init__(self):
        self.log = logging.getLogger(__name__)
        self.log.setLevel(logging.DEBUG)
