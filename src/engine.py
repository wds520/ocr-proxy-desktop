"""Local OCR and an async, streaming preserving OpenAI HTTP proxy."""
from __future__ import annotations

import asyncio
import base64
import fnmatch
import hashlib
import io
import json
import logging
import re
import socket
import threading
import time
from collections import OrderedDict
from contextlib import asynccontextmanager

import httpx
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from core import Settings, VERSION

log = logging.getLogger("ocr_proxy")
MAX_BODY = 64 * 1024 * 1024
MAX_IMAGE = 20 * 1024 * 1024
HOP = {"host", "content-length", "connection", "keep-alive", "transfer-encoding", "expect", "te", "trailer", "upgrade", "proxy-authenticate", "proxy-authorization"}


class OCRFailure(Exception):
    pass


class OCR:
    def __init__(self):
        self.engine = None
        self.cache = OrderedDict()
        self.lock = threading.Lock()

    def recognize(self, data: bytes) -> tuple[str, bool]:
        if len(data) > MAX_IMAGE:
            raise OCRFailure("图片超过 20 MB，请缩小后重试。")
        key = hashlib.sha256(data).hexdigest()
        with self.lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key], True
            try:
                if self.engine is None:
                    from rapidocr_onnxruntime import RapidOCR
                    self.engine = RapidOCR()
                result, _ = self.engine(data)
                text = "\n".join(line[1] for line in result) if result else ""
            except Exception:
                log.error("OCR recognition failed (image content omitted)")
                raise OCRFailure("OCR 识别失败，请运行自动诊断。") from None
            self.cache[key] = text
            if len(self.cache) > 256:
                self.cache.popitem(last=False)
            return text, False

    def selftest(self) -> str:
        from PIL import Image, ImageDraw, ImageFont
        image = Image.new("RGB", (1000, 180), "white")
        draw = ImageDraw.Draw(image)
        draw.text((35, 40), "OCR TEST 123456", font=ImageFont.load_default(size=64), fill="black")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        text, _ = self.recognize(buf.getvalue())
        if "123456" not in re.sub(r"\s", "", text):
            raise OCRFailure("OCR 已加载，但测试数字识别不完整。")
        return "内置 OCR 模型已加载，测试图片识别成功（123456）。"


def model_matches(model: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(model.casefold(), p.casefold()) for p in patterns)


async def transform(obj, settings: Settings, ocr: OCR, client: httpx.AsyncClient, stats: dict):
    if isinstance(obj, list):
        return [await transform(item, settings, ocr, client, stats) for item in obj]
    if not isinstance(obj, dict):
        return obj
    kind = obj.get("type")
    if kind in ("input_image", "image_url"):
        url = obj.get("image_url")
        if isinstance(url, dict):
            url = url.get("url")
        if not isinstance(url, str):
            raise OCRFailure("此图片使用文件 ID 或未知格式，请使用内嵌图片或图片 URL。")
        match = re.fullmatch(r"data:image/[\w.+-]+;base64,(.*)", url, re.S)
        if match:
            try:
                data = base64.b64decode(match[1], validate=True)
            except ValueError:
                raise OCRFailure("图片 Base64 内容无效。") from None
        elif url.startswith(("http://", "https://")):
            if not settings.fetch_remote_images:
                raise OCRFailure("请求包含远程图片；请在设置中启用“下载远程图片”后重试。")
            try:
                # Separate request: never forward upstream credentials to an image host.
                async with client.stream("GET", url, timeout=15) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > MAX_IMAGE:
                            raise OCRFailure("远程图片超过 20 MB。")
                        chunks.append(chunk)
                    data = b"".join(chunks)
            except httpx.HTTPError:
                raise OCRFailure("远程图片下载失败，请检查图片地址和网络。") from None
        else:
            raise OCRFailure("不支持此图片格式。")
        text, cached = await asyncio.to_thread(ocr.recognize, data)
        stats["images"] += 1
        stats["cached"] += int(cached)
        stats["chars"] += len(text)
        return {"type": "input_text" if kind == "input_image" else "text",
                "text": "[图片OCR内容开始]\n" + (text.strip() or "(OCR 未识别到文字)") + "\n[图片OCR内容结束]"}
    return {k: await transform(v, settings, ocr, client, stats) for k, v in obj.items()}


