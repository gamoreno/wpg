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

import math
import os
from dataclasses import asdict, is_dataclass

import numpy as np
import py_trees


def round_away_from_zero(x):
    """
    Rounds a number away from zero to the nearest integer.
    """
    return int(math.copysign(math.ceil(abs(x)), x))


def cosine_sim(A, B):
    # dot(A, B) / (norm(A) * norm(B))
    return np.dot(A, B) / (np.linalg.norm(A) * np.linalg.norm(B))


class AppException(Exception):
    """Exception for errors that we want to catch and display to the user."""
    pass


def get_last_run_dir(outputs_dir):
    """
    Returns the path to the last run directory

    Assumes that outputs_dir has subdirectories named by date in YYYY-MM-DD format, and those have
    subdirectories named by time in HH-MM-SS format
    """
    dates = [d for d in os.listdir(outputs_dir) if os.path.isdir(os.path.join(outputs_dir, d))]
    dates.sort(reverse=True)
    latest_date = dates[0]

    times = [t for t in os.listdir(os.path.join(outputs_dir, latest_date)) if
             os.path.isdir(os.path.join(outputs_dir, latest_date, t))]
    times.sort(reverse=True)
    latest_time = times[0]

    last_run_dir = os.path.join(outputs_dir, latest_date, latest_time)

    return last_run_dir


def blackboard2dict(namespace: str):
    """
    Copy all the value/pairs in the py_trees blackboard that are either basic
    types or dataclasses to a dictionary
    """
    blackboard_dict = {}

    BASIC_TYPES = (int, float, str, bool, bytes, type(None))

    if not namespace.endswith('/'):
        namespace += '/'

    # Iterate over all registered keys on the central blackboard
    for key in py_trees.blackboard.Blackboard.keys():
        if not key.startswith(namespace):
            continue
        # remove the leading namespace from the key name
        new_key = key[len(namespace):]
        try:
            value = py_trees.blackboard.Blackboard.get(key)
            if isinstance(value, BASIC_TYPES):
                blackboard_dict[new_key] = value
            elif is_dataclass(value):
                blackboard_dict[new_key] = asdict(value)
        except KeyError:
            # The key is registered by a client, but no value has been written to it yet
            blackboard_dict[new_key] = None

    return blackboard_dict
