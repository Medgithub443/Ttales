import os
import sys
import math
import time
import wave
import atexit
import shutil
import subprocess
import threading
import tempfile

# winsound — только Windows. На других ОС opusdec-бэкенд недоступен.
try:
    import winsound
    _HAS_WINSOUND = True
except ImportError:
    _HAS_WINSOUND = False


# ----------------------------------------------------------------------------
# Поиск бэкендов
# ----------------------------------------------------------------------------

def find_ffplay():
    return shutil.which("ffplay")


def find_opusdec():
    """Ищет opusdec.exe сначала в tools/opus/ рядом со скриптом, потом в PATH."""
    base = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(base, "tools", "opus", "opusdec.exe"),
        os.path.join(base, "tools", "opus", "opusdec"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return shutil.which("opusdec")


# ----------------------------------------------------------------------------
# Базовый интерфейс бэкенда
# ----------------------------------------------------------------------------

class AudioBackend:
    """Абстрактный аудио-бэкенд."""
    name = "null"
    supports_parallel_audio = False  # True, если bg и FX могут играть одновременно

    def play_background(self, opus_path):
        pass

    def stop_background(self):
        pass

    def play_oneshot(self, opus_path):
        pass

    def stop_all(self):
        self.stop_background()

    def set_volume(self, volume):
        pass

    def set_enabled(self, enabled):
        if not enabled:
            self.stop_all()

    def close(self):
        pass


class NullBackend(AudioBackend):
    """Безопасный пустой объект (Null-Object pattern)."""
    name = "null"
    supports_parallel_audio = False


# ----------------------------------------------------------------------------
# FFplay (кроссплатформенный, поддерживает loop, FX и bg независимы)
# ----------------------------------------------------------------------------

class FfplayBackend(AudioBackend):
    name = "ffplay"
    supports_parallel_audio = True   # bg и FX играют параллельно разными процессами

    def __init__(self, ffplay_path, volume=0.7):
        self.ffplay = ffplay_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self._bg_process = None
        self._bg_lock = threading.Lock()

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, float(volume)))

    def play_background(self, opus_path):
        if not opus_path or not os.path.exists(opus_path):
            return
        self.stop_background()
        args = [
            self.ffplay, "-nodisp", "-autoexit", "-loop", "0",
            "-volume", str(int(self.volume * 100)),
            "-loglevel", "quiet", "-i", opus_path,
        ]
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0,
            )
            with self._bg_lock:
                self._bg_process = proc
        except (OSError, ValueError):
            self._bg_process = None

    def stop_background(self):
        with self._bg_lock:
            proc = self._bg_process
            self._bg_process = None
        if proc is None:
            return
        try:
            proc.terminate()
            try:
                proc.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass

    def play_oneshot(self, opus_path):
        if not opus_path or not os.path.exists(opus_path):
            return
        args = [
            self.ffplay, "-nodisp", "-autoexit",
            "-volume", str(int(self.volume * 100)),
            "-loglevel", "quiet", "-i", opus_path,
        ]

        def _run():
            try:
                subprocess.run(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt" else 0,
                )
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def close(self):
        self.stop_background()


# ----------------------------------------------------------------------------
# opusdec + winsound (Windows-only, требует tools/opus/opusdec.exe)
# ----------------------------------------------------------------------------

def _get_wav_duration(wav_path):
    """Возвращает длительность WAV-файла в секундах через stdlib wave.
    Используется для планирования возобновления bg после одноразового FX.
    """
    with wave.open(wav_path, 'rb') as w:
        frames = w.getnframes()
        rate = w.getframerate()
        if rate <= 0:
            return 1.0
        return frames / float(rate)


