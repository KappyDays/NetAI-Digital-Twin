import asyncio
import os
import re
from typing import Callable, List, Optional

import carb
import omni.client
import omni.kit.material.library
from omni.kit.browser.folder.core import FileSystemFile, FileSystemFolder
from pxr import Usd, UsdShade

THUMBNAIL_PATH = ".thumbs"
THUMBNAIL_SIZE = 256
THUMBNAIL_FULL_PATH = f"/{THUMBNAIL_PATH}/{THUMBNAIL_SIZE}x{THUMBNAIL_SIZE}"

MAX_RETRY_COUNT = 3

# TODO: Replace this function with omni.usd.get_subidentifier_from_mdl once it in kit release
async def get_subidentifier_from_mdl(mdl_file: str, on_complete_fn: Callable = None):
    if not mdl_file:
        carb.log_error(f"get_subidentifier_from_mdl: Failed to read file {mdl_file}")
        if on_complete_fn:
            on_complete_fn(None)
        return []

    result, _, content = await omni.client.read_file_async(mdl_file)
    if result != omni.client.Result.OK:
        carb.log_error(f"get_subidentifier_from_material: Failed to read file {mdl_file}")
        if on_complete_fn:
            on_complete_fn(None)
        return None

    re_material_in_mdl = re.compile(r"export\s+material\s+([^\s]+)\s*\(")
    mtl_list = []
    try:
        for line in memoryview(content).tobytes().decode("utf-8").splitlines():
            # get material names from MDL file
            for match in re.finditer(re_material_in_mdl, line):
                mtl_list.append(match.group(1))
    except UnicodeDecodeError:
        carb.log_warn(f"Failed to parse {mdl_file}, try omni.kit.material.library.get_subidentifier_from_mdl")
        entries = await omni.kit.material.library.get_subidentifier_from_mdl(mdl_file=mdl_file)
        mtl_list = [entry.name for entry in entries]

    if on_complete_fn:
        on_complete_fn(mtl_list)
    return mtl_list


class MaterialType:
    USD = "usd"
    MDL = "mdl"


class SubMaterial:
    """
    Represent a sub material.
    Args:
        name (str): Name of sub material
        thumbnail (Optional[str]): Thumbnail url of sub material
        url (str): Url of sub material. Default None to use name string.
    """

    def __init__(self, name: str, thumbnail: Optional[str] = None, url: str = None):
        self.name = name
        self.thumbnail = thumbnail
        self.url = url if url else name

    def equals(self, other: "SubMaterial"):
        return self.name == other.name and self.thumbnail == other.thumbnail and self.url == other.url

    def get_default_thumbnail_url(self, file_url: str) -> str:
        """
        Get default thumbnail url of this sub material.
        Args:
            file_url: Url tof material file this sub material belongs to.
        """
        file_name = file_url.split("/")[-1]
        return os.path.dirname(file_url) + THUMBNAIL_FULL_PATH + f"/{file_name}@{self.name}.png"

    def __repr__(self) -> str:
        return f"{self.url}:{self.thumbnail}"


class UsdSubMaterial(SubMaterial):
    """
    Represent a material prim in a usd.
    Args:
        url (str): Material prim path.
    Keyword args:
        default (bool): True if prim is the default prim in usd file. Otherwise False.
    """

    def __init__(self, url: str, default: bool = False, thumbnail: Optional[str] = None):
        self.default = default
        super().__init__(url.split("/")[-1], thumbnail=thumbnail, url=url)


