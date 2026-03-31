from datetime import datetime
from collections import namedtuple, deque
from functools import partial
import traceback
from contextlib import contextmanager
import carb
import omni.kit.app
import omni.kit.commands
from typing import Any, Tuple
from .history import add_history, change_history, get_history, get_history_item
from ..commands.command import _call_callbacks as call_callbacks


# register undo/redo commands on system startup
def register_undo_commands():
    omni.kit.commands.register_all_commands_in_module(__name__)


Entry = namedtuple("Entry", ["command", "name", "level", "history_key", "time"])

_undo_stack = deque()
_redo_stack = deque()
_on_change = set()
_on_change_detailed = set()
_level = 0
_group_entry = None
_group_count = 0
_disabled_count = 0
_in_redo_command = False
_in_repeat_command = False


def _incr_command_level():
    global _level
    _level = _level + 1


def _decr_command_level():
    global _level
    if _level <= 0:
        carb.log_error(f"Can't decrement command level. Incr/decr mismatch. {_level}")
        return False
    _level = _level - 1


def _get_command_level():
    return _level


def _create_entry(command, name, level, history_key):
    global _redo_stack
    global _undo_stack
    global _in_redo_command
    entry = Entry(command, name, level, history_key, datetime.now())

    # Reset the redo stack if the command being executed is a root level command
    # and we are not in the middle of a redo command.  Leave the stack alone in that
    # case since we re-execute the commands as a fresh copy to tie in with the history system
    # but don't want to lose the ability to redo the remaining commands
    if level == 0 and not _in_redo_command:
        _redo_stack.clear()

    _undo_stack.append(entry)
    return entry


def execute(command, name, kwargs) -> Tuple[bool, Any]:
    level = _get_command_level()
    history_key = add_history(name, kwargs, level)
    _incr_command_level()
    global _group_entry

    try:
        # If command has "undo()" method it is executed using Undo System,
        # unless undo functionality has been disabled using "begin_disabled()"
        # Otherwise just call "do()".
        if _disabled_count == 0 and callable(getattr(command, "undo", None)):
            result = _execute(command, name, level, history_key)
        else:
            call_callbacks(command, name, kwargs, omni.kit.commands.PRE_DO_CALLBACK)
            result = command.do()
            call_callbacks(command, name, kwargs, omni.kit.commands.POST_DO_CALLBACK)
    except Exception as e:
        # update the history to flag it as having an error so we can render it different
        change_history(history_key, error=True)

        # if there is an active group being created, flag it as being in error state as well
        if _group_entry:
            change_history(_group_entry.history_key, error=True)

        omni.kit.commands._log_error(f"Failed to execute a command: {name}.\n{_format_exception(e)}")
        return (False, None)
    finally:
        # always decrement the group level so we don't end up with a mismatch due to an error being raised
        _decr_command_level()

        # History changed -> dispatch change event
        omni.kit.commands._dispatch_changed()

    return (True, result)


def subscribe_on_change(on_change):
    global _on_change
    _on_change.add(on_change)


def unsubscribe_on_change(on_change):
    global _on_change
    _on_change.discard(on_change)


def subscribe_on_change_detailed(on_change):
    global _on_change_detailed
    _on_change_detailed.add(on_change)


def unsubscribe_on_change_detailed(on_change):
    global _on_change_detailed
    _on_change_detailed.discard(on_change)


def can_undo():
    return len(_undo_stack) > 0


def can_redo():
    return len(_redo_stack) > 0


def can_repeat():
    return len(_undo_stack) > 0


def clear_stack():
    _undo_stack.clear()
    _redo_stack.clear()


def get_undo_stack():
    return _undo_stack


def get_redo_stack():
    return _redo_stack


