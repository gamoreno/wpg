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
import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Callable

import pyarrow as pa
import pyarrow.csv as csv

from wpg.constants import *
from wpg.utils import get_last_run_dir

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')
from wpg.wildlife import GameResult


def main() -> None:
    print('Exporting data...')
    parser = argparse.ArgumentParser(description='wpg-exp')
    parser.add_argument('data_dir', nargs='?', default='', help='Path to data directory')
    parser.add_argument(
        '--interleaved',
        action='store_true',
        help='Export interleaved rows (drone then poacher) to interleaved_data.csv',
    )
    parser.add_argument(
        '--print-summary',
        action='store_true',
        help='Print the result summary after exporting data',
    )
    parser.add_argument('--split', action='store_true', help='Keep data split into separate drone and poacher files')
    args = parser.parse_args()

    if args.split and args.interleaved:
        parser.error('Cannot use --split and --interleaved together')
        sys.exit(1)

    data_dir = args.data_dir

    if data_dir == '':
        data_dir = get_last_run_dir('multirun')

    try:
        results = concat_runs_results(data_dir, GAME_RESULT_CSV)
        summary = write_result_summary(results, data_dir, GAME_RESULT_SUMMARY_CSV)
        if args.interleaved:
            concat_runs(data_dir, INTERLEAVED_DATA_CSV, export_interleaved, run_alias='Episode')
        elif args.split:
            concat_runs(data_dir, CONCAT_DRONE_DATA_CSV, drone_only)
            concat_runs(data_dir, CONCAT_POACHER_DATA_CSV, poacher_only)
        else:
            concat_runs(data_dir, MERGED_DATA_CSV, join)
        if args.print_summary:
            print_result_summary(summary)
    except FileNotFoundError as e:
        print(f'Error: {e}')
        sys.exit(1)


def concat_runs(data_dir: str, output_file_name: str, join_func: Callable[[pa.Table, pa.Table], pa.Table],
                run_alias: str = None) -> None:
    base_dir = Path(data_dir)
    out_path = base_dir / output_file_name

    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f'Data directory not found: {base_dir}')

    if run_alias is None:
        run_alias = 'run'

    concat_tables: pa.Table | None = None
    for run_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
        drone_path = run_dir / DRONE_DATA_CSV
        poacher_path = run_dir / POACHER_DATA_CSV

        if not drone_path.exists() or not poacher_path.exists():
            continue

        drone_convert_options = csv.ConvertOptions(
            column_types={
                "poacher_action": pa.string(),
                "poacher.x": pa.float64(),
                "poacher.y": pa.float64()
            }
        )
        drone = csv.read_csv(drone_path, convert_options=drone_convert_options)

        poacher_convert_options = csv.ConvertOptions(
            column_types={"action": pa.string()}
        )
        poacher = csv.read_csv(poacher_path, convert_options=poacher_convert_options)

        drone = drone.rename_columns([
            'time' if col == 'time' else f'drone_{col}'
            for col in drone.column_names
        ])
        poacher = poacher.rename_columns([
            'time' if col == 'time' else f'poacher_{col}'
            for col in poacher.column_names
        ])

        merged = join_func(drone, poacher)
        run = pa.array([int(run_dir.name)] * merged.num_rows, type=pa.int32())
        merged = merged.add_column(0, run_alias, run)

        if concat_tables is None:
            concat_tables = merged
        else:
            concat_tables = pa.concat_tables([concat_tables, merged])

    if concat_tables is None:
        raise FileNotFoundError(
            f'No episode directories with both {DRONE_DATA_CSV} and {POACHER_DATA_CSV} found under {base_dir}'
        )
    assert concat_tables is not None
    csv.write_csv(concat_tables, out_path)
    print(f'Merged data saved to {out_path}')


def concat_runs_results(data_dir: str, output_file_name: str, run_alias: str = None) -> pa.Table:
    base_dir = Path(data_dir)
    out_path = base_dir / output_file_name

    if not base_dir.exists() or not base_dir.is_dir():
        raise FileNotFoundError(f'Data directory not found: {base_dir}')

    if run_alias is None:
        run_alias = 'run'

    concat_tables: pa.Table | None = None
    for run_dir in sorted(p for p in base_dir.iterdir() if p.is_dir()):
        results_path = run_dir / GAME_RESULT_CSV

        if not results_path.exists():
            continue

        results_convert_options = csv.ConvertOptions(
            column_types={"result": pa.string()}
        )
        results = csv.read_csv(results_path, convert_options=results_convert_options)

        run = pa.array([int(run_dir.name)] * results.num_rows, type=pa.int32())
        results = results.add_column(0, run_alias, run)

        if concat_tables is None:
            concat_tables = results
        else:
            concat_tables = pa.concat_tables([concat_tables, results])

    if concat_tables is None:
        raise FileNotFoundError(
            f'No episode directories with {GAME_RESULT_CSV} found under {base_dir}'
        )
    assert concat_tables is not None
    csv.write_csv(concat_tables, out_path)
    print(f'Merged result data saved to {out_path}')
    return concat_tables


