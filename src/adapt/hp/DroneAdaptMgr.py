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

import subprocess
from typing import Any

from json_logic import jsonLogic

from adapt.hp.strategies_to_pddl import strategies_to_pddl_domain
from adapt.st1.DroneAdaptMgr import DroneAdaptMgr
from wpg.drone import TacticStatus
from wpg.utils import AppException

import logging
log = logging.getLogger("wpg")

class HPDroneAdaptMgr(DroneAdaptMgr):
    def __init__(self, config):
        self.config = config
        self.current_strategy = None
        self.current_tactic_index = None  # the index of the current tactic in the strategy
        self.strategies = self.load_strategies(config, __package__)
        self.mission_plan = None

    def create_mission_plan(self, knowledge: dict[Any, Any]):
        pddl_domain, action_to_strategy = strategies_to_pddl_domain(self.strategies, domain_name='wildlife')

        # write pddl domain to file
        with open('domain.pddl', 'w') as f:
            f.write(pddl_domain)

        # create problem file
        with open('mission.pddl', 'w') as f:
            f.write('(define (problem wpg-mission)')
            f.write('(:domain wildlife)')
            f.write('  (:init')
            # for every key, value pair in knowledge, write a fact
            for key, value in knowledge.items():
                if isinstance(value, bool):
                    if value:
                        f.write(f'    ({key})')
                else:
                    f.write(f'    ({key} {value})')
            f.write('  )')
            f.write('  (:goal (and (at_base) (poacher_identified)))')
            f.write(')')

        # invoke planner
        try:
            proc = subprocess.run(
                ['docker', 'run', '--rm', '--platform', 'linux/amd64', '-v', './:/files', 'aibasel/downward',
                 '--alias',
                 'lama-first', '--plan-file', '/files/mission.plan', '/files/mission.pddl'], capture_output=True,
                text=True)
        except Exception as e:
            raise AppException(f"Failed to run planner: {e}")
        if proc.returncode not in [0, 10, 11, 12]:  # 10, 11, 12 means solution wasn't found
            raise AppException(f"Planner failed: exit code {proc.returncode}\n {proc.stdout}\n{proc.stderr}")

        mission_plan = []

        if proc.returncode == 0:
            # read the plan from the file line by line
            with open('mission.plan', 'r') as f:
                for plan in f:
                    if plan.startswith('('):
                        mission_plan.append(action_to_strategy[plan.strip('( )\n')])
            log.info(f"mission plan: {mission_plan}")
        else:
            log.info(f"unable to create a mission plan")

        return mission_plan

    def decide(self, knowledge: dict[Any, Any]) -> list[Any]:
        tactic_set = []

        tactic_status = TacticStatus[knowledge['actuation_state']]
        # this is needed here so that strategies can execute back to back
        # and for the proper recording of strategies in the data
        tactic = self.do_strategy_ctrl_flow(tactic_status)

        replanned = False
        if self.mission_plan is None:
            self.mission_plan = self.create_mission_plan(knowledge)
        elif tactic_status == TacticStatus.FAILURE:
            self.mission_plan = self.create_mission_plan(knowledge)
            replanned = False

        while self.current_strategy is None:
            # we're in between strategies or haven't started yet
            if self.mission_plan:
                strategy_name = self.mission_plan.pop(0)
                strategy = self.get_strategy_by_name(strategy_name)

                # make sure that the condition for starting the next strategy is satisfied
                if jsonLogic(strategy['condition'], knowledge):
                    self.start_strategy(strategy)

                    # The initial tactic status is not relevant for this next call
                    # since we're stopping all tactics, we pass IDLE as the status
                    tactic = self.do_strategy_ctrl_flow(TacticStatus.IDLE)
                elif not replanned:
                    log.info("Condition not satisfied for next strategy in mission plan. Need to replan")
                    replanned = True
                    self.mission_plan = self.create_mission_plan(knowledge)
                else:
                    log.info("Could not compute a mission plan. Giving up")
                    break
            else:
                log.info("Mission plan complete!")
                self.mission_plan = None
                break

        if tactic is not None:
            tactic_set.append((tactic['tactic'], tactic['params']))
        return tactic_set

    def get_strategy_by_name(self, name):
        for strategy in self.strategies:
            if strategy['name'] == name:
                return strategy
        return None
