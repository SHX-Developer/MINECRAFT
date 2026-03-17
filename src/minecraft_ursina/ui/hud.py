from ursina import Entity, color


class HUD:
    """In-game HUD widgets."""

    def __init__(self) -> None:
        self.crosshair_h: Entity | None = None
        self.crosshair_v: Entity | None = None
        self.hotbar_root: Entity | None = None
        self.hotbar_background: Entity | None = None
        self.hotbar_frames: list[Entity] = []
        self.hotbar_borders: list[list[Entity]] = []
        self.hotbar_icons: list[Entity] = []
        self.selected_slot = 0
        self.default_border_color = (0.42, 0.42, 0.42, 1.0)
        self.selected_border_color = (1.0, 1.0, 1.0, 1.0)

    def build(
        self,
        ui_parent: Entity,
        slot_textures: list[str | None],
        slot_fallback_colors: list,
    ) -> None:
        # Small black plus in the center.
        self.crosshair_h = Entity(
            parent=ui_parent,
            model="quad",
            color=color.black,
            position=(0, 0, -1),
            scale=(0.010, 0.0014),
        )
        self.crosshair_v = Entity(
            parent=ui_parent,
            model="quad",
            color=color.black,
            position=(0, 0, -1),
            scale=(0.0014, 0.010),
        )
        self.crosshair_h.setShaderOff()
        self.crosshair_v.setShaderOff()
        self.crosshair_h.setLightOff()
        self.crosshair_v.setLightOff()

        self._build_hotbar(ui_parent, slot_textures, slot_fallback_colors)
        self.set_selected_slot(0)

    def _build_hotbar(
        self,
        ui_parent: Entity,
        slot_textures: list[str | None],
        slot_fallback_colors: list,
    ) -> None:
        self.hotbar_frames.clear()
        self.hotbar_borders.clear()
        self.hotbar_icons.clear()

        slot_count = max(9, len(slot_textures))
        slot_size = 0.082
        slot_gap = 0.012
        base_y = -0.42
        total_width = (slot_size * slot_count) + (slot_gap * (slot_count - 1))
        start_x = -(total_width / 2) + (slot_size / 2)

        self.hotbar_root = Entity(parent=ui_parent, position=(0, base_y, -1))
        self.hotbar_root.setShaderOff()
        self.hotbar_root.setLightOff()

        # No panel strip. Keep only separate slot cells.
        self.hotbar_background = None

        for index in range(slot_count):
            x = start_x + index * (slot_size + slot_gap)
            frame = Entity(
                parent=self.hotbar_root,
                model="quad",
                color=color.rgba(44, 44, 44, 255),
                position=(x, 0, -0.02),
                scale=(slot_size, slot_size),
            )
            frame.setShaderOff()
            frame.setLightOff()

            texture_ref = slot_textures[index] if index < len(slot_textures) else None
            icon = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture=texture_ref or "white_cube",
                color=color.white if texture_ref else color.rgba(60, 60, 60, 255),
                position=(x, 0, -0.03),
                scale=(slot_size * 0.92, slot_size * 0.92),
                enabled=True,
            )
            icon.setShaderOff()
            icon.setLightOff()
            self.hotbar_frames.append(frame)
            self.hotbar_icons.append(icon)

            # Explicit border lines so selection is always obvious.
            border_thickness = 0.006
            half = slot_size / 2
            top = Entity(
                parent=self.hotbar_root,
                model="quad",
                color=self.default_border_color,
                position=(x, half, -0.01),
                scale=(slot_size, border_thickness),
            )
            bottom = Entity(
                parent=self.hotbar_root,
                model="quad",
                color=self.default_border_color,
                position=(x, -half, -0.01),
                scale=(slot_size, border_thickness),
            )
            left = Entity(
                parent=self.hotbar_root,
                model="quad",
                color=self.default_border_color,
                position=(x - half, 0, -0.01),
                scale=(border_thickness, slot_size),
            )
            right = Entity(
                parent=self.hotbar_root,
                model="quad",
                color=self.default_border_color,
                position=(x + half, 0, -0.01),
                scale=(border_thickness, slot_size),
            )
            for border in (top, bottom, left, right):
                border.setShaderOff()
                border.setLightOff()
            self.hotbar_borders.append([top, bottom, left, right])

    def set_selected_slot(self, index: int) -> None:
        if not self.hotbar_frames:
            return
        self.selected_slot = max(0, min(index, len(self.hotbar_frames) - 1))
        for i, borders in enumerate(self.hotbar_borders):
            border_color = (
                (1.0, 1.0, 1.0, 1.0)
                if i == self.selected_slot
                else (0.42, 0.42, 0.42, 1.0)
            )
            for border in borders:
                border.color = border_color
