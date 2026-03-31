# C++ Usage Examples


## Example C++ Command

```
class TestCppCommand : public Command
{
public:
    static carb::ObjectPtr<ICommand> create(const char* extensionId,
                                            const char* commandName,
                                            const carb::dictionary::Item* kwargs)
    {
        return carb::stealObject<ICommand>(new TestCppCommand(extensionId, commandName, kwargs));
    }

    TestCppCommand(const char* extensionId, const char* commandName, const carb::dictionary::Item* kwargs)
        : Command(extensionId, commandName)
    {
        if (carb::dictionary::IDictionary* iDictionary = carb::dictionary::getDictionary())
        {
            m_x = iDictionary->getAsInt(iDictionary->getItem(kwargs, "x"));
            m_y = iDictionary->getAsInt(iDictionary->getItem(kwargs, "y"));
        }
    }

    void doCommand() override
    {
        s_resultList.append(m_x);
        s_resultList.append(m_y);
    }

    void undoCommand() override
    {
        s_resultList.attr("pop")();
        s_resultList.attr("pop")();
    }

private:
    int32_t m_x = 0;
    int32_t m_y = 0;
};
```


## Registering C++ Commands

```
auto commandBridge = carb::getCachedInterface<omni::kit::commands::ICommandBridge>());
commandBridge->registerCommand("omni.kit.command_tests", "RegisteredFromCppCommand", TestCppCommand::create);
// Note the command name (in this case "RegisteredFromCppCommand") is arbitrary and does not need to match the C++ class
```


## Executing Commands From C++

```
auto commandBridge = carb::getCachedInterface<omni::kit::commands::ICommandBridge>());

// Create the kwargs dictionary.
auto iDictionary = carb::getCachedInterface<carb::dictionary::IDictionary>();
carb::dictionary::Item* kwargs = iDictionary->createItem(nullptr, "", carb::dictionary::ItemType::eDictionary);
iDictionary->makeIntAtPath(kwargs, "x", 7);
iDictionary->makeIntAtPath(kwargs, "y", 9);

// Execute the command using its name...
commandBridge->executeCommand("RegisteredFromCppCommand", kwargs);
// or without the 'Command' postfix just like Python commands...
commandBridge->executeCommand("RegisteredFromCpp", kwargs);
// or fully qualified if needed to disambiguate (works with or without the 'Command)' postfix.
commandBridge->executeCommand("omni.kit.command_tests", "RegisteredFromCppCommand", kwargs);

// The C++ command can be executed from Python exactly like any Python command,
// and we can also execute Python commands from C++ in the same ways as above:
commandBridge->executeCommand("RegisteredFromPythonCommand", kwargs);
// etc.

// Destroy the kwargs dictionary.
iDictionary->destroyItem(kwargs);
```


## Undo/Redo Commands From C++

```
auto commandBridge = carb::getCachedInterface<omni::kit::commands::ICommandBridge>());

// It doesn't matter whether the command stack contains Python commands, C++ commands,
// or a mix of both, and the same stands for when undoing/redoing commands from Python.
commandBridge->undoCommand();
commandBridge->redoCommand();

```


## Deregistering C++ Commands

```
auto commandBridge = carb::getCachedInterface<omni::kit::commands::ICommandBridge>());
commandBridge->deregisterCommand("omni.kit.command_tests", "RegisteredFromCppCommand");
```

