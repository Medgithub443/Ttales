import sys
import time

import interface
import storage
import logic
import audio

# Внутреннее состояние текущей игровой сессии
inventory = []
visited_scenes = []
story_flags = {}        # v0.5: глобальные флаги истории
audio_manager = None
settings = None

# v0.5: UI-звуки из assets/sounds/. Кешируем пути при первом обращении.
_MENU_AMBIENT_PATH = None
_MENU_CHOICE_PATH = None


def t(key, **kwargs):
    return storage.translate(key, **kwargs)


# ----------------------------------------------------------------------------
# UI-звуки (assets/sounds/)
# ----------------------------------------------------------------------------

def _menu_ambient_path():
    global _MENU_AMBIENT_PATH
    if _MENU_AMBIENT_PATH is None:
        _MENU_AMBIENT_PATH = storage.get_asset_sound_path("main_menu_ambient")
    return _MENU_AMBIENT_PATH


def _menu_choice_path():
    global _MENU_CHOICE_PATH
    if _MENU_CHOICE_PATH is None:
        _MENU_CHOICE_PATH = storage.get_asset_sound_path("main_menu_choice")
    return _MENU_CHOICE_PATH


def _play_menu_ambient():
    """Запускает фоновый эмбиент главного меню (если включён звук и файл есть)."""
    if not audio_manager or not settings.get('sound_enabled', True):
        return
    path = _menu_ambient_path()
    if path:
        audio_manager.play_background(path)


def _play_menu_choice():
    """Проигрывает одноразовый UI-клик при нажатии Enter в меню/настройках.

    v0.5 нюанс: на opusdec-бэкенде winsound однопоточный — FX остановит
    фон. Если бэкенд не поддерживает параллельное аудио, мы НЕ проигрываем
    UI-клик, чтобы сохранить атмосферу меню.
    """
    if not audio_manager or not settings.get('sound_enabled', True):
        return
    if not audio_manager.supports_parallel_audio:
        return  # не портишь ambient
    path = _menu_choice_path()
    if path:
        audio_manager.play_oneshot(path)


# ----------------------------------------------------------------------------
# Главное меню
# ----------------------------------------------------------------------------

def run_menu():
    """Показывает список доступных историй. Возвращает info-словарь сценария или None."""
    _play_menu_ambient()

    while True:
        interface.clear_terminal()
        scenarios = storage.get_available_scenarios()

        if not scenarios:
            interface.print_with_padding(t('error.no_scenarios'))
            input()
            continue

        interface.print_with_padding(t('menu.title'))
        saves = storage.load_saves()
        for index, info in enumerate(scenarios, start=1):
            name = info['name']
            filename = info['filename']
            has_save = f" {t('menu.has_save')}" if filename in saves else ""
            interface.print_with_padding(f"[{index}] {name}{has_save}")

        interface.print_with_padding(t('menu.settings'))
        interface.print_with_padding(t('menu.exit'))

        choice = interface.get_input()
        if choice == "0":
            return None
        if choice in ("-1", "settings", "настройки"):
            _play_menu_choice()
            settings_menu_loop()
            # После выхода из настроек — фон уже играет (или перезапустится ниже)
            _play_menu_ambient()
            continue
        if choice.lstrip("-").isdigit():
            if choice.startswith("-"):
                continue
            idx = int(choice) - 1
            if 0 <= idx < len(scenarios):
                _play_menu_choice()
                return scenarios[idx]


# ----------------------------------------------------------------------------
# Меню настроек
# ----------------------------------------------------------------------------

