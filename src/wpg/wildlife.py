#
# Wildlife Protection Game
# 
# Copyright 2026 Carnegie Mellon University.
# 
# NO WARRANTY. THIS CARNEGIE MELLON UNIVERSITY AND SOFTWARE ENGINEERING INSTITUTE
# MATERIAL IS FURNISHED ON AN "AS-IS" BASIS. CARNEGIE MELLON UNIVERSITY MAKES NO
# WARRANTIES OF ANY KIND, EITHER EXPRESSED OR IMPLIED, AS TO ANY MATTER INCLUDING,
# BUT NOT LIMITED TO, WARRANTY OF FITNESS FOR PURPOSE OR MERCHANTABILITY,
# EXCLUSIVITY, OR RESULTS OBTAINED FROM USE OF THE MATERIAL. CARNEGIE MELLON
# UNIVERSITY DOES NOT MAKE ANY WARRANTY OF ANY KIND WITH RESPECT TO FREEDOM FROM
# PATENT, TRADEMARK, OR COPYRIGHT INFRINGEMENT.
# 
# Licensed under a BSD (SEI)-style license, please see license.txt or contact
# permission@sei.cmu.edu for full terms.
# 
# [DISTRIBUTION STATEMENT A] This material has been approved for public release
# and unlimited distribution.  Please see Copyright notice for non-US Government
# use and distribution.
# 
# This Software includes and/or makes use of Third-Party Software each subject
# to its own license.
# 
# DM26-0661

from enum import Enum
from pathlib import Path
import pandas as pd
import py_trees

from wpg.constants import (
    DRONE_DATA_CSV,
    GAME_DATA_CSV,
    MAP_DATA_CSV,
    POACHER_DATA_CSV,
    GAME_RESULT_CSV
)
from wpg.drone import DRONE_NAMESPACE
from wpg.drone import Drone
from wpg.game_env import game_env
from wpg.game_map import CellType, GameMap
from wpg.gentypes import Coordinates
from wpg.poacher import Poacher
from wpg.utils import AppException, blackboard2dict


class LoopState(Enum):
    """Loop states."""
    INIT = 0
    SENSED = 1
    ACTED = 2
    DONE = 3


class GameResult(Enum):
    """Game results."""
    SUCCESS = 0
    POACHER_NOT_ID = 1
    POACHER_NOT_FOUND = 2
    DRONE_LOST = 3
    UNKNOWN = 4


