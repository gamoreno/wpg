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

import pandas as pd
import py_trees
from py_trees import behaviour

from wpg.actuation_plan import *
from wpg.game_env import game_env
from wpg.game_map import CellType
from wpg.gentypes import Coordinates
from wpg.rng import get_rng_manager

MOVEMENT_DIRECTIONS = [(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)]
POACHER_NAMESPACE = "poacher"


class IsDroneDetected(py_trees.behaviour.Behaviour):
    def __init__(self, name):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="drone_detected", access=py_trees.common.Access.READ)

    def update(self):
        # Only succeed if the poacher has seen the drone
        if self.blackboard.drone_detected:
            return py_trees.common.Status.SUCCESS
        return py_trees.common.Status.FAILURE


class HideUnderTreeBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Hide Under Tree'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)

        self.closest_tree_coords = None

    def initialise(self):
        self.closest_tree_coords = game_env.map.find_closest(self.blackboard.poacher_coords,
                                                             CellType.TREES,
                                                             only_poacher_area=True)
        if self.closest_tree_coords is not None:
            if self.blackboard.poacher_coords != self.closest_tree_coords:
                self.actuation_plan.add_action(Action("move_to", [self.closest_tree_coords]))

    def update(self):
        if self.closest_tree_coords is None:
            return py_trees.common.Status.FAILURE

        return py_trees.common.Status.RUNNING


class PoachBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Poach'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)
        self.rng = get_rng_manager().np_rng("poacher/wander")
        self.poaching = False  # if not poaching, it's moving
        self.wander_countdown = 0  # forces the poacher to move after hiding

    def update(self):
        """
        return SUCCESS to poach (stay in place) or FAILURE to move
        """

        # if the poacher is hiding under a tree, it should start moving now
        if game_env.map.is_tree(self.blackboard.poacher_coords):
            self.poaching = False
            self.wander_countdown = 4
            return py_trees.common.Status.FAILURE

        if self.poaching:
            if self.rng.random() < 0.2:
                # stop poaching
                self.poaching = False
                return py_trees.common.Status.FAILURE  # because it's in a select
            else:
                return py_trees.common.Status.SUCCESS  # keep poaching
        else:
            if self.wander_countdown > 0:
                self.wander_countdown -= 1
            if self.wander_countdown <= 0:
                if self.rng.random() < 0.3:
                    # start poaching
                    self.poaching = True
                    return py_trees.common.Status.SUCCESS

        return py_trees.common.Status.FAILURE  # keep moving, because it's in a select


class WanderBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Wander'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)
        self.direction_idx = 0
        self.rng = get_rng_manager().np_rng("poacher/wander")

    def update(self):
        directions = list(range(len(MOVEMENT_DIRECTIONS)))
        keep_direction = True
        while len(directions) > 0:
            if not keep_direction or self.rng.random() < 0.3:
                self.direction_idx = directions.pop(self.rng.integers(0, len(directions)))
            dx, dy = MOVEMENT_DIRECTIONS[self.direction_idx]
            new_location = Coordinates(self.blackboard.poacher_coords.x + dx, self.blackboard.poacher_coords.y + dy)
            if game_env.map.is_poacher_area(new_location) and not game_env.map.is_tree(new_location):
                self.actuation_plan.add_action(Action("move_to", [new_location]))
                return py_trees.common.Status.RUNNING
            keep_direction = False
        return py_trees.common.Status.FAILURE


class IsTreeClose(py_trees.behaviour.Behaviour):
    def __init__(self, max_distance, name='Tree Close?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.READ)
        self.max_distance = max_distance

    def update(self):
        closest_tree_coords = game_env.map.find_closest(self.blackboard.poacher_coords,
                                                        CellType.TREES,
                                                        only_poacher_area=True)
        if closest_tree_coords is None:
            return py_trees.common.Status.FAILURE
        if self.blackboard.poacher_coords.distance(closest_tree_coords) > self.max_distance:
            return py_trees.common.Status.FAILURE
        return py_trees.common.Status.SUCCESS


class IsInGunRange(py_trees.behaviour.Behaviour):
    def __init__(self, name='In Gun Range?'):
        super().__init__(name)
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="drone_in_gun_range", access=py_trees.common.Access.READ)

    def update(self):
        return py_trees.common.Status.SUCCESS if self.blackboard.drone_in_gun_range else py_trees.common.Status.FAILURE


class ShootBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Shoot'):
        super().__init__(name)
        self.actuation_plan = actuation_plan
        self.blackboard = self.attach_blackboard_client(namespace=POACHER_NAMESPACE)
        self.aim_time = 0
        self.last_aim_step = -1

    def initialise(self) -> None:
        self.aim_time = 0

    def update(self):
        if game_env.time_step - self.last_aim_step > 1:
            # lost aim
            self.aim_time = 0

        self.last_aim_step = game_env.time_step
        if self.aim_time < 2:
            self.aim_time += 1
            return py_trees.common.Status.RUNNING

        self.actuation_plan.add_action(Action("fire_gun", []))
        return py_trees.common.Status.SUCCESS


