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

import functools
import logging
import math
from enum import Enum

import pandas as pd
import py_trees
from pathfinding.core.diagonal_movement import DiagonalMovement
from pathfinding.core.grid import Grid
from pathfinding.finder.a_star import AStarFinder

from wpg.actuation_plan import *
from wpg.game_env import game_env
from wpg.game_map import CellType
from wpg.gentypes import Coordinates
from wpg.rng import get_rng_manager
from wpg.utils import round_away_from_zero

DRONE_NAMESPACE = "drone"

log = logging.getLogger(DRONE_NAMESPACE)


class IsCanNavigate(py_trees.behaviour.Behaviour):
    def __init__(self, name='Can Navigate?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="can_navigate", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.can_navigate else py_trees.common.Status.FAILURE


class IsAtBase(py_trees.behaviour.Behaviour):
    def __init__(self, name='At Base?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="at_base", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.at_base else py_trees.common.Status.FAILURE


class IsLeftBase(py_trees.behaviour.Behaviour):
    def __init__(self, name='Left Base?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="left_base", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.left_base else py_trees.common.Status.FAILURE


class TransitToAoiBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Transit to AoI'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="aoi_ingress_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)

    def initialise(self):
        self.actuation_plan.add_action(Action("move_to", [self.blackboard.aoi_ingress_coords]))

    def update(self):
        if self.blackboard.drone_coords == self.blackboard.aoi_ingress_coords:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class IsPoacherIdentified(py_trees.behaviour.Behaviour):
    def __init__(self, name='Poacher Identified?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_identified", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.poacher_identified else py_trees.common.Status.FAILURE


class RtbBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='RTB'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)
        self.base_coords = game_env.map.get_base_coords()

    def initialise(self):
        self.actuation_plan.add_action(Action("move_to", [self.base_coords]))

    def update(self):
        if self.blackboard.drone_coords == self.base_coords:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.RUNNING


class IsInAoi(py_trees.behaviour.Behaviour):
    def __init__(self, name='In AoI?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)

    def update(self):
        in_aoi = game_env.map.is_poacher_area(self.blackboard.drone_coords)
        return py_trees.common.Status.SUCCESS if in_aoi else py_trees.common.Status.FAILURE


class SearchBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, detection_range: int, actuation_plan: ActuationPlan, name='Search'):
        super().__init__(name)
        self.detection_range = detection_range
        self.actuation_plan = actuation_plan
        self.search_route = []
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)
        self.waypoint = None

    def initialise(self):
        # create search waypoint list
        self.search_route.clear()
        poacher_area = game_env.map.poacher_area_rect
        drone_pos = self.blackboard.drone_coords
        if (drone_pos.distance(poacher_area[0]) <= self.detection_range
                and drone_pos.distance(poacher_area[1]) <= self.detection_range
                and drone_pos.distance(Coordinates(poacher_area[0].x, poacher_area[1].y)) <= self.detection_range
                and drone_pos.distance(Coordinates(poacher_area[1].x, poacher_area[0].y)) <= self.detection_range):
            # it can already see the whole area. No need to add waypoints
            return

        width = poacher_area[1].x - poacher_area[0].x
        height = poacher_area[1].y - poacher_area[0].y

        # compute the area that the drone has to cover to search the whole poacher_area
        margin = math.floor(self.detection_range * math.cos(math.pi / 4))
        search_pattern_box = [
            Coordinates(
                poacher_area[0].x + min(margin, int(width / 2)),
                poacher_area[0].y + min(margin, int(height / 2))),
            Coordinates(
                poacher_area[1].x - min(margin, int(width / 2)),
                poacher_area[1].y - min(margin, int(height / 2)))]

        x = search_pattern_box[0].x
        y = search_pattern_box[1].y

        self.search_route.append(Coordinates(x, y))
        going_up = True
        new_band = True
        while new_band:
            if going_up:
                if y > search_pattern_box[0].y:
                    y = search_pattern_box[0].y
                    self.search_route.append(Coordinates(x, y))
            else:  # going down
                if y < search_pattern_box[1].y:
                    y = search_pattern_box[1].y
                    self.search_route.append(Coordinates(x, y))
            going_up = not going_up
            if x < search_pattern_box[1].x:  # going right
                x = min(search_pattern_box[1].x, x + self.detection_range)
                self.search_route.append(Coordinates(x, y))
                new_band = True
            else:
                new_band = False

    def update(self):
        if self.blackboard.poacher_visible:
            return py_trees.common.Status.SUCCESS
        if self.waypoint is not None and self.waypoint == self.blackboard.drone_coords:  # waypoint reached
            self.waypoint = None

        if self.waypoint is None:
            if not self.search_route:  # no more waypoints, failed to find poacher
                return py_trees.common.Status.FAILURE
            else:
                self.waypoint = self.search_route.pop(0)
                self.actuation_plan.add_action(Action("move_to", [self.waypoint]))

        # self.logger.info("RUNNING")
        return py_trees.common.Status.RUNNING


class IsPoacherVisible(py_trees.behaviour.Behaviour):
    def __init__(self, name='Poacher Visible?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.poacher_visible else py_trees.common.Status.FAILURE


class TrackPoacherBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, min_dist=0, name='Track Poacher'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.min_dist = min_dist
        self.avoid_trees = False  # for derived class to set to True if needed
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)

    def update(self):
        if not self.blackboard.poacher_visible:
            return py_trees.common.Status.FAILURE

        # compute target coordinates to approach poacher without getting closer than min_dist
        poacher_coords = self.blackboard.poacher_coords
        drone_coords = self.blackboard.drone_coords

        target_coords = poacher_coords

        # account for minimum distance
        if self.min_dist > 0:
            dist = self.blackboard.drone_coords.distance(self.blackboard.poacher_coords)
            if dist == 0:
                for delta in [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]:
                    target_x = drone_coords.x + round_away_from_zero(delta[0] * self.min_dist)
                    target_y = drone_coords.y + round_away_from_zero(delta[1] * self.min_dist)
                    target_coords = Coordinates(target_x, target_y)
                    if game_env.map.is_poacher_area(target_coords) and (
                            not self.avoid_trees or not game_env.map.is_tree(target_coords)):
                        break
            else:
                factor = 1 - self.min_dist / dist
                dx = poacher_coords.x - drone_coords.x
                dy = poacher_coords.y - drone_coords.y

                # these are the possible deltas to move snapping to the closest integer
                max_bounded_dx = round_away_from_zero(dx * factor)
                max_bounded_dy = round_away_from_zero(dy * factor)
                min_bounded_dx = int(dx * factor)
                min_bounded_dy = int(dy * factor)

                # try to get as close as possible to poacher, but not closer than min_dist
                potential_coords = [
                    Coordinates(drone_coords.x + min_bounded_dx, drone_coords.y + min_bounded_dy),
                    Coordinates(drone_coords.x + max_bounded_dx, drone_coords.y + min_bounded_dy),
                    Coordinates(drone_coords.x + min_bounded_dx, drone_coords.y + max_bounded_dy),
                    Coordinates(drone_coords.x + max_bounded_dx, drone_coords.y + max_bounded_dy)
                ]
                # keep potential coords that satisfy conditions:
                #   - distance is at least min_dist
                #   - is not a tree if trees should be avoided
                #   - is inside of the map
                potential_coords = [coord for coord in potential_coords if
                                    coord.distance(poacher_coords) >= self.min_dist
                                    and (not self.avoid_trees or not game_env.map.is_tree(target_coords))
                                    and game_env.map.is_valid_position(coord)]
                if len(potential_coords) == 0:
                    return py_trees.common.Status.FAILURE

                # find the closest one
                target_coords = min(potential_coords, key=lambda coord: coord.distance(poacher_coords))

        track_action = Action("move_to", [target_coords])
        if not self.actuation_plan.has_action(track_action):
            self.actuation_plan.add_action(track_action)

        return py_trees.common.Status.RUNNING


class LowAltTrackPoacherBehaviour(TrackPoacherBehaviour):
    def __init__(self, actuation_plan: ActuationPlan, min_dist=0, name='Low Alt Track Poacher'):
        super().__init__(actuation_plan, min_dist, name)
        self.avoid_trees = True


class IsPoacherInIdRange(py_trees.behaviour.Behaviour):
    def __init__(self, name='Poacher in ID range?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_in_id_range", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.poacher_in_id_range else py_trees.common.Status.FAILURE


class IdPoacherBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, continuous_id_count_required: int, total_id_count_required: int, actuation_plan: ActuationPlan,
                 name='ID Poacher'):
        super().__init__(name)
        self.continuous_id_count_required = continuous_id_count_required
        self.total_id_count_required = total_id_count_required
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_in_id_range", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_identified", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="total_id_count", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="continuous_id_done", access=py_trees.common.Access.WRITE)
        self.continuous_id_count = 0

    def initialise(self) -> None:
        self.continuous_id_count = 0

    def update(self):
        if self.blackboard.poacher_in_id_range:
            self.blackboard.total_id_count += 1
            self.continuous_id_count += 1

            if self.continuous_id_count >= self.continuous_id_count_required:
                self.blackboard.continuous_id_done = True

            if self.blackboard.total_id_count >= self.total_id_count_required and self.blackboard.continuous_id_done:
                self.blackboard.poacher_identified = True
                return py_trees.common.Status.SUCCESS
            else:
                return py_trees.common.Status.RUNNING
        else:
            return py_trees.common.Status.FAILURE


class IsShotDown(py_trees.behaviour.Behaviour):
    def __init__(self, name='Shot Down?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_shot_down", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.drone_shot_down else py_trees.common.Status.FAILURE


class IsFlyingHigh(py_trees.behaviour.Behaviour):
    def __init__(self, name='Flying High?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="flying_high", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.flying_high else py_trees.common.Status.FAILURE


class IsFlyingLow(py_trees.behaviour.Behaviour):
    def __init__(self, name='Flying Low'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="flying_low", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.flying_low else py_trees.common.Status.FAILURE


class DescendBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, asap: bool = False, name='Descend'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.asap = asap
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="flying_low", access=py_trees.common.Access.READ)

    def initialise(self):
        self.actuation_plan.add_action(Action("descend", [self.asap]))

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.flying_low else py_trees.common.Status.RUNNING


class ClimbBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Climb'):
        super().__init__(name)
        self.actuation_plan = actuation_plan

    def update(self):
        self.actuation_plan.add_action(Action("climb", []))
        return py_trees.common.Status.SUCCESS


class LowAltitudeSearchBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, detection_range: int, actuation_plan: ActuationPlan, name='Low Altitude Search'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)
        self.detection_range = detection_range
        self.seen = set()
        self.visited = set()
        self.searchable_cells = set()
        self.current_goal = None
        self.fov_cache = {}

    def initialise(self):
        self.seen.clear()
        self.searchable_cells = self.get_searchable_cells()
        self.visited = {self.blackboard.drone_coords}
        self.current_goal = None

    def update(self):
        if self.blackboard.poacher_visible:
            return py_trees.common.Status.SUCCESS

        self.visited.add(self.blackboard.drone_coords)
        self.update_seen(self.blackboard.drone_coords)

        if self.blackboard.drone_coords == self.current_goal:
            self.current_goal = None

        if self.current_goal is None:
            self.current_goal = self.get_next_goal()
            if self.current_goal is None:
                return py_trees.common.Status.FAILURE
            else:
                self.actuation_plan.add_action(Action("move_to", [self.current_goal]))

        return py_trees.common.Status.RUNNING

    def get_searchable_cells(self):
        searchable_cells = set()
        poacher_area = game_env.map.poacher_area_rect
        for x in range(poacher_area[0].x, poacher_area[1].x + 1):
            for y in range(poacher_area[0].y, poacher_area[1].y + 1):
                cell = Coordinates(x, y)
                if game_env.map.is_poacher_area(cell) and not game_env.map.is_tree(cell):
                    searchable_cells.add(cell)
        return searchable_cells

    def update_seen(self, cell):
        if cell not in self.fov_cache:
            self.fov_cache[cell] = game_env.map.get_cells_in_fov(cell, self.detection_range)

        self.seen.update(self.fov_cache[cell])

    def get_next_goal(self):
        candidates = self.searchable_cells - self.visited
        if not candidates:
            candidates = {cell for cell in self.searchable_cells if self.information_gain(cell) > 0}
        if not candidates:
            return None

        current = self.blackboard.drone_coords
        candidates_with_paths = []
        for cell in candidates:
            path = self.path_within_searchable_cells(current, cell)
            if path:
                candidates_with_paths.append((cell, path))

        if not candidates_with_paths:
            return None

        rng = get_rng_manager().np_rng("drone/low_alt_search")
        rng.shuffle(candidates_with_paths)
        _, best_path = max(
            candidates_with_paths,
            key=lambda candidate: (
                self.information_gain(candidate[0]),
                -len(candidate[1]),
            ),
        )

        return best_path[0]

    def path_within_searchable_cells(self, start, goal):
        if start == goal:
            return []

        grid_matrix = [
            [
                1 if Coordinates(x, y) in self.searchable_cells else 0
                for x in range(game_env.map.width)
            ]
            for y in range(game_env.map.height)
        ]

        grid = Grid(matrix=grid_matrix)
        finder = AStarFinder(diagonal_movement=DiagonalMovement.always)
        path, _ = finder.find_path(
            grid.node(start.x, start.y),
            grid.node(goal.x, goal.y),
            grid,
        )
        if not path:
            return []
        return [Coordinates(node.x, node.y) for node in path[1:]]

    def information_gain(self, cell):
        if cell not in self.fov_cache:
            self.fov_cache[cell] = game_env.map.get_cells_in_fov(cell, self.detection_range)

        visible = self.fov_cache[cell]

        return len(visible - self.seen)


class EvadeBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, distance=0, name='Evade Poacher'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.distance = distance
        self.blackboard = self.attach_blackboard_client(namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="flying_low", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.READ)
        self.target_cell = None

    def initialise(self) -> None:
        self.target_cell = None

    def update(self):
        if self.blackboard.poacher_visible:
            current_distance = self.blackboard.drone_coords.distance(self.blackboard.poacher_coords)
            if current_distance >= self.distance:
                return py_trees.common.Status.SUCCESS

        # if we can't see the poacher any longer but have reached the previous target cell, declare success
        if self.target_cell is not None and not self.blackboard.poacher_visible:
            if self.blackboard.drone_coords == self.target_cell:
                return py_trees.common.Status.SUCCESS

        # if we can see the poacher, compute a target cell
        if self.blackboard.poacher_visible:

            # can we still use the original target cell?
            if self.target_cell is not None and self.target_cell.distance(
                    self.blackboard.poacher_coords) >= self.distance:
                return py_trees.common.Status.RUNNING

            # find the closest reachable cell to the drone that is far enough from the poacher
            if self.blackboard.flying_low:
                # find any kind of cell that is not TREES
                new_target_cell = game_env.map.find_closest_at_least_distance_from(
                    location=self.blackboard.drone_coords,
                    cell_type=CellType.TREES,
                    min_distance_from=self.blackboard.poacher_coords,
                    min_dist=self.distance,
                    invert=True
                )
            else:
                # find any kind of cell that is not BASE (that includes trees)
                new_target_cell = game_env.map.find_closest_at_least_distance_from(
                    location=self.blackboard.drone_coords,
                    cell_type=CellType.BASE,
                    min_distance_from=self.blackboard.poacher_coords,
                    min_dist=self.distance,
                    invert=True
                )
            if new_target_cell is not None:
                if self.target_cell is None or self.target_cell != new_target_cell:
                    self.target_cell = new_target_cell
                    self.actuation_plan.add_action(Action("move_to", [self.target_cell]))

        if self.target_cell is not None:
            return py_trees.common.Status.RUNNING

        return py_trees.common.Status.FAILURE


def post_tick_handler(snapshot_visitor, behaviour_tree):
    print(
        py_trees.display.unicode_tree(
            behaviour_tree.root,
            visited=snapshot_visitor.visited,
            previously_visited=snapshot_visitor.visited
        )
    )


class TacticStatus(Enum):
    IDLE = 0
    RUNNING = 1
    SUCCESS = 2
    FAILURE = 3


@dataclass
class DroneMoP:
    poacher_tracking_time: int = 0
    poacher_imaging_time: int = 0
    poacher_identified: bool = False
    drone_shot_down: bool = False


class Drone:
    def __init__(self, config, x, y, poacher):
        self.config = config
        self.location = Coordinates(x, y)
        self.flying_low = False

        # state for move_to action
        self.move_to_target = None
        self.move_to_grid_for_flying_low = False
        self.move_to_grid = None  # grid representation of the map for pathfinding
        self.move_to_path = None

        self.detection_range = config['detection_range']
        self.id_range = config['id_range']
        self.total_id_count_required = config['total_id_count']
        self.continuous_id_count_required = config['continuous_id_count']

        self.poacher = poacher
        self.poacher_action = ''
        self.actuation_plan = ActuationPlan('drone')
        self.running_tactics = {}  # helper to log data
        self.sensed_state = None  # save sensed state to complete the data row after deciding
        self.data: pd.DataFrame = pd.DataFrame(columns=['time', 'x', 'y', 'in_aoi', 'shot_down', 'poacher_visible',
                                                        'poacher.x', 'poacher.y',
                                                        'poacher_in_id_range', 'poacher_identified', 'drone_shot_down',
                                                        'flying_low', 'gps_available', 'can_navigate',
                                                        'poacher_action',
                                                        'tactic', 'tactic_params'])

        self.measures_of_performance = DroneMoP()

        self.blackboard = py_trees.blackboard.Client(name="Drone", namespace=DRONE_NAMESPACE)
        self.blackboard.register_key(key="drone_coords", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="poacher_visible", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="poacher_in_id_range", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="poacher_identified", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="in_aoi", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="at_base", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="left_base", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="returned_to_base", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="aoi_ingress_coords", access=py_trees.common.Access.READ)
        self.blackboard.register_key(key="drone_shot_down", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="actuation_state", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="can_navigate", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="flying_low", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="flying_high", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="gps_available", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="rtb_threshold", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="gun_fire", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="total_id_count", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="continuous_id_done", access=py_trees.common.Access.WRITE)
        self.blackboard.total_id_count = 0
        self.blackboard.continuous_id_done = 0
        self.blackboard.poacher_identified = False
        self.blackboard.left_base = False
        self.blackboard.returned_to_base = False
        self.blackboard.rtb_threshold = False

        self.event = py_trees.blackboard.Client(name="Drone", namespace="event")
        self.event.register_key(key="shot_fired", access=py_trees.common.Access.READ)
        self.event.register_key(key="shot_on_target", access=py_trees.common.Access.READ)
        self.event.register_key(key="deny_gps", access=py_trees.common.Access.READ)

        self._create_top_level_bt()

        if False:  # make true to log tree state after each tick
            snapshot_visitor = py_trees.visitors.SnapshotVisitor()
            self.drone_bt.add_post_tick_handler(
                functools.partial(post_tick_handler,
                                  snapshot_visitor))
            self.drone_bt.visitors.append(snapshot_visitor)

    def _create_top_level_bt(self):
        is_shot_down = IsShotDown(name='Shot Down?')
        shot_down_inverter = py_trees.decorators.Inverter(name='Inverter', child=is_shot_down)
        self.tactics_bt = py_trees.composites.Parallel(name='Tactics',
                                                       policy=py_trees.common.ParallelPolicy.SuccessOnAll())
        tactics_fir = py_trees.decorators.FailureIsRunning(name='F->R', child=self.tactics_bt)
        is_left_base = IsLeftBase(name='Left Base?')
        left_base_fir = py_trees.decorators.FailureIsRunning(name='F->R', child=is_left_base)
        is_at_base = IsAtBase(name='At Base?')
        at_base_fir = py_trees.decorators.FailureIsRunning(name='F->R', child=is_at_base)
        drone = py_trees.composites.Sequence(name='Drone', memory=False)
        drone.add_children([shot_down_inverter, tactics_fir, left_base_fir, at_base_fir])
        self.drone_bt = py_trees.trees.BehaviourTree(drone)

    def has_returned_to_base(self) -> bool:
        return self.blackboard.left_base and game_env.map.is_base(self.location)

    def sense(self, poacher):
        self.blackboard.drone_coords = self.location
        self.blackboard.flying_low = self.flying_low
        self.blackboard.flying_high = not self.flying_low

        self.blackboard.at_base = game_env.map.is_base(self.location)
        self.blackboard.left_base = self.blackboard.left_base or not self.blackboard.at_base
        self.blackboard.returned_to_base = self.blackboard.returned_to_base or self.has_returned_to_base()

        # is poacher visible?
        dist = self.location.distance(poacher.location)
        if (dist <= self.detection_range) and not game_env.map.is_tree(poacher.location):
            if self.flying_low:
                clear_LOS = game_env.map.has_clear_line_of_sight(self.location, poacher.location)
                self.blackboard.poacher_visible = clear_LOS
            else:
                self.blackboard.poacher_visible = True
        else:
            self.blackboard.poacher_visible = False

        if self.blackboard.poacher_visible:
            self.blackboard.poacher_coords = poacher.location
            self.measures_of_performance.poacher_tracking_time += 1
        else:
            self.blackboard.poacher_coords = None

        self.blackboard.poacher_in_id_range = (dist <= self.id_range)
        if self.blackboard.poacher_in_id_range:
            self.measures_of_performance.poacher_imaging_time += 1
        if self.blackboard.poacher_identified:
            self.measures_of_performance.poacher_identified = True

        self.blackboard.in_aoi = game_env.map.is_poacher_area(self.location)

        self.blackboard.gun_fire = self.event.shot_fired
        self.measures_of_performance.drone_shot_down = self.measures_of_performance.drone_shot_down or self.event.shot_on_target
        self.blackboard.drone_shot_down = self.measures_of_performance.drone_shot_down

        # GPS denial is limited to the AoI
        self.blackboard.gps_available = not self.blackboard.in_aoi or not self.event.deny_gps
        self.blackboard.flying_low = self.flying_low
        self.blackboard.flying_high = not self.flying_low

        # we assume that the switch to optical navigation happens automatically when flying low and GPS is denied
        self.blackboard.can_navigate = self.blackboard.gps_available or self.flying_low

        # RTB Threshold: determine when the drone is at or past the threshold to return to base
        base_coords = game_env.map.get_base_coords()
        path_to_base = self._calculate_path(self.location, base_coords, self.flying_low, False)
        time_steps_before_timeout = game_env.timeout - game_env.time_step - 1
        self.blackboard.rtb_threshold = self.blackboard.rtb_threshold or (
                    len(path_to_base) * 1.10 > time_steps_before_timeout)

        self._infer_poacher_action()
        self._save_sensed_state()

        tactic_state = self._get_tactic_state()
        self.blackboard.actuation_state = tactic_state.name

    def _infer_poacher_action(self):
        self.poacher_action = ''

        if self.event.shot_fired:
            self.poacher_action = 'fire'
        elif self.config['poacher_hide_sensor']:
            if len(self.data) > 0:
                last_row = self.data.iloc[-1]
                poacher_was_visible = last_row['poacher_visible']
                if poacher_was_visible and not self.blackboard.poacher_visible:
                    tactic = self._get_current_tactic()
                    if tactic is not None and tactic['tactic'] == 'track_and_id':
                        self.poacher_action = 'hide'

    def _save_sensed_state(self):
        self.sensed_state = {
            'x': self.location.x,
            'y': self.location.y,
            'in_aoi': self.blackboard.in_aoi,
            'shot_down': self.blackboard.drone_shot_down,
            'poacher_visible': self.blackboard.poacher_visible,
            'poacher.x': self.poacher.location.x if self.blackboard.poacher_visible else pd.NA,
            'poacher.y': self.poacher.location.y if self.blackboard.poacher_visible else pd.NA,
            'poacher_in_id_range': self.blackboard.poacher_in_id_range,
            'poacher_identified': self.blackboard.poacher_identified,
            'drone_shot_down': self.blackboard.drone_shot_down,
            'flying_low': self.blackboard.flying_low,
            'gps_available': self.blackboard.gps_available,
            'can_navigate': self.blackboard.can_navigate,
            'poacher_action': self.poacher_action,
        }

    def tick(self, tactics):

        # tactics is a list of pairs: (tactic name, params)
        # the special tactic name '*stop_all*' stops all running tactics
        if any(tactic[0] == '*stop_all*' for tactic in tactics):
            self.tactics_bt.remove_all_children()
            self.running_tactics.clear()
            tactics[:] = [tactic for tactic in tactics if tactic[0] != '*stop_all*']

        for tactic in tactics:
            tactic_name, tactic_params = tactic
            self.start_tactic(tactic_name, tactic_params)

        self.drone_bt.tick()
        return self.drone_bt.root.status

    def tock(self):
        self.actuation_plan.execute_plan_on(self)

    def get_measurements(self) -> DroneMoP:
        return self.measures_of_performance

    def _get_current_tactic(self):
        tactic = None
        if len(self.running_tactics) > 0:
            tactic = next(iter(self.running_tactics.values()))
        return tactic

    def _get_tactic_state(self) -> TacticStatus:
        if len(self.tactics_bt.children) == 0:
            return TacticStatus.IDLE

        # has any tactic failed?
        tactic_failed = any(tactic.status == py_trees.common.Status.FAILURE for tactic in self.tactics_bt.children)

        # remove not RUNNING tactics from the tree and tracking running_tactics
        for child in self.tactics_bt.children:
            if child.status != py_trees.common.Status.RUNNING:
                self.running_tactics.pop(child.id, None)
        self.tactics_bt.children[:] = [
            c for c in self.tactics_bt.children if c.status == py_trees.common.Status.RUNNING]

        if tactic_failed:
            return TacticStatus.FAILURE
        elif len(self.tactics_bt.children) == 0:
            return TacticStatus.SUCCESS

        return TacticStatus.RUNNING

    def add_data_row(self, time_step, log_data: dict[str, Any] | None = None):
        # if there's any key in log_data that is not a column in self.data, add it
        if log_data is None:
            log_data = {}
        else:
            for key in log_data.keys():
                if key not in self.data.columns:
                    self.data[key] = pd.NA

        tactic_cols = {}
        tactic = self._get_current_tactic()
        if tactic is not None:
            tactic_cols = {
                'tactic': tactic['tactic'],
                'tactic_params': tactic['params'] if 'params' in tactic else pd.NA
            }

        self.data.loc[len(self.data)] = {'time': time_step} | self.sensed_state | tactic_cols | log_data

    def start_tactic(self, tactic, params):
        method = getattr(self, tactic, None)

        # 2. Check if we actually found a valid method
        if callable(method):
            # 3. Call the method, unpacking the list into separate arguments
            tactic_bt_root = method(**params)
            tactic_bt_root.name = tactic
            self.tactics_bt.add_child(tactic_bt_root)
            self.running_tactics[tactic_bt_root.id] = {'tactic': tactic, 'params': params}
        else:
            log.error(f"Unknown tactic: '{tactic}'. Ignoring.")

    ####
    # Tactics
    ####
    def transit_to_aoi(self):
        in_aoi = IsInAoi(name='In AoI')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        transit = TransitToAoiBehaviour(self.actuation_plan, name='Transit')
        transit_seq = py_trees.composites.Sequence(name='Transit_seq', memory=False)
        transit_seq.add_children([is_can_navigate, transit])
        transit_to_aoi = py_trees.composites.Selector(name='Transit to AoI', memory=False)
        transit_to_aoi.add_children([in_aoi, transit_seq])
        return transit_to_aoi

    def search_poacher(self):
        poacher_visible = IsPoacherVisible(name='Poacher Visible')
        is_in_aoi = IsInAoi(name='In AoI?')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        is_flying_high = IsFlyingHigh(name='Flying High?')
        search = SearchBehaviour(self.detection_range, self.actuation_plan, name='Search')
        sp_seq = py_trees.composites.Sequence(name='SP_seq', memory=False)
        sp_seq.add_children([is_in_aoi, is_can_navigate, is_flying_high, search])
        search_poacher = py_trees.composites.Selector(name='Search Poacher', memory=False)
        search_poacher.add_children([poacher_visible, sp_seq])
        return search_poacher

    def low_alt_search(self):
        poacher_visible = IsPoacherVisible(name='Poacher Visible')
        is_in_aoi = IsInAoi(name='In AoI?')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        is_flying_low = IsFlyingLow(name='Flying Low?')
        low_alt_search = LowAltitudeSearchBehaviour(self.detection_range, self.actuation_plan,
                                                         name='Low Altitude Search')
        splowalt_seq = py_trees.composites.Sequence(name='SPLowAlt_seq', memory=False)
        splowalt_seq.add_children([is_in_aoi, is_can_navigate, is_flying_low, low_alt_search])
        low_alt_search_2 = py_trees.composites.Selector(name='Low Altitude Search', memory=False)
        low_alt_search_2.add_children([poacher_visible, splowalt_seq])
        return low_alt_search_2

    def track_and_id(self, min_dist):
        poacher_identified = IsPoacherIdentified(name='Poacher Identified')
        is_poacher_visible = IsPoacherVisible(name='Poacher Visible?')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        is_flying_high = IsFlyingHigh(name='Flying High?')
        track_poacher = TrackPoacherBehaviour(self.actuation_plan, min_dist=min_dist, name='Track Poacher')
        is_poacher_in_id_range = IsPoacherInIdRange(name='Poacher in ID range?')
        id_poacher = IdPoacherBehaviour(self.continuous_id_count_required, self.total_id_count_required,
                                        self.actuation_plan, name='ID Poacher')
        identify_poacher = py_trees.composites.Sequence(name='Identify Poacher', memory=False)
        identify_poacher.add_children([is_poacher_in_id_range, id_poacher])
        f_r = py_trees.decorators.FailureIsRunning(name='F->R', child=identify_poacher)
        parallel1 = py_trees.composites.Parallel(name='(1)', policy=py_trees.common.ParallelPolicy.SuccessOnOne())
        parallel1.add_children([track_poacher, f_r])
        trackid_seq = py_trees.composites.Sequence(name='TrackID_seq', memory=False)
        trackid_seq.add_children([is_poacher_visible, is_can_navigate, is_flying_high, parallel1])
        track_id = py_trees.composites.Selector(name='Track&ID', memory=False)
        track_id.add_children([poacher_identified, trackid_seq])
        return track_id

    def low_alt_track_id(self, min_dist):
        poacher_identified = IsPoacherIdentified(name='Poacher Identified')
        is_poacher_visible = IsPoacherVisible(name='Poacher Visible?')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        is_flying_low = IsFlyingLow(name='Flying Low?')
        low_alt_track_poacher = LowAltTrackPoacherBehaviour(self.actuation_plan, name='Low Alt Track Poacher')
        is_poacher_in_id_range = IsPoacherInIdRange(name='Poacher in ID range?')
        id_poacher = IdPoacherBehaviour(self.continuous_id_count_required, self.total_id_count_required,
                                        self.actuation_plan, name='ID Poacher')
        identify_poacher = py_trees.composites.Sequence(name='Identify Poacher', memory=False)
        identify_poacher.add_children([is_poacher_in_id_range, id_poacher])
        f_r = py_trees.decorators.FailureIsRunning(name='F->R', child=identify_poacher)
        parallel_1 = py_trees.composites.Parallel(name='(1)', policy=py_trees.common.ParallelPolicy.SuccessOnOne())
        parallel_1.add_children([low_alt_track_poacher, f_r])
        lowalttrackid_seq = py_trees.composites.Sequence(name='LowAltTrackId_seq', memory=False)
        lowalttrackid_seq.add_children([is_poacher_visible, is_can_navigate, is_flying_low, parallel_1])
        low_altitude_track_id = py_trees.composites.Selector(name='Low Altitude Track&ID', memory=False)
        low_altitude_track_id.add_children([poacher_identified, lowalttrackid_seq])
        return low_altitude_track_id

    def rtb(self):
        at_base = IsAtBase(name='At base')
        is_can_navigate = IsCanNavigate(name='Can Navigate?')
        rtb = RtbBehaviour(self.actuation_plan, name='RTB')
        rtb_seq = py_trees.composites.Sequence(name='RTB_seq', memory=False)
        rtb_seq.add_children([is_can_navigate, rtb])
        return_to_base = py_trees.composites.Selector(name='Return to Base', memory=False)
        return_to_base.add_children([at_base, rtb_seq])
        return return_to_base

    def fly_low(self):
        flying_low = IsFlyingLow(name='Flying Low')
        descend = DescendBehaviour(self.actuation_plan, name='Descend')
        fly_low = py_trees.composites.Selector(name='Fly Low', memory=False)
        fly_low.add_children([flying_low, descend])
        return fly_low

    def fly_low_asap(self):
        flying_low = IsFlyingLow(name='Flying Low')
        descend = DescendBehaviour(self.actuation_plan, asap=True, name='Descend ASAP')
        fly_low = py_trees.composites.Selector(name='Fly Low', memory=False)
        fly_low.add_children([flying_low, descend])
        return fly_low

    def fly_high(self):
        flying_high = IsFlyingHigh(name='Flying High')
        climb = ClimbBehaviour(self.actuation_plan, name='Climb')
        fly_high = py_trees.composites.Selector(name='Fly High', memory=False)
        fly_high.add_children([flying_high, climb])
        return fly_high

    def evade_poacher(self, distance):
        is_poacher_visible = IsPoacherVisible(name='Poacher Visible?')
        evade = EvadeBehaviour(self.actuation_plan, distance=distance, name='Evade')
        evade_poacher = py_trees.composites.Sequence(name='Evade Poacher', memory=True)
        evade_poacher.add_children([is_poacher_visible, evade])
        return evade_poacher

    ####
    # actions
    ####
    def move_to(self, target_coords: Coordinates):
        if self.location == target_coords:
            self.move_to_target = None
            return True  # already there
        if self.move_to_target is None or self.move_to_target != target_coords:
            # we need to recalculate the path
            self.move_to_path = self._calculate_path(self.location, target_coords, self.flying_low, True)
            self.move_to_target = target_coords
        if len(self.move_to_path) == 0:
            log.warning(f"No path to {target_coords} found.")
            return False  # will stay here until new target is set

        next_coords = self.move_to_path.pop(0)
        self.location = Coordinates(next_coords.x, next_coords.y)
        if len(self.move_to_path) == 0:
            self.move_to_target = None

        return self.location == target_coords

    def _calculate_path(self, from_coords: Coordinates, dest_coords: Coordinates, flying_low: bool, update_grid: bool):
        if not update_grid or self.move_to_grid is None or self.move_to_grid_for_flying_low != flying_low:
            if flying_low:
                # create a matrix from the original map but make all the cells with trees have a value of 0, and the rest 1
                grid_matrix = [[0 if game_env.map.is_tree(Coordinates(x, y)) else 1 for x in range(game_env.map.width)]
                               for y
                               in range(game_env.map.height)]
                grid = Grid(matrix=grid_matrix)
            else:
                grid = Grid(game_env.map.width, game_env.map.height)
        else:
            grid = self.move_to_grid

        finder = AStarFinder(diagonal_movement=DiagonalMovement.always)
        start = grid.node(from_coords.x, from_coords.y)
        target = grid.node(dest_coords.x, dest_coords.y)
        path, runs = finder.find_path(start, target, grid)
        if len(path) > 0:
            # the first element in the path is the start position, remove it
            path.pop(0)

        # update the grid in the instance so that it can be reused
        if update_grid:
            self.move_to_grid_for_flying_low = flying_low
            self.move_to_grid = grid

        return path

    def climb(self):
        if not self.flying_low:
            return True

        # if we're moving, replan the route (no need to avoid trees)
        if self.move_to_target is not None:
            new_path = self._calculate_path(self.location, self.move_to_targete, False, True)
            if len(new_path) > 0:
                self.move_to_path = new_path

        self.flying_low = False
        return True

    def descend(self, asap: bool = False):
        """
        Command the drone to descend.

        The drone can only descend on a cell that is clear of trees.

        If the drone is not flying to a waypoint, it will go to the closest cell that is clear of trees
        and descend there. If the drone is already flying to a waypoint, the behavior depends on the
        argument asap. If False, it will descend on the first non-tree cell in the path and then
        continue to the waypoint with a new path because now it has to fly between trees. If True,
        it will descend on the closest clear cell (even if it's not in the original path) and then
        continue flying to the waypoint.
        """
        if self.flying_low:
            return True
        # if we're not over a tree, we can descend
        if not game_env.map.is_tree(self.location):
            self.flying_low = True
            return True

        descent_cell = None
        if not asap:
            # if we're moving, see if there's a non-tree cell in the path where we can descend
            if self.move_to_target is not None:
                descent_cell = next(
                    (cell for cell in self.move_to_path
                     if not game_env.map.is_tree(Coordinates(cell.x, cell.y))),
                    None
                )

        if descent_cell is None:
            descent_cell = game_env.map.find_closest(self.location,
                                                     cell_type=CellType.TREES,
                                                     invert=True)
            if descent_cell is None:
                # this should never happen, but with this it will keep trying to descend
                return False

        # find path to the closest clear cell
        descent_path = self._calculate_path(self.location, descent_cell, False, True)
        if len(descent_path) == 0:
            return False  # no path found

        if self.move_to_target is not None:
            # we're already flying to a waypoint. Update the path so that after descending, we can continue to the waypoint
            second_path_segment = self._calculate_path(descent_cell, self.move_to_target, True, True)
            self.move_to_path = descent_path + second_path_segment
        else:
            # we're not flying to a waypoint, so we can just set the path directly
            self.move_to_path = descent_path
            self.actuation_plan.add_action(Action("move_to", [descent_cell]))

        return False
