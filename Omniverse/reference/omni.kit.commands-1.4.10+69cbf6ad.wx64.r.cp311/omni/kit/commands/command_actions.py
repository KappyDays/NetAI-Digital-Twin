import omni.kit.actions.core


def register_actions(extension_id):
    import omni.kit.undo

    action_registry = omni.kit.actions.core.get_action_registry()
    actions_tag = "Command Actions"

    action_registry.register_action(
        extension_id,
        "undo",
        omni.kit.undo.undo,
        display_name="Command->Undo",
        description="Undo the last command that was executed.",
        tag=actions_tag,
    )
    action_registry.register_action(
        extension_id,
        "redo",
        omni.kit.undo.redo,
        display_name="Command->Redo",
        description="Redo the last command that was undone.",
        tag=actions_tag,
    )
    action_registry.register_action(
        extension_id,
        "repeat",
        omni.kit.undo.repeat,
        display_name="Command->Repeat",
        description="Repeat the last command that was executed or redone.",
        tag=actions_tag,
    )


def deregister_actions(extension_id):
    action_registry = omni.kit.actions.core.get_action_registry()
    action_registry.deregister_all_actions_for_extension(extension_id)
