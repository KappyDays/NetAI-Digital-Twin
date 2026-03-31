# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Agent spawning, movement, and collision detection.

Agents use kinematic transform-based movement (not velocity/force-based).
Collision detection uses proximity checks (not PhysX contact reports,
which are unreliable for kinematic-teleported bodies).
"""

import dataclasses
import numpy as np  # NOTE: numpy is bundled with Isaac Sim runtime (isaacsim.core dependency), safe to use
from pxr import UsdGeom, UsdPhysics, Gf
import omni.usd
import carb

AGENTS_PATH = "/World/Agents"
ARRIVAL_THRESHOLD = 0.3  # meters — distance to consider waypoint reached
AGENT_RADIUS = 0.3  # approximate collision radius for proximity detection


@dataclasses.dataclass
class AgentConfig:
    name: str
    agent_type: str  # "robot", "humanoid", "person"
    asset_suffix: str  # Nucleus path suffix (after assets root)
    fallback_shape: str  # "cube" or "capsule"
    color: tuple  # (r, g, b) for fallback primitive
    spawn_offset: tuple  # (x, z) offset from room center


@dataclasses.dataclass
class AgentState:
    name: str
    agent_type: str
    prim_path: str
    position: np.ndarray  # [x, y, z]
    speed: float  # m/s (computed from delta)
    current_wp_idx: int
    progress: float  # 0-100%
    collision_count: int
    waypoint_path: object  # WaypointPath instance
    move_speed: float  # target speed m/s
    _prev_position: np.ndarray = dataclasses.field(default=None)
    _in_wall_collision: bool = False  # edge-trigger flag for wall proximity
    _in_agent_collision: set = dataclasses.field(default_factory=set)  # set of agent names currently colliding

    def __post_init__(self):
        if self._prev_position is None:
            self._prev_position = self.position.copy()


# Default agent configurations
DEFAULT_AGENTS = [
    AgentConfig(
        name="Robot",
        agent_type="robot",
        asset_suffix="/Isaac/Robots/NVIDIA/Jetbot/jetbot.usd",
        fallback_shape="cube",
        color=(0.2, 0.4, 0.9),  # Blue
        spawn_offset=(2.0, 2.0),
    ),
    AgentConfig(
        name="Humanoid",
        agent_type="humanoid",
        asset_suffix="/Isaac/Robots/Unitree/H1/h1.usd",
        fallback_shape="capsule",
        color=(0.2, 0.8, 0.3),  # Green
        spawn_offset=(-2.0, -2.0),
    ),
    AgentConfig(
        name="Person",
        agent_type="person",
        asset_suffix="",  # Always use fallback — no guaranteed person asset
        fallback_shape="capsule",
        color=(0.9, 0.3, 0.2),  # Red
        spawn_offset=(0.0, 2.5),
    ),
]


def spawn_agents(stage, room_size, move_speed=1.0, waypoint_paths=None):
    """Spawn all 3 agents in the scene.

    Args:
        stage: USD Stage
        room_size: room dimension in meters
        move_speed: patrol speed in m/s
        waypoint_paths: list of WaypointPath instances (one per agent)

    Returns:
        list of AgentState
    """
    # Idempotency: remove existing agents
    existing = stage.GetPrimAtPath(AGENTS_PATH)
    if existing and existing.IsValid():
        stage.RemovePrim(AGENTS_PATH)

    # Create agents container
    UsdGeom.Xform.Define(stage, AGENTS_PATH)

    agents = []
    for i, config in enumerate(DEFAULT_AGENTS):
        prim_path = f"{AGENTS_PATH}/{config.name}"
        spawn_pos = np.array([config.spawn_offset[0], 0.0, config.spawn_offset[1]])

        # Try Nucleus asset, fallback to primitive
        loaded = False
        if config.asset_suffix:
            loaded = _try_load_asset(stage, config.asset_suffix, prim_path)

        if not loaded:
            _create_fallback_prim(stage, prim_path, config.fallback_shape, config.color)

        # Set initial position
        prim = stage.GetPrimAtPath(prim_path)
        if prim and prim.IsValid():
            xformable = UsdGeom.Xformable(prim)
            # Clear existing xform ops and set translate
            xformable.ClearXformOpOrder()
            xformable.AddTranslateOp().Set(Gf.Vec3d(*spawn_pos.tolist()))

            # Apply kinematic RigidBody + Collision
            rigid = UsdPhysics.RigidBodyAPI.Apply(prim)
            rigid.CreateKinematicEnabledAttr(True)
            UsdPhysics.CollisionAPI.Apply(prim)

        wp = waypoint_paths[i] if waypoint_paths and i < len(waypoint_paths) else None
        agent = AgentState(
            name=config.name,
            agent_type=config.agent_type,
            prim_path=prim_path,
            position=spawn_pos.copy(),
            speed=0.0,
            current_wp_idx=0,
            progress=0.0,
            collision_count=0,
            waypoint_path=wp,
            move_speed=move_speed,
        )
        agents.append(agent)

    carb.log_info(f"[KKR.PhysicsSim] Spawned {len(agents)} agents")
    return agents


def _try_load_asset(stage, asset_suffix, prim_path):
    """Try to load a Nucleus asset. Returns True on success."""
    try:
        from isaacsim.storage.native import get_assets_root_path
        from isaacsim.core.utils.stage import add_reference_to_stage

        root = get_assets_root_path()
        if root is None:
            carb.log_warn("[KKR.PhysicsSim] Nucleus asset root unavailable, using fallback")
            return False

        full_path = root + asset_suffix
        add_reference_to_stage(full_path, prim_path)

        prim = stage.GetPrimAtPath(prim_path)
        if prim and prim.IsValid():
            carb.log_info(f"[KKR.PhysicsSim] Loaded asset: {asset_suffix}")
            return True
        return False
    except Exception as e:
        carb.log_warn(f"[KKR.PhysicsSim] Asset load failed ({asset_suffix}): {e}")
        return False


def _create_fallback_prim(stage, prim_path, shape, color):
    """Create a simple colored primitive as agent fallback."""
    if shape == "cube":
        geom = UsdGeom.Cube.Define(stage, prim_path)
        geom.CreateSizeAttr(0.3)
    else:
        geom = UsdGeom.Capsule.Define(stage, prim_path)
        geom.CreateRadiusAttr(0.2)
        geom.CreateHeightAttr(0.8)
        geom.CreateAxisAttr("Y")

    geom.CreateDisplayColorAttr([Gf.Vec3f(*color)])
    carb.log_info(f"[KKR.PhysicsSim] Created fallback {shape} at {prim_path}")


def update_agents(agents, dt):
    """Move all agents toward their current waypoint.

    Uses kinematic transform-based movement (position interpolation).

    Args:
        agents: list of AgentState
        dt: physics timestep in seconds
    """
    if dt <= 0:
        return

    stage = omni.usd.get_context().get_stage()
    if stage is None:
        return

    for agent in agents:
        if agent.waypoint_path is None:
            continue

        target = agent.waypoint_path.current_target
        direction = target - agent.position
        distance = np.linalg.norm(direction)

        # Check arrival
        if distance < ARRIVAL_THRESHOLD:
            agent.waypoint_path.advance()
            agent.current_wp_idx = agent.waypoint_path.current_index
            target = agent.waypoint_path.current_target
            direction = target - agent.position
            distance = np.linalg.norm(direction)

        # Move toward target
        if distance > 0.01:
            direction_normalized = direction / distance
            step_size = min(agent.move_speed * dt, distance)
            new_pos = agent.position + direction_normalized * step_size
        else:
            new_pos = agent.position.copy()

        # Update position in USD
        prim = stage.GetPrimAtPath(agent.prim_path)
        if prim and prim.IsValid():
            xformable = UsdGeom.Xformable(prim)
            ops = xformable.GetOrderedXformOps()
            for op in ops:
                if op.GetOpType() == UsdGeom.XformOp.TypeTranslate:
                    op.Set(Gf.Vec3d(*new_pos.tolist()))
                    break

        # Compute speed
        agent._prev_position = agent.position.copy()
        agent.position = new_pos
        agent.speed = np.linalg.norm(new_pos - agent._prev_position) / dt

        # Update progress
        agent.progress = agent.waypoint_path.progress(agent.position)


def check_collisions(agents, room_size, wall_thickness=0.1):
    """Edge-triggered proximity-based collision detection for kinematic agents.

    Only increments collision_count on transition into collision state
    (not every frame while in proximity). Uses _in_wall_collision and
    _in_agent_collision flags to track state transitions.
    """
    half = room_size / 2.0
    boundary = half - wall_thickness

    for agent in agents:
        pos = agent.position
        # Wall proximity check (edge-triggered)
        near_wall = (abs(pos[0]) > boundary - AGENT_RADIUS or
                     abs(pos[2]) > boundary - AGENT_RADIUS)
        if near_wall and not agent._in_wall_collision:
            agent.collision_count += 1
        agent._in_wall_collision = near_wall

    # Inter-agent proximity check (edge-triggered)
    current_pairs = set()
    for i in range(len(agents)):
        for j in range(i + 1, len(agents)):
            dist = np.linalg.norm(agents[i].position - agents[j].position)
            if dist < AGENT_RADIUS * 2:
                pair_key = (agents[i].name, agents[j].name)
                current_pairs.add(pair_key)
                # Only count on transition into collision
                if agents[j].name not in agents[i]._in_agent_collision:
                    agents[i].collision_count += 1
                    agents[j].collision_count += 1
                agents[i]._in_agent_collision.add(agents[j].name)
                agents[j]._in_agent_collision.add(agents[i].name)

    # Clear collision flags for pairs no longer in proximity
    for agent in agents:
        agent._in_agent_collision = {
            name for name in agent._in_agent_collision
            if any((agent.name, name) in current_pairs or (name, agent.name) in current_pairs
                   for _ in [None])
        }


def destroy_agents(stage):
    """Remove all agent prims."""
    prim = stage.GetPrimAtPath(AGENTS_PATH)
    if prim and prim.IsValid():
        stage.RemovePrim(AGENTS_PATH)
        carb.log_info(f"[KKR.PhysicsSim] Removed agents at {AGENTS_PATH}")


def destroy_scene(stage):
    """Remove both room and agents."""
    from .room_builder import destroy_room
    destroy_room(stage)
    destroy_agents(stage)