class OpusDecBackend(AudioBackend):
    """v0.5.3: Гибридный бэкенд.

    - **bg**: opus → WAV через `opusdec.exe`, проигрывание через winsound
      (зацикленный). Работает надёжно — winsound loop не имеет проблем.
    - **FX**: если доступен `ffplay.exe` — играет через subprocess ffplay,
      параллельно с bg (нет ограничения winsound на одноканальность).
      Иначе — через winsound с явным PURGE (последняя попытка обойти
      причуды winsound; может работать нестабильно).

    `supports_parallel_audio = True` если ffplay доступен (FX не глушит bg).
    """
    name = "opusdec"

    def __init__(self, opusdec_path, volume=0.7, ffplay_path=None):
        self.opusdec = opusdec_path
        self.volume = max(0.0, min(1.0, float(volume)))
        self._ffplay = ffplay_path  # None, если ffplay не найден
        # supports_parallel_audio зависит от наличия ffplay для FX
        self.supports_parallel_audio = (ffplay_path is not None)
        self._wav_dir = tempfile.mkdtemp(prefix="story_wav_")
        self._wav_cache = {}
        self._decode_threads = {}
        self._decode_lock = threading.Lock()
        self._bg_opus_path = None
        self._bg_wav_path = None
        self._closed = False
        # v0.5.1: счётчик "поколения сцены" — инвалидирует устаревшие FX-колбэки,
        # чтобы декод FX из старой сцены не убил bg новой сцены, если пользователь
        # успел перейти раньше, чем отработал opusdec.
        self._scene_generation = 0
        # v0.5.2: токен последовательности FX — чтобы таймер старого FX
        # не возобновлял bg поверх нового FX (если пользователь сделал !look
        # или как-то иначе переиграл FX в той же сцене).
        self._fx_token = 0

    def _volume_to_db(self, vol):
        vol = max(0.001, min(1.0, float(vol)))
        return 20 * math.log10(vol)

    def _cache_lookup(self, opus_path, volume):
        entry = self._wav_cache.get(opus_path)
        if not entry:
            return None
        wav = entry.get("wav")
        cached_vol = entry.get("volume", -1.0)
        if wav and os.path.exists(wav) and abs(cached_vol - volume) < 0.01:
            return wav
        return None

    def _decode_async(self, opus_path, on_complete=None):
        if self._closed:
            return
        requested_volume = self.volume

        cached_wav = self._cache_lookup(opus_path, requested_volume)
        if cached_wav:
            if on_complete:
                threading.Thread(
                    target=on_complete, args=(cached_wav,), daemon=True
                ).start()
            return

        with self._decode_lock:
            existing = self._decode_threads.get(opus_path)
            if existing and existing.is_alive():
                return
            t = threading.Thread(
                target=self._decode_worker,
                args=(opus_path, requested_volume, on_complete),
                daemon=True,
            )
            self._decode_threads[opus_path] = t
        t.start()

    def _decode_worker(self, opus_path, requested_volume, on_complete):
        wav_path = None
        try:
            wav_path = self._do_decode(opus_path, requested_volume)
        except Exception:
            wav_path = None
        if not self._closed and on_complete:
            try:
                on_complete(wav_path)
            except Exception:
                pass
        with self._decode_lock:
            current = self._decode_threads.get(opus_path)
            if current is threading.current_thread():
                self._decode_threads.pop(opus_path, None)

    def _do_decode(self, opus_path, volume):
        wav_name = os.path.basename(opus_path)
        for ext in (".opus", ".ogg"):
            if wav_name.lower().endswith(ext):
                wav_name = wav_name[: -len(ext)]
                break
        vol_suffix = f"_v{int(volume * 100):02d}"
        wav_path = os.path.join(self._wav_dir, wav_name + vol_suffix + ".wav")

        gain_db = self._volume_to_db(volume)
        args = [
            self.opusdec, "--quiet", "--gain", f"{gain_db:.1f}",
            opus_path, wav_path,
        ]

        proc = None
        try:
            proc = subprocess.Popen(
                args,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if os.name == "nt" else 0,
            )
            proc.wait(timeout=60)
        except (subprocess.TimeoutExpired, OSError, ValueError):
            if proc is not None:
                try:
                    proc.kill()
                except Exception:
                    pass
            return None

        if proc is None or proc.returncode != 0:
            return None

        if os.path.exists(wav_path):
            self._wav_cache[opus_path] = {"wav": wav_path, "volume": volume}
            return wav_path
        return None

    def set_volume(self, volume):
        new_vol = max(0.0, min(1.0, float(volume)))
        if abs(new_vol - self.volume) < 0.01:
            return
        self.volume = new_vol
        bg_path = self._bg_opus_path
        if bg_path:
            self.play_background(bg_path)

    def play_background(self, opus_path):
        if self._closed:
            return
        if not opus_path:
            self.stop_background()
            return
        if not os.path.exists(opus_path):
            return

        # v0.5.1: новая "смена сцены" — инвалидируем все устаревшие FX-колбэки,
        # даже если bg остался тем же. Это критично: декод FX из предыдущей
        # сцены мог ещё не завершиться, и его колбэк не должен убивать bg новой.
        self._scene_generation += 1

        # v0.5.1: если тот же opus_path уже установлен как bg — НЕ перезапускаем
        # winsound.PlaySound. Это избегает статтера при переходе между сценами
        # с одинаковым sound_bg (типичный случай: один амбиент на всю локацию).
        # Бесшовное продолжение фона.
        if self._bg_opus_path == opus_path:
            return

        self._bg_opus_path = opus_path

        cached_wav = self._cache_lookup(opus_path, self.volume)
        if cached_wav:
            self._play_wav_background(cached_wav)
            return

        def _on_complete(wav_path):
            if self._closed or not wav_path:
                return
            if self._bg_opus_path == opus_path:
                self._play_wav_background(wav_path)

        self._decode_async(opus_path, on_complete=_on_complete)

    def _play_wav_background(self, wav_path):
        if self._closed or not _HAS_WINSOUND:
            return
        self._bg_wav_path = wav_path
        try:
            winsound.PlaySound(
                wav_path,
                winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_LOOP,
            )
        except Exception:
            pass

    def stop_background(self):
        # v0.5.1: инвалидируем устаревшие FX-колбэки (смена поколения)
        self._scene_generation += 1
        self._bg_opus_path = None
        self._bg_wav_path = None
        if _HAS_WINSOUND:
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass

    def play_oneshot(self, opus_path):
        """v0.5.3: Одноразовый FX. Диспетчеризация между ffplay и winsound.

        - Если доступен ffplay (`self._ffplay` не None) — играем FX через
          subprocess ffplay, напрямую из opus-файла. Преимущества:
            • Играет параллельно с bg (нет winsound-ограничения).
            • Не нужно декодировать opus → WAV.
            • Не нужно планировать возобновление bg.
        - Иначе — fallback на winsound с явным PURGE перед PlaySound.
          winsound одноканальный: FX остановит bg, после duration + 0.1с
          фон возобновляется.
        """
        if self._closed:
            return
        if not opus_path or not os.path.exists(opus_path):
            return

        if self._ffplay:
            self._play_fx_via_ffplay(opus_path)
        else:
            self._play_fx_via_winsound(opus_path)

    def _play_fx_via_ffplay(self, opus_path):
        """Прямое воспроизведение opus через ffplay subprocess.
        Играет параллельно с bg (отдельный процесс). Не требует декода.
        """
        args = [
            self._ffplay, "-nodisp", "-autoexit",
            "-volume", str(int(self.volume * 100)),
            "-loglevel", "quiet", "-i", opus_path,
        ]

        def _run():
            try:
                subprocess.run(
                    args,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                    if os.name == "nt" else 0,
                )
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _play_fx_via_winsound(self, opus_path):
        """v0.5.3: Fallback FX через opusdec+winsound, если ffplay недоступен.

        Добавлен явный `winsound.PlaySound(None, SND_PURGE)` перед FX —
        сбрасывает внутреннее состояние winsound, которое могло застрять
        в loop-режиме от bg. Без PURGE новый PlaySound для FX иногда
        не срабатывает на Windows 10/11.
        """
        fx_gen = self._scene_generation
        fx_bg_at_request = self._bg_opus_path
        self._fx_token += 1
        my_token = self._fx_token

        def _on_complete(wav_path):
            if self._closed or not wav_path or not _HAS_WINSOUND:
                return
            if self._scene_generation != fx_gen:
                return  # устаревший FX

            try:
                duration = _get_wav_duration(wav_path)
            except Exception:
                duration = 1.0

            # v0.5.3: Явный PURGE — сбрасывает состояние winsound.
            # Без этого на Win10/11 PlaySound для FX иногда не срабатывает,
            # если до этого играл зацикленный bg.
            try:
                winsound.PlaySound(None, winsound.SND_PURGE)
            except Exception:
                pass
            time.sleep(0.05)  # короткая пауза, чтобы PURGE завершился

            # Теперь играем FX
            try:
                winsound.PlaySound(
                    wav_path,
                    winsound.SND_FILENAME | winsound.SND_ASYNC,
                )
            except Exception:
                return

            # Планируем возобновление bg после duration + буфер
            def _resume_bg_after_fx():
                time.sleep(duration + 0.1)
                if self._closed:
                    return
                if self._fx_token != my_token:
                    return
                if self._bg_opus_path != fx_bg_at_request:
                    return
                if not self._bg_opus_path:
                    return
                cached_bg_wav = self._cache_lookup(self._bg_opus_path, self.volume)
                if cached_bg_wav:
                    self._play_wav_background(cached_bg_wav)

            threading.Thread(target=_resume_bg_after_fx, daemon=True).start()

        self._decode_async(opus_path, on_complete=_on_complete)

    def stop_all(self):
        self.stop_background()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self.stop_background()
        except Exception:
            pass
        with self._decode_lock:
            threads = list(self._decode_threads.values())
        for t in threads:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass
        if self._wav_dir and os.path.exists(self._wav_dir):
            try:
                shutil.rmtree(self._wav_dir, ignore_errors=True)
            except Exception:
                pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# AudioManager — фасад, выбирает бэкенд по settings
