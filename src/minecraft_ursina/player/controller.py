from ursina import Vec2, Vec3, camera, clamp, held_keys, mouse, raycast, scene, time
from ursina.prefabs.first_person_controller import FirstPersonController


class PlayerController(FirstPersonController):
    """First-person player with Minecraft-like movement bounds."""

    def __init__(self, on_footstep=None, **kwargs) -> None:
        super().__init__(**kwargs)
        self.on_footstep = on_footstep
        self.walk_speed = 5.0
        self.sprint_speed = 9.0
        self.speed = self.walk_speed
        self.sprint_double_tap_window = 0.27
        self.sprint_active = False
        self._time_since_last_forward_press = 99.0
        self._was_forward_held = False
        self.base_fov = float(camera.fov)
        self.sprint_fov = self.base_fov + 8.0
        self.fov_lerp_speed = 9.0
        # Physical body is exactly 2 blocks tall.
        self.height = 2.0
        # Keep eyes below the top so the camera does not clip into the 3rd block.
        self.camera_pivot.y = 1.8
        self.collider = "box"

        # Manual jump physics for smooth movement.
        self.mouse_sensitivity = Vec2(40, 40)
        self.gravity = 28.0
        self.jump_velocity = 8.5
        self.vertical_velocity = 0.0
        self.grounded = False
        self.body_radius = 0.36
        self.step_height = 0.55
        self.traverse_target = scene
        self.ignore_list = [self]
        self._step_timer = 0.0

        # If spawned inside terrain, move to nearest valid floor.
        floor_ray = raycast(
            self.world_position + Vec3(0, self.height, 0),
            self.down,
            traverse_target=self.traverse_target,
            ignore=self.ignore_list,
        )
        if floor_ray.hit:
            self.y = floor_ray.world_point.y
            self.grounded = True

    def _horizontal_blocked(self, direction: Vec3, distance: float) -> bool:
        if direction.length() <= 0:
            return False
        check_heights = (0.1, 1.0, self.height - 0.1)
        for sample_y in check_heights:
            hit = raycast(
                self.position + Vec3(0, sample_y, 0),
                direction,
                distance=distance,
                traverse_target=self.traverse_target,
                ignore=self.ignore_list,
            )
            if hit.hit:
                return True
        return False

    def _can_stand_up(self, new_y: float) -> bool:
        """Ensure full 2-block body fits and head does not enter ceiling."""
        check_levels = (0.1, 1.0, self.height - 0.05)
        for sample_y in check_levels:
            hit = raycast(
                Vec3(self.x, new_y + sample_y, self.z),
                Vec3(0, 1, 0),
                distance=0.02,
                traverse_target=self.traverse_target,
                ignore=self.ignore_list,
            )
            if hit.hit:
                return False
        return True

    def _ground_distance(self) -> float:
        ground_ray = raycast(
            self.world_position + Vec3(0, self.height, 0),
            self.down,
            traverse_target=self.traverse_target,
            ignore=self.ignore_list,
        )
        if not ground_ray.hit:
            return float("inf")
        return ground_ray.distance - self.height

    def update(self) -> None:
        self._time_since_last_forward_press += time.dt
        forward_held = held_keys["w"] > 0
        if forward_held and not self._was_forward_held:
            if self._time_since_last_forward_press <= self.sprint_double_tap_window:
                self.sprint_active = True
            self._time_since_last_forward_press = 0.0
        if not forward_held:
            self.sprint_active = False
        self._was_forward_held = forward_held
        self.speed = self.sprint_speed if self.sprint_active else self.walk_speed
        target_fov = self.sprint_fov if self.sprint_active else self.base_fov
        blend = min(1.0, time.dt * self.fov_lerp_speed)
        camera.fov += (target_fov - camera.fov) * blend

        self.rotation_y += mouse.velocity[0] * self.mouse_sensitivity[1]
        self.camera_pivot.rotation_x -= mouse.velocity[1] * self.mouse_sensitivity[0]
        self.camera_pivot.rotation_x = clamp(self.camera_pivot.rotation_x, -90, 90)

        self.direction = Vec3(
            self.forward * (held_keys["w"] - held_keys["s"])
            + self.right * (held_keys["d"] - held_keys["a"])
        ).normalized()

        move_speed = self.speed * time.dt
        moved_horizontally = False
        blocked_horizontally = False
        if self.direction.length() > 0:
            move_dir = self.direction.normalized()
            move_x = Vec3(move_dir.x, 0, 0) * move_speed
            move_z = Vec3(0, 0, move_dir.z) * move_speed

            if abs(move_x.x) > 0:
                sign_x = 1 if move_x.x > 0 else -1
                if not self._horizontal_blocked(Vec3(sign_x, 0, 0), abs(move_x.x) + self.body_radius):
                    self.x += move_x.x
                    moved_horizontally = True
                else:
                    blocked_horizontally = True
            if abs(move_z.z) > 0:
                sign_z = 1 if move_z.z > 0 else -1
                if not self._horizontal_blocked(Vec3(0, 0, sign_z), abs(move_z.z) + self.body_radius):
                    self.z += move_z.z
                    moved_horizontally = True
                else:
                    blocked_horizontally = True

        if self.sprint_active and forward_held and blocked_horizontally and not moved_horizontally:
            self.sprint_active = False
            self.speed = self.walk_speed

        # Detect whether we are standing on the ground.
        ground_distance = self._ground_distance()
        self.grounded = ground_distance <= 0.08 and self.vertical_velocity <= 0

        if self.grounded:
            if ground_distance > 0.001:
                self.y -= min(ground_distance, self.step_height)
            self.vertical_velocity = max(0.0, self.vertical_velocity)
        else:
            self.vertical_velocity -= self.gravity * time.dt

        dy = self.vertical_velocity * time.dt
        if dy > 0:
            # Upward movement: block by ceiling to prevent head clipping.
            ceiling_hits = []
            for offset in (
                Vec3(0, 0, 0),
                Vec3(self.body_radius * 0.6, 0, 0),
                Vec3(-self.body_radius * 0.6, 0, 0),
                Vec3(0, 0, self.body_radius * 0.6),
                Vec3(0, 0, -self.body_radius * 0.6),
            ):
                hit = raycast(
                    self.position + offset + Vec3(0, self.height - 0.02, 0),
                    Vec3(0, 1, 0),
                    distance=dy + 0.06,
                    traverse_target=self.traverse_target,
                    ignore=self.ignore_list,
                )
                if hit.hit:
                    ceiling_hits.append(hit.distance)
            if ceiling_hits:
                dy = max(0.0, min(ceiling_hits) - 0.03)
                self.vertical_velocity = 0.0

        target_y = self.y + dy
        if dy < 0:
            fall_distance = abs(dy)
            if ground_distance <= fall_distance + 0.02:
                target_y = self.y - ground_distance
                self.vertical_velocity = 0.0
                self.grounded = True

        if self._can_stand_up(target_y):
            self.y = target_y
        else:
            # If blocked by geometry, stop vertical motion to avoid ghosting.
            self.vertical_velocity = 0.0
            self.grounded = True

        # Hold-space auto jump.
        if held_keys["space"] and self.grounded:
            self.jump()

        # Footstep cadence while grounded and moving.
        if self.grounded and moved_horizontally:
            step_interval = 0.30 if self.sprint_active else 0.44
            self._step_timer += time.dt
            if self._step_timer >= step_interval:
                if callable(self.on_footstep):
                    self.on_footstep(self.sprint_active)
                self._step_timer = 0.0
        else:
            self._step_timer = 0.0

    def input(self, key: str) -> None:
        if key == "space":
            self.jump()

    def jump(self) -> None:
        if not self.grounded:
            return
        self.grounded = False
        self.vertical_velocity = self.jump_velocity
