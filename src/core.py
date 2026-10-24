"""Portable settings and reversible, provider-scoped Codex routing."""
from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import tomllib
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
    upstream: str = "http://127.0.0.1:8317"
    listen_port: int = 8318
    models: list[str] = field(default_factory=lambda: ["GC-*", "glm-*", "deepseek-*"])
    fetch_remote_images: bool = False
    codex_config: str = str(Path.home() / ".codex" / "config.toml")
    provider: str = "cpa-gui"

    @property
    def proxy_base(self) -> str:
        return f"http://127.0.0.1:{self.listen_port}/v1"

    @property
    def direct_base(self) -> str:
        return self.upstream.rstrip("/") + "/v1"

    def validate(self) -> None:
        parsed = urlsplit(self.upstream)
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("上游地址须为 http(s) URL，不能包含账号、密码、查询参数。")
        try:
            upstream_port = parsed.port
        except ValueError as exc:
            raise ValueError("上游端口无效。") from exc
        if parsed.path not in ("", "/"):
            raise ValueError("上游地址只填服务根地址，例如 http://127.0.0.1:8317，不要带 /v1。")
        if not 1024 <= self.listen_port <= 65535:
            raise ValueError("本地端口范围为 1024–65535。")
        if parsed.hostname.lower() in ("localhost", "127.0.0.1", "::1") and (upstream_port or (443 if parsed.scheme == "https" else 80)) == self.listen_port:
            raise ValueError("上游端口不能与 OCR 端口相同，否则会循环转发。")
        if not self.provider.strip():
            raise ValueError("请填写 Codex provider 名称。")
        if not self.models or any(not p.strip() or len(p) > 200 for p in self.models):
            raise ValueError("至少填写一条模型规则，每条不超过 200 字符。")


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or application_dir() / "data"
        self.directory.mkdir(parents=True, exist_ok=True)
        self.settings_path = self.directory / "settings.json"
        self.journal_path = self.directory / "routing.json"

    def load(self) -> Settings:
        if not self.settings_path.exists():
            return Settings()
        raw = json.loads(self.settings_path.read_text("utf-8"))
        return Settings(**{k: v for k, v in raw.items() if k in Settings.__dataclass_fields__})

    def save(self, settings: Settings):
        settings.validate()
        atomic_write(self.settings_path, json.dumps(asdict(settings), ensure_ascii=False, indent=2))

    def journal(self) -> dict | None:
        return json.loads(self.journal_path.read_text("utf-8")) if self.journal_path.exists() else None


def read_provider(path: Path, provider: str) -> tuple[str, str]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        text = stream.read()
    parsed = tomllib.loads(text)
    value = parsed.get("model_providers", {}).get(provider, {}).get("base_url")
    if not isinstance(value, str):
        raise ValueError(f"配置中找不到 provider {provider} 的 base_url。")
    return text, value


def active_provider(path: Path) -> str:
    return tomllib.loads(path.read_text("utf-8")).get("model_provider", "")


def replace_base(text: str, provider: str, expected: str, target: str) -> str:
    """Parse TOML for selection, retain all original bytes except one URL token."""
    lines = text.splitlines(keepends=True)
    inside = False
    replaced = False
    for i, line in enumerate(lines):
        stripped = line.lstrip()
        if stripped.startswith("["):
            # TOML parser handles quoted keys, spaces and section comments.
            try:
                section = tomllib.loads(line + "\n__ocr_marker__ = true\n")
                inside = section.get("model_providers", {}).get(provider, {}).get("__ocr_marker__") is True
            except (tomllib.TOMLDecodeError, AttributeError):
                inside = False
        if inside:
            match = re.match(r'''^(\s*base_url\s*=\s*)("(?:[^"\\\r\n]|\\.)*"|'[^'\r\n]*')(.*)$''', line.rstrip("\r\n"))
            if match:
                old = tomllib.loads("x = " + match[2])["x"]
                if old != expected:
                    raise ValueError("连接地址已被其他程序修改，请刷新后再操作。")
                eol = line[len(line.rstrip("\r\n")) :]
                lines[i] = match[1] + json.dumps(target) + match[3] + eol
                replaced = True
                break
    if not replaced:
        raise ValueError("无法安全定位 base_url；请使用独立 provider 配置段和单行 URL。")
    result = "".join(lines)
    tomllib.loads(result)
    return result


class Routing:
    def __init__(self, store: Store):
        self.store = store

    def enable(self, settings: Settings):
        settings.validate()
        path = Path(settings.codex_config)
        text, original = read_provider(path, settings.provider)
        if active_provider(path) != settings.provider:
            raise ValueError("所选 provider 不是 Codex 当前使用的 provider，请先在设置中选择当前 provider。")
        journal = self.store.journal()
        if journal:
            if journal["config"] != str(path.resolve()) or journal["provider"] != settings.provider or journal["proxy"] != settings.proxy_base:
                raise ValueError("有尚未恢复的连接，请先点击“恢复 Codex 直连”，再修改设置。")
            if original not in (journal["proxy"], journal["original"]):
                raise ValueError("Codex 连接已由其他程序更改；保留当前配置，请先检查诊断结果。")
        else:
            # Original WorkBuddy version may already have switched Codex to 8318.
            journal = {"config": str(path.resolve()), "provider": settings.provider,
                       "original": settings.direct_base if original == settings.proxy_base else original,
                       "proxy": settings.proxy_base}
        result = replace_base(text, settings.provider, original, settings.proxy_base)
        atomic_write(self.store.journal_path, json.dumps(journal, ensure_ascii=False, indent=2))
        # Refuse to overwrite a file changed while preparing the update.
        if read_provider(path, settings.provider)[0] != text:
            raise ValueError("Codex 配置正在被修改，请稍后重试。")
        atomic_write(path, result)

    def restore(self, settings: Settings) -> str:
        journal = self.store.journal()
        if journal:
            path = Path(journal["config"])
            provider, proxy, original = journal["provider"], journal["proxy"], journal["original"]
        else:
            path = Path(settings.codex_config)
            provider, proxy, original = settings.provider, settings.proxy_base, settings.direct_base
        text, current = read_provider(path, provider)
        if current == proxy:
            result = replace_base(text, provider, current, original)
            if read_provider(path, provider)[0] != text:
                raise ValueError("Codex 配置正在被修改，请稍后重试。")
            atomic_write(path, result)
            message = "已恢复 Codex 原连接地址。"
        elif journal and current != original:
            raise ValueError("Codex 连接已由其他程序更改，本工具保留该配置。请检查后恢复，代理继续运行。")
        else:
            message = "Codex 已使用直连地址。"
        self.store.journal_path.unlink(missing_ok=True)
        return message
