"""Portable settings for a local OpenAI-compatible OCR proxy."""
from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

VERSION = "1.0.0"


def application_dir() -> Path:
    return Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


@dataclass
class Settings:
    upstream: str = "https://gateway.onewo.com/v1"
    listen_port: int = 8318
    models: list[str] = field(default_factory=lambda: ["GC-*", "glm-*", "deepseek-*"])
    fetch_remote_images: bool = False

    @property
    def proxy_base(self) -> str:
        return f"http://127.0.0.1:{self.listen_port}"

    def validate(self) -> None:
        parsed = urlsplit(self.upstream)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("上游地址须为 http(s) URL，不能包含账号、密码、查询参数。")
        try:
            upstream_port = parsed.port
        except ValueError as exc:
            raise ValueError("上游端口无效。") from exc
        if not 1024 <= self.listen_port <= 65535:
            raise ValueError("本地端口范围为 1024–65535。")
        if parsed.hostname.lower() in ("localhost", "127.0.0.1", "::1") and (upstream_port or (443 if parsed.scheme == "https" else 80)) == self.listen_port:
            raise ValueError("上游端口不能与 OCR 端口相同，否则会循环转发。")
        if not self.models or any(not p.strip() or len(p) > 200 for p in self.models):
            raise ValueError("至少填写一条模型规则，每条不超过 200 字符。")


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or application_dir() / "data"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.directory / "settings.json"

    def load(self) -> Settings:
        if not self.settings_path.exists():
            return Settings()
        raw = json.loads(self.settings_path.read_text("utf-8"))
        return Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__})

    def save(self, settings: Settings):
        settings.validate()
        atomic_write(self.settings_path, json.dumps(asdict(settings), ensure_ascii=False, indent=2))
