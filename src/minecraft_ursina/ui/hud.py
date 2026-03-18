from ursina import Entity, Text, color


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
        self.hotbar_counts: list[Text] = []
        self.hearts_root: Entity | None = None
        self.hearts: list[list[Entity]] = []
        self.max_health = 10
        self.health = 10
        self.selected_slot = 0
        self.default_border_color = (0.42, 0.42, 0.42, 1.0)
        self.selected_border_color = (1.0, 1.0, 1.0, 1.0)

    def build(
        self,
        ui_parent: Entity,
        slot_textures: list[str | None],
        slot_fallback_colors: list,
        max_health: int = 10,
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
        self._build_health(ui_parent, max_health=max_health)
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
        self.hotbar_counts.clear()

        slot_count = max(9, len(slot_textures))
        slot_size = 0.082
        slot_gap = 0.010
        base_y = -0.42
        total_width = (slot_size * slot_count) + (slot_gap * (slot_count - 1))
        start_x = -(total_width / 2) + (slot_size / 2)

        self.hotbar_root = Entity(parent=ui_parent, position=(0, base_y, -1))
        self.hotbar_root.setShaderOff()
        self.hotbar_root.setLightOff()

        # Minecraft-like single strip panel.
        panel_outer = Entity(
            parent=self.hotbar_root,
            model="quad",
            texture="white_cube",
            color=(0.10, 0.10, 0.10, 0.94),
            position=(0, 0, -0.005),
            scale=(total_width + 0.032, slot_size + 0.040),
        )
        panel_outer.setShaderOff()
        panel_outer.setLightOff()

        self.hotbar_background = Entity(
            parent=self.hotbar_root,
            model="quad",
            texture="white_cube",
            color=(0.27, 0.27, 0.27, 0.92),
            position=(0, 0, -0.006),
            scale=(total_width + 0.022, slot_size + 0.028),
        )
        self.hotbar_background.setShaderOff()
        self.hotbar_background.setLightOff()

        panel_top_gloss = Entity(
            parent=self.hotbar_root,
            model="quad",
            texture="white_cube",
            color=(0.47, 0.47, 0.47, 0.36),
            position=(0, (slot_size + 0.028) * 0.32, -0.007),
            scale=(total_width + 0.018, 0.010),
        )
        panel_top_gloss.setShaderOff()
        panel_top_gloss.setLightOff()

        for index in range(slot_count):
            x = start_x + index * (slot_size + slot_gap)
            frame = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture="white_cube",
                color=(0.38, 0.38, 0.38, 0.98),
                position=(x, 0, -0.02),
                scale=(slot_size, slot_size),
            )
            frame.setShaderOff()
            frame.setLightOff()

            frame_inner = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture="white_cube",
                color=(0.36, 0.36, 0.28, 0.98),
                position=(x, 0, -0.021),
                scale=(slot_size * 0.88, slot_size * 0.88),
            )
            frame_inner.setShaderOff()
            frame_inner.setLightOff()

            texture_ref = slot_textures[index] if index < len(slot_textures) else None
            icon = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture=texture_ref or "white_cube",
                color=(1.0, 1.0, 1.0, 1.0) if texture_ref else (0.50, 0.50, 0.40, 1.0),
                position=(x, 0, -0.03),
                scale=(slot_size * 0.78, slot_size * 0.78),
                enabled=True,
            )
            icon.setShaderOff()
            icon.setLightOff()
            self.hotbar_frames.append(frame)
            self.hotbar_icons.append(icon)
            count_text = Text(
                parent=self.hotbar_root,
                text="",
                origin=(0.5, 0.5),
                position=(x + (slot_size * 0.28), -(slot_size * 0.28), -0.033),
                scale=0.92,
                color=color.white,
            )
            count_text.enabled = False
            self.hotbar_counts.append(count_text)

            # Selection ring for active slot.
            select_outer = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture="white_cube",
                color=(0.92, 0.97, 0.92, 0.98),
                position=(x, 0, -0.012),
                scale=(slot_size + 0.020, slot_size + 0.020),
                enabled=False,
            )
            select_cutout = Entity(
                parent=self.hotbar_root,
                model="quad",
                texture="white_cube",
                color=(0.36, 0.36, 0.28, 1.0),
                position=(x, 0, -0.011),
                scale=(slot_size + 0.006, slot_size + 0.006),
                enabled=False,
            )
            for border in (select_outer, select_cutout):
                border.setShaderOff()
                border.setLightOff()
            self.hotbar_borders.append([select_outer, select_cutout])

    def _build_health(self, ui_parent: Entity, max_health: int = 10) -> None:
        self.hearts.clear()
        self.max_health = max(1, max_health)
        self.health = self.max_health

        heart_cell = 0.0075
        heart_width = heart_cell * 5
        heart_gap = 0.012
        base_y = -0.32
        total_width = (heart_width * self.max_health) + (heart_gap * (self.max_health - 1))
        start_x = -(total_width / 2) + (heart_width / 2)

        self.hearts_root = Entity(parent=ui_parent, position=(0, base_y, -1))
        self.hearts_root.setShaderOff()
        self.hearts_root.setLightOff()

        for index in range(self.max_health):
            x = start_x + index * (heart_width + heart_gap)
            self.hearts.append(self._build_heart_icon(parent=self.hearts_root, x=x, cell=heart_cell))

        self.set_health(self.max_health)

    def set_hotbar_items(
        self,
        slot_textures: list[str | None],
        slot_fallback_colors: list,
        slot_counts: list[int | None] | None = None,
    ) -> None:
        if not self.hotbar_icons:
            return
        for i, icon in enumerate(self.hotbar_icons):
            texture_ref = slot_textures[i] if i < len(slot_textures) else None
            fallback_color = slot_fallback_colors[i] if i < len(slot_fallback_colors) else (0.50, 0.50, 0.40, 1.0)
            if texture_ref:
                icon.enabled = True
                icon.texture = texture_ref
                icon.color = (1.0, 1.0, 1.0, 1.0)
            else:
                icon.enabled = False
                icon.texture = "white_cube"
                icon.color = fallback_color

            if i >= len(self.hotbar_counts):
                continue
            label = self.hotbar_counts[i]
            count_value = slot_counts[i] if slot_counts and i < len(slot_counts) else None
            if count_value is not None and count_value > 0:
                label.text = str(count_value)
                label.enabled = True
            else:
                label.text = ""
                label.enabled = False

    def _build_heart_icon(self, parent: Entity, x: float, cell: float) -> list[Entity]:
        # 5x5 pixel heart pattern.
        pattern = (
            "01110",
            "11111",
            "11111",
            "01110",
            "00100",
        )
        icon_root = Entity(parent=parent, position=(x, 0, -0.04))
        icon_root.setShaderOff()
        icon_root.setLightOff()

        parts: list[Entity] = []
        half = (len(pattern[0]) - 1) / 2
        for row, line in enumerate(pattern):
            for col, value in enumerate(line):
                if value != "1":
                    continue
                px = (col - half) * cell
                py = ((len(pattern) - 1 - row) - half) * cell
                dot = Entity(
                    parent=icon_root,
                    model="quad",
                    texture="white_cube",
                    color=(214 / 255.0, 36 / 255.0, 36 / 255.0, 1.0),
                    position=(px, py, 0),
                    scale=(cell * 0.95, cell * 0.95),
                )
                dot.setShaderOff()
                dot.setLightOff()
                parts.append(dot)
        return parts

    def set_selected_slot(self, index: int) -> None:
        if not self.hotbar_frames:
            return
        self.selected_slot = max(0, min(index, len(self.hotbar_frames) - 1))
        for i, borders in enumerate(self.hotbar_borders):
            selected = i == self.selected_slot
            for border in borders:
                border.enabled = selected

    def set_health(self, health: int) -> None:
        self.health = max(0, min(health, self.max_health))
        for index, heart_parts in enumerate(self.hearts):
            enabled = index < self.health
            for part in heart_parts:
                part.enabled = enabled

    def set_hearts_visible(self, visible: bool) -> None:
        if self.hearts_root is not None:
            self.hearts_root.enabled = bool(visible)
