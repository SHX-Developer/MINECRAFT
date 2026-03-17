from ursina.prefabs.first_person_controller import FirstPersonController


class PlayerController(FirstPersonController):
    """First-person player with Minecraft-like movement bounds."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.speed = 5
        self.gravity = 1
        self.jump_height = 1.1
        self.jump_duration = 0.32
        self.collider = "box"
