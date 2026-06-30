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

import hashlib

import numpy as np


# import random


class RNGManager:
    """Create deterministic RNG streams derived from one root seed."""

    def __init__(self, root_seed: int):
        self.root_seed = int(root_seed)
        self._np_cache: dict[str, np.random.Generator] = {}
        # self._py_cache: dict[str, random.Random] = {}

    def _seed_for(self, key: str) -> int:
        digest = hashlib.blake2b(f"{self.root_seed}:{key}".encode("utf-8"), digest_size=16).digest()
        return int.from_bytes(digest, "little")

    def np_rng(self, key: str) -> np.random.Generator:
        if key not in self._np_cache:
            self._np_cache[key] = np.random.default_rng(self._seed_for(key))
        return self._np_cache[key]

    # def py_rng(self, key: str) -> random.Random:
    #     if key not in self._py_cache:
    #         self._py_cache[key] = random.Random(self._seed_for(key))
    #     return self._py_cache[key]


_RNG_MANAGER: RNGManager | None = None


def init_rng_manager(root_seed: int) -> RNGManager:
    """Initialize the global RNG manager for this run."""
    global _RNG_MANAGER
    _RNG_MANAGER = RNGManager(root_seed)
    return _RNG_MANAGER


def get_rng_manager() -> RNGManager:
    if _RNG_MANAGER is None:
        raise RuntimeError("RNG manager is not initialized. Call init_rng_manager() first.")
    return _RNG_MANAGER
