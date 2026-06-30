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

import json
from contextlib import nullcontext
from importlib import resources
from pathlib import Path
from types import ModuleType
from typing import Any

from json_logic import jsonLogic

from wpg.drone import TacticStatus
from wpg.utils import AppException
from wpg.wildlife import Game

import logging
log = logging.getLogger("wpg")

class DroneAdaptMgr:
    def __init__(self, config):
        self.config = config
        self.current_strategy = None
        self.current_tactic_index = None  # the index of the current tactic in the strategy
        self.strategies = self.load_strategies(config)

    def load_strategies(self, config, module: ModuleType = __package__):
        """Load strategies from file."""
        strategies_file = config['adapt']['strategies']

        # load strategies file from the main_dir if it exists, otherwise from the packaged file
        strategies_path_local = Path(config['main_dir']).joinpath(strategies_file)

        # to handle both cases uniformly, create a context manager
        cm = (
            nullcontext(strategies_path_local)
            if strategies_path_local.exists()
            else resources.as_file(resources.files(module).joinpath(strategies_file))
        )

        strategies = None
        with cm as strategies_path:
            try:
                with strategies_path.open('rt') as f:
                    data = json.load(f)
                    strategies = data['strategies']
            except FileNotFoundError as e:
                raise AppException(f"Strategies file '{strategies_path}' not found.") from e
            except json.JSONDecodeError as e:
                raise AppException(f"Failed to load strategies file '{strategies_path}': {e}") from e
        return strategies

    def run(self, game: Game):
        while not game.finished():
            knowledge = game.get_knowledge()

            tactic_set = self.decide(knowledge)

            if self.current_strategy is not None:
                log_data = {
                    'strategy': self.current_strategy['name'],
                }
            else:
                log_data = {}

            game.step(tactic_set, log_data)

    def decide(self, knowledge: dict[Any, Any]) -> list[Any]:
        tactic_set = []

        # this is needed here so that strategies can execute back to back
        # and for the proper recording of strategies in the data
        tactic = self.do_strategy_ctrl_flow(TacticStatus[knowledge['actuation_state']])

        # select strategy
        # currently, the first one whose condition is satisfied
        for strategy in self.strategies:
            if jsonLogic(strategy['condition'], knowledge):
                if strategy is self.current_strategy:
                    break  # strategy is already running
                else:
                    if self.current_strategy is not None and not self.current_strategy.get("stoppable", True):
                        break  # the current strategy is not stoppable
                    self.start_strategy(strategy)
                    tactic_set.append(('*stop_all*', {}))  # stop all tactics

                    # The initial tactic status is not relevant for this next call
                    # since we're stopping all tactics, we pass IDLE as the status
                    tactic = self.do_strategy_ctrl_flow(TacticStatus.IDLE)
                    break

        if tactic is not None:
            tactic_set.append((tactic['tactic'], tactic['params']))
        return tactic_set

    def start_strategy(self, strategy):
        log.info(f"Strategy Triggered: {strategy['name']}")
        self.current_strategy = strategy
        self.current_tactic_index = -1

    def do_strategy_ctrl_flow(self, actuation_status: TacticStatus):
        if self.current_strategy is None:
            return None
        old_tactic_index = self.current_tactic_index
        if self.current_tactic_index >= 0:
            if actuation_status != TacticStatus.RUNNING:
                assert actuation_status != TacticStatus.IDLE, "Tactic should've completed or failed"
                if actuation_status == TacticStatus.SUCCESS:
                    self.current_tactic_index += 1
                elif actuation_status == TacticStatus.FAILURE:
                    log.info(
                        f"Strategy {self.current_strategy['name']} failed at tactic {self.current_strategy['action'][self.current_tactic_index]['tactic']}.")
                    self.current_strategy = None
                    self.current_tactic_index = None
                    return None
        else:
            self.current_tactic_index = 0

        if self.current_tactic_index >= len(self.current_strategy['action']):
            # no tactics left. Strategy complete
            self.current_strategy = None
            self.current_tactic_index = None
        elif self.current_tactic_index != old_tactic_index:
            return self.current_strategy['action'][self.current_tactic_index]

        return None