class MaterialFile(FileSystemFile):
    """
    Represent a material file object.
    Args:
        url (str): Url of material file.
        sub_materials (Optional[List[UsdSubMaterial]]): Material prims in the file. None means this material file is a single material,
            otherwise muilti materials in the file.
    """

    def __init__(self, url: str, sub_materials: Optional[List[UsdSubMaterial]] = None):
        super().__init__(url)
        if url.lower().endswith(".mdl"):
            self.type = MaterialType.MDL
        else:
            self.type = MaterialType.USD

        self.sub_materials = sub_materials

    def equals(self, other: "MaterialFile") -> bool:
        if self.url != other.url:
            return False
        if self.sub_materials:
            if not other.sub_materials:
                return False
            if len(self.sub_materials) != len(other.sub_materials):
                return False
            self.sub_materials.sort(key=lambda item: item.name)
            other.sub_materials.sort(key=lambda item: item.name)
            for i in range(len(self.sub_materials)):
                if not self.sub_materials[i].equals(other.sub_materials[i]):
                    return False
        elif other.sub_materials:
            return False
        elif self.thumbnail != other.thumbnail:
            return False
        return True

    def set_thumbnail(self, thumbnail_url: str) -> bool:
        """
        Check and set thumbnail.
        Args:
            thumbnail (str): Url of thumbnail.
        Return True if the thumbnail belongs to this file, otherwise False.
        """
        if self.sub_materials:
            thumbnail_name = thumbnail_url.split("/")[-1][:-4]
            # Check if thumbnail of sub materials
            # In format: {file_name}.{material.name}
            for material in self.sub_materials:
                file_name = self.url.split("/")[-1]
                expected_name = f"{file_name}@{material.name}"
                if thumbnail_name == expected_name:
                    material.thumbnail = thumbnail_url
                    return True
            else:
                return False
        else:
            return super().set_thumbnail(thumbnail_url)


