from pathlib import Path
import hashlib
import shutil

from ursina import Entity, color
from minecraft_ursina.core.settings import (
    DIRT_TEXTURE_FILE,
    GRASS_TEXTURE_FILE,
    LEAVES_TEXTURE_FILE,
    PLANK_TEXTURE_FILE,
    STONE_TEXTURE_FILE,
    WOOD_TEXTURE_FILE,
)


def _is_valid_png(path: Path) -> bool:
    if not path.exists() or not path.is_file():
        return False
    try:
        with path.open("rb") as f:
            signature = f.read(8)
        return signature == b"\x89PNG\r\n\x1a\n"
    except OSError:
        return False


def _is_existing_file(path: Path) -> bool:
    return path.exists() and path.is_file()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            digest.update(chunk)
    return digest.hexdigest()[:12]


def _newest_existing_path(*paths: Path) -> Path | None:
    existing_paths = [path for path in paths if _is_existing_file(path)]
    if not existing_paths:
        return None
    return max(existing_paths, key=lambda path: path.stat().st_mtime_ns)


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


def _texture_ref(texture_file: str) -> str | None:
    project_root = Path(__file__).resolve().parents[3]
    runtime_dir = project_root / "textures"
    runtime_path = runtime_dir / texture_file
    source_path = (
        Path(__file__).resolve().parents[1] / "assets" / "textures" / texture_file
    )
    newest = _newest_existing_path(source_path, runtime_path)
    if newest is None:
        return None

    runtime_dir.mkdir(parents=True, exist_ok=True)
    if not _materialize_runtime_png(newest, runtime_path):
        if not _is_valid_png(runtime_path):
            return None

    stem = Path(texture_file).stem
    suffix = Path(texture_file).suffix or ".png"
    hashed_name = f"{stem}.{_file_hash(runtime_path)}{suffix}"
    hashed_runtime_path = runtime_dir / hashed_name

    if not hashed_runtime_path.exists():
        shutil.copy2(runtime_path, hashed_runtime_path)

    for stale_path in runtime_dir.glob(f"{stem}.*{suffix}"):
        if stale_path == hashed_runtime_path:
            continue
        try:
            stale_path.unlink()
        except OSError:
            pass

    return f"textures/{hashed_name}"


TEXTURE_REFS = {
    "grass": _texture_ref(GRASS_TEXTURE_FILE),
    "dirt": _texture_ref(DIRT_TEXTURE_FILE),
    "stone": _texture_ref(STONE_TEXTURE_FILE),
    "plank": _texture_ref(PLANK_TEXTURE_FILE),
    "wood": _texture_ref(WOOD_TEXTURE_FILE),
    "leaves": _texture_ref(LEAVES_TEXTURE_FILE),
}
BROKEN_TEXTURE_TYPES: set[str] = set()


class Block(Entity):
    """Single voxel block."""

    def __init__(
        self,
        position=(0, 0, 0),
        block_type: str = "grass",
        has_collider: bool = True,
    ) -> None:
        texture_ref = None if block_type in BROKEN_TEXTURE_TYPES else TEXTURE_REFS.get(block_type)
        if texture_ref:
            block_color = color.white
        elif block_type == "leaves":
            block_color = color.rgb(74, 147, 71)
        elif block_type == "wood":
            block_color = color.rgb(126, 98, 68)
        elif block_type == "plank":
            block_color = color.rgb(178, 136, 86)
        elif block_type == "stone":
            block_color = color.rgb(140, 140, 140)
        elif block_type == "dirt":
            block_color = color.rgb(118, 84, 56)
        else:
            block_color = color.rgb(62, 168, 76)

        entity_kwargs = dict(
            model="cube",
            color=block_color,
            position=position,
            collider="box" if has_collider else None,
            texture=texture_ref or "white_cube",
            shader=None,
        )
        try:
            super().__init__(**entity_kwargs)
        except Exception:
            # Fallback when a user-provided texture exists but can't be loaded.
            BROKEN_TEXTURE_TYPES.add(block_type)
            entity_kwargs["texture"] = "white_cube"
            super().__init__(**entity_kwargs)
        # macOS/OpenGL fallback: force fixed pipeline for stable rendering.
        self.setShaderOff()
        self.block_type = block_type