def settings_menu_loop():
    global audio_manager
    # ambient меню продолжает играть во время настроек (если бэкенд поддерживает
    # параллельное аудио — а если нет, то он и так играет, FX нет)
    while True:
        interface.clear_terminal()
        interface.print_with_padding(t('settings.title'))
        interface.print_blank()

        interface.print_with_padding(
            f"  {t('settings.language')}: {settings.get('language', 'ru')}"
        )
        snd_state = t('state.on') if settings.get('sound_enabled', True) else t('state.off')
        interface.print_with_padding(f"  {t('settings.sound')}: {snd_state}")
        interface.print_with_padding(
            f"  {t('settings.volume')}: {int(settings.get('sound_volume', 0.7) * 100)}%"
        )
        backend_display = settings.get('audio_backend', 'opusdec')
        active_backend = audio_manager.backend_name if audio_manager else "none"
        interface.print_with_padding(
            f"  {t('settings.audio_backend')}: {backend_display} [{active_backend}]"
        )
        interface.print_with_padding(
            f"  {t('settings.typing_speed')}: {settings.get('typing_speed', 0.01):.3f}"
        )
        margins = settings.get('margins', {})
        interface.print_with_padding(
            f"  {t('settings.margins')}: "
            f"L={margins.get('left', 4)} R={margins.get('right', 4)} T={margins.get('top', 2)}"
        )
        fs_state = t('state.on') if settings.get('fullscreen_on_start', True) else t('state.off')
        interface.print_with_padding(f"  {t('settings.fullscreen')}: {fs_state}")
        interface.print_blank()

        interface.print_with_padding(t('settings.opt.language'))
        interface.print_with_padding(t('settings.opt.sound'))
        interface.print_with_padding(t('settings.opt.volume'))
        interface.print_with_padding(t('settings.opt.backend'))
        interface.print_with_padding(t('settings.opt.typing'))
        interface.print_with_padding(t('settings.opt.margins'))
        interface.print_with_padding(t('settings.opt.fullscreen'))
        interface.print_with_padding(t('settings.opt.back'))

        choice = interface.get_input()
        if choice == "0":
            _play_menu_choice()
            return
        elif choice == "1":
            _play_menu_choice()
            _settings_change_language()
        elif choice == "2":
            _play_menu_choice()
            settings['sound_enabled'] = not settings.get('sound_enabled', True)
            if audio_manager:
                audio_manager.set_enabled(settings['sound_enabled'])
            storage.save_settings(settings)
        elif choice == "3":
            _play_menu_choice()
            _settings_change_volume()
        elif choice == "4":
            _play_menu_choice()
            _settings_change_backend()
        elif choice == "5":
            _play_menu_choice()
            _settings_change_typing()
        elif choice == "6":
            _play_menu_choice()
            _settings_change_margins()
        elif choice == "7":
            _play_menu_choice()
            settings['fullscreen_on_start'] = not settings.get('fullscreen_on_start', True)
            storage.save_settings(settings)
            if settings['fullscreen_on_start']:
                interface.enter_fullscreen()


def _settings_change_language():
    available = storage.list_available_languages()
    if not available:
        return
    current = settings.get('language', 'ru')
    try:
        idx = available.index(current)
        settings['language'] = available[(idx + 1) % len(available)]
    except ValueError:
        settings['language'] = available[0]
    storage.set_language(settings['language'])
    storage.save_settings(settings)


def _settings_change_volume():
    interface.print_with_padding(t('settings.prompt.volume'))
    val = interface.get_input()
    try:
        v = max(0, min(100, int(val)))
        settings['sound_volume'] = v / 100.0
        if audio_manager:
            audio_manager.set_volume(settings['sound_volume'])
        storage.save_settings(settings)
    except ValueError:
        pass


def _settings_change_backend():
    backends = ['opusdec', 'ffplay', 'auto', 'none']
    current = settings.get('audio_backend', 'opusdec')
    try:
        idx = backends.index(current)
        settings['audio_backend'] = backends[(idx + 1) % len(backends)]
    except ValueError:
        settings['audio_backend'] = 'opusdec'
    global audio_manager
    if audio_manager:
        audio_manager.stop_all()
        audio_manager.close()
    audio_manager = audio.AudioManager(settings)
    storage.save_settings(settings)
    # После смены бэкенда — перезапускаем menu ambient, чтобы он играл на новом бэкенде
    _play_menu_ambient()


def _settings_change_typing():
    interface.print_with_padding(t('settings.prompt.typing'))
    val = interface.get_input()
    try:
        v = float(val)
        v = max(0.0, min(0.5, v))
        settings['typing_speed'] = v
        storage.save_settings(settings)
    except ValueError:
        pass


def _settings_change_margins():
    interface.print_with_padding(t('settings.prompt.margins'))
    val = interface.get_input()
    parts = val.replace(',', ' ').split()
    try:
        if len(parts) >= 1:
            settings.setdefault('margins', {})['left'] = max(0, int(parts[0]))
        if len(parts) >= 2:
            settings['margins']['right'] = max(0, int(parts[1]))
        if len(parts) >= 3:
            settings['margins']['top'] = max(0, int(parts[2]))
        interface.set_padding(
            left=settings['margins'].get('left', 4),
            right=settings['margins'].get('right', 4),
            top=settings['margins'].get('top', 2),
        )
        storage.save_settings(settings)
    except ValueError:
        pass