def make_app(settings: Settings, ocr: OCR) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        async with httpx.AsyncClient(timeout=httpx.Timeout(600, connect=10), trust_env=False, follow_redirects=False) as client:
            app.state.client = client
            yield

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/__ocr_proxy_health")
    async def health():
        return {"ok": True, "app": "ocr-proxy-desktop", "version": VERSION, "models": settings.models}

    @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
    async def proxy(request: Request, path: str):
        if request.headers.get("origin"):
            return JSONResponse({"error": {"message": "仅供本地桌面客户端调用。"}}, status_code=403)
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BODY:
                return JSONResponse({"error": {"message": "请求超过 64 MB。"}}, status_code=413)
            chunks.append(chunk)
        body = b"".join(chunks)
        excluded = HOP | {v.strip().lower() for v in request.headers.get("connection", "").split(",")}
        headers = {k: v for k, v in request.headers.items() if k.lower() not in excluded}
        client = request.app.state.client
        if request.method == "POST" and body:
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                payload = None
            if isinstance(payload, dict) and model_matches(str(payload.get("model", "")), settings.models):
                stats = {"images": 0, "cached": 0, "chars": 0}
                try:
                    payload = await transform(payload, settings, ocr, client, stats)
                except OCRFailure as exc:
                    return JSONResponse({"error": {"message": str(exc), "type": "ocr_error"}}, status_code=422)
                if stats["images"]:
                    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                    # The new body is uncompressed even if the original had an encoding.
                    headers.pop("content-encoding", None)
                    log.info("OCR processed images=%d cache_hits=%d characters=%d", stats["images"], stats["cached"], stats["chars"])
        # Absolute construction avoids httpx base_url accidentally dropping/duplicating /v1.
        url = settings.upstream.rstrip("/") + "/" + path
        if request.url.query:
            url += "?" + request.url.query
        try:
            upstream = await client.send(client.build_request(request.method, url, headers=headers, content=body), stream=True)
        except httpx.HTTPError:
            log.warning("Upstream unavailable (credentials and request body omitted)")
            return JSONResponse({"error": {"message": "无法连接上游服务，请启动 EasyCLIProxyAPI 并运行自动诊断。", "type": "upstream_unavailable"}}, status_code=502)
        excluded = HOP | {v.strip().lower() for v in upstream.headers.get("connection", "").split(",")}
        response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                     background=BackgroundTask(upstream.aclose))
        # Preserve repeated response headers and original content encoding.
        response.raw_headers = [(k, v) for k, v in upstream.headers.raw if k.decode("ascii").lower() not in excluded]
        return response

    return app


class ProxyServer:
    def __init__(self, settings: Settings, ocr: OCR):
        self.settings, self.ocr = settings, ocr
        self.server = None
        self.thread = None
        self.socket = None

    @property
    def running(self):
        return bool(self.thread and self.thread.is_alive() and self.server and self.server.started)

    def start(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        try:
            self.socket.bind(("127.0.0.1", self.settings.listen_port))
        except OSError:
            self.socket.close()
            raise ValueError(f"端口 {self.settings.listen_port} 已占用。请关闭旧 OCR 工具或更换端口；本程序不会终止其他进程。") from None
        self.socket.listen(128)
        config = uvicorn.Config(make_app(self.settings, self.ocr), host="127.0.0.1", port=self.settings.listen_port,
                                log_config=None, access_log=False, timeout_graceful_shutdown=8)
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=lambda: self.server.run(sockets=[self.socket]), daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if self.running:
                return
            if not self.thread.is_alive():
                break
            time.sleep(0.05)
        self.stop()
        raise ValueError("本地代理启动失败，请查看诊断或日志。")

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=12)
            if self.thread.is_alive():
                raise ValueError("代理仍有请求正在结束，请稍后再试。")
        if self.socket:
            self.socket.close()
