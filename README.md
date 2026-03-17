# Minecraft Ursina Starter

Стартовая структура проекта для 3D-игры в стиле Minecraft на Python + Ursina.

## Быстрый старт

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

## Структура

- `main.py` — точка входа
- `src/minecraft_ursina/core/` — базовый игровой цикл и настройки
- `src/minecraft_ursina/world/` — генерация мира, блоки, чанки
- `src/minecraft_ursina/player/` — игрок, контроллер, инвентарь
- `src/minecraft_ursina/ui/` — HUD, меню, интерфейсы
- `src/minecraft_ursina/assets/` — текстуры, модели, звуки
- `src/minecraft_ursina/utils/` — утилиты
- `tests/` — тесты

## Следующий шаг

Реализовать:
1. `Block` entity
2. Простую генерацию плоского мира
3. ЛКМ/ПКМ для ломания и установки блока