# ----------------------------------------------------------------------------
# Системные команды (!)
# ----------------------------------------------------------------------------

def show_help():
    lines = [t('help.title')]
    rows = [
        ("!exit / !menu", 'help.exit'),
        ("!i / !inv / !inventory", 'help.inventory'),
        ("!look", 'help.look'),
        ("!save", 'help.save'),
        ("!sound on|off", 'help.sound'),
        ("!volume N", 'help.volume'),
        ("!help", 'help.help'),
    ]
    for cmd, desc_key in rows:
        lines.append(f"  {cmd:<26} — {t(desc_key)}")
    return "\n".join(lines)


def handle_meta_command(verb, arg, story, current_scene, save_key):
    if verb in ("exit", "quit", "menu"):
        return None, "exit"

    if verb in ("i", "inv", "inventory"):
        if not inventory:
            return f"{t('inventory.title')}\n{t('inventory.empty')}", "message"
        lines = [t('inventory.title')]
        for item in inventory:
            display = storage.get_item_name(item)
            lines.append(f"  - {display}")
        return "\n".join(lines), "message"

    if verb == "look":
        return None, "look"

    if verb == "save":
        storage.save_progress(save_key, current_scene, inventory, visited_scenes, story_flags)
        return t('save.saved'), "message"

    if verb == "sound":
        if arg in ("on", "1", "true", "yes", "вкл"):
            settings['sound_enabled'] = True
            if audio_manager:
                audio_manager.set_enabled(True)
            storage.save_settings(settings)
            return t('sound.on'), "message"
        elif arg in ("off", "0", "false", "no", "выкл"):
            settings['sound_enabled'] = False
            if audio_manager:
                audio_manager.set_enabled(False)
            storage.save_settings(settings)
            return t('sound.off'), "message"
        elif not arg:
            state = "ON" if settings.get('sound_enabled', True) else "OFF"
            return t('sound.status', state=state), "message"
        else:
            return t('sound.invalid'), "message"

    if verb == "volume":
        try:
            v = int(arg)
            v = max(0, min(100, v))
            settings['sound_volume'] = v / 100.0
            if audio_manager:
                audio_manager.set_volume(settings['sound_volume'])
            storage.save_settings(settings)
            return t('volume.set', value=v), "message"
        except (ValueError, TypeError):
            return t('volume.invalid'), "message"

    if verb in ("help", "?", "h"):
        return show_help(), "message"

    return t('meta.unknown', cmd=f"!{verb}"), "message"


# ----------------------------------------------------------------------------
# Звуки при входе на сцену (v0.5: продолжение bg по умолчанию, sound_stop = тишина)
# ----------------------------------------------------------------------------

def play_scene_sounds(scene_data):
    """v0.5 логика звуков:
      • sound_bg задан        → переключить фон на новый (старый останавливается)
      • sound_stop: true      → остановить текущий фон (явная тишина)
      • ни того, ни другого   → ПРОДОЛЖАТЬ играть старый фон бесшовно
      • sound_fx задан        → проиграть одноразовый эффект
                                (на opusdec-бэкенде он остановит bg; bg возобновится
                                на следующей сцене без sound_stop)
    """
    if not settings.get('sound_enabled', True) or audio_manager is None:
        return

    bg = scene_data.get('sound_bg')
    fx = scene_data.get('sound_fx')
    stop = scene_data.get('sound_stop', False)

    if bg:
        path = storage.get_sound_path(bg)
        if path:
            audio_manager.play_background(path)
        else:
            # Звук указан, но файла нет — останавливаем текущий, чтобы не было
            # несоответствия между «ожидаем новый фон» и «играет старый».
            audio_manager.stop_background()
    elif stop:
        audio_manager.stop_background()
    # else: продолжаем играть старый фон (v0.5 бесшовность)

    if fx:
        path = storage.get_sound_path(fx)
        if path:
            audio_manager.play_oneshot(path)


# ----------------------------------------------------------------------------
# Применение эффектов сцены (предметы, флаги)
# ----------------------------------------------------------------------------

