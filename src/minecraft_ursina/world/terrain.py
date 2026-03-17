from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

from ursina import Entity, Mesh, color, destroy

from minecraft_ursina.world.block import TEXTURE_REFS

GridPos = Tuple[int, int, int]
ChunkKey = Tuple[int, int]

BLOCK_TYPES = ("grass", "dirt", "stone", "plank", "wood", "leaves")
BLOCK_FALLBACK_COLORS = {
    "grass": color.rgb(62, 168, 76),
    "dirt": color.rgb(118, 84, 56),
    "stone": color.rgb(140, 140, 140),
    "plank": color.rgb(178, 136, 86),
    "wood": color.rgb(126, 98, 68),
    "leaves": color.rgb(74, 147, 71),
}
TREE_TRUNK_HEIGHT = 4
TREE_SPAWN_CHANCE = 0.025

FACES = (
    (
        (1, 0, 0),
        ((0.5, -0.5, -0.5), (0.5, 0.5, -0.5), (0.5, 0.5, 0.5), (0.5, -0.5, 0.5)),
        (1, 0, 0),
    ),
    (
        (-1, 0, 0),
        ((-0.5, -0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, 0.5, -0.5), (-0.5, -0.5, -0.5)),
        (-1, 0, 0),
    ),
    (
        (0, 1, 0),
        ((-0.5, 0.5, -0.5), (-0.5, 0.5, 0.5), (0.5, 0.5, 0.5), (0.5, 0.5, -0.5)),
        (0, 1, 0),
    ),
    (
        (0, -1, 0),
        ((-0.5, -0.5, 0.5), (-0.5, -0.5, -0.5), (0.5, -0.5, -0.5), (0.5, -0.5, 0.5)),
        (0, -1, 0),
    ),
    (
        (0, 0, 1),
        ((0.5, -0.5, 0.5), (0.5, 0.5, 0.5), (-0.5, 0.5, 0.5), (-0.5, -0.5, 0.5)),
        (0, 0, 1),
    ),
    (
        (0, 0, -1),
        ((-0.5, -0.5, -0.5), (-0.5, 0.5, -0.5), (0.5, 0.5, -0.5), (0.5, -0.5, -0.5)),
        (0, 0, -1),
    ),
)


@dataclass
class BlockHit:
    position: GridPos
    normal: GridPos


def _build_texture_atlas() -> tuple[str | None, dict[str, tuple[float, float, float, float]]]:
    try:
        from PIL import Image
    except Exception:
        return None, {}

    project_root = Path(__file__).resolve().parents[3]
    runtime_dir = project_root / "textures"
    runtime_dir.mkdir(parents=True, exist_ok=True)

    images = []
    for block_type in BLOCK_TYPES:
        ref = TEXTURE_REFS.get(block_type)
        image_path = (project_root / ref) if ref else None
        if image_path and image_path.exists():
            with Image.open(image_path) as img:
                images.append((block_type, img.convert("RGBA")))
        else:
            rgba = BLOCK_FALLBACK_COLORS[block_type]
            fallback = Image.new(
                "RGBA",
                (16, 16),
                (int(rgba.r * 255), int(rgba.g * 255), int(rgba.b * 255), 255),
            )
            images.append((block_type, fallback))

    if not images:
        return None, {}

    tile_size = max(max(image.width, image.height) for _, image in images)
    atlas_width = tile_size * len(images)
    atlas = Image.new("RGBA", (atlas_width, tile_size), (255, 255, 255, 255))

    resampling = getattr(getattr(Image, "Resampling", Image), "NEAREST")
    uv_rects: dict[str, tuple[float, float, float, float]] = {}
    for index, (block_type, image) in enumerate(images):
        if image.size != (tile_size, tile_size):
            image = image.resize((tile_size, tile_size), resample=resampling)
        atlas.paste(image, (index * tile_size, 0))

        # Half-pixel inset to avoid texture bleeding between atlas tiles.
        inset = 0.5
        u0 = ((index * tile_size) + inset) / atlas_width
        u1 = (((index + 1) * tile_size) - inset) / atlas_width
        v0 = inset / tile_size
        v1 = (tile_size - inset) / tile_size
        uv_rects[block_type] = (u0, v0, u1, v1)

    digest = hashlib.sha1(atlas.tobytes()).hexdigest()[:12]
    atlas_name = f"chunk_atlas.{digest}.png"
    atlas_path = runtime_dir / atlas_name
    if not atlas_path.exists():
        atlas.save(atlas_path, format="PNG")

    for stale_path in runtime_dir.glob("chunk_atlas.*.png"):
        if stale_path == atlas_path:
            continue
        try:
            stale_path.unlink()
        except OSError:
            pass

    return f"textures/{atlas_name}", uv_rects


