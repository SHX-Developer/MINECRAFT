from pathlib import Path
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
        Entity,
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
        def __init__(self) -> None:
            super().__init__()
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
            }

            self.terrain = Terrain(
                size=TERRAIN_SIZE,
                base_depth=TERRAIN_BASE_DEPTH,
                chunk_size=CHUNK_SIZE,
            )
            self.terrain.generate_hills(base_y=0)
            self.player = PlayerController(position=(0, 10, 0), on_footstep=self._on_player_footstep)
            self.player.camera_pivot.rotation_x = -30
            self.player.cursor.visible = False
            self.placeable_blocks = ["grass", "dirt", "stone", "plank", "wood", "leaves"]
            self.block_display_colors = {
                "grass": color.rgb(60, 170, 70),
                "dirt": color.rgb(130, 92, 60),
                "stone": color.rgb(150, 150, 150),
                "plank": color.rgb(178, 136, 86),
                "wood": color.rgb(126, 98, 68),
                "leaves": color.rgb(74, 147, 71),
            }
            self.selected_block_index = 0
            self.hud = HUD()
            self.hud.build(
                camera.ui,
                slot_textures=[TEXTURE_REFS.get(block_type) for block_type in self.placeable_blocks],
                slot_fallback_colors=[
                    self.block_display_colors["grass"],
                    self.block_display_colors["dirt"],
                    self.block_display_colors["stone"],
                    self.block_display_colors["plank"],
                    self.block_display_colors["wood"],
                    self.block_display_colors["leaves"],
                ],
            )
            self.hand_root = Entity(
                parent=camera,
                model="cube",
                color=color.rgb(238, 186, 128),
                position=(0.63, -0.58, 1.03),
                rotation=(24, -38, -8),
                scale=(0.20, 0.34, 0.20),
                always_on_top=True,
            )
            self.hand_root.setShaderOff()
            self.hand_root.setLightOff()
            self.held_block_anchor = Entity(
                parent=camera,
                position=(0.53, -0.34, 1.00),
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
            py = round(self.player.y)
            pz = round(self.player.z)
            return position in {(px, py, pz), (px, py - 1, pz)}

        def _sync_held_block_visual(self) -> None:
            block_type = self.placeable_blocks[self.selected_block_index]
            texture_ref = TEXTURE_REFS.get(block_type)
            self.held_block_entity.texture = texture_ref or "white_cube"
            self.held_block_entity.color = (
                color.white if texture_ref else self.block_display_colors.get(block_type, color.white)
            )

        def _play_sfx(self, stem: str, volume: float = 0.35) -> None:
            try:
                snd = Audio(stem, autoplay=True, loop=False, volume=volume)
                invoke(destroy, snd, delay=1.5)
            except Exception:
                pass

        def _on_player_footstep(self, sprinting: bool) -> None:
            step_stem = self.footstep_run_sound if sprinting else self.footstep_walk_sound
            self._play_sfx(step_stem, volume=0.22 if sprinting else 0.18)

        def _break_block_with_animation(self, position: tuple[int, int, int]) -> None:
            if position in self._breaking_blocks or not self.terrain.has_block(position):
                return
            self._breaking_blocks.add(position)

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
            selected_index: int | None = None
            if key.startswith("num_"):
                num_key = key[4:]
                if num_key.isdigit():
                    selected_index = int(num_key) - 1
            elif key.isdigit():
                selected_index = int(key) - 1

            if selected_index is not None:
                if not (0 <= selected_index < len(self.placeable_blocks)):
                    return
                self.selected_block_index = selected_index
                self.hud.set_selected_slot(self.selected_block_index)
                self._sync_held_block_visual()
                return

            hit = self._look_block()
            if not hit:
                return

            if key == "left mouse down":
                self._break_block_with_animation(hit.position)
                return

            if key == "right mouse down":
                place_pos = (
                    hit.position[0] + hit.normal[0],
                    hit.position[1] + hit.normal[1],
                    hit.position[2] + hit.normal[2],
                )
                if self.terrain.has_block(place_pos):
                    return
                if self._player_inside_block(place_pos):
                    return
                block_type = self.placeable_blocks[self.selected_block_index]
                self.terrain.add_block(place_pos, block_type)
                self._play_sfx(self.block_action_sound_stems.get(block_type, "break_stone"), volume=0.24)

        def update(self) -> None:
            if self.sky_dome:
                self.sky_dome.position = self.player.position

            self._lod_timer += time.dt
            player_position = (self.player.x, self.player.y, self.player.z)
            if self._should_refresh_lod(player_position):
                self._refresh_lod(player_position)

    GameController()

    mouse.locked = True

    app.run()
