import carb.settings
import omni.kit.commands


class ChangeSettingCommand(omni.kit.commands.Command):
    """
    Change setting **Command**.

    Args:
        path: Path to the setting to change.
        value: New value to change to.
        prev: Previous value to for undo operation. If `None` current value would be saved as previous.
    """

    def __init__(self, path, value, prev=None):
        super().__init__()
        self._value = value
        self._prev = prev
        self._path = path
        self._settings = carb.settings.get_settings()

    def do(self):
        if self._prev is None:
            self._prev = self._settings.get(self._path)
        self._settings.set(self._path, self._value)

    def undo(self):
        self._settings.set(self._path, self._prev)


class ChangeDraggableSettingCommand(omni.kit.commands.Command):
    """
    Change draggable setting **Command**.

    Args:
        path: Path to the setting to change.
        value: New value to change to.
    """

    def __init__(self, path, value):
        super().__init__()
        self._value = value
        self._path = path
        self._settings = carb.settings.get_settings()

    def do(self):
        self._settings.set(self._path, self._value)
