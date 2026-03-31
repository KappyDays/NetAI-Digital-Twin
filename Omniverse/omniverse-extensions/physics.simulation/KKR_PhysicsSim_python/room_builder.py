# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Room environment generator.

Creates a simple room (floor + 4 walls + ceiling) with physics colliders
in the USD Stage. All surfaces are static (no RigidBody).
"""

from pxr import UsdGeom, UsdPhysics, UsdLux, Gf
import omni.usd
import carb


ROOM_PATH = "/World/Room"
WALL_THICKNESS = 0.1  # meters


def generate_room(stage, room_path=ROOM_PATH, size=10.0, height=3.0):
    """Generate a room with floor, 4 walls, ceiling, lighting, and physics scene.

    Args:
        stage: USD Stage
        room_path: prim path for the room Xform
        size: room width/depth in meters
        height: room height in meters

    Returns:
        room_path string
    """
    # Idempotency: remove existing room
    existing = stage.GetPrimAtPath(room_path)
    if existing and existing.IsValid():
        stage.RemovePrim(room_path)

    # Ensure /World exists
    world_prim = stage.GetPrimAtPath("/World")
    if not world_prim or not world_prim.IsValid():
        UsdGeom.Xform.Define(stage, "/World")

    # Create room Xform
    UsdGeom.Xform.Define(stage, room_path)

    half = size / 2.0
    wt = WALL_THICKNESS

    # Floor
    _create_box(
        stage, f"{room_path}/Floor",
        position=(0, -wt / 2, 0),
        scale=(half, wt / 2, half),
        color=(0.4, 0.4, 0.45),
    )

    # Ceiling
    _create_box(
        stage, f"{room_path}/Ceiling",
        position=(0, height + wt / 2, 0),
        scale=(half, wt / 2, half),
        color=(0.9, 0.9, 0.9),
    )

    # Wall North (+Z)
    _create_box(
        stage, f"{room_path}/Wall_North",
        position=(0, height / 2, half + wt / 2),
        scale=(half, height / 2, wt / 2),
        color=(0.7, 0.7, 0.75),
    )

    # Wall South (-Z)
    _create_box(
        stage, f"{room_path}/Wall_South",
        position=(0, height / 2, -(half + wt / 2)),
        scale=(half, height / 2, wt / 2),
        color=(0.7, 0.7, 0.75),
    )

    # Wall East (+X)
    _create_box(
        stage, f"{room_path}/Wall_East",
        position=(half + wt / 2, height / 2, 0),
        scale=(wt / 2, height / 2, half),
        color=(0.65, 0.65, 0.7),
    )

    # Wall West (-X)
    _create_box(
        stage, f"{room_path}/Wall_West",
        position=(-(half + wt / 2), height / 2, 0),
        scale=(wt / 2, height / 2, half),
        color=(0.65, 0.65, 0.7),
    )

    # Physics scene
    ensure_physics_scene(stage)

    # Lighting
    light_path = f"{room_path}/Light"
    if not stage.GetPrimAtPath(light_path).IsValid():
        light = UsdLux.DistantLight.Define(stage, light_path)
        light.CreateIntensityAttr(3000)
        light.CreateAngleAttr(0.53)

    carb.log_info(f"[KKR.PhysicsSim] Room generated at {room_path} ({size}m x {size}m x {height}m)")
    return room_path


def _create_box(stage, path, position, scale, color):
    """Create a UsdGeom.Cube with CollisionAPI (static, no RigidBody).

    UsdGeom.Cube has default extent [-1, 1] per axis, so scale=(s,s,s)
    creates a box of dimensions 2s x 2s x 2s.
    """
    cube = UsdGeom.Cube.Define(stage, path)
    cube.CreateSizeAttr(2.0)

    # Transform
    xformable = UsdGeom.Xformable(cube.GetPrim())
    xformable.AddTranslateOp().Set(Gf.Vec3d(*position))
    xformable.AddScaleOp().Set(Gf.Vec3d(*scale))

    # Collision (static — no RigidBody)
    UsdPhysics.CollisionAPI.Apply(cube.GetPrim())

    # Display color
    cube.CreateDisplayColorAttr([Gf.Vec3f(*color)])

    return cube


def ensure_physics_scene(stage):
    """Ensure at least one PhysicsScene exists in the stage."""
    # Check for any existing physics scene
    for prim in stage.Traverse():
        if prim.IsA(UsdPhysics.Scene):
            return

    # Create one
    scene = UsdPhysics.Scene.Define(stage, "/physicsScene")
    scene.CreateGravityDirectionAttr(Gf.Vec3f(0, -1, 0))
    scene.CreateGravityMagnitudeAttr(9.81)
    carb.log_info("[KKR.PhysicsSim] Created PhysicsScene at /physicsScene")


def check_existing_scene(stage):
    """Check if /World has existing geometry content (not just lights or Xforms).

    Returns True if meaningful geometry exists that could serve as a scene.
    """
    world_prim = stage.GetPrimAtPath("/World")
    if not world_prim or not world_prim.IsValid():
        return False

    for child in world_prim.GetAllChildren():
        if child.IsA(UsdGeom.Gprim) or child.IsA(UsdGeom.Xform):
            # Check if it has any geometry descendants
            for desc in child.GetAllDescendants():
                if desc.IsA(UsdGeom.Gprim):
                    return True
            if child.IsA(UsdGeom.Gprim):
                return True

    return False


def destroy_room(stage, room_path=ROOM_PATH):
    """Remove the room prim and all children."""
    prim = stage.GetPrimAtPath(room_path)
    if prim and prim.IsValid():
        stage.RemovePrim(room_path)
        carb.log_info(f"[KKR.PhysicsSim] Removed room at {room_path}")