class DenyGpsBehaviour(py_trees.behaviour.Behaviour):
    def __init__(self, actuation_plan: ActuationPlan, name='Deny GPS'):
        super().__init__(name)
        self.actuation_plan = actuation_plan

    def update(self):
        self.actuation_plan.add_action(Action("deny_gps", []))
        return py_trees.common.Status.SUCCESS


class ActionMonitorVisitor(py_trees.visitors.VisitorBase):
    """visitor to extract the last action performed by the poacher"""

    def __init__(self):
        super().__init__()
        self.action = []

    def initialise(self) -> None:
        self.action = []

    def run(self, behaviour: behaviour.Behaviour) -> None:
        if behaviour.name.startswith('action:'):
            self.action.append(behaviour.name[len('action:'):])

    def get_action(self) -> str:
        return self.action


@dataclass
class PoacherSideMoP:
    drone_visible_time: int = 0
    drone_in_gun_range_time: int = 0


class Poacher:
    def __init__(self, config, x, y):
        self.behavior_version = config['behavior']
        self.detection_range = config['detection_range']
        self.detection_probability = config['detection_probability']
        self.gun_range = config['gun_range']
        self.gun_accuracy = config['gun_accuracy']
        self.gps_denial_probability = config['gps_denial_probability']
        self.hide_tree_max_distance = config['hide_tree_max_distance']
        self.location = Coordinates(x, y)
        self.drone_detected = False
        self.actuation_plan = ActuationPlan('poacher')
        self.sensed_state = None
        self.data: pd.DataFrame = pd.DataFrame(columns=['time', 'x', 'y', 'drone_detected', 'action'])

        self.drone_mop = PoacherSideMoP()

        # 1. Setup the Blackboard connection
        self.blackboard = py_trees.blackboard.Client(name="Poacher", namespace=POACHER_NAMESPACE)
        self.blackboard.register_key(key="drone_detected", access=py_trees.common.Access.WRITE)
        self.blackboard.drone_detected = False
        self.blackboard.register_key(key="poacher_coords", access=py_trees.common.Access.WRITE)
        self.blackboard.register_key(key="drone_in_gun_range", access=py_trees.common.Access.WRITE)
        self.blackboard.drone_in_gun_range = False

        self.event = py_trees.blackboard.Client(name="Poacher", namespace="event")
        self.event.register_key(key="shot_fired", access=py_trees.common.Access.WRITE)
        self.event.shot_fired = False
        self.event.register_key(key="shot_on_target", access=py_trees.common.Access.WRITE)
        self.event.shot_on_target = False
        self.event.register_key(key="deny_gps", access=py_trees.common.Access.WRITE)
        self.event.deny_gps = False

        self.poacher_bt = self.create_tree(self.behavior_version)
        self.action_monitor_visitor = ActionMonitorVisitor()
        self.poacher_bt.add_visitor(self.action_monitor_visitor)

    def create_tree(self, version: int):
        if version == 4 or version == 5:
            # poacher has gun
            poacher = self._create_tree_v4()
        elif version == 6 or version == 7:
            # poacher has a gun and hides
            poacher = self._create_tree_v6()
        else:
            poacher = py_trees.composites.Selector(name='Poacher', memory=False)
            if version == 2 or version == 3:
                # poacher can hide under trees
                is_drone_detected = IsDroneDetected(name='Drone Detected?')
                hide_under_tree = HideUnderTreeBehaviour(self.actuation_plan, name='action:hide')
                hide = py_trees.composites.Sequence(name='Hide', memory=False)
                hide.add_children([is_drone_detected, hide_under_tree])
                poacher.add_children([hide])
            wander = WanderBehaviour(self.actuation_plan, name='Wander')
            poach = PoachBehaviour(self.actuation_plan, name='Poach')
            do = py_trees.composites.Selector(name='Do', memory=False)
            do.add_children([poach, wander])

            poacher.add_children([do])

        if version == 3 or version == 5 or version == 7:
            # GPS-denying poacher (with some probability)
            # see if we need to add GPS denial
            rng = get_rng_manager().np_rng("poacher/deny_gps")
            if rng.random() <= self.gps_denial_probability:
                deny_gps = DenyGpsBehaviour(self.actuation_plan, name='action:deny_gps')
                gps_denying_poacher = py_trees.composites.Sequence(name='GPS-Denying Poacher', memory=False)
                gps_denying_poacher.add_children([deny_gps, poacher])
                return py_trees.trees.BehaviourTree(gps_denying_poacher)

        return py_trees.trees.BehaviourTree(poacher)

    def _create_tree_v4(self):
        is_drone_detected = IsDroneDetected(name='Drone Detected?')
        inverter = py_trees.decorators.Inverter(name='Inverter', child=is_drone_detected)

        is_in_gun_range = IsInGunRange(name='In Gun Range?')
        shoot = ShootBehaviour(self.actuation_plan, name='action:fire')
        shoot_if_in_range = py_trees.composites.Sequence(name='Shoot If In Range', memory=False)
        shoot_if_in_range.add_children([is_in_gun_range, shoot])
        deal_with_drone = py_trees.composites.Selector(name='Deal with Drone', memory=False)
        deal_with_drone.add_children([inverter, shoot_if_in_range])

        wander = WanderBehaviour(self.actuation_plan, name='Wander')
        poach = PoachBehaviour(self.actuation_plan, name='Poach')
        do = py_trees.composites.Selector(name='Do', memory=False)
        do.add_children([poach, wander])

        poacher = py_trees.composites.Sequence(name='Poacher', memory=False)
        poacher.add_children([deal_with_drone, do])
        return poacher

    def _create_tree_v6(self):
        is_drone_detected = IsDroneDetected(name='Drone Detected?')
        inverter = py_trees.decorators.Inverter(name='Inverter', child=is_drone_detected)
        is_tree_close = IsTreeClose(self.hide_tree_max_distance, name='Tree Close?')
        hide_under_tree = HideUnderTreeBehaviour(self.actuation_plan, name='action:hide')
        hide = py_trees.composites.Sequence(name='Hide', memory=False)
        hide.add_children([is_tree_close, hide_under_tree])

        is_in_gun_range = IsInGunRange(name='In Gun Range?')
        shoot = ShootBehaviour(self.actuation_plan, name='action:fire')
        shoot_if_in_range = py_trees.composites.Sequence(name='Shoot If In Range', memory=False)
        shoot_if_in_range.add_children([is_in_gun_range, shoot])
        deal_with_drone = py_trees.composites.Selector(name='Deal with Drone', memory=False)
        deal_with_drone.add_children([inverter, hide, shoot_if_in_range])

        wander = WanderBehaviour(self.actuation_plan, name='Wander')
        poach = PoachBehaviour(self.actuation_plan, name='Poach')
        do = py_trees.composites.Selector(name='Do', memory=False)
        do.add_children([poach, wander])

        poacher = py_trees.composites.Sequence(name='Poacher', memory=False)
        poacher.add_children([deal_with_drone, do])
        return poacher

    def sense(self, drone):
        self.blackboard.poacher_coords = self.location

        distance = self.location.distance(drone.location)

        # drone detection
        self.drone_detected = False  # assume the drone is not detected
        computed_LOS = False  # to avoid computing LOS twice
        drone_in_detection_range = distance <= self.detection_range
        if drone_in_detection_range:
            clear_LOS = (not drone.flying_low) or game_env.map.has_clear_line_of_sight(self.location, drone.location)
            computed_LOS = True
            if clear_LOS:
                self.drone_mop.drone_visible_time += 1
                rng = get_rng_manager().np_rng("poacher/detect_drone")
                if rng.random() <= self.detection_probability:
                    self.drone_detected = True

        # drone in gun range
        self.blackboard.drone_in_gun_range = False  # assume not in range
        if distance <= self.gun_range:
            if not computed_LOS:
                clear_LOS = (not drone.flying_low) or game_env.map.has_clear_line_of_sight(self.location,
                                                                                           drone.location)
            if clear_LOS:
                self.blackboard.drone_in_gun_range = True
                self.drone_mop.drone_in_gun_range_time += 1

        # Push the raw sensor data to the blackboard for the next tick
        self.blackboard.drone_detected = self.drone_detected

        self._save_sensed_state()

    def get_measurements(self) -> PoacherSideMoP:
        return self.drone_mop

    def _save_sensed_state(self):
        self.sensed_state = {
            'x': self.location.x,
            'y': self.location.y,
            'drone_detected': self.drone_detected
        }

    def tick(self):
        self.poacher_bt.tick()
        return self.poacher_bt.root.status

    def tock(self):
        self.actuation_plan.execute_plan_on(self)

    def add_data_row(self, time_step):
        self.data.loc[len(self.data)] = {
                                            'time': time_step,
                                        } | self.sensed_state | {'action': self.action_monitor_visitor.get_action()}

    ####
    # actions
    ####
    def move_to(self, target_coords: Coordinates):
        target_x, target_y = target_coords.x, target_coords.y
        next_x, next_y = self.location.x, self.location.y
        if target_x > next_x:
            next_x += 1
        elif target_x < next_x:
            next_x -= 1
        if target_y > next_y:
            next_y += 1
        elif target_y < next_y:
            next_y -= 1
        self.location = Coordinates(next_x, next_y)

        return self.location == target_coords

    def fire_gun(self):
        self.event.shot_fired = True
        rng = get_rng_manager().np_rng("poacher/fire_gun")
        self.event.shot_on_target = rng.random() <= self.gun_accuracy

        return True  # done

    def deny_gps(self):
        self.event.deny_gps = True
        return True  # done