# implement these as bare commands so they integrate properly with the history part of the system
class Undo(omni.kit.commands.Command):
    def __init__(self):
        super().__init__()

    def do(self):
        global _redo_stack
        if not can_undo():
            return False

        keep_going = True
        cmds = []
        history_entries = []
        while keep_going and len(_undo_stack) > 0:
            entry = _undo_stack.pop()
            if entry.level == 0:
                _redo_stack.append(entry)
                keep_going = False
            try:
                history_entry = get_history_item(entry.history_key)
                kwargs = history_entry.kwargs if history_entry else dict()
                call_callbacks(entry.command, entry.name, kwargs, omni.kit.commands.PRE_UNDO_CALLBACK)
                entry.command.undo()
                call_callbacks(entry.command, entry.name, kwargs, omni.kit.commands.POST_UNDO_CALLBACK)
                cmds.append(entry.name)
                if history_entry:
                    history_entries.append(history_entry)
            except Exception as e:
                carb.log_error(f"Failed to undo a command: {entry.name}.\n{_format_exception(e)}")

        # take care of alerting the undo set of listeners here
        # the command side will be handled in the calling code
        #
        # Note: The on_change events sent when undoing a command are identical to the
        # ones generated when the command was originally executed or is then redone,
        # except when a command group is undone in which case all commands that are
        # part of the group will be sent as a list to a single call of the callback.
        #
        # I don't think this makes sense, firstly because when commands are executed
        # individually (as opposed to part of a group), there is no way to determine
        # whether the command is being executed, undone, or redone. Secondly, groups
        # of commands will generate individual callbacks when originally executed or
        # redone, but only a single callback for the entire group when it is undone.
        #
        # Another confusing aspect of these on_change callbacks is that there is an
        # identically named API exposed via the 'omni.kit.commands' module which is
        # used to notify subscribers when a command is registered, deregistered, or
        # added to the command history (which is distinct from the undo/redo stack).
        #
        # Ideally we should clean up both of these APIs, but there is existing code
        # that depends on the existing behaviour. There have been discussions about
        # deprecating this entire 'omni.kit.undo' module in favour of new APIs that
        # are exposed through 'omni.kit.commands' instead, which may be a good time
        # to address this.
        _dispatch_changed(cmds)
        _dispatch_changed_detailed(history_entries)

        return True


class Redo(omni.kit.commands.Command):
    def __init__(self):
        super().__init__()

    def do(self):
        global _redo_stack
        global _in_redo_command
        if not can_redo():
            return False

        # we have to play with the command level to make it look like redo isn't in the stack
        # the entry that is executed should be at the root level, not redo
        _decr_command_level()
        try:
            # treat this as a group of 1
            entry = _redo_stack.pop()
            _in_redo_command = True
            return _execute_group_entries([entry])
        finally:
            _in_redo_command = False
            _incr_command_level()


class Repeat(omni.kit.commands.Command):
    def __init__(self):
        super().__init__()

    def do(self):
        global _undo_stack
        global _in_repeat_command
        if not can_repeat():
            return False

        # we have to play with the command level to make it look like repeat isn't in the stack
        # the entry that is executed should be at the root level, not repeat
        _decr_command_level()
        try:
            # find the last base level command and treat it as a group of 1
            for entry in reversed(_undo_stack):
                if entry.level == 0:
                    _in_repeat_command = True
                    return _execute_group_entries([entry])
        finally:
            _in_repeat_command = False
            _incr_command_level()


def undo():
    (success, ret_val) = omni.kit.commands.execute("Undo")
    return success and ret_val


def redo():
    (success, ret_val) = omni.kit.commands.execute("Redo")
    return success and ret_val


def repeat():
    (success, ret_val) = omni.kit.commands.execute("Repeat")
    return success and ret_val


# helper used to execute commands in the group scope when 'redo' or 'repeat' is called on the group
def _execute_group_entries(entries):
    history = get_history()
    for e in entries:
        kwargs = history[e.history_key].kwargs if e.history_key in history else {}
        command = e.command
        if _in_repeat_command:
            # If we're repeating the command, we must create a new instance,
            # and if it's a group command we must also copy the 'do' function.
            command = e.command.__class__(**kwargs)
            if isinstance(command, GroupCommand):
                command.do = e.command.do
        (success, _) = execute(command, e.name, kwargs)
        if not success:
            raise Exception("Failed to redo or repeat commands")

    return True


class GroupCommand(object):
    def __init__(self):
        super().__init__()
        # this is set once all the children run and the group is closed
        # it will capture all of the children (and their descendants) so we can redo them later
        self.do = lambda *_: carb.log_error("Descendants for group not set")

    # there is never anythign to do 'undo' for a group command
    # all the undo work is handled by the children of the group
    def undo(self):
        pass


def begin_group():
    """Begin group of **Commands**."""
    global _group_entry
    global _group_count

    _group_count = _group_count + 1
    if _group_count == 1:
        level = _get_command_level()
        _incr_command_level()  # this should only be called if an undo entry is created
        history_key = add_history("Group", {}, level)
        _group_entry = _create_entry(GroupCommand(), "Group", level, history_key)


def end_group():
    """End group of **Commands**."""
    global _group_entry
    global _group_count
    global _undo_stack

    _group_count = _group_count - 1
    if _group_count == 0 and _group_entry is not None:
        _decr_command_level()

        try:
            # create a real do function now that we have the full list of entries associated with the group
            # grab all entries after the group until the end of the list and capture that list in a partial
            # function for processing if 'redo' is called on the group
            group_index = _undo_stack.index(_group_entry)
            group_entries = list(filter(lambda entry: entry.level == 1, list(_undo_stack)[group_index + 1 :]))
            if group_entries:
                _group_entry.command.do = partial(_execute_group_entries, group_entries)

        finally:
            # have to manually call the listeners since groups don't go through higher level command code
            _dispatch_changed([_group_entry.name])
            history_entry = get_history_item(_group_entry.history_key)
            if history_entry:
                _dispatch_changed_detailed([history_entry])
            omni.kit.commands._dispatch_changed()

            # whether there was anything to capture or not, this group is closed, so clear out the entry
            _group_entry = None


