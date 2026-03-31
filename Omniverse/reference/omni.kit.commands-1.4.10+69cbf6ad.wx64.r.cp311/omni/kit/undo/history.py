import carb.settings

from collections import namedtuple, OrderedDict
from functools import lru_cache
from itertools import islice

# implementing the history as an OrderedDict so we can cap the max size
# while keeping consistent indices that outside systems can hold on to
# doing it as a deque would let us cap the size, but the indices change
# when the cap is hit and it slides the oldest item off
# this way outside code can keep the index as well as iterate over it and things stay in the proper order
MAX_HISTORY_SIZE = 1000000
_history = OrderedDict()
_history_index = 0

HistoryEntry = namedtuple("HistoryEntry", ["name", "kwargs", "level", "error"])


@lru_cache()
def _get_crash_report_history_count():
    return carb.settings.get_settings().get("/exts/omni.kit.commands/crashReportHistoryCount")


# Only convert to string primitive types, others may lead to crash (UsdStage was one of them).
PRIMITIVE_TYPES = {"<class 'str'>", "<class 'int'>", "<class 'float'>", "<class 'bool'>", "<class 'pxr.Sdf.Path'>"}


def _format_history_entry(history: HistoryEntry):
    s = ""
    for k, v in history.kwargs.items():
        s += "(" if not s else ","
        value = str(v) if str(type(v)) in PRIMITIVE_TYPES else "?"
        s += f"{k}={value}"
    if s:
        s += ")"
    return history.name + s


def add_history(name: str, kwargs: dict, level: int):
    """Add a **Command** execution to the history.

    Takes: (Command name, Arguments, Groupping level).
    Return: index that can be used to modify it later"""
    global _history_index
    _history_index = _history_index + 1
    _history[_history_index] = HistoryEntry(name, kwargs, level, False)

    # now make sure we have <= MAX_HISTORY_SIZE elements in the history
    while True:
        # if the head of the history is a root command and we are under the size limit, we are done
        # otherwise we need to remove the entire group so we don't end up with children at the front of the history
        key = next(iter(_history)) if len(_history) else None
        if not key or (_history[key].level == 0 and len(_history) < MAX_HISTORY_SIZE):
            break

        # pop the entry from the front of the list and move on
        _history.popitem(last=False)

    # store last N commands for crash report (if we crash later)
    n = _get_crash_report_history_count()
    if n > 0:
        # join last N elements of history into comma separted string
        lastCommands = [_format_history_entry(x) for x in islice(reversed(_history.values()), n)]
        settings = carb.settings.get_settings()
        settings.set("/crashreporter/data/lastCommands", ",".join(reversed(lastCommands)))
        settings.set("/crashreporter/data/lastCommand", next(iter(lastCommands), ""))

    return _history_index


def change_history(key: int, **kwargs):
    """Update the history entry for **key**.

    key: Index of the history entry to modify.
    kwargs: any of the properties of HistoryEntry."""
    if key in _history:
        _history[key] = _history[key]._replace(**kwargs)


def get_history():
    """Get **Command** execution history.

    Returns a list of tuples: HistoryEntry(Command name, Arguments, Groupping level, Error status)."""
    return _history


def get_history_item(history_key: int) -> HistoryEntry:
    try:
        return _history[history_key]

    # if the key is missing return None, any other erros should flow through to the caller
    except KeyError:
        return None


def clear_history():
    """Clear **Command** execution history."""
    _history.clear()
