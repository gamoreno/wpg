# WPG Configuration
The configuration of WPG is implemented using [Hydra](https://hydra.cc/).
The following sections describe the available configuration options,
how to run simulations in parallel, and how to configure the logger.

## Configuration Options

 Below are the available configuration options, organized by their respective groups in the YAML file.
See the [default configuration file](../src/wpg/conf/config.yaml).

### Simulation (`sim`)

Configuration related to the core simulation loop and environment.

| **Parameter** | **Default** | **Description**                                          |
|:--------------|:------------|:---------------------------------------------------------|
| `timeout`     | `100`       | Number of steps the drone can fly (a.k.a. battery life). |
| `seed`        | `null`      | Seed for random number generation.                       |

---

### Map (`map`)

Configuration for the simulation grid and physical environment.

| **Parameter**       | **Default** | **Description**                                                                                                                                                                     |
|:--------------------|:------------|:------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `width`             | `20`        | Width of the map in cells.                                                                                                                                                          |
| `height`            | `20`        | Height of the map in cells.                                                                                                                                                         |
| `poacher_area_size` | `12`        | Length of the side of the square poacher area in cells.                                                                                                                             |
| `tree_density`      | `0.25`      | Tree density (e.g., 0.25 means 25% of the map has trees). Note that this density may be adjusted when the map is generated to avoid isolated areas completely blocked off by trees. |

---

### Drone (`drone`)

Configuration for the drone's sensors and identification capabilities.

| **Parameter**         | **Default** | **Description**                                                                                                                                                                                         |
|:----------------------|:------------|:--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `detection_range`     | `5`         | Range within which the drone can detect the poacher with a clear line of sight (LOS). When the drone is flying high, LOS is always clear. When flying low, it can be blocked by trees.                  |
| `id_range`            | `3`         | Range within which the drone can take images of the poacher for identification.                                                                                                                         |
| `continuous_id_count` | `4`         | The number of continuous ID images (one per step) required for identification.                                                                                                                          |
| `total_id_count`      | `8`         | The total number of ID images (one per step) required for identification.                                                                                                                               |
| `poacher_hide_sensor` | `false`     | Whether the drone can detect when the poacher is hiding as an action. This is based only on what the drone can infer. For example, it does not detect when the poacher is going towards a tree to hide. |

---

### Poacher (`poacher`)

Configuration for the adversary's behavior, detection, and combat abilities.

| **Parameter**            | **Default** | **Description**                                                                                                                                                                                                        |
|:-------------------------|:------------|:-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| `behavior`               | `1`         | Behavior of the poacher (see reference table in the broader documentation).                                                                                                                                            |
| `detection_range`        | `2`         | Range within which the poacher can detect the drone with a clear line of sight (LOS). When the drone is flying high, LOS is always clear. When flying low, it can be blocked by trees.                                 |
| `detection_probability`  | `1.0`       | Probability that the poacher can detect the drone within the detection conditions above.                                                                                                                               |
| `hide_tree_max_distance` | `2`         | For behaviors that have other adversarial actions in addition to hiding, this is the maximum distance that the poacher will move to hide. If no tree is within this distance, the poacher will use a different action. |
| `gun_range`              | `1`         | Range for the poacher's gun.                                                                                                                                                                                           |
| `gun_accuracy`           | `0.7`       | Probability that the poacher can hit the drone with the gun.                                                                                                                                                           |
| `gps_denial_probability` | `1.0`       | For behaviors with GPS denial, the probability that the poacher will jam the GPS signal. If GPS is denied, it is denied for the entire simulation.                                                                     |


## Running Multiple Simulations in Parallel
To run multiple simulations in parallel, the Hydra Joblib Launcher plugin is used.

To install it:
```shell
python -m pip install hydra-joblib-launcher --upgrade                                                                         
```

To run multiple simulations in parallel, use these options: `--multirun hydra/launcher=joblib`.
For example:
```shell
wpg --multirun hydra/launcher=joblib run="range(100)" sim.seed=1234567 poacher.behavior=2 adapt.strategies=strategies-v2.1.json
```

## Configuring the Logger
To change the default log level to DEBUG, use this option: `hydra.verbose=true`.

To disable logging, use this option: `hydra/job_logging=disabled`.

