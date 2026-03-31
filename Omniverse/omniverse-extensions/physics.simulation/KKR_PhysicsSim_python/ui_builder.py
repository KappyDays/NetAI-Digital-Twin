# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
UI Builder for KKR.PhysicsSim extension.

Provides:
- Control panel: room generation, agent spawning, speed/size settings
- Real-time dashboard: per-agent position, speed, waypoint, progress, collisions
- Scene lifecycle: destroy_sim_scene() for stage close / extension shutdown
"""

import omni.ui as ui
import omni
import omni.usd
import omni.timeline
import carb

from .room_builder import generate_room, ensure_physics_scene
from .agent_manager import (
    spawn_agents, update_agents, check_collisions,
    destroy_scene, AgentState,
)
from .waypoint_system import generate_waypoints, WaypointPath


class UIBuilder:
    def __init__(self):
        self.frames = []
        self.wrapped_ui_elements = []

        # Simulation state
        self._agents = []
        self._room_generated = False
        self._step_counter = 0
        self._sim_running = False
        self._elapsed_time = 0.0

        # Settings
        self._room_size = 10.0
        self._move_speed = 1.0
        self._agents_only = False

        # Dashboard UI labels (updated at ~10Hz)
        self._agent_labels = {}  # name -> dict of ui.Label refs
        self._status_label = None
        self._elapsed_label = None
        self._agents_count_label = None

    # ── Public interface (called by extension.py boilerplate) ────────

    def build_ui(self):
        """Build the extension UI."""
        self._build_control_section()
        self._build_dashboard_section()

    def on_menu_callback(self):
        pass

    def on_timeline_event(self, event):
        if event.type == int(omni.timeline.TimelineEventType.PLAY):
            self._sim_running = True
            self._step_counter = 0
        elif event.type == int(omni.timeline.TimelineEventType.STOP):
            self._sim_running = False

    def on_physics_step(self, step):
        """Called every physics step (~60Hz). Movement at full rate, UI at ~10Hz."""
        if not self._agents:
            return

        dt = step
        self._elapsed_time += dt

        # Movement + collision at full physics rate
        update_agents(self._agents, dt)
        check_collisions(self._agents, self._room_size)

        # Throttle UI updates to ~10Hz
        self._step_counter += 1
        if self._step_counter % 6 != 0:
            return

        self._update_dashboard()

    def on_stage_event(self, event):
        pass

    def cleanup(self):
        """Clean up UI widgets AND destroy scene prims.

        Called by boilerplate on:
        - on_shutdown()
        - _on_window(visible=False)
        - _on_stage_event(OPENED/CLOSED)

        Scene prims are destroyed here because the boilerplate calls cleanup()
        on stage close. This matches the lakehouse.proto lifecycle contract.
        """
        # Destroy scene prims
        self._destroy_sim_scene_internal()

        # Clean up UI widgets (standard pattern)
        for elem in self.wrapped_ui_elements:
            try:
                elem.cleanup()
            except Exception:
                pass
        self.wrapped_ui_elements = []
        self.frames = []
        self._agent_labels = {}
        self._status_label = None
        self._elapsed_label = None
        self._agents_count_label = None

    # ── Control Section ──────────────────────────────────────────────

    def _build_control_section(self):
        frame = ui.CollapsableFrame("Simulation Control", collapsed=False)
        self.frames.append(frame)
        with frame:
            with ui.VStack(spacing=5, height=0):
                # Room size
                with ui.HStack(spacing=5, height=0):
                    ui.Label("Room Size (m):", width=120)
                    size_field = ui.FloatField(width=80)
                    size_field.model.set_value(self._room_size)
                    size_field.model.add_value_changed_fn(
                        lambda m: setattr(self, '_room_size', max(5.0, min(20.0, m.get_value_as_float())))
                    )

                # Agent speed
                with ui.HStack(spacing=5, height=0):
                    ui.Label("Agent Speed (m/s):", width=120)
                    speed_field = ui.FloatField(width=80)
                    speed_field.model.set_value(self._move_speed)
                    speed_field.model.add_value_changed_fn(
                        lambda m: setattr(self, '_move_speed', max(0.1, min(5.0, m.get_value_as_float())))
                    )

                # Agents only checkbox
                with ui.HStack(spacing=5, height=0):
                    cb = ui.CheckBox(width=20)
                    cb.model.set_value(self._agents_only)
                    cb.model.add_value_changed_fn(
                        lambda m: setattr(self, '_agents_only', m.get_value_as_bool())
                    )
                    ui.Label("Add Agents Only (skip room generation)")

                ui.Spacer(height=5)

                # Buttons
                with ui.HStack(spacing=10, height=0):
                    ui.Button(
                        "Generate Room & Spawn Agents",
                        clicked_fn=self._on_setup_scene,
                        height=30,
                        style={"Button": {"background_color": 0xFF2D5F2D}},
                    )
                    ui.Button(
                        "Clear Scene",
                        clicked_fn=self._on_clear_scene,
                        height=30,
                        style={"Button": {"background_color": 0xFF5F2D2D}},
                    )

    # ── Dashboard Section ────────────────────────────────────────────

    def _build_dashboard_section(self):
        frame = ui.CollapsableFrame("Agent Dashboard", collapsed=False)
        self.frames.append(frame)
        with frame:
            with ui.VStack(spacing=3, height=0):
                # Status bar
                with ui.HStack(spacing=10, height=0):
                    self._status_label = ui.Label("Status: Stopped", width=150)
                    self._elapsed_label = ui.Label("Elapsed: 0.0s", width=150)
                    self._agents_count_label = ui.Label(f"Agents: {len(self._agents)}", width=100)

                ui.Spacer(height=5)

                # Header row
                with ui.HStack(spacing=2, height=0):
                    ui.Label("Name", width=70, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Type", width=65, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Position (X, Y, Z)", width=160, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Speed", width=60, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Waypoint", width=65, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Progress", width=60, style={"color": 0xFF88AAFF, "font_size": 13})
                    ui.Label("Collisions", width=60, style={"color": 0xFF88AAFF, "font_size": 13})

                ui.Line(style={"color": 0xFF444444}, height=2)

                # Agent rows
                self._agent_labels = {}
                if self._agents:
                    for agent in self._agents:
                        self._build_agent_row(agent)
                else:
                    ui.Label(
                        "No agents spawned. Click 'Generate Room & Spawn Agents' to start.",
                        style={"color": 0xFF888888},
                    )

    def _build_agent_row(self, agent):
        """Build a single agent row in the dashboard."""
        labels = {}
        type_colors = {"robot": 0xFF4488FF, "humanoid": 0xFF44FF88, "person": 0xFFFF8844}
        color = type_colors.get(agent.agent_type, 0xFFCCCCCC)

        with ui.HStack(spacing=2, height=0):
            labels["name"] = ui.Label(agent.name, width=70, style={"color": color, "font_size": 12})
            labels["type"] = ui.Label(agent.agent_type, width=65, style={"font_size": 12})
            labels["position"] = ui.Label(
                f"{agent.position[0]:.2f}, {agent.position[1]:.2f}, {agent.position[2]:.2f}",
                width=160, style={"font_size": 12},
            )
            labels["speed"] = ui.Label(f"{agent.speed:.2f} m/s", width=60, style={"font_size": 12})

            wp_total = agent.waypoint_path.total_waypoints if agent.waypoint_path else 0
            labels["waypoint"] = ui.Label(
                f"WP {agent.current_wp_idx + 1}/{wp_total}",
                width=65, style={"font_size": 12},
            )
            labels["progress"] = ui.Label(f"{agent.progress:.1f}%", width=60, style={"font_size": 12})
            labels["collisions"] = ui.Label(str(agent.collision_count), width=60, style={"font_size": 12})

        self._agent_labels[agent.name] = labels

    def _update_dashboard(self):
        """Update dashboard labels with current agent states (~10Hz)."""
        for agent in self._agents:
            labels = self._agent_labels.get(agent.name)
            if not labels:
                continue

            try:
                labels["position"].text = (
                    f"{agent.position[0]:.2f}, {agent.position[1]:.2f}, {agent.position[2]:.2f}"
                )
                labels["speed"].text = f"{agent.speed:.2f} m/s"

                wp_total = agent.waypoint_path.total_waypoints if agent.waypoint_path else 0
                labels["waypoint"].text = f"WP {agent.current_wp_idx + 1}/{wp_total}"
                labels["progress"].text = f"{agent.progress:.1f}%"
                labels["collisions"].text = str(agent.collision_count)
            except Exception:
                pass  # UI elements may be destroyed

        if self._status_label:
            try:
                self._status_label.text = f"Status: {'Running' if self._sim_running else 'Stopped'}"
            except Exception:
                pass
        if self._elapsed_label:
            try:
                self._elapsed_label.text = f"Elapsed: {self._elapsed_time:.1f}s"
            except Exception:
                pass
        if hasattr(self, '_agents_count_label') and self._agents_count_label:
            try:
                self._agents_count_label.text = f"Agents: {len(self._agents)}"
            except Exception:
                pass

    # ── Scene Management ─────────────────────────────────────────────

    def _on_setup_scene(self):
        """Generate room and/or spawn agents."""
        stage = omni.usd.get_context().get_stage()
        if stage is None:
            carb.log_warn("[KKR.PhysicsSim] No stage available")
            return

        # Room generation
        if not self._agents_only:
            generate_room(stage, size=self._room_size)
            self._room_generated = True
        else:
            # Ensure physics scene for agents-only mode
            ensure_physics_scene(stage)

        # Generate waypoints for each agent
        waypoint_paths = []
        for i in range(3):
            wps = generate_waypoints(self._room_size, i)
            waypoint_paths.append(WaypointPath(wps))

        # Spawn agents
        self._agents = spawn_agents(stage, self._room_size, self._move_speed, waypoint_paths)
        self._elapsed_time = 0.0
        self._step_counter = 0

        # Rebuild dashboard to show agent rows
        self._rebuild_dashboard()

    def _on_clear_scene(self):
        """Remove all generated prims (room + agents)."""
        self._destroy_sim_scene_internal()
        self._rebuild_dashboard()

    def _destroy_sim_scene_internal(self):
        """Internal: destroy scene prims and reset state."""
        try:
            stage = omni.usd.get_context().get_stage()
            if stage is not None:
                destroy_scene(stage)
        except Exception as e:
            carb.log_warn(f"[KKR.PhysicsSim] Scene cleanup error: {e}")

        self._agents = []
        self._room_generated = False
        self._sim_running = False
        self._elapsed_time = 0.0
        self._step_counter = 0

    def _rebuild_dashboard(self):
        """Rebuild the dashboard section with current agent data."""
        # The dashboard is rebuilt by the extension.py _build_ui() on next window show.
        # For immediate refresh, we update labels directly if they exist.
        # If agents changed (added/removed), we need a full UI rebuild.
        # Trigger by rebuilding frames — this is a lightweight approach.
        if len(self.frames) >= 2:
            dashboard_frame = self.frames[1]
            try:
                dashboard_frame.clear()
                with dashboard_frame:
                    with ui.VStack(spacing=3, height=0):
                        # Status bar
                        with ui.HStack(spacing=10, height=0):
                            self._status_label = ui.Label(
                                f"Status: {'Running' if self._sim_running else 'Stopped'}",
                                width=150,
                            )
                            self._elapsed_label = ui.Label(
                                f"Elapsed: {self._elapsed_time:.1f}s",
                                width=150,
                            )
                            self._agents_count_label = ui.Label(f"Agents: {len(self._agents)}", width=100)

                        ui.Spacer(height=5)

                        # Header
                        with ui.HStack(spacing=2, height=0):
                            ui.Label("Name", width=70, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Type", width=65, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Position (X, Y, Z)", width=160, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Speed", width=60, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Waypoint", width=65, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Progress", width=60, style={"color": 0xFF88AAFF, "font_size": 13})
                            ui.Label("Collisions", width=60, style={"color": 0xFF88AAFF, "font_size": 13})

                        ui.Line(style={"color": 0xFF444444}, height=2)

                        # Agent rows
                        self._agent_labels = {}
                        if self._agents:
                            for agent in self._agents:
                                self._build_agent_row(agent)
                        else:
                            ui.Label(
                                "No agents spawned. Click 'Generate Room & Spawn Agents' to start.",
                                style={"color": 0xFF888888},
                            )
            except Exception as e:
                carb.log_warn(f"[KKR.PhysicsSim] Dashboard rebuild error: {e}")
