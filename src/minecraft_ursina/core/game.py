from pathlib import Path
import math
import random
import shutil

from minecraft_ursina.core.settings import (
    BGM_FILE,
    BGM_VOLUME,
    CHUNK_SIZE,
    COLLIDER_DISTANCE_BLOCKS,
    LOD_UPDATE_INTERVAL,
    LOD_UPDATE_MIN_MOVE,
    RENDER_DISTANCE_BLOCKS,
    SKY_TEXTURE_FILE,
    SKY_COLOR,
    TERRAIN_BASE_DEPTH,
    TERRAIN_SIZE,
    WINDOW_BORDERLESS,
    WINDOW_FULLSCREEN,
    WINDOW_TITLE,
    WINDOW_VSYNC,
)


def _is_valid_png(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        with path.open("rb") as f:
            return f.read(8) == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _convert_to_png(source_path: Path, target_path: Path) -> bool:
    try:
        from PIL import Image

        with Image.open(source_path) as image:
            image.save(target_path, format="PNG")
        return _is_valid_png(target_path)
    except Exception:
        return False


def _materialize_runtime_png(source_path: Path, runtime_path: Path) -> bool:
    if source_path == runtime_path:
        return _is_valid_png(runtime_path)
    if _is_valid_png(source_path):
        shutil.copy2(source_path, runtime_path)
        return True
    return _convert_to_png(source_path, runtime_path)


def run_game() -> None:
    from panda3d.core import loadPrcFileData
    from ursina import (
        Audio,
        Button,
        Entity,
        Text,
        Ursina,
        Vec3,
        application,
        camera,
        color,
        destroy,
        held_keys,
        invoke,
        mouse,
        scene,
        time,
        window,
    )
    from minecraft_ursina.player.controller import PlayerController
    from minecraft_ursina.ui.hud import HUD
    from minecraft_ursina.world.block import TEXTURE_REFS
    from minecraft_ursina.world.terrain import Terrain

    if not WINDOW_VSYNC:
        loadPrcFileData("", "sync-video 0")

    app = Ursina(
        title=WINDOW_TITLE,
        borderless=WINDOW_BORDERLESS,
        fullscreen=WINDOW_FULLSCREEN,
    )
    # Work around texture importer crash in some Ursina/Python setups.
    application.development_mode = False

    window.color = color.rgb(*(int(channel * 255) for channel in SKY_COLOR))
    window.fps_counter.enabled = True
    window.exit_button.visible = False

    class GameController(Entity):
        def __init__(self, mode: str = "creative") -> None:
            super().__init__()
            self.game_mode = "survival" if str(mode).lower() == "survival" else "creative"
            self.is_survival = self.game_mode == "survival"
            project_root = Path(__file__).resolve().parents[3]
            runtime_sounds_dir = project_root / "sounds"
            runtime_sounds_dir.mkdir(parents=True, exist_ok=True)
            runtime_dir = project_root / "textures"
            runtime_sky_path = runtime_dir / SKY_TEXTURE_FILE
            source_sky_path = (
                Path(__file__).resolve().parents[1] / "assets" / "textures" / SKY_TEXTURE_FILE
            )
            self.sky_texture_ref: str | None = None
            freshest_sky_path: Path | None = None
            sky_candidates = [path for path in (source_sky_path, runtime_sky_path) if path.exists()]
            if sky_candidates:
                freshest_sky_path = max(sky_candidates, key=lambda path: path.stat().st_mtime_ns)
                runtime_dir.mkdir(parents=True, exist_ok=True)
                if not _materialize_runtime_png(freshest_sky_path, runtime_sky_path):
                    if _is_valid_png(runtime_sky_path):
                        freshest_sky_path = runtime_sky_path
                    else:
                        freshest_sky_path = None
                else:
                    freshest_sky_path = runtime_sky_path
            if freshest_sky_path:
                sky_stem = Path(SKY_TEXTURE_FILE).stem
                sky_suffix = Path(SKY_TEXTURE_FILE).suffix or ".png"
                sky_tag = f"{freshest_sky_path.stat().st_mtime_ns}_{freshest_sky_path.stat().st_size}"
                sky_cache_name = f"{sky_stem}.{sky_tag}{sky_suffix}"
                sky_cache_path = runtime_dir / sky_cache_name
                if not sky_cache_path.exists():
                    shutil.copy2(freshest_sky_path, sky_cache_path)
                for stale_path in runtime_dir.glob(f"{sky_stem}.*{sky_suffix}"):
                    if stale_path == sky_cache_path:
                        continue
                    try:
                        stale_path.unlink()
                    except OSError:
                        pass
                self.sky_texture_ref = f"textures/{sky_cache_name}"

            self.sky_dome: Entity | None = None
            if self.sky_texture_ref:
                self.sky_dome = Entity(
                    model="sphere",
                    texture=self.sky_texture_ref,
                    scale=700,
                    double_sided=True,
                    shader=None,
                )
                self.sky_dome.setShaderOff()
                self.sky_dome.setLightOff()

            sounds_dir = Path(__file__).resolve().parents[1] / "assets" / "sounds"
            preferred_stem = Path(BGM_FILE).stem
            candidate_files = [
                sounds_dir / f"{preferred_stem}.ogg",
                sounds_dir / f"{preferred_stem}.wav",
                sounds_dir / f"{preferred_stem}.mp3",
            ]
            music_path = next((p for p in candidate_files if p.exists()), None)
            self.background_music: Audio | None = None
            if music_path:
                try:
                    runtime_music_path = runtime_sounds_dir / music_path.name
                    if not runtime_music_path.exists():
                        shutil.copy2(music_path, runtime_music_path)

                    self.background_music = Audio(
                        runtime_music_path.stem,
                        loop=True,
                        autoplay=False,
                        volume=BGM_VOLUME,
                    )
                    invoke(self.background_music.play, delay=0.2)
                except Exception:
                    self.background_music = None

            self.footstep_walk_sound = "step_walk"
            self.footstep_run_sound = "step_run"
            self.block_action_sound_stems = {
                "grass": "break_grass",
                "dirt": "break_dirt",
                "stone": "break_stone",
                "plank": "break_plank",
                "wood": "break_wood",
                "leaves": "break_leaves",
                "sand": "break_sand",
                "brick": "break_brick",
                "bedrock": "break_bedrock",
            }

            self.terrain = Terrain(
                size=TERRAIN_SIZE,
                base_depth=TERRAIN_BASE_DEPTH,
                chunk_size=CHUNK_SIZE,
            )
            self.terrain.generate_hills(base_y=0)
            self.respawn_position = self._find_spawn_point()
            self.player = PlayerController(
                position=self.respawn_position,
                on_footstep=self._on_player_footstep,
                on_fall_damage=self._on_player_fall_damage,
                is_water_at=self.terrain.is_water,
            )
            self.hand_color_rgb = (212, 184, 153)  # warm beige skin tone
            if hasattr(self.player, "hand") and self.player.hand is not None:
                self.player.hand.color = color.rgb(*self.hand_color_rgb)
                self.player.hand.texture = "white_cube"
                self.player.hand.enabled = False
            self.player.camera_pivot.rotation_x = -30
            self.player.cursor.visible = False
            self.hotbar_size = 9
            self.placeable_blocks = [
                "grass",
                "dirt",
                "stone",
                "plank",
                "wood",
                "leaves",
                "sand",
                "brick",
                "bedrock",
            ]
            self.block_display_colors = {
                "grass": color.rgb(60, 170, 70),
                "dirt": color.rgb(130, 92, 60),
                "stone": color.rgb(150, 150, 150),
                "plank": color.rgb(178, 136, 86),
                "wood": color.rgb(126, 98, 68),
                "leaves": color.rgb(74, 147, 71),
                "sand": color.rgb(196, 186, 122),
                "brick": color.rgb(170, 75, 67),
                "bedrock": color.rgb(82, 82, 82),
            }
            self.selected_block_index = 0
            self.max_health = 10
            self.health = self.max_health
            self.hotbar_slots: list[str | None] = [None for _ in range(self.hotbar_size)]
            self.inventory_counts: dict[str, int] = {}
            self.survival_break_times = {
                "grass": 1.0,
                "dirt": 1.0,
                "sand": 1.0,
                "wood": 3.0,
                "plank": 3.0,
                "stone": 5.0,
                "brick": 5.0,
                "leaves": 0.5,
                "bedrock": float("inf"),
            }
            self._survival_break_target: tuple[int, int, int] | None = None
            self._survival_break_progress = 0.0
            self._break_effect_target: tuple[int, int, int] | None = None
            self._break_effect_root: Entity | None = None
            self._break_effect_segments: list[Entity] = []
            self._break_effect_base_position = Vec3(0, 0, 0)
            self.hud = HUD()
            self.hud.build(
                camera.ui,
                slot_textures=[None for _ in range(self.hotbar_size)],
                slot_fallback_colors=[(0.50, 0.50, 0.40, 1.0) for _ in range(self.hotbar_size)],
                max_health=self.max_health,
            )
            self.hud.set_hearts_visible(self.is_survival)
            if self.is_survival:
                self.hud.set_health(self.health)
            self._refresh_hotbar_from_state()
            self.hand_idle_position = Vec3(0.78, -0.58, 1.03)
            self.hand_action_offset = Vec3(0.06, -0.04, -0.06)
            self.held_block_idle_position = Vec3(0.53, -0.34, 1.00)
            self.held_block_action_offset = Vec3(0.05, -0.03, -0.06)
            self._hand_action_duration = 0.11
            self._hand_action_timer = 0.0
            self._hand_action_strength = 0.0
            self.hand_root = Entity(
                parent=camera,
                model="cube",
                texture="white_cube",
                color=color.rgb(*self.hand_color_rgb),
                position=self.hand_idle_position,
                rotation=(24, -38, -8),
                scale=(0.20, 0.34, 0.20),
                always_on_top=True,
            )
            self._apply_solid_color(self.hand_root, self.hand_color_rgb)
            self.held_block_anchor = Entity(
                parent=camera,
                position=self.held_block_idle_position,
                rotation=(8, -35, 8),
                always_on_top=True,
            )
            self.held_block_entity = Entity(
                parent=self.held_block_anchor,
                model="cube",
                position=(0, 0, 0),
                scale=(0.23, 0.23, 0.23),
                color=color.white,
                texture="white_cube",
                always_on_top=True,
            )
            self.held_block_entity.setShaderOff()
            self.held_block_entity.setLightOff()
            self._sync_held_block_visual()
            self._lod_timer = 0.0
            self._breaking_blocks: set[tuple[int, int, int]] = set()
            self._last_lod_player_pos = (self.player.x, self.player.y, self.player.z)
            self.chicken_texture_ref = "textures/chicken.png"
            self.chickens: list[dict] = []
            self._spawn_chickens(count=random.randint(4, 6))
            self._auto_place_interval = 0.25
            self._auto_place_timer = 0.0
            self._auto_break_interval = 0.25
            self._auto_break_timer = 0.0
            self._screen_shake_timer = 0.0
            self._screen_shake_duration = 0.0
            self._screen_shake_strength = 0.0
            self._refresh_lod(player_position=self._last_lod_player_pos)

        def _refresh_lod(self, player_position: tuple[float, float, float]) -> None:
            self.terrain.update_lod(
                player_position=player_position,
                render_distance=RENDER_DISTANCE_BLOCKS,
                collider_distance=COLLIDER_DISTANCE_BLOCKS,
            )
            self._last_lod_player_pos = player_position
            self._lod_timer = 0.0

        def _should_refresh_lod(self, player_position: tuple[float, float, float]) -> bool:
            if self._lod_timer >= LOD_UPDATE_INTERVAL:
                return True
            dx = player_position[0] - self._last_lod_player_pos[0]
            dz = player_position[2] - self._last_lod_player_pos[2]
            return (dx * dx + dz * dz) >= (LOD_UPDATE_MIN_MOVE * LOD_UPDATE_MIN_MOVE)

        def _look_block(self):
            return self.terrain.raycast_block(
                origin=camera.world_position,
                direction=camera.forward,
                max_distance=7.0,
            )

        def _player_inside_block(self, position: tuple[int, int, int]) -> bool:
            px = round(self.player.x)
            pz = round(self.player.z)
            lower_body_y = math.floor(self.player.y + 0.51)
            upper_body_y = math.floor(self.player.y + self.player.height - 0.01)
            x, y, z = position
            return x == px and z == pz and lower_body_y <= y <= upper_body_y

        def _refresh_hotbar_from_state(self) -> None:
            if self.is_survival:
                collected = [block for block in self.placeable_blocks if self.inventory_counts.get(block, 0) > 0]
                self.hotbar_slots = collected[: self.hotbar_size]
                if len(self.hotbar_slots) < self.hotbar_size:
                    self.hotbar_slots.extend([None] * (self.hotbar_size - len(self.hotbar_slots)))
            else:
                self.hotbar_slots = self.placeable_blocks[: self.hotbar_size]
                if len(self.hotbar_slots) < self.hotbar_size:
                    self.hotbar_slots.extend([None] * (self.hotbar_size - len(self.hotbar_slots)))

            if self.selected_block_index >= len(self.hotbar_slots):
                self.selected_block_index = max(0, len(self.hotbar_slots) - 1)
            if self.is_survival and self.hotbar_slots:
                selected_block = self.hotbar_slots[self.selected_block_index]
                if selected_block is None:
                    for i, block in enumerate(self.hotbar_slots):
                        if block is not None:
                            self.selected_block_index = i
                            break

            slot_textures: list[str | None] = []
            slot_colors: list = []
            slot_counts: list[int | None] = []
            for block_type in self.hotbar_slots:
                slot_textures.append(TEXTURE_REFS.get(block_type) if block_type else None)
                slot_colors.append(
                    self.block_display_colors.get(block_type, (0.50, 0.50, 0.40, 1.0))
                    if block_type
                    else (0.50, 0.50, 0.40, 1.0)
                )
                if self.is_survival and block_type:
                    slot_counts.append(self.inventory_counts.get(block_type, 0))
                else:
                    slot_counts.append(None)

            self.hud.set_hotbar_items(slot_textures, slot_colors, slot_counts)
            self.hud.set_selected_slot(self.selected_block_index)
            self._sync_held_block_visual()

        def _selected_hotbar_block_type(self) -> str | None:
            if not self.hotbar_slots:
                return None
            if not (0 <= self.selected_block_index < len(self.hotbar_slots)):
                return None
            return self.hotbar_slots[self.selected_block_index]

        def _cycle_selected_slot(self, step: int) -> None:
            if not self.hotbar_slots:
                return
            self.selected_block_index = (self.selected_block_index + step) % len(self.hotbar_slots)
            self.hud.set_selected_slot(self.selected_block_index)
            self._sync_held_block_visual()

        def _add_inventory_block(self, block_type: str, amount: int = 1) -> None:
            if not self.is_survival or amount <= 0:
                return
            if block_type not in self.placeable_blocks:
                return
            self.inventory_counts[block_type] = self.inventory_counts.get(block_type, 0) + amount
            self._refresh_hotbar_from_state()

        def _consume_selected_block(self, amount: int = 1) -> bool:
            block_type = self._selected_hotbar_block_type()
            if not block_type:
                return False
            if not self.is_survival:
                return True
            current = self.inventory_counts.get(block_type, 0)
            if current < amount:
                return False
            remaining = current - amount
            if remaining <= 0:
                self.inventory_counts.pop(block_type, None)
            else:
                self.inventory_counts[block_type] = remaining
            self._refresh_hotbar_from_state()
            return True

        def _sync_held_block_visual(self) -> None:
            if not hasattr(self, "held_block_entity") or self.held_block_entity is None:
                return
            block_type = self._selected_hotbar_block_type()
            if not block_type:
                self.held_block_entity.enabled = False
                return
            self.held_block_entity.enabled = True
            texture_ref = TEXTURE_REFS.get(block_type)
            self.held_block_entity.texture = texture_ref or "white_cube"
            self.held_block_entity.color = (
                color.white if texture_ref else self.block_display_colors.get(block_type, color.white)
            )

        def _trigger_hand_action_animation(self, strength: float = 1.0) -> None:
            # Small punch when placing/breaking blocks.
            self._hand_action_timer = self._hand_action_duration
            self._hand_action_strength = max(self._hand_action_strength, max(0.25, strength))

        def _update_hand_action_animation(self) -> None:
            if self._hand_action_timer <= 0.0:
                self.hand_root.position = Vec3(self.hand_idle_position)
                self.held_block_anchor.position = Vec3(self.held_block_idle_position)
                self._hand_action_strength = 0.0
                return

            self._hand_action_timer = max(0.0, self._hand_action_timer - time.dt)
            t = 1.0 - (self._hand_action_timer / max(0.0001, self._hand_action_duration))
            punch = math.sin(t * math.pi) * self._hand_action_strength
            self.hand_root.position = self.hand_idle_position + (self.hand_action_offset * punch)
            self.held_block_anchor.position = self.held_block_idle_position + (
                self.held_block_action_offset * punch
            )

        def _play_sfx(self, stem: str, volume: float = 0.35) -> None:
            try:
                snd = Audio(stem, autoplay=True, loop=False, volume=volume)
                invoke(destroy, snd, delay=1.5)
            except Exception:
                pass

        def _apply_solid_color(self, entity: Entity, rgb: tuple[int, int, int]) -> None:
            # Force a neutral texture so tint is always visible immediately.
            entity.texture = "white_cube"
            entity.color = (rgb[0] / 255.0, rgb[1] / 255.0, rgb[2] / 255.0, 1.0)
            entity.shader = None
            entity.setShaderOff()
            entity.setLightOff()

        def _column_top_block_y(self, x: int, z: int, y_min: int = -24, y_max: int = 96) -> int | None:
            for y in range(y_max, y_min - 1, -1):
                if self.terrain.has_block((x, y, z)):
                    return y
            return None

        def _can_spawn_at(self, x: int, z: int) -> bool:
            top_y = self._column_top_block_y(x, z)
            if top_y is None:
                return False
            if self.terrain.blocks.get((x, top_y, z)) != "grass":
                return False
            # Keep spawn on lower plains, not in mountain elevations.
            if top_y > 2:
                return False
            for test_y in (top_y + 1, top_y + 2):
                if self.terrain.has_block((x, test_y, z)) or self.terrain.is_water((x, test_y, z)):
                    return False
            return True

        def _find_spawn_point(self) -> Vec3:
            # Prefer near center on grass plains.
            for radius in range(0, 64):
                samples = max(8, radius * 12)
                for i in range(samples):
                    angle = (i / samples) * math.tau
                    x = int(round(math.cos(angle) * radius))
                    z = int(round(math.sin(angle) * radius))
                    if not self._can_spawn_at(x, z):
                        continue
                    top_y = self._column_top_block_y(x, z)
                    if top_y is None:
                        continue
                    return Vec3(x, top_y + 1, z)
            # Fallback keeps game playable if no ideal spot found.
            return Vec3(0, 10, 0)

        def _spawn_chickens(self, count: int = 1) -> None:
            spawned = 0
            attempts = 0
            while spawned < count and attempts < (count * 120):
                attempts += 1
                px = int(round(self.respawn_position.x + random.randint(-22, 22)))
                pz = int(round(self.respawn_position.z + random.randint(-22, 22)))
                top_y = self._column_top_block_y(px, pz)
                if top_y is None:
                    continue
                if self.terrain.is_water((px, top_y + 1, pz)):
                    continue

                chicken_height = 1.12
                chicken_entity = self._build_chicken_entity(position=(px, top_y + 0.5, pz))

                chicken_data = {
                    "entity": chicken_entity,
                    "height": chicken_height,
                    "dir": Vec3(random.uniform(-1, 1), 0, random.uniform(-1, 1)).normalized(),
                    "walk_speed": random.uniform(0.95, 1.35),
                    "gravity": 24.0,
                    "jump_velocity": 7.0,
                    "vertical_velocity": 0.0,
                    "grounded": True,
                    "wander_timer": random.uniform(0.7, 2.2),
                    "cluck_timer": random.uniform(2.5, 7.0),
                    "left_leg": chicken_entity.left_leg,
                    "right_leg": chicken_entity.right_leg,
                    "step_phase": random.uniform(0.0, math.tau),
                }
                self.chickens.append(chicken_data)
                spawned += 1

        def _build_chicken_entity(self, position: tuple[float, float, float]) -> Entity:
            root = Entity(
                parent=scene,
                position=position,
                scale=(1.0, 1.0, 1.0),
                collider=None,
                shader=None,
            )
            root.setShaderOff()
            root.setLightOff()

            body = Entity(
                parent=root,
                model="cube",
                position=(0, 0.48, 0),
                scale=(0.60, 0.42, 0.68),
                shader=None,
            )
            self._apply_solid_color(body, (176, 176, 176))

            head = Entity(
                parent=root,
                model="cube",
                position=(0, 0.88, 0.25),
                scale=(0.34, 0.34, 0.34),
                shader=None,
            )
            self._apply_solid_color(head, (196, 196, 196))

            beak = Entity(
                parent=root,
                model="cube",
                position=(0, 0.80, 0.45),
                scale=(0.14, 0.08, 0.18),
                shader=None,
            )
            self._apply_solid_color(beak, (243, 168, 38))

            comb = Entity(
                parent=root,
                model="cube",
                position=(0, 1.08, 0.25),
                scale=(0.08, 0.10, 0.12),
                shader=None,
            )
            self._apply_solid_color(comb, (185, 36, 45))

            left_leg = Entity(
                parent=root,
                model="cube",
                position=(-0.14, 0.17, 0.04),
                scale=(0.08, 0.34, 0.08),
                shader=None,
            )
            self._apply_solid_color(left_leg, (204, 145, 52))

            right_leg = Entity(
                parent=root,
                model="cube",
                position=(0.14, 0.17, 0.04),
                scale=(0.08, 0.34, 0.08),
                shader=None,
            )
            self._apply_solid_color(right_leg, (204, 145, 52))

            left_wing = Entity(
                parent=root,
                model="cube",
                position=(-0.34, 0.50, 0.02),
                scale=(0.14, 0.26, 0.42),
                shader=None,
            )
            self._apply_solid_color(left_wing, (146, 146, 146))

            right_wing = Entity(
                parent=root,
                model="cube",
                position=(0.34, 0.50, 0.02),
                scale=(0.14, 0.26, 0.42),
                shader=None,
            )
            self._apply_solid_color(right_wing, (146, 146, 146))

            left_eye = Entity(
                parent=root,
                model="cube",
                position=(-0.08, 0.90, 0.47),
                scale=(0.06, 0.06, 0.06),
                shader=None,
            )
            self._apply_solid_color(left_eye, (18, 18, 18))

            right_eye = Entity(
                parent=root,
                model="cube",
                position=(0.08, 0.90, 0.47),
                scale=(0.06, 0.06, 0.06),
                shader=None,
            )
            self._apply_solid_color(right_eye, (18, 18, 18))

            root.left_leg = left_leg
            root.right_leg = right_leg
            return root

        def _update_chickens(self) -> None:
            if not self.chickens:
                return

            for chicken in self.chickens:
                entity = chicken["entity"]
                if not entity or not entity.enabled:
                    continue

                chicken["wander_timer"] -= time.dt
                if chicken["wander_timer"] <= 0.0:
                    if random.random() < 0.22:
                        chicken["dir"] = Vec3(0, 0, 0)
                    else:
                        chicken["dir"] = Vec3(random.uniform(-1, 1), 0, random.uniform(-1, 1)).normalized()
                    chicken["wander_timer"] = random.uniform(0.8, 2.8)

                move_dir = chicken["dir"]
                move_speed = chicken["walk_speed"] * time.dt
                current_x = entity.x
                current_z = entity.z
                col_x = int(round(current_x))
                col_z = int(round(current_z))
                top_y = self._column_top_block_y(col_x, col_z)
                if top_y is None:
                    continue

                target_stand_y = top_y + 0.5
                if entity.y <= target_stand_y + 0.03 and chicken["vertical_velocity"] <= 0:
                    chicken["grounded"] = True
                    entity.y = target_stand_y
                    chicken["vertical_velocity"] = 0.0
                else:
                    chicken["grounded"] = False
                    chicken["vertical_velocity"] -= chicken["gravity"] * time.dt

                if move_dir.length() > 0.001:
                    forward_probe_x = int(round(current_x + move_dir.x * 0.75))
                    forward_probe_z = int(round(current_z + move_dir.z * 0.75))
                    ahead_top_y = self._column_top_block_y(forward_probe_x, forward_probe_z)
                    if ahead_top_y is None:
                        chicken["dir"] = Vec3(random.uniform(-1, 1), 0, random.uniform(-1, 1)).normalized()
                    else:
                        height_delta = ahead_top_y - top_y
                        if height_delta > 1:
                            chicken["dir"] = Vec3(random.uniform(-1, 1), 0, random.uniform(-1, 1)).normalized()
                        else:
                            if height_delta == 1 and chicken["grounded"]:
                                chicken["vertical_velocity"] = chicken["jump_velocity"]
                                chicken["grounded"] = False
                            if height_delta < -2:
                                chicken["dir"] = Vec3(random.uniform(-1, 1), 0, random.uniform(-1, 1)).normalized()
                            else:
                                entity.x += move_dir.x * move_speed
                                entity.z += move_dir.z * move_speed
                                if move_dir.length() > 0.01:
                                    entity.rotation_y = math.degrees(math.atan2(move_dir.x, move_dir.z))
                                chicken["step_phase"] += time.dt * (6.0 + chicken["walk_speed"] * 2.0)
                                step_sin = math.sin(chicken["step_phase"])
                                chicken["left_leg"].rotation_x = 18.0 * step_sin
                                chicken["right_leg"].rotation_x = -18.0 * step_sin

                entity.y += chicken["vertical_velocity"] * time.dt

                if move_dir.length() <= 0.001 or not chicken["grounded"]:
                    chicken["left_leg"].rotation_x *= 0.78
                    chicken["right_leg"].rotation_x *= 0.78

                chicken["cluck_timer"] -= time.dt
                if chicken["cluck_timer"] <= 0.0:
                    if random.random() < 0.42:
                        self._play_sfx("hen", volume=0.20)
                    chicken["cluck_timer"] = random.uniform(3.0, 9.0)

        def _on_player_footstep(self, sprinting: bool) -> None:
            step_stem = self.footstep_run_sound if sprinting else self.footstep_walk_sound
            self._play_sfx(step_stem, volume=0.22 if sprinting else 0.18)

        def _apply_screen_shake(self, strength: float = 2.0, duration: float = 0.22) -> None:
            self._screen_shake_strength = max(self._screen_shake_strength, strength)
            self._screen_shake_duration = max(self._screen_shake_duration, duration)
            self._screen_shake_timer = self._screen_shake_duration

        def _apply_damage(self, amount: int) -> None:
            if not self.is_survival:
                return
            if amount <= 0 or self.health <= 0:
                return
            prev_health = self.health
            self.health = max(0, self.health - amount)
            if self.health != prev_health:
                self.hud.set_health(self.health)
                self._play_sfx("hit", volume=0.34)
                self._apply_screen_shake(strength=1.8, duration=0.20)
            if self.health <= 0:
                self._respawn_player()

        def _respawn_player(self) -> None:
            self.respawn_position = self._find_spawn_point()
            self.player.position = Vec3(self.respawn_position)
            self.player.vertical_velocity = 0.0
            self.player.grounded = False
            self.player.sprint_active = False
            if hasattr(self.player, "_fall_peak_y"):
                self.player._fall_peak_y = None
            if self.is_survival:
                self.health = self.max_health
                self.hud.set_health(self.health)
            self._refresh_lod((self.player.x, self.player.y, self.player.z))

        def _on_player_fall_damage(self, hearts_lost: int, fall_height: float) -> None:
            del fall_height
            if not self.is_survival:
                return
            self._apply_damage(hearts_lost)

        def _try_place_held_block(self) -> None:
            hit = self._look_block()
            if not hit:
                return
            block_type = self._selected_hotbar_block_type()
            if not block_type:
                return
            place_pos = (
                hit.position[0] + hit.normal[0],
                hit.position[1] + hit.normal[1],
                hit.position[2] + hit.normal[2],
            )
            if self.terrain.has_block(place_pos):
                return
            if self._player_inside_block(place_pos):
                return
            if self.is_survival and not self._consume_selected_block(amount=1):
                return
            self.terrain.add_block(place_pos, block_type)
            self._trigger_hand_action_animation(strength=0.95)
            self._play_sfx(self.block_action_sound_stems.get(block_type, "break_stone"), volume=0.24)

        def _try_break_look_block(self) -> None:
            hit = self._look_block()
            if not hit:
                return
            block_type = self.terrain.blocks.get(hit.position)
            if block_type is None:
                return
            if self.is_survival and block_type == "bedrock":
                return
            self._break_block_with_animation(hit.position, collect_to_inventory=self.is_survival)

        def _clear_break_effect(self) -> None:
            self._break_effect_target = None
            self._break_effect_base_position = Vec3(0, 0, 0)
            for segment in self._break_effect_segments:
                destroy(segment)
            self._break_effect_segments.clear()
            if self._break_effect_root is not None:
                destroy(self._break_effect_root)
                self._break_effect_root = None

        def _setup_break_effect_for(self, position: tuple[int, int, int]) -> None:
            if self._break_effect_target == position and self._break_effect_root is not None:
                return
            self._clear_break_effect()
            self._break_effect_target = position
            self._break_effect_base_position = Vec3(position[0], position[1], position[2])
            self._break_effect_root = Entity(parent=scene, position=self._break_effect_base_position, shader=None)
            self._break_effect_root.setShaderOff()
            self._break_effect_root.setLightOff()

            # Crack segments are thin dark slivers that appear progressively.
            crack_specs = (
                ((0.00, 0.32, 0.51), (0.03, 0.03, 0.42), (0, 0, 24)),
                ((0.02, 0.06, 0.51), (0.03, 0.03, 0.52), (0, 0, -16)),
                ((0.18, 0.20, 0.51), (0.03, 0.03, 0.28), (0, 0, 35)),
                ((-0.20, -0.06, 0.51), (0.03, 0.03, 0.31), (0, 0, -27)),
                ((0.51, 0.12, 0.00), (0.40, 0.03, 0.03), (0, 20, 0)),
                ((-0.51, -0.08, 0.02), (0.34, 0.03, 0.03), (0, -18, 0)),
                ((0.00, 0.51, 0.00), (0.36, 0.03, 0.03), (18, 0, 0)),
                ((0.00, -0.20, 0.51), (0.03, 0.03, 0.35), (0, 0, 10)),
                ((0.51, -0.22, 0.02), (0.28, 0.03, 0.03), (0, 8, 0)),
                ((-0.18, 0.28, 0.51), (0.03, 0.03, 0.22), (0, 0, 60)),
                ((0.22, -0.14, 0.51), (0.03, 0.03, 0.20), (0, 0, -56)),
                ((0.00, 0.28, -0.51), (0.03, 0.03, 0.34), (0, 0, 14)),
            )
            for pos, scl, rot in crack_specs:
                segment = Entity(
                    parent=self._break_effect_root,
                    model="cube",
                    texture="white_cube",
                    color=(0.02, 0.02, 0.02, 0.0),
                    position=pos,
                    scale=scl,
                    rotation=rot,
                    shader=None,
                    enabled=False,
                )
                segment.setShaderOff()
                segment.setLightOff()
                segment.setTransparency(True)
                self._break_effect_segments.append(segment)

        def _update_break_effect(self, position: tuple[int, int, int], progress_ratio: float) -> None:
            self._setup_break_effect_for(position)
            if self._break_effect_root is None:
                return

            ratio = max(0.0, min(1.0, progress_ratio))
            shake = 0.003 + (0.020 * ratio)
            self._break_effect_root.position = self._break_effect_base_position + Vec3(
                random.uniform(-shake, shake),
                random.uniform(-shake * 0.8, shake * 0.8),
                random.uniform(-shake, shake),
            )

            total = len(self._break_effect_segments)
            visible = min(total, max(1, int(math.ceil(ratio * total)))) if ratio > 0.0 else 0
            alpha = 0.18 + (ratio * 0.62)
            for i, segment in enumerate(self._break_effect_segments):
                is_visible = i < visible
                segment.enabled = is_visible
                if is_visible:
                    segment.color = (0.02, 0.02, 0.02, alpha)

        def _reset_survival_break_state(self) -> None:
            self._survival_break_target = None
            self._survival_break_progress = 0.0
            self._clear_break_effect()

        def _update_survival_breaking(self) -> None:
            hit = self._look_block()
            if not hit:
                self._reset_survival_break_state()
                return

            position = hit.position
            block_type = self.terrain.blocks.get(position)
            if not block_type or block_type == "bedrock":
                self._reset_survival_break_state()
                return

            if self._survival_break_target != position:
                self._survival_break_target = position
                self._survival_break_progress = 0.0

            break_time = self.survival_break_times.get(block_type, 1.0)
            self._survival_break_progress += time.dt
            if self._hand_action_timer <= 0.02:
                self._trigger_hand_action_animation(strength=0.62)
            if math.isfinite(break_time) and break_time > 0:
                progress_ratio = min(0.98, self._survival_break_progress / break_time)
                self._update_break_effect(position, progress_ratio)
            else:
                self._reset_survival_break_state()
                return
            if self._survival_break_progress < break_time:
                return

            self._reset_survival_break_state()
            self._break_block_with_animation(position, collect_to_inventory=True)

        def _break_block_with_animation(
            self,
            position: tuple[int, int, int],
            collect_to_inventory: bool = False,
        ) -> None:
            if position in self._breaking_blocks or not self.terrain.has_block(position):
                return
            self._breaking_blocks.add(position)
            self._trigger_hand_action_animation(strength=1.0)

            block_type = self.terrain.blocks.get(position, "stone")
            texture_ref = TEXTURE_REFS.get(block_type)
            self._play_sfx(self.block_action_sound_stems.get(block_type, "break_stone"), volume=0.30)
            particle_color = (
                color.white if texture_ref else self.block_display_colors.get(block_type, color.white)
            )
            center = Vec3(position[0], position[1], position[2])
            for _ in range(14):
                spawn_offset = Vec3(
                    random.uniform(-0.28, 0.28),
                    random.uniform(-0.20, 0.25),
                    random.uniform(-0.28, 0.28),
                )
                piece = Entity(
                    parent=scene,
                    model="cube",
                    position=center + spawn_offset,
                    texture=texture_ref or "white_cube",
                    color=particle_color,
                    scale=random.uniform(0.06, 0.12),
                    shader=None,
                )
                piece.setShaderOff()
                piece.setLightOff()
                piece.animate_position(
                    piece.position
                    + Vec3(
                        random.uniform(-0.95, 0.95),
                        random.uniform(0.30, 0.85),
                        random.uniform(-0.95, 0.95),
                    ),
                    duration=0.17,
                )
                piece.animate_position(
                    piece.position
                    + Vec3(
                        random.uniform(-1.2, 1.2),
                        random.uniform(-1.5, -0.7),
                        random.uniform(-1.2, 1.2),
                    ),
                    duration=0.25,
                    delay=0.17,
                )
                piece.animate_scale(0.01, duration=0.30, delay=0.12)
                piece.animate_rotation(
                    (
                        random.uniform(240, 520),
                        random.uniform(240, 520),
                        random.uniform(240, 520),
                    ),
                    duration=0.35,
                )
                invoke(destroy, piece, delay=0.40)

            def _finish_break() -> None:
                self.terrain.remove_block(position)
                if collect_to_inventory:
                    self._add_inventory_block(block_type, amount=1)
                self._breaking_blocks.discard(position)

            invoke(_finish_break, delay=0.03)

        def input(self, key: str) -> None:
            movement_aliases = {
                "ц": "w",
                "ф": "a",
                "ы": "s",
                "в": "d",
            }
            if key in movement_aliases:
                held_keys[movement_aliases[key]] = 1
                return
            if key.endswith(" up"):
                released = key[:-3]
                if released in movement_aliases:
                    held_keys[movement_aliases[released]] = 0
                    return
            if key == "m" and self.background_music:
                if self.background_music.playing:
                    self.background_music.pause()
                else:
                    self.background_music.play()
                return

            if key == "scroll up":
                self._cycle_selected_slot(1)
                return
            if key == "scroll down":
                self._cycle_selected_slot(-1)
                return

            selected_index: int | None = None
            if key.startswith("num_"):
                num_key = key[4:]
                if num_key.isdigit():
                    selected_index = int(num_key) - 1
            elif key.isdigit():
                selected_index = int(key) - 1

            if selected_index is not None:
                if not (0 <= selected_index < self.hotbar_size):
                    return
                self.selected_block_index = selected_index
                self.hud.set_selected_slot(self.selected_block_index)
                self._sync_held_block_visual()
                return

            if key == "left mouse down":
                self._auto_break_timer = 0.0
                if self.is_survival:
                    self._reset_survival_break_state()
                else:
                    self._try_break_look_block()
                return

            if key == "right mouse down":
                self._auto_place_timer = 0.0
                self._try_place_held_block()
                return

        def update(self) -> None:
            if self.sky_dome:
                self.sky_dome.position = self.player.position
            self._update_hand_action_animation()

            self._lod_timer += time.dt
            player_position = (self.player.x, self.player.y, self.player.z)
            if self._should_refresh_lod(player_position):
                self._refresh_lod(player_position)
            self._update_chickens()

            if held_keys["right mouse"]:
                self._auto_place_timer += time.dt
                while self._auto_place_timer >= self._auto_place_interval:
                    self._auto_place_timer -= self._auto_place_interval
                    self._try_place_held_block()
            else:
                self._auto_place_timer = 0.0

            if self.is_survival:
                if held_keys["left mouse"]:
                    self._update_survival_breaking()
                else:
                    self._reset_survival_break_state()
            else:
                if held_keys["left mouse"]:
                    self._auto_break_timer += time.dt
                    while self._auto_break_timer >= self._auto_break_interval:
                        self._auto_break_timer -= self._auto_break_interval
                        self._try_break_look_block()
                else:
                    self._auto_break_timer = 0.0

            if self._screen_shake_timer > 0.0:
                self._screen_shake_timer = max(0.0, self._screen_shake_timer - time.dt)
                fade = self._screen_shake_timer / max(0.001, self._screen_shake_duration)
                camera.rotation_z = random.uniform(-1.0, 1.0) * self._screen_shake_strength * fade
            else:
                camera.rotation_z *= 0.6

    active_game: dict[str, GameController | None] = {"controller": None}

    menu_root = Entity(parent=camera.ui, model="quad", color=(0.0, 0.0, 0.0, 0.76), scale=(2.2, 1.4), z=-2)
    menu_root.setShaderOff()
    menu_root.setLightOff()

    title = Text(
        parent=menu_root,
        text="Minecraft Ursina",
        origin=(0, 0),
        position=(0, 0.28, -0.03),
        scale=2.2,
        color=color.rgb(240, 240, 240),
    )
    title.setShaderOff()
    title.setLightOff()

    subtitle = Text(
        parent=menu_root,
        text="Выберите режим",
        origin=(0, 0),
        position=(0, 0.17, -0.03),
        scale=1.25,
        color=color.rgb(210, 210, 210),
    )
    subtitle.setShaderOff()
    subtitle.setLightOff()

    def _start_game(selected_mode: str) -> None:
        if active_game["controller"] is not None:
            return
        active_game["controller"] = GameController(mode=selected_mode)
        destroy(menu_root)
        mouse.locked = True
        mouse.visible = False

    survival_button = Button(
        parent=menu_root,
        text="Выживание",
        text_color=color.black,
        text_size=1.6,
        color=color.rgb(80, 148, 88),
        scale=(0.34, 0.10),
        position=(0, 0.01, -0.03),
        highlight_color=color.rgb(96, 170, 105),
        pressed_color=color.rgb(65, 124, 72),
    )
    survival_button.on_click = lambda: _start_game("survival")
    survival_button.setShaderOff()
    survival_button.setLightOff()

    creative_button = Button(
        parent=menu_root,
        text="Творческий",
        text_color=color.black,
        text_size=1.6,
        color=color.rgb(79, 118, 172),
        scale=(0.34, 0.10),
        position=(0, -0.13, -0.03),
        highlight_color=color.rgb(95, 134, 188),
        pressed_color=color.rgb(62, 99, 151),
    )
    creative_button.on_click = lambda: _start_game("creative")
    creative_button.setShaderOff()
    creative_button.setLightOff()

    mouse.locked = False
    mouse.visible = True

    app.run()
