import storage
from difflib import get_close_matches


def find_next_scene(user_input, actions_dict):
    """Подбирает синоним команды через difflib.
    Возвращает (next_scene_id, matched_phrase) или (None, None).

    v0.5: движок больше не показывает игроку подсказку «понял как ...».
    Но matched_phrase всё равно возвращается — он может использоваться для
    внутренней отладки или логирования.
    """
    if not actions_dict:
        return None, None

    all_possible_phrases = []
    phrase_to_scene = {}

    for next_scene, synonyms in actions_dict.items():
        for synonym in synonyms:
            all_possible_phrases.append(synonym)
            phrase_to_scene[synonym] = next_scene

    matches = get_close_matches(user_input, all_possible_phrases, n=1, cutoff=0.6)
    if matches:
        matched_phrase = matches[0]
        return phrase_to_scene[matched_phrase], matched_phrase
    return None, None


def check_item_requirements(next_scene_id, story_data, inventory):
    """Проверяет, есть ли у игрока нужный предмет для перехода.
    Возвращает (allowed, error_message). Имя предмета берётся из алиасов storage.
    """
    target_scene_data = story_data.get(next_scene_id, {})
    if "required_item" in target_scene_data:
        required = target_scene_data["required_item"]
        if required not in inventory:
            display_name = storage.get_item_name(required)
            return False, f"Вы не можете этого сделать. Нужен предмет: «{display_name}»."
    return True, ""


def check_flags_requirements(next_scene_id, story_data, story_flags):
    """Проверяет, выполнены ли требования по глобальным флагам для перехода.
    Возвращает (allowed, error_message).

    Логика:
      • target_scene["required_flags"] = {"flag_name": bool, ...}
      • Для каждого флага в required_flags движок смотрит текущее значение в
        story_flags (по умолчанию False, если флаг не установлен).
      • Если текущее значение НЕ равно требуемому — переход блокируется.
    """
    target_scene_data = story_data.get(next_scene_id, {})
    required = target_scene_data.get("required_flags")
    if not required:
        return True, ""
    for flag_name, required_value in required.items():
        current_value = bool(story_flags.get(flag_name, False))
        if current_value != bool(required_value):
            return False, "Вы не можете этого сделать. Условия не выполнены."
    return True, ""


def is_meta_command(user_input):
    """True, если строка начинается с '!' — это системная команда."""
    return user_input.startswith("!")


def parse_meta_command(user_input):
    """Разбирает !команду. Возвращает (verb, arg)."""
    body = user_input[1:].strip()
    if not body:
        return "", ""
    parts = body.split(maxsplit=1)
    verb = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""
    return verb, arg