def apply_scene_effects(scene_data):
    """Применяется при входе на сцену: выдаёт/забирает предметы, выставляет флаги."""
    # Выдача предмета
    if "get_item" in scene_data and scene_data["get_item"] not in inventory:
        inventory.append(scene_data["get_item"])

    # v0.5: Изъятие предмета (take_away_item)
    if "take_away_item" in scene_data:
        item_id = scene_data["take_away_item"]
        if item_id in inventory:
            inventory.remove(item_id)

    # v0.5: Установка флагов (set_flags)
    flags_to_set = scene_data.get("set_flags")
    if flags_to_set and isinstance(flags_to_set, dict):
        for flag_name, flag_value in flags_to_set.items():
            story_flags[flag_name] = bool(flag_value)


# ----------------------------------------------------------------------------
# Точка входа
# ----------------------------------------------------------------------------

def main():
    global inventory, visited_scenes, story_flags, audio_manager, settings

    # 1) Настройки и язык интерфейса
    settings = storage.load_settings()
    storage.load_lang_pack()
    storage.set_language(settings.get('language', 'ru'))

    # 2) Отступы (левый, правый, верхний)
    margins = settings.get('margins', {})
    interface.set_padding(
        left=margins.get('left', 4),
        right=margins.get('right', 4),
        top=margins.get('top', 2),
    )

    # 3) Инициализация консоли
    interface.init_ansi()
    if settings.get('fullscreen_on_start', True):
        interface.enter_fullscreen()

    # 4) Аудио-менеджер (v0.5: по умолчанию opusdec)
    audio_manager = audio.AudioManager(settings)

    # ---- Главный цикл программы ----
    while True:
        inventory = []
        visited_scenes = []
        story_flags = {}      # v0.5: сброс флагов на новую игру

        selected = run_menu()
        if not selected:
            interface.clear_terminal()
            interface.print_with_padding(t('goodbye'))
            time.sleep(1)
            audio_manager.stop_all()
            break

        # При входе в сценарий — останавливаем menu ambient
        audio_manager.stop_background()

        archive = storage.open_story_archive(selected['path'])
        if not archive or not archive['stories']:
            interface.clear_terminal()
            interface.print_with_padding(t('error.corrupted', name=selected['name']))
            sys.stdout.write(f"\n{' ' * interface.LEFT_PAD}{t('game.press_enter')}")
            input()
            storage.close_story_archive()
            continue

        manifest = archive['manifest']
        story_lang = settings.get('language', 'ru')
        if story_lang not in archive['stories'] or archive['stories'][story_lang] is None:
            story_lang = next(
                (code for code in manifest.get('languages', [])
                 if archive['stories'].get(code)),
                None
            )
        if not story_lang:
            interface.clear_terminal()
            interface.print_with_padding(t('error.no_lang'))
            sys.stdout.write(f"\n{' ' * interface.LEFT_PAD}{t('game.press_enter')}")
            input()
            storage.close_story_archive()
            continue

        story = archive['stories'][story_lang]
        storage.set_active_item_names(story_lang)

        # v0.5: стартовая сцена — из manifest.start_scene (с fallback на первый ключ)
        start_scene_id = storage.get_start_scene()
        if start_scene_id and start_scene_id in story:
            current_scene = start_scene_id
        else:
            current_scene = list(story.keys())[0] if story else ""

        # Загрузка сохранения (v0.5: с story_flags)
        save_key = selected['filename']
        saves = storage.load_saves()
        if save_key in saves:
            save_data = saves[save_key]
            if isinstance(save_data, dict) and "current_scene" in save_data:
                saved_scene = save_data["current_scene"]
                if saved_scene in story:
                    interface.clear_terminal()
                    interface.print_with_padding(t('save.found', name=selected['name']))
                    interface.print_with_padding(t('menu.continue'))
                    interface.print_with_padding(t('menu.restart'))

                    if interface.get_input() == "1":
                        current_scene = saved_scene
                        inventory = save_data.get("inventory", [])
                        visited_scenes = save_data.get("visited_scenes", [])
                        story_flags = save_data.get("story_flags", {})
                        if current_scene in visited_scenes:
                            visited_scenes.remove(current_scene)

        interface.clear_terminal()
        interface.print_with_padding(t('menu.scenario_start', name=selected['name'].upper()))

        scene_changed = True
        system_message = ""
        clear_screen_next = True

        # ---- Игровой цикл текущей истории ----
        while True:
            try:
                if clear_screen_next:
                    interface.clear_terminal()
                clear_screen_next = True

                scene_data = story[current_scene]

                if system_message:
                    interface.print_with_padding(system_message)
                    interface.print_blank()
                    system_message = ""

                # v0.5: эффекты сцены (предметы + флаги) — перед показом текста,
                # чтобы выдача/изъятие отразились сразу.
                apply_scene_effects(scene_data)

                # Какой текст показывать
                if current_scene in visited_scenes and "text_visited" in scene_data:
                    text_to_show = scene_data["text_visited"]
                else:
                    text_to_show = scene_data.get("text", "")

                if current_scene not in visited_scenes:
                    visited_scenes.append(current_scene)

                # Звуки сцены — только при реальной смене сцены.
                # v0.5.1: раньше play_scene_sounds вызывался на каждой итерации цикла,
                # в том числе при пустом Enter — это приводило к повторам FX и
                # рестартам bg. Теперь звуки играют только при первом входе на сцену
                # (scene_changed=True устанавливается при переходе и при !look).
                if scene_changed:
                    play_scene_sounds(scene_data)

                # Рендер текста
                if scene_changed:
                    interface.type_text(text_to_show,
                                        delay=settings.get('typing_speed', 0.01))
                    scene_changed = False
                else:
                    interface.print_with_padding(text_to_show)

                # Конечная ветка (v0.5: ЗВУКИ ПРОДОЛЖАЮТ ИГРАТЬ во время ожидания Enter)
                actions = scene_data.get("actions", {})
                if not actions:
                    interface.print_blank()
                    interface.print_with_padding(t('game.end'))
                    storage.delete_save(save_key)
                    # ВАЖНО: НЕ вызываем audio_manager.stop_all() здесь.
                    # Игрок должен дослушать звуки. Останавливаем только когда
                    # он подтвердил выход (нажал Enter).
                    sys.stdout.write(f"\n{' ' * interface.LEFT_PAD}{t('game.press_enter')}")
                    input()
                    # Теперь, когда игрок подтвердил выход — останавливаем звуки.
                    audio_manager.stop_all()
                    break

                user_input = interface.get_input()
                if not user_input:
                    clear_screen_next = False
                    continue

                # Системные команды (!)
                if logic.is_meta_command(user_input):
                    verb, arg = logic.parse_meta_command(user_input)
                    if not verb:
                        clear_screen_next = False
                        continue
                    msg, action = handle_meta_command(
                        verb, arg, story, current_scene, save_key
                    )
                    if action == "exit":
                        raise KeyboardInterrupt
                    elif action == "look":
                        scene_changed = True
                        if msg:
                            system_message = msg
                    else:
                        if msg:
                            system_message = msg
                        else:
                            clear_screen_next = False
                    continue

                # Игровая команда — подбор синонима
                next_scene, matched_phrase = logic.find_next_scene(user_input, actions)

                if next_scene:
                    # v0.5: проверка и предмета, и флагов
                    allowed, error_msg = logic.check_item_requirements(next_scene, story, inventory)
                    if not allowed:
                        system_message = error_msg
                        continue
                    allowed, error_msg = logic.check_flags_requirements(next_scene, story, story_flags)
                    if not allowed:
                        system_message = error_msg
                        continue

                    current_scene = next_scene
                    scene_changed = True
                    storage.save_progress(save_key, current_scene, inventory,
                                          visited_scenes, story_flags)
                    # v0.5: хинт «понял как ...» удалён — движок молча переходит
                else:
                    system_message = t('game.unknown_command')

            except KeyboardInterrupt:
                # Ctrl+C или !exit — пользователь явно решил выйти
                storage.save_progress(save_key, current_scene, inventory,
                                      visited_scenes, story_flags)
                audio_manager.stop_all()
                interface.clear_terminal()
                interface.print_with_padding(t('interrupt.title'))
                interface.print_with_padding(t('interrupt.return'))
                time.sleep(1.2)
                break

        storage.close_story_archive()

    # При полном выходе из программы — освобождаем ресурсы аудио
    audio_manager.close()


if __name__ == "__main__":
    main()
