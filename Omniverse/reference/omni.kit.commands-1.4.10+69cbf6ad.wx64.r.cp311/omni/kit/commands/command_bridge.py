import carb

from ._kit_commands import *
from .command import (
    Command,
    execute,
    register,
    unregister,
    get_command_class,
)


class CommandBridge:
    def on_startup(self):
        self._command_bridge = acquire_command_bridge()

        def register_cpp_command(
            extension_id: str, command_name: str, default_kwargs: dict, optional_kwargs: dict, required_kwargs: dict
        ):
            def constructor(self, **kwargs):
                # Check whether all the required keyword arguments specified from C++ have been provided.
                for required_kwarg in self._required_kwargs:
                    if not required_kwarg in kwargs:
                        carb.log_error(
                            f"Required keyword argument '{required_kwarg}' not found when executing C++ command '{self.__class__.__name__}'."
                        )

                # Check whether all the provided keyword arguments were specified as expected from C++.
                for supplied_key, supplied_value in kwargs.items():
                    expected_value = self._all_kwargs.get(supplied_key, None)
                    if expected_value is None:
                        carb.log_warn(
                            f"Unexpected keyword argument '{supplied_key}' encountered when executing C++ command '{self.__class__.__name__}'."
                        )

                # Merge the provided keyword arguments with the defaults specified from C++.
                kwargs_with_defaults = {}
                kwargs_with_defaults.update(self._default_kwargs)
                kwargs_with_defaults.update(kwargs)

                # Create the underlying C++ command object that can later be 'done' and 'undone.
                self._cpp_command_object = self._command_bridge.create_cpp_command_object(
                    self.__class__.__module__, self.__class__.__name__, **kwargs_with_defaults
                )

            def do(self):
                return self._cpp_command_object.do()

            def undo(self):
                self._cpp_command_object.undo()

            new_cpp_command_class = type(
                command_name,
                (omni.kit.commands.Command,),
                {
                    "__module__": extension_id,
                    "__init__": constructor,
                    "_default_kwargs": default_kwargs,
                    "_optional_kwargs": optional_kwargs,
                    "_required_kwargs": required_kwargs,
                    "_all_kwargs": {**default_kwargs, **optional_kwargs, **required_kwargs},
                    "_command_bridge": self._command_bridge,
                    "do": do,
                    "undo": undo,
                },
            )

            omni.kit.commands.register(new_cpp_command_class)

        def get_qualified_command_name(extension_id: str, command_name: str):
            return extension_id + "." + command_name if extension_id else command_name

        def deregister_cpp_command(extension_id: str, command_name: str):
            qualified_command_name = get_qualified_command_name(extension_id, command_name)
            command_class = omni.kit.commands.get_command_class(qualified_command_name)
            if command_class:
                omni.kit.commands.unregister(command_class)
                command_class._command_bridge = None

        def execute_command_from_cpp(extension_id: str, command_name: str, **kwargs):
            qualified_command_name = get_qualified_command_name(extension_id, command_name)
            return omni.kit.commands.execute(qualified_command_name, **kwargs)

        import omni.kit.undo

        self._command_bridge.enable(
            register_cpp_command,
            deregister_cpp_command,
            execute_command_from_cpp,
            omni.kit.undo.undo,
            omni.kit.undo.redo,
            omni.kit.undo.repeat,
            omni.kit.undo.begin_group,
            omni.kit.undo.end_group,
            omni.kit.undo.begin_disabled,
            omni.kit.undo.end_disabled,
        )

    def on_shutdown(self):
        self._command_bridge.disable()
        release_command_bridge(self._command_bridge)
        self._command_bridge = None
