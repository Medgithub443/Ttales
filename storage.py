import os
import sys
import json
import zipfile
import tempfile
import shutil

# ----------------------------------------------------------------------------
# Пути (привязаны к расположению этого файла, а не к CWD)
# ----------------------------------------------------------------------------

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STORY_DIRECTORY = os.path.join(_BASE_DIR, "scenarios")
SETTINGS_DIRECTORY = os.path.join(_BASE_DIR, "settings")
LANG_DIRECTORY = os.path.join(_BASE_DIR, "lang")
ASSETS_SOUNDS_DIRECTORY = os.path.join(_BASE_DIR, "assets", "sounds")
SETTINGS_FILE = os.path.join(SETTINGS_DIRECTORY, "settings.json")
SAVE_FILE = os.path.join(_BASE_DIR, "saves.json")


def ensure_folders():
    """Создаёт нужные папки, если их ещё нет."""
    for d in (STORY_DIRECTORY, SETTINGS_DIRECTORY, LANG_DIRECTORY, ASSETS_SOUNDS_DIRECTORY):
        if not os.path.exists(d):
            os.makedirs(d)


# ----------------------------------------------------------------------------
# Кеш открытого архива текущей истории
# ----------------------------------------------------------------------------

_active_archive = {
    'zip': None,
    'path': None,
    'manifest': None,
    'item_names': {},
    'item_names_per_lang': {},
    'sounds_dir': None,
    'sound_cache': {},
}


# ----------------------------------------------------------------------------
# Поиск сценариев
# ----------------------------------------------------------------------------

def get_available_scenarios():
    """Возвращает список [{'filename','path','name','languages','start_scene'}] отсортированный по имени."""
    ensure_folders()
    result = []
    for filename in sorted(os.listdir(STORY_DIRECTORY)):
        if not filename.lower().endswith('.zip'):
            continue
        path = os.path.join(STORY_DIRECTORY, filename)
        info = {'filename': filename, 'path': path, 'name': filename,
                'languages': [], 'start_scene': None}
        try:
            with zipfile.ZipFile(path, 'r') as zf:
                if 'manifest.json' in zf.namelist():
                    manifest = json.loads(zf.read('manifest.json'))
                    info['name'] = manifest.get('name', filename)
                    info['languages'] = manifest.get('languages', [])
                    info['start_scene'] = manifest.get('start_scene')
        except (zipfile.BadZipFile, json.JSONDecodeError, KeyError):
            info['name'] = filename + " (повреждён)"
        result.append(info)
    return result


# ----------------------------------------------------------------------------
# Открытие архива истории (v0.5: без проверки контрольной суммы)
# ----------------------------------------------------------------------------

def open_story_archive(zip_path):
    """Открывает ZIP-архив истории. Возвращает dict с manifest, stories, item_names_per_lang.

    Поддерживает два формата JSON:
      1) Новый (v0.5): {"item_names": {...}, "scenes": {...}}
      2) Legacy (плоский): {scene_id: {...}, ...}
    Контрольная сумма НЕ проверяется — ZIP CRC32 достаточно.
    """
    global _active_archive
    close_story_archive()

    zf = zipfile.ZipFile(zip_path, 'r')
    names = zf.namelist()

    if 'manifest.json' not in names:
        zf.close()
        return None

    try:
        manifest = json.loads(zf.read('manifest.json'))
    except json.JSONDecodeError:
        zf.close()
        return None

    stories = {}
    item_names_per_lang = {}
    for lang_code in manifest.get('languages', []):
        story_filename = f"{lang_code}.json"
        if story_filename not in names:
            continue
        try:
            raw = json.loads(zf.read(story_filename))
        except json.JSONDecodeError:
            stories[lang_code] = None
            item_names_per_lang[lang_code] = {}
            continue

        if isinstance(raw, dict) and 'scenes' in raw and isinstance(raw['scenes'], dict):
            stories[lang_code] = raw['scenes']
            item_names_per_lang[lang_code] = raw.get('item_names', {}) or {}
        else:
            stories[lang_code] = raw if isinstance(raw, dict) else {}
            item_names_per_lang[lang_code] = {}

    _active_archive = {
        'zip': zf,
        'path': zip_path,
        'manifest': manifest,
        'item_names': {},
        'item_names_per_lang': item_names_per_lang,
        'sounds_dir': None,
        'sound_cache': {},
    }

    return {
        'manifest': manifest,
        'stories': stories,
        'item_names_per_lang': item_names_per_lang,
    }


def close_story_archive():
    global _active_archive
    if _active_archive['zip'] is not None:
        try:
            _active_archive['zip'].close()
        except Exception:
            pass
    if _active_archive['sounds_dir'] and os.path.exists(_active_archive['sounds_dir']):
        try:
            shutil.rmtree(_active_archive['sounds_dir'], ignore_errors=True)
        except Exception:
            pass
    _active_archive = {
        'zip': None,
        'path': None,
        'manifest': None,
        'item_names': {},
        'item_names_per_lang': {},
        'sounds_dir': None,
        'sound_cache': {},
    }


def set_active_item_names(lang):
    per_lang = _active_archive.get('item_names_per_lang', {})
    _active_archive['item_names'] = per_lang.get(lang, {})


def get_item_name(item_id):
    return _active_archive.get('item_names', {}).get(item_id, item_id)


def get_start_scene():
    """Возвращает start_scene из активного манифеста или None (тогда движок использует первый ключ)."""
    manifest = _active_archive.get('manifest') or {}
    return manifest.get('start_scene')


