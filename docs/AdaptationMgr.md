# Adding a Custom Adaptation Manager

WPG can also be used with a custom implementation of mission autonomy.
That is done by creating a Python package with a class that implements the
adaptation manager that implements mission autonomy.

Adding a new adaptation manager requires adding the class that implements it
and extending WPG's configuration so that it can be loaded.

## Adding the Adaptation Manager Class
First, create a new package for the adaptation manager.
- Create a new directory for the package under `src/adapt`, for example `src/adapt/myadaptmgr`
- Create an empty `__init__.py` in that directory 

Then, create a new file `myadaptmgr.py` in that directory.
This file will contain the implementation of the adaptation manager.

The skeleton of such a class is shown below.

```python
from typing import Any
from wpg.wildlife import Game

class MyAdaptMgr:
    def __init__(self, config):
        # optionally get custom configuration parameters
        self.my_param = config['adapt']['my_param']

    def run(self, game: Game):
        while not game.finished():
            knowledge = game.get_knowledge()
            tactic_set = self.decide(knowledge)
            # optionally add a column to the recorded simulation data
            log_data = { 'column_name': 0 }
            game.step(tactic_set, log_data)

    def decide(self, knowledge: dict[Any, Any]) -> list[Any]:
        # example to start the track_and_id tactic
        tactic_set = [ ('track_and_id', {'min_dist': 0}) ]
        return tactic_set
```

