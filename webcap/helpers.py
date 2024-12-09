import re
import asyncio
from pathlib import Path
from contextlib import suppress


async def task_pool(fn, all_args, threads=10, global_kwargs=None):
    if global_kwargs is None:
        global_kwargs = {}

    tasks = {}
    all_args = list(all_args)

    def new_task():
        with suppress(IndexError):
            arg = all_args.pop(0)
            task = asyncio.create_task(fn(arg, **global_kwargs))
            tasks[task] = arg

    for _ in range(threads):  # Start initial batch of tasks
        new_task()

    while tasks:  # While there are tasks pending
        # Wait for the first task to complete
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            arg = tasks.pop(task)
            result = task.result()
            yield arg, result
            new_task()


def str_or_file_list(l):
    """
    Chains together list elements into a unified list, including the contents of any elements that are files.
    """
    if not isinstance(l, (list, tuple, set)):
        l = [l]
    final_list = {}
    for entry in l:
        f = str(entry).strip()
        f_path = Path(f).resolve()
        if f_path.is_file():
            with open(f_path, "r") as f:
                for line in f:
                    final_list[line.strip()] = None
        else:
            final_list[f] = None

    return list(final_list)


sub_regex = re.compile(r"[^a-zA-Z0-9_\.-]")
sub_regex_multiple = re.compile(r"\-+")


def sanitize_filename(filename):
    """
    Sanitizes a filename by replacing non-alphanumeric characters with underscores.
    """
    filename = sub_regex.sub("-", filename)
    # collapse multiple underscores
    filename = sub_regex_multiple.sub("-", filename)
    return filename