# ----------------------------------------------------------------------------
# Звуки: извлечение opus из архива истории во временную папку
# ----------------------------------------------------------------------------

def get_sound_path(sound_name):
    """Возвращает локальный путь к opus-файлу по имени, извлекая из архива при необходимости.
    Возвращает None, если файла нет.
    """
    if _active_archive['zip'] is None:
        return None

    if sound_name in _active_archive['sound_cache']:
        return _active_archive['sound_cache'][sound_name]

    zf = _active_archive['zip']
    candidates = [
        f"sounds/{sound_name}.opus",
        f"sounds/{sound_name}",
        f"{sound_name}.opus",
    ]
    found = None
    for c in candidates:
        if c in zf.namelist():
            found = c
            break
    if not found:
        return None

    if _active_archive['sounds_dir'] is None:
        _active_archive['sounds_dir'] = tempfile.mkdtemp(prefix='story_sounds_')

    local_path = os.path.join(_active_archive['sounds_dir'], os.path.basename(found))
    try:
        with open(local_path, 'wb') as f:
            f.write(zf.read(found))
    except Exception:
        return None

    _active_archive['sound_cache'][sound_name] = local_path
    return local_path


# ----------------------------------------------------------------------------
# Звуки движка (assets/sounds/) — не из сценария, а из папки игры
# ----------------------------------------------------------------------------

def get_asset_sound_path(name):
    """Возвращает путь к opus-файлу из assets/sounds/ или None, если файла нет.
    Используется для UI-звуков: main_menu_ambient.opus, main_menu_choice.opus, и т.д.
    """
    ensure_folders()
    candidates = [
        os.path.join(ASSETS_SOUNDS_DIRECTORY, f"{name}.opus"),
        os.path.join(ASSETS_SOUNDS_DIRECTORY, name),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


# ----------------------------------------------------------------------------
# Сохранения игры (v0.5: добавлено story_flags)
# ----------------------------------------------------------------------------

def load_saves():
    if not os.path.exists(SAVE_FILE):
        return {}
    try:
        with open(SAVE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def save_progress(scenario_filename, scene_name, inventory, visited_scenes, story_flags):
    """Записывает прогресс на диск. story_flags — dict {flag_name: bool}."""
    saves = load_saves()
    saves[scenario_filename] = {
        "current_scene": scene_name,
        "inventory": inventory,
        "visited_scenes": visited_scenes,
        "story_flags": story_flags,
    }
    try:
        with open(SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(saves, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


def delete_save(scenario_filename):
    saves = load_saves()
    if scenario_filename in saves:
        del saves[scenario_filename]
        try:
            with open(SAVE_FILE, "w", encoding="utf-8") as f:
                json.dump(saves, f, ensure_ascii=False, indent=2)
        except OSError:
            pass


# ----------------------------------------------------------------------------
# Настройки программы (v0.5: audio_backend=opusdec по умолчанию, margins.top)
# ----------------------------------------------------------------------------

_DEFAULT_SETTINGS = {
    "language": "ru",
    "sound_enabled": True,
    "sound_volume": 0.7,
    "audio_backend": "opusdec",   # v0.5: opusdec — основной по умолчанию
    "typing_speed": 0.01,
    "fullscreen_on_start": True,
    "margins": {
        "left": 4,
        "right": 4,
        "top": 2,
    },
}


def load_settings():
    ensure_folders()
    if not os.path.exists(SETTINGS_FILE):
        save_settings(_DEFAULT_SETTINGS)
        return dict(_DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return dict(_DEFAULT_SETTINGS)

    merged = dict(_DEFAULT_SETTINGS)
    for k, v in _DEFAULT_SETTINGS.items():
        if isinstance(v, dict):
            merged[k] = {**v, **data.get(k, {})}
        else:
            merged[k] = data.get(k, v)
    return merged


def save_settings(settings):
    ensure_folders()
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Языковые пакеты интерфейса (раздельные файлы: lang/ru.json, lang/en.json, ...)
# ----------------------------------------------------------------------------

_lang_data = {}
_current_lang = "ru"


def list_available_languages():
    ensure_folders()
    if not os.path.exists(LANG_DIRECTORY):
        return []
    codes = []
    for fname in sorted(os.listdir(LANG_DIRECTORY)):
        if fname.endswith('.json'):
            codes.append(fname[:-5])
    return codes


def load_lang_pack(lang=None):
    global _lang_data
    ensure_folders()
    if lang is not None:
        path = os.path.join(LANG_DIRECTORY, f"{lang}.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
    _lang_data = {}
    if not os.path.exists(LANG_DIRECTORY):
        return _lang_data
    for fname in os.listdir(LANG_DIRECTORY):
        if not fname.endswith('.json'):
            continue
        code = fname[:-5]
        try:
            with open(os.path.join(LANG_DIRECTORY, fname), "r", encoding="utf-8") as f:
                _lang_data[code] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
    return _lang_data


def set_language(lang):
    global _current_lang
    if not _lang_data:
        load_lang_pack()
    if lang in _lang_data:
        _current_lang = lang
    elif _lang_data:
        _current_lang = list(_lang_data.keys())[0]


def translate(key, **kwargs):
    if not _lang_data:
        load_lang_pack()
    table = _lang_data.get(_current_lang, {})
    text = table.get(key)
    if text is None:
        text = _lang_data.get('en', {}).get(key, key)
    try:
        return text.format(**kwargs)
    except Exception:
        return text
