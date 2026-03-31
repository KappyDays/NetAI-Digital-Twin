"""Commands for Omniverse Kit.

:mod:`omni.kit.commands` module is used to register and execute **Commands**. It is built on top of :mod:`omni.kit.undo` module to enable undo/redo operations with **Commands**.

**Command** is any class with ``do()`` method and optionally ``undo()`` method. If **Command** has ``undo()`` method it is put on the undo stack when executed.
It must be inherited from :class:`Command` class for type checking.

Example of creating your command, registering it, passing arguments and undoing.

.. code-block:: python

    class MyOrange(omni.kit.commands.Command):
        def __init__(self, bar: list):
            self._bar = bar

        def do(self):
            self._bar.append('orange')

        def undo(self):
            del self._bar[-1]

>>> import omni.kit.commands
>>> omni.kit.commands.register(MyOrangeCommand)
>>> my_list = []
>>> omni.kit.commands.execute("MyOrange", bar=my_list)
>>> my_list
['orange']
>>> import omni.kit.undo
>>> omni.kit.undo.undo()
>>> my_list
[]
>>> omni.kit.undo.redo()
>>> my_list
['orange']

"""

__all__ = [
    "Command",
    "create",
    "register",
    "register_all_commands_in_module",
    "unregister_module_commands",
    "unregister",
    "PRE_DO_CALLBACK",
    "POST_DO_CALLBACK",
    "PRE_UNDO_CALLBACK",
    "POST_UNDO_CALLBACK",
    "register_callback",
    "unregister_callback",
    "get_command_class",
    "get_command_class_signature",
    "get_command_doc",
    "get_command_parameters",
    "get_commands",
    "get_commands_list",
    "execute",
    "execute_argv",
    "get_argument_parser_from_function",
    "set_logging_enabled",
    "subscribe_on_change",
    "unsubscribe_on_change",
]

from .command import (
    Command,
    create,
    register,
    register_all_commands_in_module,
    unregister_module_commands,
    unregister,
    PRE_DO_CALLBACK,
    POST_DO_CALLBACK,
    PRE_UNDO_CALLBACK,
    POST_UNDO_CALLBACK,
    register_callback,
    unregister_callback,
    get_command_class,
    get_command_class_signature,
    get_command_doc,
    get_command_parameters,
    get_commands,
    get_commands_list,
    execute,
    execute_argv,
    get_argument_parser_from_function,
    _log_error,
    set_logging_enabled,
)
from .command_actions import register_actions, deregister_actions
from .command_bridge import CommandBridge
from .on_change import subscribe_on_change, unsubscribe_on_change, _dispatch_changed
import omni.ext
import omni.kit.app
from carb.eventdispatcher import get_eventdispatcher

# this is needed for physx.ui
# once it properly imports its own dependencies, it can be removed
from typing import Any


class CommandExt(omni.ext.IExt):
    """Monitor for new extensions and register all commands in python modules of those extensions,
       along with setting up a bridge that allows commands to be registered and executed from C++,
       and registration of actions that wrap some basic command functionality like undo and redo.
    """

    def on_startup(self, ext_id):
        # Setup the command bridge
        self._command_bridge = CommandBridge()
        self._command_bridge.on_startup()

        # Register command related actions
        self._ext_name = omni.ext.get_extension_name(ext_id)
        register_actions(self._ext_name)

        # Monitor for commands in new or reloaded extensions
        def on_change(_):
            def register_subclasses(cls):
                register(cls)
                for subcls in cls.__subclasses__():
                    register_subclasses(subcls)

            register_subclasses(Command)


        self._change_script_sub = get_eventdispatcher().observe_event(
            on_event=on_change, observer_name="kit.commands ExtensionChange", event_name=omni.ext.GLOBAL_EVENT_SCRIPT_CHANGED
        )

    def on_shutdown(self):
        # Stop monitoring for commands in new or reloaded extensions
        self._change_script_sub = None

        # Deregister command related actions
        deregister_actions(self._ext_name)

        # Shutdown the command bridge
        self._command_bridge.on_shutdown()
        self._command_bridge = None
