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

import logging
import sys

import hydra
import numpy as np
from hydra.core.hydra_config import HydraConfig
from hydra.errors import InstantiationException
from hydra.types import RunMode
from omegaconf import DictConfig, OmegaConf

from wpg.rng import init_rng_manager
from wpg.utils import AppException
from wpg.wildlife import Game


@hydra.main(version_base=None, config_path="conf", config_name="config")
def main(cfg: DictConfig) -> None:
    hydra_cfg = HydraConfig.get()
    log = logging.getLogger(__package__)

    # is it in multirun mode?
    multirun = hydra_cfg.mode == RunMode.MULTIRUN

    # handle random seed
    if cfg.sim.seed is None:
        base_seed = np.random.default_rng().integers(0, 1_000_000_000)
    else:
        base_seed = cfg.sim.seed

    if multirun:
        seed = base_seed + cfg.run * 1000
        log.info(f"seed: {base_seed}, run_seed: {seed}")
    else:
        seed = base_seed
        log.info(f"seed: {seed}")

    # Convert Hydra's special DictConfig into a normal Python dict
    config = OmegaConf.to_container(cfg, resolve=True)

    config['main_dir'] = get_main_dir()
    output_dir = hydra_cfg.runtime.output_dir
    game = None

    try:
        moe_calculator = hydra.utils.instantiate(cfg.moe.calculator)

        # Create a game instance
        init_rng_manager(seed)
        game = Game(config, moe_calculator)

        adapt_mgr = hydra.utils.instantiate(cfg.adapt.manager, config)

        adapt_mgr.run(game)

        log.info(f"Game ended with {game.get_result().name}")
        game.save_data(output_dir)

        if not multirun:
            game.visualize(output_dir)
    except AppException as ex:
        log.error(f"{ex}")
        if game is not None:
            game.save_result(output_dir)
        logging.shutdown()
        sys.exit(1)
    except InstantiationException as ex:
        if isinstance(ex.__cause__, AppException):
            log.error(f"{ex.__cause__}")
            logging.shutdown()
            sys.exit(1)


def get_main_dir():
    hydra_cfg = HydraConfig.get()

    main_dir = next((source.path for source in hydra_cfg.runtime.config_sources if source.provider == 'command-line'),
                    None)
    if main_dir is None:
        main_dir = next((source.path for source in hydra_cfg.runtime.config_sources if
                         source.provider.startswith('hydra.searchpath')), None)
    if main_dir is None:
        main_dir = '.'

    return main_dir


if __name__ == "__main__":
    main()
