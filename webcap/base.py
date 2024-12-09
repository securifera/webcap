import logging

logging.basicConfig(level=logging.ERROR, format="%(name)s [%(levelname)s] %(message)s")


class WebCapBase:
    def __init__(self):
        self.log = logging.getLogger(__name__)
