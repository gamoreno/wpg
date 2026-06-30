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

from typing import Optional

import numpy as np
import pandas as pd

from wpg.gentypes import Coordinates
from wpg.rng import get_rng_manager


class CellType:
    """Cell types in the game map."""
    DESERT = 0
    SAVANNA = 1
    TREES = 2
    BASE = 3


class GameMap:
    """Game map class."""

    def __init__(self, width: int, height: int, poacher_area_size: int, config: dict) -> None:
        """
        Initialize a new game map.

        Args:
            width (int): The width of the game map.
            height (int): The height of the game map.
            poacher_area_size (int): The size of the side of square poacher area.
            config (dict): Configuration dictionary.
        """
        rng = get_rng_manager().np_rng("wildlife/map")
        self.width = width
        self.height = height
        # Initialize the whole map as Desert (0)
        self.grid = np.full((height, width), CellType.DESERT)

        # Populate the poacher area
        tree_density = config['tree_density']
        self.poacher_area_rect = [Coordinates(self.width - poacher_area_size, 0),
                                  Coordinates(self.width - 1, poacher_area_size - 1)]
        for x in range(self.poacher_area_rect[0].x, self.poacher_area_rect[1].x + 1):
            for y in range(self.poacher_area_rect[0].y, self.poacher_area_rect[1].y + 1):
                # Randomly assign savanna or savanna with trees
                self.grid[y][x] = rng.choice([CellType.SAVANNA, CellType.TREES], p=[1.0 - tree_density, tree_density])

        self.base_coords = Coordinates(0, height - 1)
        self.grid[self.base_coords.y][self.base_coords.x] = CellType.BASE

        # generate a random poacher coords in the right half of its area
        # so that it's not too close to the ingress point
        poacher_min_x = self.poacher_area_rect[0].x + (self.poacher_area_rect[1].x - self.poacher_area_rect[0].x) // 2
        self.initial_poacher_coords = Coordinates(
            rng.integers(poacher_min_x, self.poacher_area_rect[1].x + 1),
            rng.integers(self.poacher_area_rect[0].y, self.poacher_area_rect[1].y + 1))
        self.grid[self.initial_poacher_coords.y][self.initial_poacher_coords.x] = CellType.SAVANNA

        self.connect_savanna()

    @classmethod
    def load_map(cls, map_file: str, poacher_area_size: int) -> "GameMap":
        """
        Load a game map from a file saved by save_map.

        Args:
            map_file (str): The file path to load the map from.
            poacher_area_size (int): The size of the side of square poacher area.

        Returns:
            GameMap: A game map initialized from the saved map data.
        """
        grid = pd.read_csv(map_file, header=None).to_numpy(dtype=int)
        height, width = grid.shape

        game_map = cls.__new__(cls)
        game_map.width = width
        game_map.height = height
        game_map.grid = grid
        game_map.poacher_area_rect = [
            Coordinates(width - poacher_area_size, 0),
            Coordinates(width - 1, poacher_area_size - 1),
        ]
        game_map.base_coords = Coordinates(0, height - 1)

        return game_map

    def get_base_coords(self) -> Coordinates:
        return self.base_coords

    def is_valid_position(self, coordinates: Coordinates) -> bool:
        """
        Check if a position is valid.

        Args:
            coordinates (Coordinates): The coordinates of the position.

        Returns:
            bool: True if the position is valid, False otherwise.
        """
        return 0 <= coordinates.x < self.width and 0 <= coordinates.y < self.height

    def is_poacher_area(self, coordinates: Coordinates) -> bool:
        """
        Check if a position is in the poacher area.

        Args:
            coordinates (Coordinates): The coordinates of the position.

        Returns:
            bool: True if the position is in the poacher area, False otherwise.
        """
        # Now based entirely on cell type, not coordinates!
        if not self.is_valid_position(coordinates):
            return False
        return self.grid[coordinates.y][coordinates.x] in [CellType.SAVANNA, CellType.TREES]

    def is_kind(self, coordinates: Coordinates, cell_type: CellType) -> bool:
        return self.grid[coordinates.y][coordinates.x] == cell_type

    def is_base(self, coordinates: Coordinates) -> bool:
        return self.is_kind(coordinates, CellType.BASE)

    def is_tree(self, coordinates: Coordinates) -> bool:
        """
        Check if there's a tree in a position.

        Args:
            coordinates (Coordinates): The coordinates of the position.

        Returns:
            bool: True if there's a tree in the position, False otherwise.
        """
        return self.is_kind(coordinates, CellType.TREES)

    def find_closest(self, location: Coordinates, cell_type: CellType, only_poacher_area: bool = False,
                     invert: bool = False, min_dist=0) -> Optional[Coordinates]:
        if self.is_kind(location, cell_type) != invert and min_dist < 1:
            return location

        if only_poacher_area:
            in_area = lambda coord: self.is_poacher_area(coord)
        else:
            in_area = lambda coord: self.is_valid_position(coord)

        radius = 1
        hit_valid_area = True
        while hit_valid_area:
            hit_valid_area = False

            # Iterate over the perimeter of a square centered at the location,
            # searching the horizontal borders first.
            for y in [location.y - radius, location.y + radius]:
                for x in range(location.x - radius, location.x + radius + 1):
                    coord = Coordinates(x, y)
                    if in_area(coord):
                        hit_valid_area = True
                        if self.is_kind(coord, cell_type) != invert and coord.distance(location) >= min_dist:
                            return coord

            # Search the vertical borders.
            for x in [location.x - radius, location.x + radius]:
                for y in range(location.y - radius, location.y + radius + 1):
                    coord = Coordinates(x, y)
                    if in_area(coord):
                        hit_valid_area = True
                        if self.is_kind(coord, cell_type) != invert and coord.distance(location) >= min_dist:
                            return coord

            radius += 1

        return None

    def find_closest_at_least_distance_from(
            self,
            location: Coordinates,
            cell_type: CellType,
            min_distance_from: Coordinates,
            min_dist: float,
            only_poacher_area: bool = False,
            invert: bool = False
    ) -> Optional[Coordinates]:
        """
        Find the closest matching cell to location that is at least min_dist
        away from min_distance_from.
        """
        if only_poacher_area:
            in_area = lambda coord: self.is_poacher_area(coord)
        else:
            in_area = lambda coord: self.is_valid_position(coord)

        candidates = []
        for y in range(self.height):
            for x in range(self.width):
                coord = Coordinates(x, y)
                if not in_area(coord):
                    continue
                if self.is_kind(coord, cell_type) == invert:
                    continue
                if coord.distance(min_distance_from) < min_dist:
                    continue
                candidates.append(coord)

        if len(candidates) == 0:
            return None

        return min(candidates, key=lambda coord: (coord.distance(location), coord.y, coord.x))

    def cells_in_line(self, start: Coordinates, end: Coordinates) -> list[Coordinates]:
        """
        Return every map cell touched by the line segment between cell centers.

        Cells are treated as open unit squares. This means a line that only
        touches a cell edge or corner is not considered to touch that cell.
        """
        if not self.is_valid_position(start) or not self.is_valid_position(end):
            return []

        start_x = start.x + 0.5
        start_y = start.y + 0.5
        end_x = end.x + 0.5
        end_y = end.y + 0.5

        cells = []
        for y in range(min(start.y, end.y), max(start.y, end.y) + 1):
            for x in range(min(start.x, end.x), max(start.x, end.x) + 1):
                coord = Coordinates(x, y)
                if self._segment_intersects_cell(start_x, start_y, end_x, end_y, coord):
                    cells.append(coord)

        return sorted(cells, key=lambda coord: (coord.x - start.x) ** 2 + (coord.y - start.y) ** 2)

    def has_clear_line_of_sight(self, start: Coordinates, end: Coordinates) -> bool:
        """
        Determine whether trees block line of sight between two map coordinates.

        The line of sight is interrupted if the center-to-center line segment
        intersects any tree cell, including the start or end cell.
        """
        if not self.is_valid_position(start) or not self.is_valid_position(end):
            return False

        return not any(self.is_tree(coord) for coord in self.cells_in_line(start, end))

    @staticmethod
    def _segment_intersects_cell(
            start_x: float,
            start_y: float,
            end_x: float,
            end_y: float,
            cell: Coordinates,
    ) -> bool:
        # Liang-Barsky line clipping algorithm https://en.wikipedia.org/wiki/Liang-Barsky_algorithm
        dx = end_x - start_x
        dy = end_y - start_y
        t_min = 0.0
        t_max = 1.0

        for p, q in (
                (-dx, start_x - cell.x),
                (dx, cell.x + 1 - start_x),
                (-dy, start_y - cell.y),
                (dy, cell.y + 1 - start_y),
        ):
            if p == 0:
                if q < 0:
                    return False
                continue

            t = q / p
            if p < 0:
                if t > t_max:
                    return False
                t_min = max(t_min, t)
            else:
                if t < t_min:
                    return False
                t_max = min(t_max, t)

        if t_max - t_min < 0.0000001:  # it only touches a corner
            return False

        return True

    def get_cells_in_fov(self, center: Coordinates, fov_range: int) -> set[Coordinates]:
        cells_in_fov = set()
        for x in range(center.x - fov_range, center.x + fov_range + 1):
            for y in range(center.y - fov_range, center.y + fov_range + 1):
                candidate = Coordinates(x, y)
                if not self.is_valid_position(candidate):
                    continue
                if center.distance(candidate) > fov_range:
                    continue
                if self.has_clear_line_of_sight(center, candidate):
                    cells_in_fov.add(Coordinates(x, y))
        return cells_in_fov

    def get_neighboring_cells(self, center: Coordinates) -> list[Coordinates]:
        # return neighboring cells not including the cell itself and only including cells in the map
        neighboring = []
        for x in range(center.x - 1, center.x + 2):
            for y in range(center.y - 1, center.y + 2):
                candidate = Coordinates(x, y)
                if candidate == center or not self.is_valid_position(candidate):
                    continue
                neighboring.append(candidate)
        return neighboring

    def savanna_components(self) -> list[list[tuple[int, int]]]:
        """  
        Find all disconnected savanna components in the poacher area.

        For each unvisited savanna cell, runs an iterative DFS using a stack to collect all reachable connected savanna
        cells into a component. Two cells are connected if they touch on a side or corner (8-directional connectivity). 
        """
        x0 = self.poacher_area_rect[0].x
        y0 = self.poacher_area_rect[0].y
        x1 = self.poacher_area_rect[1].x
        y1 = self.poacher_area_rect[1].y

        visited = set()
        components = []

        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                if (self.grid[y][x] == CellType.SAVANNA and (x, y) not in visited):
                    component = []
                    stack = [(x, y)]

                    while stack:
                        cx, cy = stack.pop()
                        if (cx, cy) in visited:
                            continue
                        visited.add((cx, cy))
                        component.append((cx, cy))

                        for neighbor in self.get_neighboring_cells(Coordinates(cx, cy)):
                            nx = neighbor.x
                            ny = neighbor.y

                            if (self.grid[ny][nx] == CellType.SAVANNA and (nx, ny) not in visited):
                                stack.append((nx, ny))
                    components.append(component)

        return components

    def connect_savanna(self) -> None:
        """
        connect_savanna combines all savanna cells in the poacher area form a single connected component.

        The function merges all smaller savanna components into the largest one until only one remains.
        
        For each smaller component, it will find the closest cell pair by Chebyshev distance.
        
        Then it will walk a straight diagonal path between them, converting any trees along the way to savanna.
        """
        while True:
            components = self.savanna_components()

            if len(components) <= 1:
                return

            components.sort(key=len, reverse=True)

            main_component = components[0]

            for component in components[1:]:
                closest_pair = None
                closest_distance = None

                for mx, my in main_component:
                    for ox, oy in component:
                        distance = max(abs(mx - ox), abs(my - oy))

                        if (closest_distance is None or distance < closest_distance):
                            closest_distance = distance
                            closest_pair = ((mx, my), (ox, oy))
                (mx, my), (ox, oy) = closest_pair

                x = ox
                y = oy

                while (x, y) != (mx, my):
                    if x < mx:
                        x += 1
                    elif x > mx:
                        x -= 1

                    if y < my:
                        y += 1
                    elif y > my:
                        y -= 1

                    self.grid[y][x] = CellType.SAVANNA

    def save_map(self, output_path: str) -> None:
        """
        Save the game map to a file.

        Args:
            output_path (str): The file path to save the map to.
        """
        # Save the map layout so the visualizer can render it
        df = pd.DataFrame(self.grid)
        df.to_csv(output_path, index=False, header=False)

    def get_poacher_initial_position(self) -> Coordinates:
        return self.initial_poacher_coords
