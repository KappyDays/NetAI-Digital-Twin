# Public API for module omni.kit.window.usd_paths:

## Classes

- class MenuHelperExtension
  - def __init__(self)
  - def menu_startup(self, window_name, menu_desc, menu_group, appear_after = '', header = None, verbose = False) -> bool
  - def menu_shutdown(self) -> bool
  - def menu_refresh(self)

- class UsdPathsExtension(omni.ext.IExt, MenuHelperExtension)
  - WINDOW_NAME: str
  - MENU_GROUP: str
  - def __init__(self)
  - def on_startup(self, ext_id)
  - def on_shutdown(self)
  - async def get_asset_paths(self, on_complete_fn, get_path_fn)

## Functions

- def get_extension()
- def get_instance()
- def get_extension_path(sub_directory)

## Other

- re: builtin module
- os: builtin module
- asyncio: builtin module
- carb: public module
- omni.ext: public module
- omni.ui: public module
- Usd: unknown module
- UsdGeom: unknown module
- UsdShade: unknown
- UsdUtils: unknown
- Ar: unknown
- Sdf: unknown module
