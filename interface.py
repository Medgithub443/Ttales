import os
import sys
import time
import ctypes
import textwrap
import shutil

# --- Цвета (ретро-терминал как на MEME-картинке YOU CLIMB A TREE. MORE FOREST.) ---
GREEN = "\033[1;92m"
GREEN_DIM = "\033[92m"
RESET = "\033[0m"

# Поля по умолчанию (могут перенастраиваться из settings.json через set_padding)
LEFT_PAD = 4
RIGHT_PAD = 4
TOP_PAD = 2  # в строках


# ----------------------------------------------------------------------------
# Внутренние утилиты
# ----------------------------------------------------------------------------

def _get_terminal_width():
    try:
        size = shutil.get_terminal_size((100, 24))
        return max(20, size.columns)
    except Exception:
        return 100


def set_padding(left=None, right=None, top=None):
    """Перенастраивает отступы — вызывается из main.py после загрузки settings."""
    global LEFT_PAD, RIGHT_PAD, TOP_PAD
    if left is not None:
        LEFT_PAD = max(0, int(left))
    if right is not None:
        RIGHT_PAD = max(0, int(right))
    if top is not None:
        TOP_PAD = max(0, int(top))


def _wrap_lines(text, width=None):
    if width is None:
        width = _get_terminal_width()
    usable = max(10, width - LEFT_PAD - RIGHT_PAD)
    result = []
    for raw_line in text.split('\n'):
        if raw_line.strip():
            wrapped = textwrap.wrap(
                raw_line,
                width=usable,
                break_long_words=False,
                break_on_hyphens=False,
            )
            result.extend(wrapped if wrapped else [''])
        else:
            result.append('')
    return result


# ----------------------------------------------------------------------------
# Инициализация консоли
# ----------------------------------------------------------------------------

def init_ansi():
    if os.name == 'nt':
        os.system('')
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
        try:
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass


def enter_fullscreen():
    if os.name != 'nt':
        return
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    try:
        STD_OUTPUT_HANDLE = ctypes.c_void_p(-11)
        CONSOLE_FULLSCREEN_MODE = 1
        h_out = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        if kernel32.SetConsoleDisplayMode(h_out, CONSOLE_FULLSCREEN_MODE, None):
            return
    except (AttributeError, OSError, ValueError):
        pass
    try:
        VK_F11 = 0x7A
        KEYEVENTF_KEYUP = 0x0002
        user32.keybd_event(VK_F11, 0, 0, 0)
        time.sleep(0.05)
        user32.keybd_event(VK_F11, 0, KEYEVENTF_KEYUP, 0)
    except Exception:
        try:
            hwnd = kernel32.GetConsoleWindow()
            if hwnd:
                user32.ShowWindow(hwnd, 3)
                user32.UpdateWindow(hwnd)
        except Exception:
            pass


def maximize_console():
    enter_fullscreen()


# ----------------------------------------------------------------------------
# Вывод
# ----------------------------------------------------------------------------

def clear_terminal():
    """Очищает экран с верхним отступом TOP_PAD строк."""
    os.system('cls' if os.name == 'nt' else 'clear')
    print('\n' * TOP_PAD)


def print_blank():
    print()


def print_with_padding(text):
    for line in _wrap_lines(text):
        if line:
            print(f"{' ' * LEFT_PAD}{GREEN}{line}{RESET}")
        else:
            print()


def type_text(text, delay=0.01):
    sys.stdout.write(GREEN)
    lines = _wrap_lines(text)
    for i, line in enumerate(lines):
        sys.stdout.write(' ' * LEFT_PAD)
        for char in line:
            sys.stdout.write(char)
            sys.stdout.flush()
            time.sleep(delay)
        if i < len(lines) - 1:
            sys.stdout.write('\n')
    sys.stdout.write(RESET + '\n')


def print_centered(text):
    width = _get_terminal_width()
    usable = max(10, width - LEFT_PAD - RIGHT_PAD)
    for line in text.split('\n'):
        if line:
            pad = max(0, (usable - len(line)) // 2)
            print(f"{' ' * LEFT_PAD}{' ' * pad}{GREEN}{line}{RESET}")
        else:
            print()


# ----------------------------------------------------------------------------
# Ввод
# ----------------------------------------------------------------------------

def get_input():
    sys.stdout.write(f"\n{' ' * LEFT_PAD}{GREEN}>> {RESET}")
    sys.stdout.flush()
    try:
        return input().lower().strip()
    except (EOFError, KeyboardInterrupt):
        raise
