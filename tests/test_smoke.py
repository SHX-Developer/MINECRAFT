def test_project_layout_imports() -> None:
    from minecraft_ursina.core.game import run_game

    assert callable(run_game)
