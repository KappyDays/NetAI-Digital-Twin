import argparse
import carb
from collections import defaultdict
import inspect
import re
import sys
from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Tuple, Type

from .on_change import _dispatch_changed

_commands = defaultdict(dict)
LOGGING_ENABLED = True

# Callback types
PRE_DO_CALLBACK = 'pre_do'
POST_DO_CALLBACK = 'post_do'
PRE_UNDO_CALLBACK = 'pre_undo'
POST_UNDO_CALLBACK = 'post_undo'

# Callback dictionary:
#   Keys: tuple(command class name minus any trailing 'Command', module name), callback type.
#   Value: list of callables.
_callbacks: Dict[Tuple[str, str], Dict[str, List[Callable]]] = defaultdict(lambda: defaultdict(list))

# Callback ID object. We don't expose this publicly to prevent users from relying on its internal representation.
class CallbackID:
    def __init__(self, command_name, module_name, callback_type, callback):
        self.__command_name = command_name
        self.__module_name = module_name
        self.__cb_type = callback_type
        self.__callable = callback

    def get(self):
        return (self.__command_name, self.__module_name, self.__cb_type, self.__callable)


class Command(ABC):
    """Base class for all **Commands**."""

    @abstractmethod
    def do(self):
        pass

    def modify_callback_info(self, cb_type: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """Returns a dictionary of information to be passed to callbacks of the given type.

        By default callbacks are passed a copy of the arguments which were passed to **execute()** when the command
        was invoked. This method can be overridden to modify that information for specific callback types.

        Args:
            cb_type: Type of callback the information will be passed to.
            args: A dictionary containing a copy of the arguments with which the command was invoked. This is a
                  shallow copy so implementations may add, remove or replace dictionary elements but should not
                  modify any of the objects contained within it.

        Returns:
            A dictionary of information to be passed to callbacks of the specified type.
        """
        return args


def _log_error(message: str):
    if LOGGING_ENABLED:
        carb.log_error(message)


def set_logging_enabled(enabled: bool):
    global LOGGING_ENABLED
    LOGGING_ENABLED = enabled


def _get_module_and_class(name: str) -> Tuple[str, str]:
    x = name.rsplit(".", 1)
    if len(x) > 1:
        return x[0], x[1]
    return "", x[0]


def _get_module_and_stripped_class(name: str) -> Tuple[str, str]:
    if name.endswith('Command'):
        name = name[:-7]
    return _get_module_and_class(name)


def create(name, **kwargs):
    """Create **Command** object.

    Args:
        name: **Command** name.
        **kwargs: Arbitrary keyword arguments to be passed into into **Command** constructor.

    Returns:
        **Command** object if succeeded. `None` if failed.
    """

    command_class = get_command_class(name)
    if not command_class:
        return None
    return command_class(**kwargs)


def register(command_class: Type[Command]):
    """Register a **Command**.

    Args:
        command_class: **Command** class.
    """
    if not issubclass(command_class, Command):
        _log_error(f"Can't register command: {command_class} it is not a subclass of a Command.")
        return

    global _commands
    name = command_class.__name__
    module = command_class.__module__

    if module in _commands[name]:
        carb.log_verbose('Command: "{}" is already registered. Overwriting it.'.format(name))

    # If the class contains the "Command" suffix, register it without the suffix
    if name.endswith("Command"):
        name = name[:-7]

    _commands[name][module] = command_class

    _dispatch_changed()


def register_all_commands_in_module(module):
    """Register all **Commands** found in specified module.

    Register all classes in module which inherit :class:`omni.kit.commands.Command`.

    Args:
        module: Module name or module object.

    Returns:
        An accessor object that contains a function for every command to execute it. e.g. if you register
        the commands "Run" and "Hide" then the accessor behaves like:

        .. code-block:: python

            class Accessor:
                @staticmethod
                def Run(**kwargs):
                    execute("Run", **kwargs)
                @staticmethod
                def Hide(**kwargs):
                    execute("Hide", **kwargs)

        This gives you a nicer syntax for running your commands:

        .. code-block:: python

            cmds = register_all_commands_in_module(module)
            cmds.Run(3.14)
            cmds.Hide("Behind the tree")
    """

    class CommandInterface:
        class Immediate:
            pass

    def add_command(cls, name: str, command: Command):
        def execute_command(cls, **kwargs):
            return execute(command.__name__, **kwargs)

        def execute_command_immediate(cls, **kwargs):
            return command.do_immediate(**kwargs)

        execute_command.__doc__ = command.__doc__
        execute_command.__name__ = name
        setattr(cls, name, execute_command)
        # If the command has an immediate mode add that to the command interface too
        if hasattr(command, "do_immediate"):
            if not hasattr(cls, "imm"):
                setattr(cls, "imm", CommandInterface.Immediate())
            execute_command_immediate.__doc__ = command.do_immediate.__doc__
            execute_command_immediate.__name__ = name
            setattr(cls.imm, name, command.do_immediate)

    if isinstance(module, str) and module in sys.modules:
        module = sys.modules[module]
    for name in dir(module):
        obj = getattr(module, name)
        if isinstance(obj, type) and issubclass(obj, Command) and obj is not Command:
            register(obj)
            # Strip the redundant "Command" suffix if it exists on the command, so you can run "CreateNodeCommand"
            # by calling command_interface.CreateNode()
            if obj.__name__.endswith("Command"):
                add_command(CommandInterface, obj.__name__[:-7], obj)
            else:
                add_command(CommandInterface, obj.__name__, obj)
    return CommandInterface()


def unregister_module_commands(command_interface):
    """Unregister the list of commands registered by register_all_commands_in_module

    Args:
        command_interface: An object whose only members are command classes that were registered
    """
    if command_interface is None:
        return
    for command_name in dir(command_interface):
        command_class = get_command_class(command_name)
        if command_class is not None:
            unregister(command_class)


def unregister(command_class: Type[Command]):
    """Unregister a **Command**.

    Args:
        command_class: **Command** class.
    """
    if not issubclass(command_class, Command):
        _log_error(f"Can't unregister command: {command_class} it is not a subclass of a Command.")
        return

    global _commands, _callbacks
    name = command_class.__name__

    # If the class contains the "Command" suffix, unregister it without the suffix
    if name.endswith("Command"):
        name = name[:-7]

    module = command_class.__module__
    _commands[name].pop(module, None)
    _callbacks.pop((name, module), None)

    _dispatch_changed()


def get_command_class(name: str) -> Type[Command]:
    """Get **Command** class(type) by name.

    Args:
        name: **Command** name. It may include a module name to be more specific and avoid conflicts.

    Returns:
        **Command** class if succeeded. `None` if can't find a command with this name.
    """

    module_name, class_name = _get_module_and_class(name)

    cmds = _commands[class_name]
    if len(cmds) == 0:
        # Backward compatibility - allow commands to be invoked with "Command" suffix in their name
        if name.endswith("Command"):
            stripped_name = name[:-7]
            module_name, class_name = _get_module_and_class(stripped_name)
            cmds = _commands[class_name]
            if not cmds:
                return None
        else:
            return None

    if len(cmds) == 1:
        return next(iter(cmds.values()))
    else:
        if module_name == "":
            _log_error(f"There are multiple commands with {name}. Pass full command name including module name.")
            return None
        return cmds.get(module_name, None)


def get_command_class_signature(name: str):
    """Get the init signature for a **Command**.

    Args:
        name: **Command** name. It may include a module name to be more specific and avoid conflicts.

    Returns:
        __init__ signature
    """
    command_class = get_command_class(name)
    if command_class is None:
        return None

    function = command_class.__init__
    return inspect.signature(function)


def get_command_doc(name: str) -> str:
    """Get **Command** docstring by name.

    Args:
        name: **Command** name. It may include a module name to be more specific and avoid conflicts.

    Returns:
        Python docstring (__doc__) from a command type.
    """
    command_class = get_command_class(name)
    return inspect.getdoc(command_class) if command_class else ""


def register_callback(name: str, cb_type: str, callback: Callable[[Dict[str, Any]], None]) -> CallbackID:
    """Register a callback for a command.

    Args:
        name: **Command** name. It may include a module name to be more specific and avoid conflicts.
        cb_type: Type of callback. Currently supported types are:
                     PRE_DO_CALLBACK - called before the command is executed
                     POST_DO_CALLBACK - called after the command is executed
                     PRE_UNDO_CALLBACK - called before the command is undone
                     POST_UNDO_CALLBACK - called after the command is undone
        callback: Callable to be called. Will be passed a dictionary of information specific to that
                  command invocation. By default the dictionary will contain the parameters passed to
                  execute(), but this may be overridden by individual commands so check their documentation.
                  Many command parameters are optional so it is important that callbacks check for their
                  presence before attempting to access them. The callback must not make any changes to
                  the dictionary passed to it.

    Returns:
        An ID that can be passed to **unregister_callback**.
    """
    global _callbacks
    module_name, class_name = _get_module_and_stripped_class(name)
    _callbacks[(class_name, module_name)][cb_type] += [callback]
    return CallbackID(class_name, module_name, cb_type, callback)


def unregister_callback(id: CallbackID):
    """Unregister a command callback previously registered through **register_callback**.

    Args:
        id: The ID returned by **register_callback** when the callback was registered.
    """
    global _callbacks
    if isinstance(id, CallbackID):
        class_name, module_name, cb_type, callback = id.get()
        cbs = _callbacks[(class_name, module_name)][cb_type]
        try:
            cbs.remove(callback)
            return
        except:
            pass
        carb.log_error(f'Attempt to unregister a {cb_type} callback on {module_name}.{class_name} which was not registered.')
    else:
        carb.log_error('Invalid callback id')


class CommandParameter:
    """Parameter details from inspect.Parameter with documentation if present"""

    def __init__(self, param: inspect.Parameter, doc):
        self._param = param
        self._doc = doc

    @property
    def name(self) -> str:
        if self._param.kind == inspect.Parameter.VAR_POSITIONAL:
            return "*" + self._param.name
        elif self._param.kind == inspect.Parameter.VAR_KEYWORD:
            return "**" + self._param.name
        return self._param.name

    @property
    def type(self):
        if self._param.annotation is inspect._empty:
            return None
        return self._param.annotation

    @property
    def type_str(self) -> str:
        if self._param.annotation is inspect._empty:
            return ""
        return inspect.formatannotation(self._param.annotation)

    @property
    def default(self):
        if self._param.default is inspect._empty:
            return None
        return self._param.default

    @property
    def default_str(self) -> str:
        if self._param.default is inspect._empty:
            return ""
        return str(self._param.default)

    @property
    def doc(self) -> str:
        return self._doc


def get_command_parameters(name: str) -> List[Type[CommandParameter]]:
    """Get all parameters for a **Commands**.

    Args:
        name: **Command** name. It may include a module name to be more specific and avoid conflicts.

    Returns:
        A list of **CommandParameter** (except 'self' parameter)
    """
    command_class = get_command_class(name)
    if command_class is None:
        return []

    result = []
    function = command_class.__init__
    vardata = _get_argument_doc(function.__doc__ or command_class.__doc__)

    sig = inspect.signature(function)
    for param in sig.parameters.values():
        if param.name == "self":
            continue
        var_help = ""
        if param.name in vardata and "doc" in vardata[param.name]:
            var_help = vardata[param.name]["doc"]
        result.append(CommandParameter(param, var_help))

    return result


def get_commands():
    """Get all registered **Commands**."""
    return _commands


def get_commands_list() -> List[Type[Command]]:
    """Return list of all **Command** classes registered."""
    return [c for m in _commands.values() for c in m.values()]


def _get_callback_info(cb_type:str, command: Command, cmd_args: Dict[str, Any]) -> Dict[str, Any]:
    cmd_args = cmd_args.copy()
    info = command.modify_callback_info(cb_type, cmd_args)
    if isinstance(info, dict):
        return info
    return cmd_args

def _call_callbacks(command: Command, name: str, kwargs: Dict[str, Any], cb_type: str):
    module_name, class_name = _get_module_and_stripped_class(name)
    callbacks = _callbacks[(class_name, module_name)][cb_type]
    if callbacks:
        info = _get_callback_info(cb_type, command, kwargs)
        for cb in callbacks:
            cb(info)

def execute(name, **kwargs) -> Tuple[bool, Any]:
    """Execute **Command**.

    Args:
        name: **Command** name. Can be class name (e.g. "My") or full name including module (e.g. "foo.bar.MyCommand")
        **kwargs: Arbitrary keyword arguments to be passed into into **Command** constructor.
    """
    # Create command using passed params
    command = create(name, **kwargs)

    # Check command is valid
    if not command:
        _log_error("Can't execute command: \"{}\", it wasn't registered or ambigious.".format(name))
        return (False, None)
    if not callable(getattr(command, "do", None)):
        _log_error("Can't execute command: \"{}\", it doesn't have do() method.".format(name))
        return (False, None)

    import omni.kit.undo  # Prevent a circular dependency which breaks the doc-gen

    # Execute the command.
    result = omni.kit.undo.execute(command, name, kwargs)
    return result


def execute_argv(name, argv: list) -> Tuple[bool, Any]:
    """Execute **Command** using argument list..

    Attempts to convert argument list into **Command**'s kwargs. If a **Command** has *get_argument_parser* method defined, it will be called to get :class:`argparse.ArgumentParser` instance to use for parsing.
    Otherwise command docstring is used to extract argument information.

    Args:
        name: **Command** name.
        argv: Argument list.
    """

    command_class = get_command_class(name)
    if not command_class:
        return (False, None)

    kwargs = {}
    cmd_argparse = None
    if hasattr(command_class, "get_argument_parser"):
        cmd_argparse = command_class.get_argument_parser()
    else:
        cmd_argparse = get_argument_parser_from_function(command_class.__init__)

    try:
        parsed_args = cmd_argparse.parse_known_args(argv)
        kwargs = vars(parsed_args[0])
    except SystemExit:
        pass

    return execute(name, **kwargs)


def _get_argument_doc(doc):
    if doc is None:
        return {}

    vardata = {}
    param_name = None
    for line in doc.splitlines():
        stripped = line.strip()
        if stripped:
            m = re.match(r"\s*(?P<param>\w+)(?P<type>.*): (?P<doc>.*)", line)
            if m is not None:
                param_name = m.group("param")
                vardata[param_name] = {}
                vardata[param_name]["doc"] = m.group("doc")
            elif param_name is not None:
                # group multiline doc with previous param
                vardata[param_name]["doc"] += " " + stripped
        else:
            param_name = None

    return vardata


def get_argument_parser_from_function(function):
    fn_argparse = argparse.ArgumentParser()
    # Note: should probably be replaced with `vardata = _get_argument_doc(function)`
    param_regex = re.compile(r":param (?P<param>\w+)[\[\s\[]*(?P<meta>[\w\s\,]*)[\]\]*]*: (?P<doc>.*)")
    vardata = {}
    for var_match in re.finditer(param_regex, function.__doc__):
        param_name = var_match.group("param")
        vardata[param_name] = {}
        vardata[param_name]["doc"] = var_match.group("doc")
        vardata[param_name]["meta"] = var_match.group("meta")

    varnames = function.__code__.co_varnames
    for var_name in varnames:
        if var_name == "self":
            continue
        var_help = ""
        is_required = True
        nargs = None
        if var_name in vardata:
            var_help = vardata[var_name]["doc"]
            if "optional" in vardata[var_name]["meta"]:
                is_required = False
            if "list" in vardata[var_name]["meta"]:
                nargs = "*"
        if nargs is not None:
            fn_argparse.add_argument(
                "--" + var_name, nargs=nargs, metavar=var_name, help=var_help, required=is_required
            )
        else:
            fn_argparse.add_argument("--" + var_name, metavar=var_name, help=var_help, required=is_required)

    return fn_argparse