# ----------------------------------------------------------------------------

class AudioManager:
    def __init__(self, settings):
        self.enabled = settings.get("sound_enabled", True)
        self.volume = settings.get("sound_volume", 0.7)
        preferred = settings.get("audio_backend", "opusdec")
        self.backend = self._select_backend(preferred)

        if self.backend.name == "null":
            sys.stderr.write(
                "\n[ВНИМАНИЕ] Не удалось найти подходящий аудио-движок.\n"
                "Доступные опции:\n"
                "  • tools/opus/opusdec.exe (Windows-only, по умолчанию)\n"
                "  • ffplay (из FFmpeg) в PATH\n"
                "Звук будет отключён.\n\n"
            )
        else:
            sys.stderr.write(f"\n[Аудио] Используется движок: {self.backend.name}\n\n")
        self.backend.set_volume(self.volume)

        atexit.register(self.close)

    def _select_backend(self, preferred):
        """v0.5.3: opusdec — основной по умолчанию. Если есть и opusdec, и ffplay —
        используем гибридный OpusDecBackend (bg через winsound, FX через ffplay,
        параллельное воспроизведение). Иначе — fallback на чистый ffplay, потом NullBackend.
        """
        if preferred == "none":
            return NullBackend()

        if preferred == "ffplay":
            p = find_ffplay()
            if p:
                return FfplayBackend(p, self.volume)
            return NullBackend()

        if preferred == "opusdec":
            p = find_opusdec()
            ffplay_p = find_ffplay()
            if p and _HAS_WINSOUND:
                # Гибрид: bg через opusdec+winsound, FX через ffplay (если есть)
                backend = OpusDecBackend(p, self.volume, ffplay_path=ffplay_p)
                if ffplay_p:
                    sys.stderr.write(
                        f"\n[Аудио] Гибрид: bg=opusdec+winsound, FX=ffplay ({ffplay_p})\n\n"
                    )
                else:
                    sys.stderr.write(
                        "\n[Аудио] opusdec+winsound (без ffplay; FX через winsound с PURGE)\n"
                        "       Для надёжного FX рекомендуется установить ffplay.exe\n"
                        "       Запустите: python scripts/get_ffplay.py\n\n"
                    )
                return backend
            # opusdec недоступен — пробуем ffplay как запасной
            if ffplay_p:
                sys.stderr.write(
                    "\n[ВНИМАНИЕ] opusdec недоступен (нет opusdec.exe или не Windows). "
                    "Использую ffplay как запасной.\n\n"
                )
                return FfplayBackend(ffplay_p, self.volume)
            return NullBackend()

        # auto: opusdec+winsound (+ ffplay для FX если есть) → ffplay → null
        p = find_opusdec()
        ffplay_p = find_ffplay()
        if p and _HAS_WINSOUND:
            return OpusDecBackend(p, self.volume, ffplay_path=ffplay_p)
        if ffplay_p:
            return FfplayBackend(ffplay_p, self.volume)
        return NullBackend()

    def set_volume(self, volume):
        self.volume = max(0.0, min(1.0, float(volume)))
        self.backend.set_volume(self.volume)

    def set_enabled(self, enabled):
        self.enabled = bool(enabled)
        self.backend.set_enabled(self.enabled)

    def play_background(self, opus_path):
        if not self.enabled:
            return
        self.backend.play_background(opus_path)

    def stop_background(self):
        self.backend.stop_background()

    def play_oneshot(self, opus_path):
        if not self.enabled:
            return
        self.backend.play_oneshot(opus_path)

    def stop_all(self):
        self.backend.stop_all()

    def close(self):
        try:
            self.backend.stop_all()
        except Exception:
            pass
        try:
            self.backend.close()
        except Exception:
            pass

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    @property
    def backend_name(self):
        return self.backend.name

    @property
    def supports_parallel_audio(self):
        """True, если бэкенд может проигрывать FX параллельно с bg.
        main.py использует это, чтобы решить — проигрывать UI-клик, или нет.
        """
        return getattr(self.backend, "supports_parallel_audio", False)
