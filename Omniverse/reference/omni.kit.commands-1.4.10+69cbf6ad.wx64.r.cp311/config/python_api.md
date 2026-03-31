# Public API for module omni.kit.undo:

## Functions

- def begin_disabled()
- def begin_group()
- def can_redo()
- def can_repeat()
- def can_undo()
- def clear_history()
- def clear_stack()
- def disabled()
- def end_disabled()
- def end_group()
- def execute(command, name, kwargs) -> Tuple[bool, Any]
- def get_history()
- def get_redo_stack()
- def get_undo_stack()
- def group()
- def redo()
- def repeat()
- def subscribe_on_change(on_change)
- def subscribe_on_change_detailed(on_change)
- def undo()
- def unsubscribe_on_change(on_change)
- def unsubscribe_on_change_detailed(on_change)

# Public API for module omni.kit.commands:

## Classes

- class Command(ABC)
  - def do(self)
  - def modify_callback_info(self, cb_type: str, args: Dict[str, Any]) -> Dict[str, Any]

## Functions

- def create(name, **kwargs)
- def register(command_class: Type[Command])
- def register_all_commands_in_module(module)
- def unregister_module_commands(command_interface)
- def unregister(command_class: Type[Command])
- def register_callback(name: str, cb_type: str, callback: Callable[[Dict[str, Any]], None]) -> CallbackID
- def unregister_callback(id: CallbackID)
- def get_command_class(name: str) -> Type[Command]
- def get_command_class_signature(name: str)
- def get_command_doc(name: str) -> str
- def get_command_parameters(name: str) -> List[Type[CommandParameter]]
- def get_commands()
- def get_commands_list() -> List[Type[Command]]
- def execute(name, **kwargs) -> Tuple[bool, Any]
- def execute_argv(name, argv: list) -> Tuple[bool, Any]
- def get_argument_parser_from_function(function)
- def set_logging_enabled(enabled: bool)
- def subscribe_on_change(on_change)
- def unsubscribe_on_change(on_change)

## Variables

- PRE_DO_CALLBACK: str
- POST_DO_CALLBACK: str
- PRE_UNDO_CALLBACK: str
- POST_UNDO_CALLBACK: str

# Public API for module omni.kit.commands.builtin:

## Classes

- class ChangeDraggableSettingCommand(omni.kit.commands.Command)
  - def __init__(self, path, value)
  - def do(self)

- class ChangeSettingCommand(omni.kit.commands.Command)
  - def __init__(self, path, value, prev = None)
  - def do(self)
  - def undo(self)
