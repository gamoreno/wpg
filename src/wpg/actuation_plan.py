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

from dataclasses import dataclass, field
from typing import List, Any
import logging
log = logging.getLogger(__package__)

@dataclass
class Action:
    name: str
    params: List[Any] = field(default_factory=list)


class ActuationPlan:
    """
    Represents a list of actions that can be executed on a target system.

    This class provides methods to add actions to the plan, check if a specific action is in the plan,
    and execute the plan on a given target system.

    The target system class must have methods that match the name and parameters of the actions
    passed. These methods carry out the actual operations when called with the provided parameters.
    However, they don't need to complete in a single invocation (e.g., moving to a target position one
    cell at a time). The method must return True when the action completes; False, otherwise. 
    """

    def __init__(self, name: str = "Unnamed Plan"):
        self.name = name
        self.actions = []

    def add_action(self, action: Action):

        # if an action (ignoring params) is already in the plan, remove it first
        self.actions[:] = [a for a in self.actions if a.name != action.name]
        log.debug(f"Adding action {action.name}({action.params}) to {self.name} plan.")
        # Add the new action to the list
        self.actions.append(action)

    def has_action(self, action: Action):
        return action in self.actions

    def execute_plan_on(self, target_sys):

        # execute each action and remove it from the list once completed (returns True)
        self.actions[:] = [
            action for action in self.actions
            if not self.execute_action(action.name, action.params, target_sys)
        ]

    def execute_action(self, name: str, params: list, target_sys: object):
        # 1. Look for a method on target_sys that matches the string 'name'
        method = getattr(target_sys, name, None)

        if callable(method):
            # 3. Call the method, unpacking the list into separate arguments
            done = method(*params)
            return done
        else:
            log.error(f"Unknown action: '{name}'. Ignoring.")
            return True
