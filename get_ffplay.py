#!/usr/bin/env python3
"""
get_ffplay.py — скачивает готовую сборку FFmpeg для Windows и извлекает
только ffplay.exe в tools/ffmpeg/.

Запуск:
    python scripts/get_ffplay.py

Что делает:
  1. Скачивает ffmpeg-release-essentials.zip (~109 MB) с gyan.dev
     — официальные подписанные сборки FFmpeg для Windows.
  2. Извлекает ТОЛЬКО ffplay.exe (~10 MB) в tools/ffmpeg/ffplay.exe.
  3. Удаляет скачанный ZIP.

После этого:
  - audio_backend "opusdec" автоматически использует ffplay для FX
    (гибридный режим: bg через opusdec+winsound, FX через ffplay).
  - audio_backend "ffplay" использует ffplay для всего.
  - audio_backend "auto" выбирает最优ший доступный бэкенд.

Альтернативы ручной установки:
  • winget install "FFmpeg (Essentials Build)"
  • choco install ffmpeg
  • scoop install ffmpeg-essentials
"""

import os
import sys
import urllib.request
import zipfile
import shutil

URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

# Целевая папка: ../tools/ffmpeg/ относительно этого скрипта
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_DIR = os.path.dirname(_SCRIPT_DIR)
DEST_DIR = os.path.join(_PROJECT_DIR, "tools", "ffmpeg")
DEST_FILE = os.path.join(DEST_DIR, "ffplay.exe")


def _progress_hook(block_num, block_size, total_size):
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, downloaded * 100 // total_size)
        mb_down = downloaded / (1024 * 1024)
        mb_total = total_size / (1024 * 1024)
        sys.stdout.write(
            f"\r  {mb_down:6.1f} / {mb_total:6.1f} MB  ({percent:3d}%)"
        )
        sys.stdout.flush()


def main():
    os.makedirs(DEST_DIR, exist_ok=True)

    if os.path.exists(DEST_FILE):
        print(f"ffplay.exe уже существует: {DEST_FILE}")
        print(f"  Размер: {os.path.getsize(DEST_FILE) / (1024 * 1024):.1f} MB")
        try:
            ans = input("Перезаписать? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            ans = ""
        if ans != "y":
            print("Отмена. Текущий ffplay.exe не изменён.")
            return 0

    print()
    print("=== Загрузчик ffplay.exe ===")
    print()
    print(f"Источник: {URL}")
    print(f"Размер ZIP: ~109 MB (извлекаем только ffplay.exe ~10 MB)")
    print(f"Назначение: {DEST_FILE}")
    print()
    print("Это может занять несколько минут в зависимости от скорости сети.")
    print()

    tmp_zip = os.path.join(DEST_DIR, "_ffmpeg_download.zip")

    try:
        print("Скачивание...")
        try:
            urllib.request.urlretrieve(URL, tmp_zip, reporthook=_progress_hook)
        except urllib.error.URLError as e:
            print()
            print(f"\n[ОШИБКА] Не удалось скачать: {e}")
            print()
            print("Альтернативы:")
            print("  1. Скачайте вручную с https://www.gyan.dev/ffmpeg/builds/")
            print("     (файл ffmpeg-release-essentials.zip)")
            print("  2. Распакуйте ffplay.exe из архива в tools/ffmpeg/")
            print()
            print("  Или используйте пакетный менеджер:")
            print("    winget install \"FFmpeg (Essentials Build)\"")
            print("    choco install ffmpeg")
            print("    scoop install ffmpeg-essentials")
            print()
            print("  После установки убедитесь, что ffplay.exe доступен в PATH")
            print("  или скопируйте его в tools/ffmpeg/ffplay.exe.")
            return 1
        print()
        print("Скачивание завершено.")

        print("Извлечение ffplay.exe...")
        try:
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                ffplay_members = [
                    m for m in zf.namelist()
                    if m.endswith("ffplay.exe") and not m.startswith("__")
                ]
                if not ffplay_members:
                    print("[ОШИБКА] ffplay.exe не найден в архиве.")
                    print("Содержимое архива (первые 20 элементов):")
                    for name in zf.namelist()[:20]:
                        print(f"  {name}")
                    return 1
                member = ffplay_members[0]
                print(f"  Извлекаю: {member}")
                with zf.open(member) as src, open(DEST_FILE, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        except zipfile.BadZipFile:
            print("[ОШИБКА] Скачанный файл не является валидным ZIP.")
            return 1

        size_mb = os.path.getsize(DEST_FILE) / (1024 * 1024)
        print()
        print(f"Готово! ffplay.exe сохранён в: {DEST_FILE}")
        print(f"  Размер: {size_mb:.1f} MB")
        print()
        print("=== Что дальше ===")
        print()
        print("Вариант 1 (рекомендуется): оставить audio_backend = \"opusdec\".")
        print("  Движок автоматически использует ffplay для FX (параллельно с bg).")
        print("  bg продолжает играть через opusdec+winsound.")
        print()
        print("Вариант 2: переключиться на чистый ffplay.")
        print("  В settings/settings.json:")
        print('    "audio_backend": "ffplay"')
        print("  Или в меню настроек игры: [4] Сменить аудио-движок.")
        print()
        print("Запустите игру: python boot.py")
        return 0

    finally:
        if os.path.exists(tmp_zip):
            try:
                os.remove(tmp_zip)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
