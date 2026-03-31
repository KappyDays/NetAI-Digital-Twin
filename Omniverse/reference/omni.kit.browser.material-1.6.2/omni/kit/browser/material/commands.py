import omni.kit.commands
from pxr import Sdf, UsdGeom, Usd


from typing import Any


class ChangePrimVarCommand(omni.kit.commands.Command):
    """
    Change prim var undoable **Command**.

    Args:
        prim_path (str): Prim path.
        primvar_name (str): Name of primvar
        value: Value to change to.
        prev: Value to undo to. Default is None, means to use previous primvar value if exists.
        type_to_create_if_not_exist: If not None AND primvar does not already exist, a new primvar will be created with given type and value.
    """

    def __init__(
        self,
        prim_path: str,
        primvar_name: str,
        value: Any,
        prev: Any = None,
        type_to_create_if_not_exist: Sdf.ValueTypeNames = None,
    ):
        self._value = value
        self._prev = prev
        self._prim_path = Sdf.Path(prim_path)
        self._primvar_name = primvar_name
        self._type_to_create_if_not_exist = type_to_create_if_not_exist
        self._new_primvar = False
        self._edit_target = None
        self._changed = False

    def do(self):
        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(self._prim_path)
        if prim:
            primvars_api = UsdGeom.PrimvarsAPI(prim)
            if primvars_api:
                primvar = primvars_api.GetPrimvar(self._primvar_name)
                if primvar:
                    if self._prev is None:
                        self._prev = primvar.Get()
                else:
                    if self._type_to_create_if_not_exist is not None:
                        primvar = primvars_api.CreatePrimvar(self._primvar_name, self._type_to_create_if_not_exist)
                        self._new_primvar = True

                if primvar:
                    self._edit_target = stage.GetEditTarget()
                    primvar.Set(self._value)
                    self._changed = True

    def undo(self):
        if not self._changed:
            return
        stage = omni.usd.get_context().get_stage()
        prim = stage.GetPrimAtPath(self._prim_path)
        if prim:
            primvars_api = UsdGeom.PrimvarsAPI(prim)
            if primvars_api:
                if self._new_primvar:
                    with Usd.EditContext(stage, self._edit_target):
                        primvars_api.RemovePrimvar(self._primvar_name)
                else:
                    primvar = primvars_api.GetPrimvar(self._primvar_name)
                    if primvar:
                        primvar.Set(self._prev)


omni.kit.commands.register_all_commands_in_module(__name__)