def write_result_summary(results: pa.Table, data_dir: str, output_file_name: str) -> pa.Table:
    out_path = Path(data_dir) / output_file_name
    steps = results.column('steps').to_pylist()
    moes = results.column('moe').to_pylist()
    result_values = results.column('result').to_pylist()
    total_runs = len(result_values)

    result_counts = Counter(result_values)
    summary_data = {
        'total_runs': pa.array([total_runs], type=pa.int32()),
        'average_steps': pa.array([average(steps)], type=pa.float64()),
        'average_moe': pa.array([average(moes)], type=pa.float64()),
    }

    for result in GameResult:
        summary_data[result.name] = pa.array(
            [result_counts[result.name]],
            type=pa.int32(),
        )

    summary = pa.table(summary_data)
    csv.write_csv(summary, out_path)
    print(f'Result summary saved to {out_path}')
    return summary


def print_result_summary(summary: pa.Table) -> None:
    print('Result summary:')
    print(summary.to_pandas().to_string(index=False))


def average(values: list[int | float | None]) -> float | None:
    numeric_values = [value for value in values if value is not None]
    if len(numeric_values) == 0:
        return None
    return sum(numeric_values) / len(numeric_values)


def join(drone: pa.Table, poacher: pa.Table) -> pa.Table:
    merged = drone.join(poacher, keys='time', join_type='full outer')

    # compute distance between drone and poacher
    drone_x = merged.column('drone_x').to_pylist()
    drone_y = merged.column('drone_y').to_pylist()
    poacher_x = merged.column('drone_poacher.x').to_pylist()
    poacher_y = merged.column('drone_poacher.y').to_pylist()

    distances: list[float | None] = []
    for i in range(merged.num_rows):
        if None in (drone_x[i], drone_y[i], poacher_x[i], poacher_y[i]):
            distances.append(None)
            continue
        distances.append(math.dist((drone_x[i], drone_y[i]), (poacher_x[i], poacher_y[i])))
    merged = merged.append_column('drone_poacher.dist', pa.array(distances, type=pa.float64()))

    return merged


def drone_only(drone: pa.Table, poacher: pa.Table) -> pa.Table:
    merged = join(drone, poacher)

    # remove all the columns that start with 'poacher_'
    merged = merged.drop([col for col in merged.column_names if col.startswith('poacher_')])
    return merged


def poacher_only(drone: pa.Table, poacher: pa.Table) -> pa.Table:
    return poacher


def export_interleaved(drone: pa.Table, poacher: pa.Table) -> pa.Table:
    merged = drone.join(poacher, keys='time', join_type='full outer')

    merged_times = merged.column('time').to_pylist()
    drone_x = merged.column('drone_x').to_pylist()
    drone_y = merged.column('drone_y').to_pylist()
    poacher_x = merged.column('poacher_x').to_pylist()
    poacher_y = merged.column('poacher_y').to_pylist()
    drone_tactic = merged.column('drone_tactic').to_pylist()
    drone_poacher_action = merged.column('drone_poacher_action').to_pylist()

    times: list[int] = []
    players: list[str] = []
    locations: list[float | None] = []
    actions: list[str] = []

    for i, time_value in enumerate(merged_times):
        location = None
        if None not in (drone_x[i], drone_y[i], poacher_x[i], poacher_y[i]):
            location = math.dist((drone_x[i], drone_y[i]), (poacher_x[i], poacher_y[i]))

        drone_action = drone_tactic[i] if drone_tactic[i] is not None else ''

        times.append(time_value)
        players.append('A')
        locations.append(location)
        actions.append(drone_action)

        poacher_action = drone_poacher_action[i] if drone_poacher_action[i] is not None else ''
        times.append(time_value)
        players.append('B')
        locations.append(location)
        actions.append(poacher_action)

    interleaved = pa.table({
        'Time': pa.array(times),
        'Player': pa.array(players, type=pa.string()),
        'Location': pa.array(locations, type=pa.float64()),
        'Action': pa.array(actions, type=pa.string()),
    })
    return interleaved