class Chunk:
    """Single renderable chunk with one mesh and one collider."""

    def __init__(self, manager: "ChunkManager", key: ChunkKey) -> None:
        self.manager = manager
        self.key = key
        self.entity: Entity | None = None
        self.collider_enabled = False

    def destroy(self) -> None:
        if not self.entity:
            return
        self.manager.entity_to_chunk.pop(self.entity, None)
        destroy(self.entity)
        self.entity = None

    def set_collider_enabled(self, enabled: bool) -> None:
        self.collider_enabled = enabled
        if self.entity and self.entity.enabled:
            self.entity.collider = "mesh" if enabled else None

    def rebuild(self) -> None:
        positions = self.manager.chunk_blocks.get(self.key, set())
        if not positions:
            self.destroy()
            return

        vertices: list[tuple[float, float, float]] = []
        triangles: list[tuple[int, int, int]] = []
        uvs: list[tuple[float, float]] = []
        normals: list[tuple[float, float, float]] = []
        colors: list = []

        for x, y, z in positions:
            block_type = self.manager.blocks.get((x, y, z))
            if not block_type:
                continue
            face_color = (
                color.white if self.manager.atlas_texture_ref else BLOCK_FALLBACK_COLORS.get(block_type, color.white)
            )
            u0, v0, u1, v1 = self.manager.atlas_uv_rects.get(block_type, (0.0, 0.0, 1.0, 1.0))
            face_uvs = ((u0, v0), (u0, v1), (u1, v1), (u1, v0))

            for (nx, ny, nz), face_vertices, face_normal in FACES:
                neighbor_pos = (x + nx, y + ny, z + nz)
                if neighbor_pos in self.manager.blocks:
                    continue

                base = len(vertices)
                for uv, (vx, vy, vz) in zip(face_uvs, face_vertices):
                    vertices.append((x + vx, y + vy, z + vz))
                    uvs.append(uv)
                    normals.append(face_normal)
                    colors.append(face_color)
                triangles.append((base, base + 1, base + 2))
                triangles.append((base, base + 2, base + 3))

        if not triangles:
            self.destroy()
            return

        mesh = Mesh(
            vertices=vertices,
            triangles=triangles,
            uvs=uvs,
            normals=normals,
            colors=colors,
            mode="triangle",
        )

        texture_ref = self.manager.atlas_texture_ref or "white_cube"
        if self.entity is None:
            self.entity = Entity(
                model=mesh,
                texture=texture_ref,
                collider="mesh" if self.collider_enabled else None,
                shader=None,
                double_sided=True,
            )
            self.entity.setShaderOff()
            self.entity.setLightOff()
            self.manager.entity_to_chunk[self.entity] = self.key
        else:
            self.entity.model = mesh
            self.entity.texture = texture_ref
            self.entity.collider = "mesh" if self.collider_enabled else None


