# SPDX-FileCopyrightText: Copyright (c) 2022-2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Waypoint path definitions and progress tracking for autonomous agents.

Each agent gets a unique patrol route within the room bounds.
Waypoints are placed with a safety margin from walls to prevent clipping.
"""

import numpy as np


class WaypointPath:
    """Manages a cyclic waypoint path for a single agent."""

    def __init__(self, waypoints):
        """
        Args:
            waypoints: list of np.ndarray [x, y, z] positions
        """
        self.waypoints = waypoints
        self.current_index = 0
        self._total = len(waypoints)

    @property
    def current_target(self):
        return self.waypoints[self.current_index]

    @property
    def total_waypoints(self):
        return self._total

    def advance(self):
        """Move to the next waypoint, looping back to the start."""
        self.current_index = (self.current_index + 1) % self._total

    def progress(self, current_pos):
        """Calculate patrol progress as percentage (0-100).

        Progress = (completed_waypoints + fraction_to_next) / total * 100
        """
        target = self.current_target
        if self.current_index == 0:
            prev = self.waypoints[-1]
        else:
            prev = self.waypoints[self.current_index - 1]

        total_dist = np.linalg.norm(target - prev)
        remaining = np.linalg.norm(target - current_pos)

        if total_dist < 0.01:
            fraction = 1.0
        else:
            fraction = max(0.0, min(1.0, 1.0 - remaining / total_dist))

        return (self.current_index + fraction) / self._total * 100.0


def generate_waypoints(room_size, agent_index, num_waypoints=4, margin=1.5):
    """Generate a unique waypoint path for an agent inside the room.

    Args:
        room_size: room dimension in meters (square room)
        agent_index: 0=robot, 1=humanoid, 2=person (determines path shape)
        num_waypoints: number of waypoints per path
        margin: minimum distance from wall center (wall_thickness + agent_radius + buffer)

    Returns:
        list of np.ndarray [x, y, z] waypoint positions
    """
    half = room_size / 2.0 - margin
    y_heights = [0.0, 0.0, 0.0]  # all agents at ground level
    y = y_heights[min(agent_index, len(y_heights) - 1)]

    if agent_index == 0:
        # Robot: rectangular patrol near walls (clockwise)
        waypoints = [
            np.array([half, y, half]),
            np.array([half, y, -half]),
            np.array([-half, y, -half]),
            np.array([-half, y, half]),
        ]
    elif agent_index == 1:
        # Humanoid: diagonal cross pattern through center
        waypoints = [
            np.array([half * 0.7, y, half * 0.7]),
            np.array([-half * 0.7, y, -half * 0.7]),
            np.array([half * 0.7, y, -half * 0.7]),
            np.array([-half * 0.7, y, half * 0.7]),
        ]
    else:
        # Person: offset inner rectangle
        inner = half * 0.5
        waypoints = [
            np.array([inner, y, inner]),
            np.array([-inner, y, inner]),
            np.array([-inner, y, -inner]),
            np.array([inner, y, -inner]),
        ]

    return waypoints[:num_waypoints]