When run, the initializer `__init__` receives a dictionary with the configuration,
which the class can use to access existing or custom parameters.
After WPG is ready to start the simulation, the `run` method is invoked.
From this point on, the control is inverted, and instead of the game invoking
the adaptation manager in each time step, the adaptation manager lets the game
know when it can execute a simulation step.
This inversion of control allows for the implementation of a proxy class that
connects WPG to an adaptation manager running in a separate process and possibly
implemented in a different language, as it is supported by [DARTSim](https://github.com/cps-sei/dartsim).
Using this control flow, the simulation waits for the adaptation manager to
have done its job before proceeding.
The `run` method implements a simple loop.
It reads the knowledge and then uses it to decide what tactic to execute, if any.
The tactic set is passed to the game with its `step` method.
It is a set because it can include the special tactic `*stop_all*` in addition
to a new tactic to be started if the current executing tactic must be stopped.
The `step` method also allows passing additional data to be recorded with the
simulation data.

## Connecting the Adaptation Manager to WPG
To use the adaptation manager with WPG, a new configuration file
must be added to the `wpg/conf/adapt` directory.
This configuration file is a `yaml` file whose name is the name that
will be used to select the adaptation manager in the WPG configuration.
For example, if the file is named `myadaptmgr.yaml`, it can be selected
by adding `adapt=myadaptmgr` to the `wpg` command-line arguments.

The file must have the following content, adjusted appropriately to match the
package, module and class names of the adaptation manager:

```yaml
manager:
  _target_: adapt.myadaptmgr.myadaptmgr.MyAdaptMgr
```
If the adaptation manager has any configuration parameters, they can be added
to this file.
For example, suppose that the adaptation manager has a parameter `horizon`
that can be set to a value in the configuration file.
Then, the configuration file would look like this:

```yaml
manager:
  _target_: adapt.myadaptmgr.myadaptmgr.MyAdaptMgr

horizon: 5
```

That is the default value for the parameter, which can be overridden as needed.
For example, WPG could be invoked with the command `wpg adapt=myadaptmgr adapt.horizon=10`.

The configuration of WPG is implemented with [Hydra](https://hydra.cc/).
Refer to the [Hydra documentation](https://hydra.cc/docs/intro/) for more information if needed.

## Reference
The following tables list the state variables available in the knowledge dictionary
and the tactics provided by the task autonomy of the drone.

### State variables available in the knowledge dictionary

| **Key**               | **Value**                                     | **Description**                                                                          |
|:----------------------|:----------------------------------------------|:-----------------------------------------------------------------------------------------|
| `actuation_state`     | `IDLE` \| `RUNNING` \| `SUCCESS` \| `FAILURE` | Status of tactic execution.                                                              |
| `aoi_ingress_coords`  | `{'x': ?, 'y': ?}`                            | Coordinates where the drone enters the AoI.                                              |
| `can_navigate`        | `boolean`                                     | True if the drone is capable of moving and navigating.                                   |
| `continuous_id_done`  | `boolean`                                     | True if the consecutive identification requirement has been met.                         |
| `drone_coords`        | `{'x': ?, 'y': ?}`                            | Coordinates of the drone.                                                                |
| `drone_shot_down`     | `boolean`                                     | True if the drone has been shot down.                                                    |
| `flying_high`         | `boolean`                                     | True if the drone is currently flying at a high altitude.                                |
| `flying_low`          | `boolean`                                     | True if the drone is currently flying at a low altitude.                                 |
| `gps_available`       | `boolean`                                     | True if GPS signal is available (not jammed by the poacher).                             |
| `gun_fire`            | `boolean`                                     | True if gunfire from the poacher has been detected.                                      |
| `in_aoi`              | `boolean`                                     | True if the drone is currently inside the AoI.                                           |
| `left_base`           | `boolean`                                     | True if the drone has departed from the base.                                            |
| `poacher_coords`      | `{'x': ?, 'y': ?}` \| `None`                  | Coordinates of the poacher if visible, or None otherwise.                                |
| `poacher_identified`  | `boolean`                                     | True if the poacher identification requirement has been met.                             |
| `poacher_in_id_range` | `boolean`                                     | True if the poacher is in identification range.                                          |
| `poacher_visible`     | `boolean`                                     | True if the poacher is within the drone's line of sight/detection range.                 |
| `returned_to_base`    | `boolean`                                     | True if the drone has returned to base.                                                  |
| `rtb_threshold`       | `boolean`                                     | True if the drone has hit the battery/time limit threshold required to return to base.   |
| `total_id_count`      | `int`                                         | Total accumulated image/time steps counting toward the final identification requirement. |

### Tactics provided by the task autonomy of the drone

| **Name**           | **Parameter** | **Precondition**                            | **Success Postcondition**                           | **Description**                                                                                                                                                                                           |
|:-------------------|:--------------|:--------------------------------------------|:----------------------------------------------------|:----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `evade_poacher`    | `distance`    | `poacher_visible, can_navigate`             | `drone_location.dist( poacher_location) >=distance` | Move to the closest location that is at least `distance` away from the poacher                                                                                                                            |
| `fly_high`         |               |                                             | `flying_high`                                       | Climb, if needed, to fly high                                                                                                                                                                             |
| `fly_low`          |               |                                             | `flying_low`                                        | Descend, if needed, to fly low. If it is already moving to a location, it tries to find a location in its current path that is clear of trees to descend and recomputes a path avoiding trees from there. |
| `fly_low_asap`     |               |                                             | `flying_low`                                        | Descend, if needed, to fly low. If it is already moving to a location, it flies to the closest location clear of trees to descend, and recomputes a path avoiding trees from there.                       |
| `low_alt_track_id` | `min_dist`    | `poacher_visible, can_navigate, flying_low` | `poacher_identified`                                | Follow the poacher keeping a distance of at least `min_dist` and avoiding trees. Every time step the poacher is within identification range, an image counting towards the ID requirement is taken.       |
| `low_alt_search`   |               | `in_aoi, can_navigate, flying_low`          | `poacher_visible`                                   | Fly avoiding trees until it has covered the whole AoI with `drone.detection_range`.                                                                                                                       |
| `rtb`              |               | `can_navigate`                              | `at_base`                                           | Return to base.                                                                                                                                                                                           |
| `search_poacher`   |               | `in_aoi, can_navigate, flying_high`         | `poacher_visible`                                   | Fly a lawn mower pattern that covers the AoI according to `drone.detection_range`.                                                                                                                        |
| `track_and_id`     | `min_dist`    |                                             | `poacher_identified`                                | Follows the poacher keeping a distance of at least `min_dist`. Every time step the poacher is within identification range, an image counting towards the ID requirement is taken.                         |
| `transit_to_aoi`   |               | `can_navigate`                              | `in_aoi`                                            | Fly to the AoI ingress point if not already in the AoI.                                                                                                                                                   |