class ChunkManager:
    """Owns chunk data, load/unload logic and dirty-mesh rebuilds."""

    def __init__(self, size: int, base_depth: int, chunk_size: int = 16, seed: int | None = None) -> None:
        self.size = size
        self.base_depth = base_depth
        self.chunk_size = max(16, chunk_size)
        self.seed = seed if seed is not None else random.randint(1, 1_000_000_000)
        self.rng = random.Random(self.seed)
        self.mountain_centers: list[tuple[float, float, float, float]] = []

        self.blocks: Dict[GridPos, str] = {}
        self.chunk_blocks: Dict[ChunkKey, set[GridPos]] = {}
        self.generated_chunks: set[ChunkKey] = set()
        self.loaded_chunks: Dict[ChunkKey, Chunk] = {}
        self.entity_to_chunk: dict[Entity, ChunkKey] = {}
        self.dirty_chunks: set[ChunkKey] = set()

        self._base_y = 0
        self._mode = "hills"
        self.atlas_texture_ref, self.atlas_uv_rects = _build_texture_atlas()
        self._prepare_mountains()

    def reset(self, mode: str, base_y: int) -> None:
        self._mode = mode
        self._base_y = base_y
        self.blocks.clear()
        self.chunk_blocks.clear()
        self.generated_chunks.clear()
        self.dirty_chunks.clear()

        for chunk in self.loaded_chunks.values():
            chunk.destroy()
        self.loaded_chunks.clear()
        self.entity_to_chunk.clear()

        self._prepare_mountains()
        self._load_all_chunks()

    def _prepare_mountains(self) -> None:
        half = self.size // 2 - 4
        count = max(10, self.size // 7)
        self.mountain_centers = []
        for _ in range(count):
            mx = self.rng.uniform(-half, half)
            mz = self.rng.uniform(-half, half)
            peak_height = self.rng.uniform(6.0, 13.5)
            radius = self.rng.uniform(6.0, 13.5)
            self.mountain_centers.append((mx, mz, peak_height, radius))

    def _chunk_key(self, position: GridPos) -> ChunkKey:
        x, _, z = position
        return (math.floor(x / self.chunk_size), math.floor(z / self.chunk_size))

    def _distance_sq_to_chunk(self, px: float, pz: float, key: ChunkKey) -> float:
        cx, cz = key
        min_x = (cx * self.chunk_size) - 0.5
        max_x = min_x + self.chunk_size
        min_z = (cz * self.chunk_size) - 0.5
        max_z = min_z + self.chunk_size

        if px < min_x:
            dx = min_x - px
        elif px > max_x:
            dx = px - max_x
        else:
            dx = 0.0

        if pz < min_z:
            dz = min_z - pz
        elif pz > max_z:
            dz = pz - max_z
        else:
            dz = 0.0

        return (dx * dx) + (dz * dz)

    def _within_bounds(self, x: int, z: int) -> bool:
        half = self.size // 2
        return (-half <= x < half) and (-half <= z < half)

    def _all_world_chunk_keys(self) -> list[ChunkKey]:
        half = self.size // 2
        min_x = -half
        max_x = half - 1
        min_z = -half
        max_z = half - 1

        min_cx = math.floor(min_x / self.chunk_size)
        max_cx = math.floor(max_x / self.chunk_size)
        min_cz = math.floor(min_z / self.chunk_size)
        max_cz = math.floor(max_z / self.chunk_size)

        keys: list[ChunkKey] = []
        for cx in range(min_cx, max_cx + 1):
            for cz in range(min_cz, max_cz + 1):
                keys.append((cx, cz))
        return keys

    def _base_height_noise(self, x: int, z: int) -> float:
        s = self.seed * 0.000001
        return (
            math.sin((x * 0.15) + s * 17.0) * 0.9
            + math.cos((z * 0.14) - s * 13.0) * 0.9
            + math.sin((x + z) * 0.07 + s * 9.0) * 0.5
        )

    def _mountain_boost(self, x: int, z: int) -> float:
        boost = 0.0
        for mx, mz, peak_height, radius in self.mountain_centers:
            dx = x - mx
            dz = z - mz
            dist_sq = dx * dx + dz * dz
            radius_sq = radius * radius
            if dist_sq >= radius_sq:
                continue
            influence = 1.0 - (dist_sq / radius_sq)
            boost += influence * peak_height
        return boost

    def _stable_noise_01(self, x: int, z: int, salt: int = 0) -> float:
        value = (
            (x * 374761393)
            + (z * 668265263)
            + (self.seed * 2246822519)
            + (salt * 3266489917)
        ) & 0xFFFFFFFF
        value ^= value >> 13
        value = (value * 1274126177) & 0xFFFFFFFF
        value ^= value >> 16
        return value / 0xFFFFFFFF

    def _tree_placements(self, x: int, ground_y: int, z: int) -> list[tuple[GridPos, str]]:
        trunk_top_y = ground_y + TREE_TRUNK_HEIGHT
        placements: list[tuple[GridPos, str]] = [
            ((x, ground_y + dy, z), "wood")
            for dy in range(1, TREE_TRUNK_HEIGHT + 1)
        ]

        leaves: set[GridPos] = set()
        for ox in range(-2, 3):
            for oz in range(-2, 3):
                if abs(ox) == 2 and abs(oz) == 2:
                    continue
                leaves.add((x + ox, trunk_top_y, z + oz))

        for ox in range(-1, 2):
            for oz in range(-1, 2):
                leaves.add((x + ox, trunk_top_y + 1, z + oz))

        leaves.add((x, trunk_top_y + 2, z))

        trunk_positions = {position for position, _ in placements}
        for position in sorted(leaves):
            if position in trunk_positions:
                continue
            placements.append((position, "leaves"))

        return placements

    def _can_place_tree(self, placements: list[tuple[GridPos, str]]) -> bool:
        for (x, y, z), _ in placements:
            if not self._within_bounds(x, z):
                return False
            if (x, y, z) in self.blocks:
                return False
        return True

    def _try_place_tree(self, x: int, ground_y: int, z: int) -> None:
        if self._stable_noise_01(x, z, salt=11) >= TREE_SPAWN_CHANCE:
            return
        # Secondary gate reduces clustering and keeps trees more natural.
        if self._stable_noise_01(x, z, salt=29) < 0.35:
            return

        placements = self._tree_placements(x, ground_y, z)
        if not self._can_place_tree(placements):
            return

        for position, block_type in placements:
            self._set_block_data(position, block_type)

    def _set_block_data(self, position: GridPos, block_type: str) -> None:
        self.blocks[position] = block_type
        chunk_key = self._chunk_key(position)
        self.chunk_blocks.setdefault(chunk_key, set()).add(position)

    def _generate_chunk_data(self, key: ChunkKey) -> None:
        if key in self.generated_chunks:
            return
        self.generated_chunks.add(key)

        x_start = key[0] * self.chunk_size
        z_start = key[1] * self.chunk_size
        grass_surfaces: list[tuple[int, int, int]] = []
        for x in range(x_start, x_start + self.chunk_size):
            for z in range(z_start, z_start + self.chunk_size):
                if not self._within_bounds(x, z):
                    continue

                if self._mode == "flat":
                    if (x, self._base_y, z) not in self.blocks:
                        self._set_block_data((x, self._base_y, z), "grass")
                    continue

                mountain_boost = self._mountain_boost(x, z)
                surface_offset = int(round(self._base_height_noise(x, z) + mountain_boost))
                surface_offset = max(0, min(surface_offset, 18))
                surface_y = self._base_y + surface_offset

                # Build solid terrain columns so mountains are not hollow.
                # Depth grows with mountain height and keeps stone inside.
                extra_depth = int(mountain_boost * 0.45)
                full_depth = self.base_depth + 8 + extra_depth
                bottom_y = self._base_y - full_depth

                stone_patch = math.sin(x * 0.41 + z * 0.37 + self.seed) > 0.96
                surface_block = "stone" if mountain_boost > 5.5 or stone_patch else "grass"

                for y in range(bottom_y, surface_y + 1):
                    if (x, y, z) in self.blocks:
                        continue
                    if y == surface_y:
                        block_type = surface_block
                    elif y >= surface_y - 3:
                        block_type = "dirt"
                    else:
                        block_type = "stone"
                    self._set_block_data((x, y, z), block_type)

                if surface_block == "grass":
                    grass_surfaces.append((x, surface_y, z))

        for x, surface_y, z in grass_surfaces:
            self._try_place_tree(x, surface_y, z)

    def _load_chunk(self, key: ChunkKey) -> None:
        self._generate_chunk_data(key)
        if key in self.loaded_chunks:
            return
        self.loaded_chunks[key] = Chunk(self, key)
        self.dirty_chunks.add(key)

    def _load_all_chunks(self) -> None:
        for key in self._all_world_chunk_keys():
            self._load_chunk(key)
        self._rebuild_dirty_chunks()

    def _mark_chunk_and_neighbors_dirty(self, position: GridPos) -> None:
        x, _, z = position
        chunk_key = self._chunk_key(position)
        self.dirty_chunks.add(chunk_key)

        cx, cz = chunk_key
        local_x = x - (cx * self.chunk_size)
        local_z = z - (cz * self.chunk_size)
        if local_x == 0:
            self.dirty_chunks.add((cx - 1, cz))
        elif local_x == self.chunk_size - 1:
            self.dirty_chunks.add((cx + 1, cz))

        if local_z == 0:
            self.dirty_chunks.add((cx, cz - 1))
        elif local_z == self.chunk_size - 1:
            self.dirty_chunks.add((cx, cz + 1))

    def _rebuild_dirty_chunks(self) -> None:
        if not self.dirty_chunks:
            return
        dirty = tuple(self.dirty_chunks)
        self.dirty_chunks.clear()
        for key in dirty:
            chunk = self.loaded_chunks.get(key)
            if chunk:
                chunk.rebuild()

    def add_block(self, position: GridPos, block_type: str = "grass") -> None:
        self._set_block_data(position, block_type)
        self._mark_chunk_and_neighbors_dirty(position)
        self._rebuild_dirty_chunks()

    def remove_block(self, position: GridPos) -> None:
        if position not in self.blocks:
            return
        self.blocks.pop(position, None)
        chunk_key = self._chunk_key(position)
        chunk_positions = self.chunk_blocks.get(chunk_key)
        if chunk_positions:
            chunk_positions.discard(position)
            if not chunk_positions:
                self.chunk_blocks.pop(chunk_key, None)

        self._mark_chunk_and_neighbors_dirty(position)
        self._rebuild_dirty_chunks()

    def has_block(self, position: GridPos) -> bool:
        return position in self.blocks

    def update(
        self,
        player_position: tuple[float, float, float],
        render_distance_blocks: float,
        collider_distance_blocks: float,
    ) -> None:
        # Map is loaded eagerly once and stays visible; update only collider range.
        del render_distance_blocks

        px, _, pz = player_position
        collider_sq = collider_distance_blocks * collider_distance_blocks
        for key, chunk in self.loaded_chunks.items():
            dist_sq = self._distance_sq_to_chunk(px, pz, key)
            chunk.set_collider_enabled(dist_sq <= collider_sq)

        self._rebuild_dirty_chunks()

    def raycast_block(
        self,
        origin,
        direction,
        max_distance: float = 7.0,
    ) -> BlockHit | None:
        try:
            ox = float(origin[0]) + 0.5
            oy = float(origin[1]) + 0.5
            oz = float(origin[2]) + 0.5
        except (TypeError, IndexError, KeyError):
            ox = float(origin.x) + 0.5
            oy = float(origin.y) + 0.5
            oz = float(origin.z) + 0.5

        try:
            dx = float(direction[0])
            dy = float(direction[1])
            dz = float(direction[2])
        except (TypeError, IndexError, KeyError):
            dx = float(direction.x)
            dy = float(direction.y)
            dz = float(direction.z)

        length = math.sqrt(dx * dx + dy * dy + dz * dz)
        if length <= 1e-8:
            return None
        inv_length = 1.0 / length
        dx *= inv_length
        dy *= inv_length
        dz *= inv_length

        eps = 1e-4
        ox += dx * eps
        oy += dy * eps
        oz += dz * eps

        x = math.floor(ox)
        y = math.floor(oy)
        z = math.floor(oz)

        step_x = 1 if dx > 0 else -1 if dx < 0 else 0
        step_y = 1 if dy > 0 else -1 if dy < 0 else 0
        step_z = 1 if dz > 0 else -1 if dz < 0 else 0
        inf = float("inf")

        if step_x == 0:
            t_max_x, t_delta_x = inf, inf
        else:
            boundary_x = x + (1 if step_x > 0 else 0)
            t_max_x = (boundary_x - ox) / dx
            t_delta_x = 1.0 / abs(dx)

        if step_y == 0:
            t_max_y, t_delta_y = inf, inf
        else:
            boundary_y = y + (1 if step_y > 0 else 0)
            t_max_y = (boundary_y - oy) / dy
            t_delta_y = 1.0 / abs(dy)

        if step_z == 0:
            t_max_z, t_delta_z = inf, inf
        else:
            boundary_z = z + (1 if step_z > 0 else 0)
            t_max_z = (boundary_z - oz) / dz
            t_delta_z = 1.0 / abs(dz)

        last_normal = (0, 0, 0)
        traveled = 0.0
        while traveled <= max_distance:
            position = (x, y, z)
            if position in self.blocks:
                return BlockHit(position=position, normal=last_normal)

            if t_max_x <= t_max_y and t_max_x <= t_max_z:
                traveled = t_max_x
                t_max_x += t_delta_x
                x += step_x
                last_normal = (-step_x, 0, 0)
            elif t_max_y <= t_max_x and t_max_y <= t_max_z:
                traveled = t_max_y
                t_max_y += t_delta_y
                y += step_y
                last_normal = (0, -step_y, 0)
            else:
                traveled = t_max_z
                t_max_z += t_delta_z
                z += step_z
                last_normal = (0, 0, -step_z)

        return None


class Terrain:
    """Facade used by the game layer. Keeps public API stable."""

    def __init__(self, size: int = 24, seed: int | None = None, base_depth: int = 6, chunk_size: int = 16) -> None:
        self.manager = ChunkManager(size=size, base_depth=base_depth, chunk_size=chunk_size, seed=seed)
        self.blocks = self.manager.blocks

    def generate_flat(self, y: int = 0) -> None:
        self.manager.reset(mode="flat", base_y=y)

    def generate_hills(self, base_y: int = 0) -> None:
        self.manager.reset(mode="hills", base_y=base_y)

    def add_block(self, position: GridPos, block_type: str = "grass", has_collider: bool = True) -> None:
        del has_collider
        self.manager.add_block(position=position, block_type=block_type)

    def remove_block(self, position: GridPos) -> None:
        self.manager.remove_block(position=position)

    def has_block(self, position: GridPos) -> bool:
        return self.manager.has_block(position=position)

    def update_lod(
        self,
        player_position: tuple[float, float, float],
        render_distance: float,
        collider_distance: float,
    ) -> None:
        self.manager.update(
            player_position=player_position,
            render_distance_blocks=render_distance,
            collider_distance_blocks=collider_distance,
        )

    def raycast_block(self, origin, direction, max_distance: float = 7.0) -> BlockHit | None:
        return self.manager.raycast_block(origin=origin, direction=direction, max_distance=max_distance)
