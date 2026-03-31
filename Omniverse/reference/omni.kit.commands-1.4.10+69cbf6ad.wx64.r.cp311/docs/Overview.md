
```{csv-table}
**Extension**: {{ extension_version }},**Documentation Generated**: {sub-ref}`today`
```

# Overview

{doc}`CHANGELOG`

Commands and Undo/Redo system.

**Command** is undo/redo system primitive. It is a class which gets instantiated and ``do`` method is called on an instance. The instance is stored then in undo stack if it contains an ``undo`` method. When undo is called ``undo`` method will be executed on the same instance.

To create a command derive from {class}`omni.kit.commands.Command` and add a ``do`` method and optionally ``undo`` method.  If you consider also `redo` operation ``do()``/``undo()`` methods can be called inifinite amout of times. You can also create **command** with only ``do()`` method which would means it is not undoable and won't be added to `undo stack`.


Here is a simple example:

```{code-block} python
import omni.kit.commands

class NumIncrement(omni.kit.commands.Command):
    def __init__(num: int):
        self._num = num

    def do(self):
        self._num = self._num + 1
        return self._num # Result can be optionally returned

    def undo(self):
        self._num = self._num - 1
```

Here we create a **command** class ``NumIncrement``. By inhering from {class}`omni.kit.commands.Command` it is automatically discovered and registered by **Kit** if it is inside one of public extensions module. You can also register it explicitly with: ``omni.kit.commands.register(NumIncrement)`` call.
To execute a command one can call ``x = omni.kit.commands.execute("NumIncrement", num=10)`` from anywhere. Commands may also return values in ``do`` method.

## Guidelines

There are some useful rules to follow when creating a command:

1. All arguments must be simple types (numbers, strings, lists etc) to enable serialization and calling of commands from a console.
2. Try to make commands as simple as possible. Compose complex commands of other commands using grouping to minimize side effects.
3. Write at least one test for each command!
4. To signal failure from a command, raise an Error.  This will automatically trigger the command (and any descendants) to call ``undo`` if they define it.


## Groups

Commands can be grouped meaning that executing a group of commands will execute all of them and *undo* and *redo* operations will also cover the whole group.

First of all commands executed inside of a command are grouped automatically:

```{code-block} python
import omni.kit.commands

class SpawnFewPrims(omni.kit.commands.Command):
    def do(self):
        omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Sphere")
        omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Cone")

    def undo(self):
        pass
```

In this example you don't even need to write an ``undo`` method. Undoing that command will automatically call undo on nested commands. But you must define ``undo`` method to hint that command **is** undoable.


One can explicitly group commands using API:

```{code-block} python
import omni.kit.commands

omni.kit.undo.begin_group()
omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Sphere")
omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Cone")
omni.kit.undo.end_group()

# or similiarly:

with omni.kit.undo.group():
    omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Sphere")
    omni.kit.commands.execute("CreatePrimWithDefaultXform", prim_type="Cone")
```

## C++ Support

Commands were originally written in (and only available to use from) Python, but they can now be registered, deregistered, executed, and undone/redone from C++

- Commands registered from C++ should always be deregistered from C++ (although deregistering them from Python may not be fatal).

- Commands registered from Python should always be deregistered from Python (although deregistering them from C++ may not be fatal).

- All C++ commands have an 'undo' function on the Python side (unlike Python commands which can be created without undo functionality), so when executed they will always be placed on the undo/redo stack.

{doc}`USAGE_CPP`


## Command API Reference

{doc}`API`
