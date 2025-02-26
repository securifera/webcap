# set multiprocess start method to spawn
import multiprocessing

try:
    multiprocessing.set_start_method("spawn")
except RuntimeError:
    pass

from .browser import Browser

__all__ = ["Browser"]
