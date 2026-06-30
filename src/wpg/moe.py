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

from wpg.utils import AppException
from wpg.wildlife import GameResult


class WeightedMoeCalculator:
    """Calculate a weighted measure of effectiveness from Hydra configuration."""

    def __init__(self, results):
        self.results = {}
        for result_name, result_config in results.items():
            self.results[result_name] = self._parse_result_config(result_name, result_config)

        self._validate_bounds()

    def calculate(self, game) -> float:
        if game.timeout <= 0 or game.get_result() == GameResult.UNKNOWN:
            return 0.0

        result_name = game.get_result().name
        if result_name not in self.results:
            raise AppException(f"MOE configuration does not define result '{result_name}'.")

        result_config = self.results[result_name]
        lower_bound, upper_bound = result_config["bounds"]
        weighted_sum = sum(
            weight * self._component_value(component, game)
            for component, weight in result_config["weights"].items()
        )

        return lower_bound + (upper_bound - lower_bound) * weighted_sum

    def _parse_result_config(self, result_name, result_config):
        bounds = result_config.get("range", None)
        if bounds is None or len(bounds) != 2:
            raise AppException(f"MOE result '{result_name}' must define a range [lower-bound, upper-bound].")

        lower_bound = float(bounds[0])
        upper_bound = float(bounds[1])
        if lower_bound > upper_bound:
            raise AppException(
                f"MOE result '{result_name}' has invalid range [{lower_bound}, {upper_bound}]."
            )

        weights = dict(result_config.get("weights", {}))
        if not weights:
            raise AppException(f"MOE result '{result_name}' must define at least one weight.")

        unknown_components = sorted(set(weights) - set(self._components()))
        if unknown_components:
            raise AppException(
                f"MOE result '{result_name}' has unknown component(s): {', '.join(unknown_components)}."
            )

        negative_components = [
            component for component, weight in weights.items()
            if float(weight) < 0.0
        ]
        if negative_components:
            raise AppException(
                f"MOE result '{result_name}' has negative weight(s): {', '.join(negative_components)}."
            )

        total_weight = sum(float(weight) for weight in weights.values())
        if total_weight <= 0.0:
            raise AppException(f"MOE result '{result_name}' weights must sum to a positive value.")

        normalized_weights = {
            component: float(weight) / total_weight
            for component, weight in weights.items()
        }

        return {
            "bounds": (lower_bound, upper_bound),
            "weights": normalized_weights,
        }

    def _validate_bounds(self) -> None:
        intervals = [
            (result_name, result_config["bounds"][0], result_config["bounds"][1])
            for result_name, result_config in self.results.items()
        ]

        for index, (left_name, left_lower, left_upper) in enumerate(intervals):
            for right_name, right_lower, right_upper in intervals[index + 1:]:
                if max(left_lower, right_lower) <= min(left_upper, right_upper):
                    raise AppException(
                        "MOE result ranges overlap: "
                        f"{left_name} [{left_lower}, {left_upper}] and "
                        f"{right_name} [{right_lower}, {right_upper}]."
                    )

    def _component_value(self, component: str, game) -> float:
        return self._components()[component](game)

    def _components(self):
        return {
            "mission_duration": self._mission_duration,
            "poacher_tracking_time": self._poacher_tracking_time,
            "poacher_imaging_time": self._poacher_imaging_time,
            "poacher_identified": self._poacher_identified,
            "drone_shot_down": self._drone_shot_down,
            "drone_visible_time": self._drone_visible_time,
            "drone_in_gun_range_time": self._drone_in_gun_range_time,
        }

    def _clamp(self, value: float) -> float:
        return min(max(value, 0.0), 1.0)

    def _higher_is_better(self, value, timeout) -> float:
        return self._clamp(value / timeout)

    def _lower_is_better(self, value, timeout) -> float:
        return 1.0 - self._higher_is_better(value, timeout)

    def _mission_duration(self, game) -> float:
        return self._lower_is_better(game.time_step, game.timeout)

    def _poacher_tracking_time(self, game) -> float:
        return self._higher_is_better(
            game.drone.get_measurements().poacher_tracking_time,
            game.timeout,
        )

    def _poacher_imaging_time(self, game) -> float:
        return self._higher_is_better(
            game.drone.get_measurements().poacher_imaging_time,
            game.timeout,
        )

    def _poacher_identified(self, game) -> float:
        return 1.0 if game.drone.get_measurements().poacher_identified else 0.0

    def _drone_shot_down(self, game) -> float:
        return 0.0 if game.drone.get_measurements().drone_shot_down else 1.0

    def _drone_visible_time(self, game) -> float:
        return self._lower_is_better(
            game.poacher.get_measurements().drone_visible_time,
            game.timeout,
        )

    def _drone_in_gun_range_time(self, game) -> float:
        return self._lower_is_better(
            game.poacher.get_measurements().drone_in_gun_range_time,
            game.timeout,
        )
