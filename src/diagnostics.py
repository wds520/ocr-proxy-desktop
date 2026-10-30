from __future__ import annotations

import platform
import socket
from datetime import datetime
from urllib.parse import urlsplit

import httpx

from core import Settings, Store, VERSION
from engine import upstream_url


def safe_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or "unknown"
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{host}{port}{parsed.path}"
    except ValueError:
        return "（地址格式无效）"


def run_diagnostics(settings: Settings, store: Store, ocr, owned_running: bool, emit=lambda value: None) -> str:
    lines = [f"OCR Proxy Desktop {VERSION}", datetime.now().astimezone().isoformat(timespec="seconds"),
             f"系统：{platform.system()} {platform.release()} / {platform.machine()}", ""]

    def add(level: str, title: str, detail: str):
        line = f"[{level}] {title}\n  {detail}"
        lines.append(line)
        emit(line)

    try:
        settings.validate()
        add("通过", "应用设置", "地址、端口和模型规则格式正确。")
    except Exception:
        add("失败", "应用设置", "设置格式无效，请检查上游地址、本地端口和模型规则。")
        return "\n".join(lines)

    try:
        probe = store.directory / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("通过", "便携数据目录", "应用目录可写，设置与日志保存在 data 文件夹。")
    except OSError:
        add("失败", "便携数据目录", "目录不可写，请移动到有写权限的文件夹。")

    try:
        with httpx.Client(trust_env=False, timeout=2) as client:
            response = client.get(f"http://127.0.0.1:{settings.listen_port}/__ocr_proxy_health")
            health = response.json() if response.status_code == 200 else {}
        if health.get("app") == "ocr-proxy-desktop":
            add("通过" if owned_running else "注意", "本地 OCR 服务", "代理已响应健康检查。" if owned_running else "检测到另一个便携版实例，请检查是否重复启动。")
        elif health.get("ok"):
            add("注意", "本地 OCR 服务", "检测到旧版 OCR 代理，请通过原工具停止后再启用便携版。")
        else:
            add("失败", "本地 OCR 服务", "端口被其他 HTTP 服务占用，请更换端口。")
    except Exception:
        with socket.socket() as probe:
            probe.settimeout(0.5)
            occupied = probe.connect_ex(("127.0.0.1", settings.listen_port)) == 0
        add("失败" if owned_running or occupied else "通过", "本地监听端口",
            "服务没有正确响应，请检查端口冲突。" if occupied or owned_running else "代理当前未启用，本地端口可用。")

    try:
        with httpx.Client(trust_env=False, timeout=4, follow_redirects=False) as client:
            response = client.get(upstream_url(settings.upstream, "v1/models"))
        if response.status_code in (401, 403):
            add("注意", "上游连通性", f"服务已响应 HTTP {response.status_code}，需要客户端鉴权；本诊断不会读取或发送密钥。")
        elif response.status_code == 200:
            add("通过", "上游模型接口", "上游 /v1/models 可访问。")
        else:
            add("注意", "上游模型接口", f"服务已响应 HTTP {response.status_code}，请检查上游服务地址或状态。")
    except Exception:
        add("失败", "上游连通性", "上游无法连接或超时，请检查上游地址、网络与端口。")

    try:
        add("通过", "本地 OCR 实际识别", ocr.selftest())
    except Exception:
        add("失败", "本地 OCR 实际识别", "模型或运行库无法识别测试图片，请重新完整解压便携包，检查 _internal 文件夹。")

    lines += ["", "诊断未调用付费大模型接口，未读取 API 密钥。",
              "上游 HTTP 可达和本地 OCR 通过，不代表账号鉴权、模型权限或真实会话已经验证。"]
    return "\n".join(lines)