class Game:
    """Game class."""

    def __init__(self, config, moe_calculator=None) -> None:
        """
        Initialize a new game.
        """
        self.result = GameResult.UNKNOWN
        self.loop_state = LoopState.INIT
        self.moe_calculator = moe_calculator
        self.timeout = config['sim']['timeout']
        game_env.timeout = self.timeout
        game_env.time_step = 0
        map_width = config['map']['width']
        map_height = config['map']['height']
        poacher_area_size = config['map']['poacher_area_size']
        game_env.map = GameMap(map_width, map_height, poacher_area_size, config['map'])
        poacher_initial_coords = game_env.map.get_poacher_initial_position()
        self.poacher = Poacher(
            config['poacher'],
            poacher_initial_coords.x,
            poacher_initial_coords.y
        )
        base_coords = game_env.map.get_base_coords()

        drone_config = config['drone']
        drone_config['main_dir'] = config['main_dir']
        self.drone = Drone(drone_config, base_coords.x, base_coords.y, self.poacher)
        self.time_step = 0
        self.data: pd.DataFrame = pd.DataFrame(
            columns=['time', 'poacher.x', 'poacher.y', 'drone.x', 'drone.y', 'drone.poacher_visible',
                     'drone.identified poacher', 'poacher.detected drone'])
        self.drone_data: pd.DataFrame = pd.DataFrame(
            columns=['time', 'x', 'y', 'poacher_visible', 'identified_poacher'])
        self.poacher_data: pd.DataFrame = pd.DataFrame(columns=['time', 'x', 'y', 'drone_detected'])

        self.blackboard = py_trees.blackboard.Client(name="Game", namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="aoi_ingress_coords", access=py_trees.common.Access.WRITE)
        self.blackboard.aoi_ingress_coords = Coordinates(map_width - poacher_area_size, poacher_area_size - 1)
        # make sure the AOI ingress point is savanna
        game_env.map.grid[self.blackboard.aoi_ingress_coords.y][self.blackboard.aoi_ingress_coords.x] = CellType.SAVANNA
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_identified", access=py_trees.common.Access.READ)

    def _sense(self):
        game_env.time_step = self.time_step
        self.poacher.sense(self.drone)
        self.drone.sense(self.poacher)

        # actions executed in the last time step may have left events on the blackboard
        # these events are used during the sense methods and they must be cleared now
        self._reset_event_blackboard()

        # we save data after sensing but before tick, because otherwise the positions may not match the sensed values
        self._add_game_data_row()

    def finished(self) -> bool:
        return self.loop_state == LoopState.DONE

    def get_knowledge(self):
        if self.loop_state != LoopState.SENSED:
            self._sense()
            self.loop_state = LoopState.SENSED

        return blackboard2dict('/drone')

    def step(self, tactics, log_data) -> bool:
        if self.loop_state == LoopState.DONE:
            return False

        if self.loop_state != LoopState.SENSED:
            self._sense()

        self.poacher.tick()
        drone_status = self.drone.tick(tactics)

        # execute selected action
        self.drone.tock()
        self.poacher.tock()

        # these two methods must ensure that the added data has the sensed state before ticking
        # and any action decided during the tick
        self.drone.add_data_row(self.time_step, log_data)
        self.poacher.add_data_row(self.time_step)

        self.time_step += 1
        self.loop_state = LoopState.ACTED

        if drone_status != py_trees.common.Status.RUNNING or self.time_step >= self.timeout:
            self.loop_state = LoopState.DONE

            if self.time_step >= self.timeout and not self.drone.has_returned_to_base():
                self.result = GameResult.DRONE_LOST  # ran out of time before RTB
            elif drone_status == py_trees.common.Status.FAILURE:
                self.result = GameResult.DRONE_LOST  # shot down
            elif self.drone.get_measurements().poacher_identified:
                self.result = GameResult.SUCCESS
            elif self.drone.get_measurements().poacher_tracking_time == 0:
                self.result = GameResult.POACHER_NOT_FOUND
            else:
                self.result = GameResult.POACHER_NOT_ID  # tracked it some but not identified

        return self.loop_state != LoopState.DONE

    def get_result(self):
        """
        Get the result of the game.
        """
        return self.result

    def _reset_event_blackboard(self) -> None:
        """
        Reset all event namespace values on the py_trees blackboard.
        """
        for key in py_trees.blackboard.Blackboard.keys():
            if key.startswith("/event/"):
                py_trees.blackboard.Blackboard.set(key, False)

    def _add_game_data_row(self) -> None:
        """
        Add a new row to the game data.
        """
        self.data.loc[self.time_step] = {
            'time': self.time_step,
            'poacher.x': self.poacher.location.x,
            'poacher.y': self.poacher.location.y,
            'drone.x': self.drone.location.x,
            'drone.y': self.drone.location.y,
            'drone.poacher_visible': self.blackboard.poacher_visible,
            'drone.identified poacher': self.blackboard.poacher_identified,
            'poacher.detected drone': self.poacher.drone_detected
        }

    def save_data(self, output_dir) -> None:
        """
        Save the game data to a file.
        """
        self.data.to_csv(Path(output_dir).joinpath(GAME_DATA_CSV), index=False)
        self.drone.data.to_csv(Path(output_dir).joinpath(DRONE_DATA_CSV), index=False)
        self.poacher.data.to_csv(Path(output_dir).joinpath(POACHER_DATA_CSV), index=False)
        game_env.map.save_map(Path(output_dir).joinpath(MAP_DATA_CSV))
        self.save_result(output_dir)

    def save_result(self, output_dir) -> None:
        """
        Save the game result to a file.
        """
        game_result = pd.DataFrame([{'steps': self.time_step,
                                     'result': self.get_result().name,
                                     'moe': self.get_measure_of_effectiveness()}])
        game_result.to_csv(Path(output_dir).joinpath(GAME_RESULT_CSV), index=False)
        print(game_result.to_string(index=False))

    def get_measure_of_effectiveness(self):
        if self.moe_calculator is None:
            raise AppException("No MOE calculator configured.")

        return self.moe_calculator.calculate(self)

    def visualize(self, output_dir) -> None:
        """
        Visualize the game data.
        """
        from wpg.visualizer.gamevisualizer import GameVisualizer

        visualizer = GameVisualizer(Path(output_dir))
        visualizer.run()
