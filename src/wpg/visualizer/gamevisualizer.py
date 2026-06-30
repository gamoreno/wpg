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

import os
from io import BytesIO

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import pygame
import pandas as pd
import sys
import importlib.resources

from wpg.game_map import CellType

from wpg.constants import (
    DRONE_DATA_CSV,
    GAME_DATA_CSV,
    MAP_DATA_CSV,
    POACHER_DATA_CSV,
    GAME_RESULT_CSV,
)

from pathlib import Path

from wpg.wildlife import GameResult

class GameVisualizer:
    def __init__(self, output_dir):
        pygame.init()

        # Window and panel dimensions
        self.GRID_WIDTH, self.GRID_HEIGHT = 800, 800
        self.PANEL_WIDTH = 300
        self.WIDTH = self.GRID_WIDTH + self.PANEL_WIDTH
        self.HEIGHT = self.GRID_HEIGHT

        # Side panel colors
        self.PANEL_BG = (40, 40, 45)
        self.PANEL_TEXT = (200, 200, 200)
        self.PANEL_HEADER = (180, 180, 80)
        self.PANEL_WHITE = (255, 255, 255)

        # Side panel layout settings
        self.PANEL_PAD_X = 14
        self.PANEL_PAD_Y = 14
        self.VALUE_RIGHT_X = self.PANEL_WIDTH - self.PANEL_PAD_X
        self.LINE_HEIGHT = 20
        self.SECTION_GAP = 18
        self.SECTION_HEIGHT = 22

        # Settings for autoplay mode
        self.playing = False
        self.last_step_time = 0
        self.step_delay = 250

        # Font for time step display
        self.time_font = pygame.font.SysFont(None, 22)

        # Generate application window
        self.screen = pygame.display.set_mode((self.WIDTH, self.HEIGHT))
        pygame.display.set_caption("Wildlife Protection Game Visualizer")

        # Fonts that are used for the current time step display
        self.small_font   = pygame.font.SysFont(None, 19)
        self.section_font = pygame.font.SysFont(None, 25)
        self.field_font   = pygame.font.SysFont(None, 19)

        # Load all of the simulation and map data
        self.df = pd.read_csv(output_dir.joinpath(GAME_DATA_CSV))
        self.drone_df = pd.read_csv(output_dir.joinpath(DRONE_DATA_CSV))
        self.poacher_df = pd.read_csv(output_dir.joinpath(POACHER_DATA_CSV))
        self.map_grid =pd.read_csv(output_dir.joinpath(MAP_DATA_CSV), header=None,).values
        self.results_df = pd.read_csv(output_dir.joinpath(GAME_RESULT_CSV))
        
        # Current simulation state 
        self.time_step = 0
        self.frame = 0

        # Dynamic Grid Calculations
        self.map_rows, self.map_cols = self.map_grid.shape
        self.cell_width = self.GRID_WIDTH / self.map_cols
        self.cell_height = self.GRID_HEIGHT / self.map_rows

        # fallback colors if sprite loading fails
        self.terrain_colors = {
            CellType.DESERT: (237, 201, 175),  # Desert
            CellType.SAVANNA: (154, 205, 50),  # Savanna
            CellType.TREES: (34, 139, 34)  # Trees
        }

        # --- NEW: Load and Scale Sprites ---
        # Calculate target size (75% of cell size) for characters
        target_size_x = int(self.cell_width * 0.75)
        target_size_y = int(self.cell_height * 0.75)

        # Calculate target size for full cell sprites (backgrounds and tree objects)
        full_cell_size_x = int(self.cell_width)
        full_cell_size_y = int(self.cell_height)

        poacher_scale = 0.5
        self.poacher_sprites = self.load_sprites('sprites/poacher.png', target_size_x * poacher_scale,
                                                 target_size_y * poacher_scale, 1)
        self.drone_sprites = self.load_sprites('sprites/drone.png', target_size_x, target_size_y, 2)
        drone_high_x = int(self.cell_width * 1.0)
        drone_high_y = int(self.cell_height * 1.0)
        self.drone_sprites_high = self.load_sprites('sprites/drone.png', drone_high_x, drone_high_y, 2)
        self.drone_sprites_low  = self.drone_sprites
        self.drone_explode_sprites = self.load_sprites('sprites/droneexplode.png', target_size_x, target_size_y, 1)

        # Load tree object sprite separately
        self.tree_object_sprite = self.load_sprites('sprites/trees.png', full_cell_size_x, full_cell_size_y, 1)

        savanna_sprites = self.load_sprites('sprites/savanna.png', full_cell_size_x, full_cell_size_y, 1)
        self.terrain_sprites = {
            CellType.DESERT: self.load_sprites('sprites/desert.png', full_cell_size_x, full_cell_size_y, 1),
            CellType.SAVANNA: savanna_sprites,
            # For tree cells (type 2), the background is savanna
            CellType.TREES: savanna_sprites,
            CellType.BASE: self.load_sprites('sprites/base.png', full_cell_size_x, full_cell_size_y, 1),
        }

        self._build_static_panel()
        self._update_panel_values()

    def load_sprites(self, sprite_file_path: str, target_size_x: int, target_size_y: int, num_sprites: int):
        sprites = []

        # Try to load the sprite sheet
        try:
            # Load the full sheet
            sprite_data = importlib.resources.files(__package__).joinpath(sprite_file_path).read_bytes()
            sprite_sheet = pygame.image.load(BytesIO(sprite_data)).convert_alpha()

            # Calculate the dimensions of a single sprite
            sheet_width = sprite_sheet.get_width()
            sheet_height = sprite_sheet.get_height()
            sprite_width = sheet_width // num_sprites  # Calculate sprite width based on num_sprites

            # Define the rectangles for the sprites
            for i in range(num_sprites):
                rect_sprite = pygame.Rect(i * sprite_width, 0, sprite_width, sheet_height)
                raw_sprite = sprite_sheet.subsurface(rect_sprite)
                # Scale the sprite and store it in the list
                sprites.append(pygame.transform.smoothscale(raw_sprite, (target_size_x, target_size_y)))
        except FileNotFoundError:
            print(f"Warning: '{sprite_file_path}' not found. Falling back to simple square.")
            sprites = None
        return sprites

    def _update_panel_values(self):
        # Grab the data from the output csv files 
        game_row = self.df.iloc[self.time_step]
        drone_row = self.drone_df.iloc[self.time_step]
        poacher_row = self.poacher_df.iloc[self.time_step]

        if self.time_step == len(self.df) - 1:
            result = str(self.results_df.iloc[0]["result"])
        else:
            result = ""

        gc = self._get_color
        W = self.PANEL_WHITE

        self._current_values = [
            (str(int(game_row["time"])), W),
            (str(int(drone_row["x"])), W),
            (str(int(drone_row["y"])), W),
            (str(drone_row["in_aoi"]), gc(drone_row["in_aoi"])),
            (str(drone_row["drone_shot_down"]), gc(not drone_row["drone_shot_down"])),
            (str(drone_row["poacher_visible"]), gc(drone_row["poacher_visible"])),
            (str(drone_row["poacher_in_id_range"]), gc(drone_row["poacher_in_id_range"])),
            (str(drone_row["poacher_identified"]), gc(drone_row["poacher_identified"])),
            (str(drone_row["flying_low"]), gc(drone_row["flying_low"])),
            (str(drone_row["gps_available"]), gc(drone_row["gps_available"])),
            (str(drone_row["can_navigate"]), gc(drone_row["can_navigate"])),
            (str(drone_row["tactic"]), W),
            (str(drone_row["strategy"]), W),
            (str(int(poacher_row["x"])), W),
            (str(int(poacher_row["y"])), W),
            (str(poacher_row["drone_detected"]), gc(poacher_row["drone_detected"])),
            (str(poacher_row["action"]), W),
            (result, W),
        ]

    def _build_static_panel(self):
        # Create the main side panel surface and fill with the background color
        self._static_panel = pygame.Surface((self.PANEL_WIDTH, self.HEIGHT))
        self._static_panel.fill(self.PANEL_BG)
        
        # Will store the positions of where things need to be drawn
        self._value_y_positions = []

        sections = [
            ("DRONE", [
                "X:", "Y:", "In Area of Interest:", "Shot Down:",
                "Poacher Visible:", "Poacher In ID Range:", "Poacher Identified:",
                "Flying Low:", "GPS Available:", "Can Navigate:", "Tactic:", "Strategy:"
            ]),
            ("POACHER", ["X:", "Y:", "Drone Detected:", "Action:"]),
        ]

        x = self.PANEL_PAD_X
        y = self.PANEL_PAD_Y

        pygame.draw.line(self._static_panel, (80, 80, 90), (0, 0), (0, self.HEIGHT), 2)

        # Draws a section header bar and returns its vertical position where the corresponding dynamic value should be rendered
        def draw_header(label, y_pos):
            rect = pygame.Rect(0, y_pos - 2, self.PANEL_WIDTH, self.SECTION_HEIGHT + 4)
            pygame.draw.rect(self._static_panel, (55, 55, 65), rect)
            surf = self.section_font.render(label, True, self.PANEL_HEADER)
            label_y = rect.centery - surf.get_height() // 2
            self._static_panel.blit(surf, (x, label_y))
            return label_y

        self._value_y_positions.append(draw_header("TIME STEP:", y))
        y += self.SECTION_HEIGHT + 12

        # Loop to draw the section headers as well as the field labels per section
        for section_name, labels in sections:
            y += self.SECTION_GAP
            draw_header(section_name, y)
            y += self.SECTION_HEIGHT + 8
            for label in labels:
                self._static_panel.blit(self.field_font.render(label, True, self.PANEL_TEXT), (x, y))
                self._value_y_positions.append(y)
                y += self.LINE_HEIGHT

        y += self.SECTION_GAP
        self._value_y_positions.append(draw_header("RESULT:", y))

        # Draw the control instructions for the side panel
        controls_y = self.HEIGHT - 175
        for text in (
            "Controls:",
            "[ENTER] Auto Play",
            "[SPACE] Stop Auto Play",
            "[D / RIGHT] Next Step",
            "[A / LEFT] Prev Step",
            "[R] Restart",
            "[ESC] Exit",
        ):
            self._static_panel.blit(
                self.small_font.render(text, True, (120, 120, 130)),
                (20, controls_y),
            )
            controls_y += 22

        # _static_panel is now frozen, never written to again
        self._current_values = []

    def draw_game_grid(self):
        for i in range(self.map_rows):
            for j in range(self.map_cols):
                cell_type = self.map_grid[i][j]
                x = j * self.cell_width
                y = i * self.cell_height

                # Determine the background sprite to draw
                background_sprites = self.terrain_sprites.get(cell_type)

                if background_sprites:
                    self.screen.blit(background_sprites[0], (x, y))
                else:
                    # Fallback to drawing a solid color if no sprite is found
                    color = self.terrain_colors.get(cell_type, (255, 255, 255))
                    pygame.draw.rect(self.screen, color, (x, y, self.cell_width, self.cell_height))

                # Draw grid lines
                pygame.draw.rect(self.screen, (100, 100, 100), (x, y, self.cell_width, self.cell_height), 1)

    def draw_poacher(self):
        poacher_x = int(self.df.loc[self.time_step, 'poacher.x'])
        poacher_y = int(self.df.loc[self.time_step, 'poacher.y'])
        sprite_index = self.frame % len(self.poacher_sprites) if self.poacher_sprites else 0
        self.draw_character(self.poacher_sprites, sprite_index, poacher_x, poacher_y, (255, 0, 0))

    def draw_drone(self):
        drone_x = int(self.df.loc[self.time_step, "drone.x"])
        drone_y = int(self.df.loc[self.time_step, "drone.y"])

        drone_row = self.drone_df.iloc[self.time_step]
        shot_down = bool(drone_row["drone_shot_down"])
        flying_low = bool(drone_row["flying_low"])

        show_crash = shot_down

        if self.time_step == len(self.df) - 1:
            game_result = str(self.results_df.iloc[0]["result"])
            if game_result == GameResult.DRONE_LOST.name:
                show_crash = True

        if show_crash and self.drone_explode_sprites:
            num_frames = len(self.drone_explode_sprites)
            sprite_index = min(self.frame % (num_frames * 2) // 2, num_frames - 1)
            sprites = self.drone_explode_sprites
        else:
            sprites = self.drone_sprites_low if flying_low else self.drone_sprites_high
            sprite_index = self.frame % len(sprites) if sprites else 0

        self.draw_character(sprites, sprite_index, drone_x, drone_y, (0, 0, 255))

    def draw_character(self, sprite_sheet, sprite_index, cell_x, cell_y, fallback_color):
        if sprite_sheet:
            sprite = sprite_sheet[sprite_index]
            offset_x = (self.cell_width - sprite.get_width()) / 2
            offset_y = (self.cell_height - sprite.get_height()) / 2

            sprite_x = cell_x * self.cell_width + offset_x
            sprite_y = cell_y * self.cell_height + offset_y
            self.screen.blit(sprite, (sprite_x, sprite_y))
        else:
            offset_x = self.cell_width * 0.125
            offset_y = self.cell_height * 0.125

            sprite_x = cell_x * self.cell_width + offset_x
            sprite_y = cell_y * self.cell_height + offset_y
            pygame.draw.rect(self.screen, fallback_color,
                             (sprite_x, sprite_y, self.cell_width * 0.75, self.cell_height * 0.75))

    def draw_tree_objects(self):
        if not self.tree_object_sprite:
            return
        sprite = self.tree_object_sprite[0]
        offset_x = (self.cell_width - sprite.get_width()) / 2
        offset_y = (self.cell_height - sprite.get_height()) / 2
        for i in range(self.map_rows):
            for j in range(self.map_cols):
                if self.map_grid[i][j] == CellType.TREES:
                    x = j * self.cell_width + offset_x
                    y = i * self.cell_height + offset_y
                    self.screen.blit(sprite, (x, y))

    def draw_side_panel(self):
        # Draw the pre-rendered static panel we generated
        panel_x = self.GRID_WIDTH
        self.screen.blit(self._static_panel, (panel_x, 0))

        # Draw the current values at their corresponding y-positions
        for i, ((value, color), y) in enumerate(
                zip(self._current_values, self._value_y_positions)):

            # Use a larger font exclusively for the time step value
            font = self.time_font if i == 0 or i == len(self._current_values) - 1 else self.field_font
            surf = font.render(value, True, color)

            # Right align all of the values within the panel
            value_x = (
                panel_x
                + self.VALUE_RIGHT_X
                - surf.get_width()
            )

            self.screen.blit(surf, (value_x, y))

    def _get_color(self, state):
        """Helper to color-code true/false text."""
        return (100, 255, 100) if state else (255, 100, 100)

    def handle_events(self):
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit()
                    sys.exit()

                elif event.key == pygame.K_RETURN:
                    self.playing = True

                elif event.key == pygame.K_SPACE:
                    self.playing = False

                elif event.key == pygame.K_RIGHT or event.key == pygame.K_d:
                    self.playing = False
                    if self.time_step < len(self.df) - 1:
                        self.time_step += 1
                        self._update_panel_values()

                elif event.key == pygame.K_LEFT or event.key == pygame.K_a:
                    self.playing = False
                    if self.time_step > 0:
                        self.time_step -= 1
                        self._update_panel_values()

                elif event.key == pygame.K_r:
                    self.playing = False
                    self.time_step = 0
                    self._update_panel_values()

        if self.playing:
            current_time = pygame.time.get_ticks()

            if current_time - self.last_step_time >= self.step_delay:
                self.last_step_time = current_time

                if self.time_step < len(self.df) - 1:
                    self.time_step += 1
                    self._update_panel_values()
                else:
                    self.playing = False   

    def run(self):
        clock = pygame.time.Clock()
        while True:
            self.handle_events()

            # Draw everything in the correct order
            self.draw_game_grid()  # 1. Draw backgrounds (savanna for tree cells)
            self.draw_poacher()  # 2. Draw poacher
            self.draw_tree_objects()  # 3. Draw tree objects on top
            self.draw_drone()  # 4. Draw drone (on top of trees)
            self.draw_side_panel()  # 5. Draw side panel

            pygame.display.flip()
            self.frame += 1
            clock.tick(10)  # Hz