@contextmanager
def group():
    """Group multiple commands in one.

    This function is a context manager.

    Example:

    .. code-block:: python

        with omni.kit.undo.group():
            omni.kit.commands.execute("Foo1")
            omni.kit.commands.execute("Foo2")
    """

    begin_group()
    try:
        yield
    finally:
        end_group()


def begin_disabled():
    """
    Begin preventing **Commands** being added to the undo stack.
    Must be paired with a subsequent call to end_disabled()
    """
    global _disabled_count
    _disabled_count = _disabled_count + 1


def end_disabled():
    """
    Stop preventing **Commands** being added to the undo stack.
    Must be paired with a prior call to begin_disabled()
    """
    global _disabled_count
    if _disabled_count > 0:
        _disabled_count = _disabled_count - 1
    else:
        carb.log_error(f"undo.end_disabled() called without matching prior call to undo.begin_disabled()")


@contextmanager
def disabled():
    """Prevent commands being added to the undo stack.

    This function is a context manager.

    Example:

    .. code-block:: python

        with omni.kit.undo.disabled():
            omni.kit.commands.execute("Foo1")
            omni.kit.commands.execute("Foo2")
    """

    begin_disabled()
    try:
        yield
    finally:
        end_disabled()


def _execute(command, name, level, history_key):
    try:
        # create an undo entry on the stack and execute its do function
        entry = _create_entry(command, name, level, history_key)
        # We want the callbacks to execute within the same undo group as the command
        # so that any commands they execute will be undone at the same time as this.
        history_entry = get_history_item(history_key)
        kwargs = history_entry.kwargs if history_entry else dict()
        call_callbacks(command, name, kwargs, omni.kit.commands.PRE_DO_CALLBACK)
        result = command.do()
        call_callbacks(command, name, kwargs, omni.kit.commands.POST_DO_CALLBACK)
    except Exception as error:
        # If the current command fails we need to unwind anything that came from it.
        # Undo entries on the stack until we get back to the current entry.
        # Any commands after this one in the stack were spawned by this command.
        cmd_names = []
        history_entries = []
        while True:
            last_entry = _undo_stack.pop()

            # run undo on the command so we don't leave things in a half complete state
            # trap any errors individually so each command has a chance to run
            try:
                last_entry.command.undo()

                # make sure to alert the system of changes to all involved commands
                # only add to the list if the undo command completed successfully
                cmd_names.append(last_entry.name)
                history_entry = get_history_item(last_entry.history_key)
                if history_entry:
                    history_entries.append(history_entry)
            except Exception as e:
                carb.log_error(f"Failed to undo a command: {last_entry.name}.\n{_format_exception(e)}")

            if last_entry == entry:
                # add it to the redo stack if it is a base level command
                if level == 0:
                    _redo_stack.append(entry)

                # when we get back to the current command we are done
                break

        # pump the callbacks with all commands that changed
        _dispatch_changed(cmd_names)
        _dispatch_changed_detailed(history_entries)

        # re-raise the original error so the command system can handle it
        # only need to manage the undo stack here, command system will take care of the rest
        raise error

    if name:
        _dispatch_changed([name])

    history_entry = get_history_item(history_key)
    if history_entry:
        _dispatch_changed_detailed([history_entry])

    return result


def _dispatch_changed(cmd_names=[]):
    for f in _on_change:
        f(cmd_names)


def _dispatch_changed_detailed(cmd_entries=[]):
    for f in _on_change_detailed:
        f(cmd_entries)


def _format_exception(e: Exception, remove_n_last_frames: int = 2) -> str:
    """Pretty format exception. Include exception info, call stack of exception itself and this function callstack.
    This function is meant to be used in ``except`` clause.

    Args:
        e: Exception.
        remove_n_last_frames: Number of last call stack frames to be removed. Usually this function and few above are meaningless to the user.

    Returns:
        Formatted string.
    """
    stack = traceback.format_list(traceback.extract_stack()[:-remove_n_last_frames])
    stack.extend(["[...skipped...]\n"])
    stack.extend(traceback.format_list(traceback.extract_tb(e.__traceback__)))
    return "".join(stack) + f"\n {e.__class__} {e}"
