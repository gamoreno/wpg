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

import argparse
from pathlib import Path

from wpg.utils import get_last_run_dir
from wpg.visualizer.gamevisualizer import GameVisualizer


def main():
    parser = argparse.ArgumentParser(description='wpg-viz')
    parser.add_argument('data_dir', nargs='?', default='', help='Path to data directory')
    args = parser.parse_args()

    data_dir = args.data_dir

    if data_dir == '':
        data_dir = get_last_run_dir('outputs')
    visualizer = GameVisualizer(Path(data_dir))
    visualizer.run()
