"""Local-only, fail-closed installation of prerecorded PUBLIC starter voice ZIPs.

Each archive has manifest.json and 144 <phrase-uuid>.mp3 at its root.
The exact existing starter IDs/text and model/voice revisions are verified.
No SQLite writes, external TTS, remote calls, or arbitrary ZIP extraction.
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
import hashlib
import json
import os
import stat
import tempfile
import threading
import zipfile

from tools.build_kokoro_voicepacks import (
    CATALOG, SOURCE, catalog, digest, pack_id, public_rows, verify,
)

ROOT = Path(__file__).resolve().parent
INSTALLED_ROOT = ROOT / "local_voicepacks"

MAX_ZIP_BYTES = 32 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 48 * 1024 * 1024
MAX_FILE_BYTES = 3 * 1024 * 1024
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_COMPRESSION_RATIO = 200
EXPECTED_FILES = 145  # manifest + 144 mp3 files


class InvalidVoicePack(ValueError):
    """Safe public error; never contains any input lesson text."""


class VoicePackLibrary:
    def __init__(self, root=INSTALLED_ROOT, pt_catalog=None):
        self.root = Path(root)
        self.pt_catalog = pt_catalog
        self.lock = threading.RLock()
        self.installed = {}
        self.reload()

    def reload(self):
        installed = {}
        configuration = catalog()
        for voice in configuration["voices"]:
            if voice["locale"] == "pt-PT":
                continue  # The original committed Kokoro recordings are separate.
            directory = self.root / voice["id"]
            try:
                if directory.exists() and not directory.is_symlink():
                    verify(directory)
                    manifest = json.loads((directory / "manifest.json").read_text("utf-8"))
                    installed[voice["id"]] = {
                        "manifest_hash": digest(directory / "manifest.json"),
                        "locale": voice["locale"],
                        "entries": {e["phrase_id"]: e for e in manifest["entries"]},
                    }
            except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                # An invalid/corrupt package must never be played.
                continue
        with self.lock:
            self.installed = installed

    def voices(self):
        with self.lock:
            installed = set(self.installed)
        pt_ready = bool(self.pt_catalog and self.pt_catalog.status()["ready"])
        return [
            {"id": v["id"], "locale": v["locale"], "gender": v["gender"],
             "installed": (pt_ready if v["locale"] == "pt-PT" else v["id"] in installed),
             "is_kokoro": True}
            for v in catalog()["voices"]
        ]

    def for_phrase(self, phrase_id, text, locale, voice_id):
        if not isinstance(text, str) or not voice_id:
            return None
        with self.lock:
            selected = self.installed.get(voice_id)
            # en-GB is an *accent variant* of en-US study text/progress.
            # Never create a second language mastery record for an accent.
            audio_locale = selected["locale"] if selected else None
            if (not selected or
                    not (audio_locale == locale or
                         (locale == "en-US" and audio_locale == "en-GB"))):
                return None
            item = selected["entries"].get(phrase_id)
        if not item or hashlib.sha256(text.encode("utf-8")).hexdigest() != item["text_sha256"]:
            return None
        return {
            "url": f"/api/voice-media/{voice_id}/{phrase_id}.mp3",
            "sha256": item["sha256"],
            "text_sha256": item["text_sha256"],
            "duration_seconds": item["duration_seconds"],
            "pack_id": pack_id(voice_id),
            "voice_id": voice_id,
        }

    def media(self, voice_id, phrase_id):
        """Return an already validated clip, rechecking its hash before serving."""
        with self.lock:
            item = self.installed.get(voice_id, {}).get("entries", {}).get(phrase_id)
        if item is None:
            return None
        directory = self.root / voice_id
        path = directory / (phrase_id + ".mp3")
        if directory.is_symlink() or path.is_symlink() or not path.is_file():
            return None
        if path.stat().st_size != item["bytes"]:
            return None
        with path.open("rb") as stream:
            data = stream.read(MAX_FILE_BYTES + 1)
        if (len(data) != item["bytes"]
                or hashlib.sha256(data).hexdigest() != item["sha256"]):
            return None
        return data

    def _validate_archive(self, archive_bytes):
        if not isinstance(archive_bytes, bytes) or not 0 < len(archive_bytes) <= MAX_ZIP_BYTES:
            raise InvalidVoicePack("ZIP отсутствует или превышает 32 МБ")
        try:
            with zipfile.ZipFile(BytesIO(archive_bytes)) as source:
                files = source.infolist()
                if len(files) not in (EXPECTED_FILES, EXPECTED_FILES + 1):
                    raise InvalidVoicePack("Ожидаются манифест, 144 MP3 и опциональная лицензия")
                names = [f.filename for f in files]
                if len(names) != len(set(names)) or "manifest.json" not in names:
                    raise InvalidVoicePack("Повторяющиеся файлы или отсутствует манифест")
                total = 0
                for info in files:
                    # Reject ZIP symlinks, file traversal, nested directories, encryption.
                    mode = info.external_attr >> 16
                    if (info.is_dir() or stat.S_ISLNK(mode)
                            or info.flag_bits & 1 or "/" in info.filename
                            or "\\" in info.filename or info.filename.startswith(".")
                            or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)):
                        raise InvalidVoicePack("Небезопасный файл в ZIP")
                    limit = (MAX_MANIFEST_BYTES if info.filename == "manifest.json" else
                             100_000 if info.filename == "LICENSE-dialogs-openrail.md"
                             else MAX_FILE_BYTES)
                    if info.file_size < 1 or info.file_size > limit:
                        raise InvalidVoicePack("Недопустимый размер файла")
                    if info.file_size > max(1, info.compress_size) * MAX_COMPRESSION_RATIO:
                        raise InvalidVoicePack("Подозрительное сжатие ZIP")
                    total += info.file_size
                    if total > MAX_UNCOMPRESSED_BYTES:
                        raise InvalidVoicePack("ZIP превышает предел распакованных данных")
                raw_manifest = source.read("manifest.json")
                try:
                    manifest = json.loads(raw_manifest)
                except (ValueError, UnicodeError):
                    raise InvalidVoicePack("Неверный JSON-манифест") from None
                if not isinstance(manifest, dict):
                    raise InvalidVoicePack("Неверный формат манифеста")
                config = catalog()
                name = manifest.get("voice_id")
                valid = {v["id"]: v for v in config["voices"] if v["locale"] != "pt-PT"}
                if not isinstance(name, str) or name not in valid:
                    raise InvalidVoicePack("Голос отсутствует в локальном каталоге")
                voice = valid[name]
                model = config["models"][voice["model"]]
                if (manifest.get("schema_version") != 1
                        or manifest.get("pack_id") != pack_id(name)
                        or manifest.get("locale") != voice["locale"]
                        or manifest.get("model") != model["repository"]
                        or manifest.get("revision") != model["revision"]
                        or manifest.get("source_sha256") != digest(SOURCE)
                        or manifest.get("catalog_sha256") != digest(CATALOG)
                        or manifest.get("complete") is not True
                        or manifest.get("synthetic_audio") is not True):
                    raise InvalidVoicePack("Несовместимый манифест или исходные фразы")
                entries = manifest.get("entries")
                if not isinstance(entries, list) or len(entries) != 144:
                    raise InvalidVoicePack("Аудиопакет должен содержать 144 записи")
                expected = {row["phrase_id"]: row for row in public_rows(voice["locale"])}
                entry_ids = [e.get("phrase_id") for e in entries if isinstance(e, dict)]
                if (len(entry_ids) != 144 or not all(isinstance(i, str) for i in entry_ids)
                        or len(set(entry_ids)) != 144 or set(entry_ids) != set(expected)):
                    raise InvalidVoicePack("Идентификаторы фраз не совпадают")
                expected_names = {"manifest.json"} | {f"{identifier}.mp3" for identifier in entry_ids}
                is_russian = voice["model"] == "russian"
                redis = manifest.get("redistribution")
                license_text = ""
                if is_russian:
                    expected_names.add("LICENSE-dialogs-openrail.md")
                    if (not isinstance(redis, dict)
                            or redis.get("requires_acceptance") is not True
                            or redis.get("license_file") != "LICENSE-dialogs-openrail.md"
                            or redis.get("dataset_repository")
                               != "langswap/dialogs-ru-emotional-conversations"):
                        raise InvalidVoicePack("Не указана обязательная лицензия русского голоса")
                    raw_license = source.read("LICENSE-dialogs-openrail.md") if (
                        "LICENSE-dialogs-openrail.md" in names) else b""
                    if (not 1000 < len(raw_license) < 100_000
                            or hashlib.sha256(raw_license).hexdigest()
                               != redis.get("license_sha256")):
                        raise InvalidVoicePack("Отсутствуют подлинные условия OpenRAIL")
                    try:
                        license_text = raw_license.decode("utf-8")
                    except UnicodeDecodeError:
                        raise InvalidVoicePack("Лицензия должна быть в UTF-8") from None
                    if not all(w in license_text for w in (
                            "OpenRAIL", "Use Restrictions", "Distribution")):
                        raise InvalidVoicePack("Условия OpenRAIL неполные")
                if set(names) != expected_names:
                    raise InvalidVoicePack("Посторонние или отсутствующие файлы")
                total_bytes = 0
                for entry in entries:
                    row = expected[entry["phrase_id"]]
                    for field, value in row.items():
                        if entry.get(field) != value:
                            raise InvalidVoicePack("Текст или ID изменён относительно источника")
                    path = f"{entry['phrase_id']}.mp3"
                    if entry.get("file") != path:
                        raise InvalidVoicePack("Несовпадение имени аудио")
                    size = source.getinfo(path).file_size
                    if (not 1800 <= size <= MAX_FILE_BYTES or entry.get("bytes") != size
                            or entry.get("codec") != "mp3"
                            or entry.get("sample_rate_hz") != 24000
                            or entry.get("channels") != 1
                            or type(entry.get("duration_seconds")) not in (int, float)
                            or not 0.4 <= entry["duration_seconds"] <= 45):
                        raise InvalidVoicePack("Недопустимые параметры аудио")
                    # Hash the complete decoded archive entry without interpreting it.
                    raw = source.read(path)
                    if hashlib.sha256(raw).hexdigest() != entry.get("sha256"):
                        raise InvalidVoicePack("Неверная контрольная сумма MP3")
                    if not (raw[:3] == b"ID3" or
                            (len(raw) >= 2 and raw[0] == 0xFF and (raw[1] & 0xE0) == 0xE0)):
                        raise InvalidVoicePack("Файл не похож на MP3")
                    total_bytes += size
                if manifest.get("summary") != {"files": 144, "bytes": total_bytes}:
                    raise InvalidVoicePack("Неверный итоговый размер пакета")
                return {"voice_id": name, "locale": voice["locale"],
                        "files": 144, "bytes": total_bytes,
                        "requires_openrail": is_russian, "license_text": license_text,
                        "manifest_sha256": hashlib.sha256(raw_manifest).hexdigest()}
        except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError, OSError):
            raise InvalidVoicePack("Невозможно прочитать ZIP") from None

    def preview(self, archive_bytes):
        info = self._validate_archive(archive_bytes)
        with self.lock:
            existing = self.installed.get(info["voice_id"])
        info["state"] = (
            "already-installed" if existing and existing["manifest_hash"] == info["manifest_sha256"]
            else "conflict" if existing else "ready-to-install"
        )
        return info

    def install(self, archive_bytes, accepted_openrail=False):
        info = self.preview(archive_bytes)
        if info["requires_openrail"] and accepted_openrail is not True:
            raise InvalidVoicePack("Для установки русского голоса нужно принять условия OpenRAIL")
        if info["state"] == "already-installed":
            return {**info, "installed": True, "changed": False}
        if info["state"] == "conflict":
            raise InvalidVoicePack("Другая версия уже установлена. Автозамена запрещена")
        self.root.mkdir(parents=True, exist_ok=True)
        destination = self.root / info["voice_id"]
        with self.lock:
            if destination.exists() or destination.is_symlink():
                raise InvalidVoicePack("Пакет уже существует")
            with tempfile.TemporaryDirectory(prefix=".voice-stage-", dir=self.root) as directory:
                # Rename a child, not the TemporaryDirectory root, so cleanup
                # succeeds after committing the validated directory.
                stage = Path(directory) / "staged"
                stage.mkdir()
                with zipfile.ZipFile(BytesIO(archive_bytes)) as source:
                    for name in source.namelist():
                        (stage / name).write_bytes(source.read(name))
                # Independently verify the on-disk files before exposing them.
                try:
                    verify(stage)
                except (ValueError, OSError, KeyError, TypeError):
                    raise InvalidVoicePack("Пакет не прошёл проверку после установки") from None
                if destination.exists():
                    raise InvalidVoicePack("Пакет установлен одновременно другим запросом")
                os.rename(stage, destination)
            self.reload()
        return {**info, "installed": True, "changed": True}