class MaterialFolder(FileSystemFolder):
    """
    Represent a material folder.
    Keyword args:
        on_sub_materials_loaded_fn: Function called when multi sub materials load comppleted. Function signure:
            void on_sub_materials_loaded_fn(folder: MaterialFolder)

    Other args and keyword args, please refre to "FileSystemFolder"
    """

    def __init__(self, *args, **kwargs):
        self.sub_materials_count: int = 0
        self.sub_materials_loaded: bool = False
        super().__init__(*args, **kwargs)

    def destroy(self) -> None:
        super().destroy()

    @property
    def file_item_count(self) -> int:
        count = 0
        for file in self.files:
            if hasattr(file, "sub_materials") and file.sub_materials:
                count += len(file.sub_materials)
            else:
                count += 1
        return count

    def create_folder_object(self, *args, **kwargs) -> FileSystemFolder:
        """
        Overridden. Create folder object when a sub folder found
        """
        return MaterialFolder(*args, **kwargs)

    def create_file_object(self, url: str) -> Optional[MaterialFile]:
        """
        Overridden. Create file object.
        """
        file = MaterialFile(url)
        return file

    async def _on_file_found_async(self, url: str) -> Optional[MaterialFile]:
        file = await super()._on_file_found_async(url)
        if file:
            if await self._load_sub_material_async(file):
                return file
            else:
                return None
        return file

    async def _load_sub_material_async(self, material_file: MaterialFile) -> bool:
        retry_count = 0
        while retry_count <= MAX_RETRY_COUNT:
            if retry_count:
                carb.log_info(f"[{material_file.url}] Retry #{retry_count}")
            if material_file.type == MaterialType.MDL:
                if not await self._load_mdl_sub_materials_async(material_file, retry_count=retry_count):
                    retry_count += 1
                    await asyncio.sleep(0.5)
                else:
                    break
            else:
                return await self._load_usd_sub_materials_async(material_file)
        else:
            carb.log_error(
                f"Timeout {self._timeout} seconds when reading subidendifiers from {material_file.url}. Please check your network and connection to the url. Otherwise increase the timeout."
            )
            self.has_timeout = True
        return True

    def _create_usd_material_file_object(self, url: str) -> Optional[MaterialFile]:  # pragma: no cover - never called
        # usd files
        stage = Usd.Stage.Open(url)
        if stage:
            if stage.HasDefaultPrim():
                default_prim = stage.GetDefaultPrim()
            else:
                default_prim = None
            material_prims = []
            for prim in stage.TraverseAll():
                if prim.IsA(UsdShade.Material):
                    default = True if default_prim and prim == default_prim else False
                    material_prims.append(UsdSubMaterial(prim.GetPath().pathString, default=default))
            if not material_prims:
                # Invalid since No materials in usd file
                return None
            else:
                # Materials in usd
                return MaterialFile(url, sub_materials=material_prims)
        else:
            return None

    async def _load_mdl_sub_materials_async(self, material_file: MaterialFile, retry_count=0) -> bool:
        try:
            # OM-60914: Sometimes there maybe invalid utf-8 chars in mdl file
            # As a result, get_subidentifier_from_mdl cannot parse the file
            # Use omni.kit.material.library.get_subidentifier_from_mdl instead but it is slower first time
            subids = await asyncio.wait_for(
                get_subidentifier_from_mdl(material_file.url), timeout=self._timeout * (retry_count + 1)
            )
        except asyncio.TimeoutError:
            subids = None
            return False
        except asyncio.CancelledError:
            subids = None
            return False
        if subids is None:
            return False
        if subids:
            # remove duplicated sub ids, for example: omniverse://ov-content/NVIDIA/Materials/Base/Glass/Clear_Glass.mdl
            subids = set(subids)
            if len(subids) == 1:
                # If only one subid in material file, do nothing if subid is same as file name
                material_file.sub_materials = []
                dirs = material_file.url.split("/")
                file_name = dirs[-1].split(".")[0]
                sub_id = next(iter(subids))
                if sub_id != file_name:
                    sub_material = SubMaterial(sub_id)
                    # Find thumbnail
                    await self._load_sub_material_default_thumbnail(sub_material, material_file.url)
                    material_file.sub_materials = [sub_material]
            elif len(subids) > 1:
                # If more than 1 subid, get all subids and related thumbnails
                material_file.sub_materials = []
                self.sub_materials_count += len(subids)
                for name in subids:
                    sub_material = SubMaterial(name)
                    # Find thumbnail
                    await self._load_sub_material_default_thumbnail(sub_material, material_file.url)

                    material_file.sub_materials.append(sub_material)
        return True

    async def _load_usd_sub_materials_async(self, material_file: MaterialFile) -> bool:
        # usd files
        stage = Usd.Stage.Open(material_file.url)
        if stage:
            if stage.HasDefaultPrim():
                default_prim = stage.GetDefaultPrim()
            else:
                default_prim = None
            sub_materials = []
            for prim in stage.TraverseAll():
                if prim.IsA(UsdShade.Material):
                    default = True if default_prim and prim == default_prim else False
                    sub_material = UsdSubMaterial(prim.GetPath().pathString, default=default)
                    # Find thumbnail
                    await self._load_sub_material_default_thumbnail(sub_material, material_file.url)

                    sub_materials.append(sub_material)
            if len(sub_materials) == 1:
                # If only one subid in material file, do nothing if subid is same as file name
                material_file.sub_materials = []
                dirs = material_file.url.split("/")
                file_name = dirs[-1].split(".")[0]
                sub_id = next(iter(sub_materials))
                if sub_id != file_name:
                    # Find thumbnail
                    await self._load_sub_material_default_thumbnail(sub_material, material_file.url)
                    if not sub_material.thumbnail:
                        try:
                            thumbnail = material_file.get_default_thumbnail_url()
                            (result, list_entry) = await omni.client.stat_async(thumbnail)
                            if result == omni.client.Result.OK:
                                sub_material.thumbnail = thumbnail
                        except asyncio.CancelledError:
                            pass
                    material_file.sub_materials = [sub_material]
            elif len(sub_materials) > 1:
                # Materials in usd
                self.sub_materials_count += len(sub_materials)
                material_file.sub_materials = sub_materials
            return True
        return False

    async def _load_sub_material_default_thumbnail(self, sub_material: SubMaterial, file_url: str) -> None:
        """
        Load default thumbnail if exists.
        Args:
            file_url: Url of material file.
        """
        thumbnail = sub_material.get_default_thumbnail_url(file_url)
        try:
            (result, list_entry) = await omni.client.stat_async(thumbnail)
            if result == omni.client.Result.OK:
                sub_material.thumbnail = thumbnail
        except asyncio.CancelledError:
            pass
