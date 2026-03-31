import os
import carb
import omni.kit.commands
from pxr import Usd, Sdf, UsdGeom, Gf, Tf, UsdShade, UsdLux


def create_test_stage():
    settings = carb.settings.get_settings()
    default_prim_name = settings.get("/persistent/app/stage/defaultPrimName")
    rootname = f"/{default_prim_name}"

    stage = omni.usd.get_context().get_stage()
    kit_folder = carb.tokens.get_tokens_interface().resolve("${kit}")
    omni_pbr_mtl = os.path.normpath(kit_folder + "/mdl/core/Base/OmniPBR.mdl")

    sunflower_hdr = omni.kit.window.usd_paths.get_extension_path("data/sunflowers.hdr")
    lenna_dds = omni.kit.window.usd_paths.get_extension_path("textures/lenna.dds")
    lenna_gif = omni.kit.window.usd_paths.get_extension_path("textures/lenna.gif")
    lenna_jpg = omni.kit.window.usd_paths.get_extension_path("textures/lenna.jpg")
    lenna_png = omni.kit.window.usd_paths.get_extension_path("textures/lenna.png")
    lenna_tga = omni.kit.window.usd_paths.get_extension_path("textures/lenna.tga")

    # create Looks folder
    omni.kit.commands.execute(
        "CreatePrim",
        prim_path=omni.usd.get_stage_next_free_path(stage, "{}/Looks".format(rootname), False),
        prim_type="Scope",
        select_new_prim=False,
    )

    # create GroundMat material
    mtl_name = "GroundMat"
    mtl_path = omni.usd.get_stage_next_free_path(
        stage, "{}/Looks/{}".format(rootname, omni.usd.make_valid_identifier(mtl_name)), False
    )
    omni.kit.commands.execute(
        "CreateMdlMaterialPrim", mtl_url=omni_pbr_mtl, mtl_name=mtl_name, mtl_path=mtl_path
    )
    ground_mat_prim = stage.GetPrimAtPath(mtl_path)
    shader = UsdShade.Material(ground_mat_prim).ComputeSurfaceSource("mdl")[0]
    shader.SetSourceAssetSubIdentifier("OmniPBR", "mdl")
    omni.usd.create_material_input(ground_mat_prim, "reflection_roughness_constant", 0.36, Sdf.ValueTypeNames.Float)
    omni.usd.create_material_input(ground_mat_prim, "specular_level", 0.25, Sdf.ValueTypeNames.Float)
    omni.usd.create_material_input(
        ground_mat_prim, "diffuse_color_constant", Gf.Vec3f(0.08, 0.08, 0.08), Sdf.ValueTypeNames.Color3f
    )
    omni.usd.create_material_input(ground_mat_prim, "diffuse_tint", Gf.Vec3f(1, 1, 1), Sdf.ValueTypeNames.Color3f)
    omni.usd.create_material_input(ground_mat_prim, "diffuse_tint", Gf.Vec3f(1, 1, 1), Sdf.ValueTypeNames.Color3f)
    omni.usd.create_material_input(ground_mat_prim, "metallic_constant", 0.0, Sdf.ValueTypeNames.Float)
    omni.usd.create_material_input(ground_mat_prim, "reflection_roughness_constant", 0.36, Sdf.ValueTypeNames.Float)

    # add additional files to shader
    omni.usd.create_material_input(
        ground_mat_prim, "diffuse_texture", Sdf.AssetPath(lenna_dds), Sdf.ValueTypeNames.Asset
    )
    omni.usd.create_material_input(ground_mat_prim, "ao_texture", Sdf.AssetPath(lenna_gif), Sdf.ValueTypeNames.Asset)
    omni.usd.create_material_input(
        ground_mat_prim, "normalmap_texture", Sdf.AssetPath(lenna_jpg), Sdf.ValueTypeNames.Asset
    )
    omni.usd.create_material_input(
        ground_mat_prim, "reflectionroughness_texture", Sdf.AssetPath(lenna_png), Sdf.ValueTypeNames.Asset
    )
    omni.usd.create_material_input(
        ground_mat_prim, "metallic_texture", Sdf.AssetPath(lenna_tga), Sdf.ValueTypeNames.Asset
    )

    # create GroundCube
    ground_cube_path = omni.usd.get_stage_next_free_path(stage, "{}/GroundCube".format(rootname), False)
    omni.kit.commands.execute(
        "CreatePrim",
        prim_path=ground_cube_path,
        prim_type="Cube",
        select_new_prim=False,
        attributes={UsdGeom.Tokens.size: 100, UsdGeom.Tokens.extent: [(-50, -50, -50), (50, 50, 50)]},
    )
    ground_cube_prim = stage.GetPrimAtPath(ground_cube_path)

    # set transform
    ground_cube_prim.CreateAttribute("xformOp:translate", Sdf.ValueTypeNames.Double3, False).Set(Gf.Vec3d(0, -50, 0))
    ground_cube_prim.CreateAttribute("xformOp:scale", Sdf.ValueTypeNames.Double3, False).Set(Gf.Vec3d(2000, 1, 2000))
    ground_cube_prim.CreateAttribute("xformOpOrder", Sdf.ValueTypeNames.String, False).Set(
        ["xformOp:translate", "xformOp:scale"]
    )

    # set doNotCastShadows
    primvars_api = UsdGeom.PrimvarsAPI(ground_cube_prim)
    primvars_api.CreatePrimvar("doNotCastShadows", Sdf.ValueTypeNames.Bool).Set(True)

    # set misc
    omni.kit.commands.execute(
        "BindMaterial",
        prim_path=ground_cube_path,
        material_path=mtl_path,
        strength=UsdShade.Tokens.strongerThanDescendants,
    )

    # create DistantLight
    distant_light_path = omni.usd.get_stage_next_free_path(stage, "{}/DistantLight".format(rootname), False)
    omni.kit.commands.execute(
        "CreatePrim",
        prim_path=distant_light_path,
        prim_type="DistantLight",
        select_new_prim=False,
        # https://github.com/PixarAnimationStudios/USD/commit/b5d3809c943950cd3ff6be0467858a3297df0bb7
        attributes={UsdLux.Tokens.inputsAngle: 1.0, UsdLux.Tokens.inputsColor: Gf.Vec3f(1, 1, 1), UsdLux.Tokens.inputsIntensity: 2000} if hasattr(UsdLux.Tokens, 'inputsIntensity') else \
            {UsdLux.Tokens.angle: 1.0, UsdLux.Tokens.color: Gf.Vec3f(1, 1, 1), UsdLux.Tokens.intensity: 2000},
    )
    distant_light_prim = stage.GetPrimAtPath(distant_light_path)

    # set transform
    distant_light_prim.CreateAttribute("xformOp:scale", Sdf.ValueTypeNames.Double3, False).Set(
        Gf.Vec3d(1, 1.0000004, 1.0000004)
    )
    distant_light_prim.CreateAttribute("xformOp:rotateZYX", Sdf.ValueTypeNames.Double3, False).Set(
        Gf.Vec3d(242.08, 327.06, 0)
    )
    distant_light_prim.CreateAttribute("xformOp:translate", Sdf.ValueTypeNames.Double3, False).Set(Gf.Vec3d(0, 0, 0))
    distant_light_prim.CreateAttribute("xformOpOrder", Sdf.ValueTypeNames.String, False).Set(
        ["xformOp:translate", "xformOp:rotateZYX", "xformOp:scale"]
    )

    # create DomeLight
    dome_light_path = omni.usd.get_stage_next_free_path(stage, "{}/DomeLight".format(rootname), False)
    omni.kit.commands.execute(
        "CreatePrim",
        prim_path=dome_light_path,
        prim_type="DomeLight",
        select_new_prim=False,
        # https://github.com/PixarAnimationStudios/USD/commit/b5d3809c943950cd3ff6be0467858a3297df0bb7
        attributes={
            UsdLux.Tokens.inputsIntensity: 1000,
            UsdLux.Tokens.inputsSpecular: 1,
            UsdLux.Tokens.inputsTextureFile: sunflower_hdr,
            UsdLux.Tokens.inputsTextureFormat: UsdLux.Tokens.latlong,
            UsdGeom.Tokens.visibility: UsdGeom.Tokens.inherited,
        } if hasattr(UsdLux.Tokens, 'inputsIntensity') else \
        {
            UsdLux.Tokens.intensity: 1000,
            UsdLux.Tokens.specular: 1,
            UsdLux.Tokens.textureFile: sunflower_hdr,
            UsdLux.Tokens.textureFormat: UsdLux.Tokens.latlong,
            UsdGeom.Tokens.visibility: UsdGeom.Tokens.inherited,
        },
    )
    dome_light_prim = stage.GetPrimAtPath(dome_light_path)

    # set misc
    # https://github.com/PixarAnimationStudios/USD/commit/3738719d72e60fb78d1cd18100768a7dda7340a4
    if hasattr(UsdLux.Tokens, 'inputsShapingFocusTint'):
        dome_light_prim.GetAttribute(UsdLux.Tokens.inputsShapingFocusTint).Set(Gf.Vec3f(0, 0, 0))
        dome_light_prim.GetAttribute(UsdLux.Tokens.inputsShapingFocus).Set(0)
    else:
        dome_light_prim.GetAttribute(UsdLux.Tokens.shapingFocusTint).Set(Gf.Vec3f(0, 0, 0))
        dome_light_prim.GetAttribute(UsdLux.Tokens.shapingFocus).Set(0)
