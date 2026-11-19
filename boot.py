#!/usr/bin/env python3
"""
boot.py — точка входа v0.5.

Проверяет окружение, создаёт недостающие папки и файлы по умолчанию,
информирует пользователя об отсутствующих ресурсах (opusdec.exe, UI-звуки,
сценарии) и затем запускает main.main().

Запуск:
    python boot.py
"""

import os
import sys
import shutil


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _print(msg):
    """Вывод с префиксом [boot]."""
    print(f"[boot] {msg}")


def ensure_folders():
    """Создаёт структуру папок проекта, если её ещё нет."""
    folders = [
        "scenarios",
        "settings",
        "lang",
        "assets/sounds",
        "tools/opus",
        "scripts",
    ]
    for folder in folders:
        path = os.path.join(_BASE_DIR, folder)
        if not os.path.exists(path):
            os.makedirs(path, exist_ok=True)
            _print(f"Создана папка: {folder}/")


def ensure_settings():
    """Если settings/settings.json отсутствует — создаёт с дефолтами."""
    path = os.path.join(_BASE_DIR, "settings", "settings.json")
    if not os.path.exists(path):
        sys.path.insert(0, _BASE_DIR)
        import storage
        storage.save_settings(storage._DEFAULT_SETTINGS)
        _print("Создан settings/settings.json (defaults)")


def check_lang_files():
    """Проверяет наличие хотя бы одного языкового пакета."""
    lang_dir = os.path.join(_BASE_DIR, "lang")
    files = [f for f in os.listdir(lang_dir) if f.endswith(".json")] if os.path.exists(lang_dir) else []
    if not files:
        _print("ВНИМАНИЕ: в папке lang/ нет языковых пакетов (*.json).")
        _print("       Движок запустится, но интерфейс будет на технических ключах.")
        return False
    return True


def check_opusdec():
    """Проверяет наличие opusdec.exe (Windows) или opusdec в PATH (любая ОС)."""
    bundled = os.path.join(_BASE_DIR, "tools", "opus", "opusdec.exe")
    bundled_alt = os.path.join(_BASE_DIR, "tools", "opus", "opusdec")
    in_path = shutil.which("opusdec")

    if os.path.isfile(bundled):
        _print(f"opusdec найден: tools/opus/opusdec.exe")
        return True
    if os.path.isfile(bundled_alt):
        _print(f"opusdec найден: tools/opus/opusdec")
        return True
    if in_path:
        _print(f"opusdec найден в PATH: {in_path}")
        return True

    _print("ВНИМАНИЕ: opusdec не найден.")
    _print("       По умолчанию движок использует opusdec-бэкенд.")
    _print("       Скачайте opus-tools с https://opus-codec.org/downloads/")
    _print("       и положите opusdec.exe в tools/opus/")
    _print("       Либо установите FFmpeg (ffplay) и поменяйте audio_backend на 'ffplay' в settings/settings.json")
    return False


def check_ffplay():
    """Дополнительная проверка ffplay как запасного бэкенда."""
    p = shutil.which("ffplay")
    if p:
        _print(f"ffplay (запасной бэкенд) найден в PATH: {p}")
        return True
    return False


def check_ui_sounds():
    """Проверяет наличие UI-звуков в assets/sounds/."""
    sounds_dir = os.path.join(_BASE_DIR, "assets", "sounds")
    required = ["main_menu_ambient.opus", "main_menu_choice.opus"]
    missing = [s for s in required if not os.path.isfile(os.path.join(sounds_dir, s))]
    if missing:
        _print(f"ВНИМАНИЕ: в assets/sounds/ отсутствуют: {', '.join(missing)}")
        _print("       Меню будет без звука. Положите opus-файлы в assets/sounds/.")
        _print("       • main_menu_ambient.opus — фоновый эмбиент меню (зацикленный)")
        _print("       • main_menu_choice.opus — одноразовый клик при нажатии Enter в меню/настройках")
        return False
    _print(f"UI-звуки найдены: {len(required)} файлов в assets/sounds/")
    return True


def check_scenarios():
    """Проверяет наличие хотя бы одного ZIP-сценария."""
    sc_dir = os.path.join(_BASE_DIR, "scenarios")
    zips = [f for f in os.listdir(sc_dir) if f.lower().endswith(".zip")] if os.path.exists(sc_dir) else []
    if not zips:
        _print("ВНИМАНИЕ: в папке scenarios/ нет ZIP-архивов историй.")
        _print("       Играть будет не во что. Положите .zip в scenarios/.")
        _print("       Собрать свой сценарий: python scripts/build_scenario.py --help")
        return False
    _print(f"Сценариев найдено: {len(zips)}")
    return True


def main():
    print()
    print("=" * 60)
    print(" Текстовый квест-движок v0.5 — bootstrap")
    print("=" * 60)
    print()

    _print("Проверка окружения...")
    print()

    ensure_folders()
    ensure_settings()
    check_lang_files()
    check_opusdec()
    check_ffplay()
    check_ui_sounds()
    check_scenarios()

    print()
    _print("Проверка завершена. Запуск игры...")
    print()

    # Импортируем main после подготовки окружения
    sys.path.insert(0, _BASE_DIR)
    import main
    main.main()


if __name__ == "__main__":
    main()
