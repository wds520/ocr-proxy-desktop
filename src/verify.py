"""Isolated end-to-end checks, also executable from the frozen desktop binary."""
from __future__ import annotations

import base64
import gzip
import io
import json
import socket
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

from core import Settings, Store, Routing, VERSION, atomic_write, read_provider, replace_base
from engine import OCR, ProxyServer, model_matches


def verify_bundle(output: Path) -> int:
    records = []

    def check(name, fn):
        started = time.monotonic()
        try:
            fn()
            records.append({"check": name, "passed": True, "seconds": round(time.monotonic() - started, 3)})
        except Exception as exc:
            records.append({"check": name, "passed": False, "error_type": type(exc).__name__})

    def require(condition):
        if not condition:
            raise AssertionError("Verification failed")

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_):
            pass

        def do_POST(self):
            body = self.rfile.read(int(self.headers.get("content-length", "0")))
            try:
                payload = json.loads(body)
            except ValueError:
                payload = {}
            if payload.get("stream"):
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(b'data: {"delta":"first"}\n\n')
                self.wfile.flush()
                time.sleep(0.5)
                self.wfile.write(b"data: [DONE]\n\n")
                self.wfile.flush()
                self.close_connection = True
                return
            result = json.dumps({"payload": payload, "raw": base64.b64encode(body).decode(),
                                 "path": self.path, "authorization": self.headers.get("authorization")}).encode()
            compressed = self.path.startswith("/v1/compressed")
            if compressed:
                result = gzip.compress(result)
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(result)))
            self.send_header("X-Upstream", "preserved")
            if compressed:
                self.send_header("Content-Encoding", "gzip")
            self.end_headers()
            self.wfile.write(result)

        def do_GET(self):
            self.send_response(401)
            self.send_header("Content-Length", "0")
            self.end_headers()

    with tempfile.TemporaryDirectory(prefix="ocr-proxy-check-") as temp:
        root = Path(temp)
        config = root / "config.toml"
        original_text = 'model_provider = "cpa-gui"\r\n# keep me\r\n[model_providers.cpa-gui]\r\nbase_url = \'http://127.0.0.1:8317/v1\' # keep comment\r\nenv_key = "TEST_ONLY"\r\n[model_providers.other]\r\nbase_url = "https://example.invalid/v1"\r\n'
        atomic_write(config, original_text)
        store = Store(root / "data")
        settings = Settings(codex_config=str(config))
        routing = Routing(store)

        def routing_cycle():
            routing.enable(settings)
            text, base = read_provider(config, "cpa-gui")
            require(base == settings.proxy_base and "# keep comment\r\n" in text)
            require(read_provider(config, "other")[1] == "https://example.invalid/v1")
            require("TEST_ONLY" not in store.journal_path.read_text())
            routing.enable(settings)
            require(store.journal()["original"] == settings.direct_base)
            routing.restore(settings)
            require(read_provider(config, "cpa-gui")[1] == settings.direct_base)
            require(not store.journal_path.exists())
        check("Codex switch, repeated enable, scoped edit, CRLF, restore", routing_cycle)

        def recovery():
            routing.enable(settings)
            new_routing = Routing(Store(root / "data"))
            new_routing.restore(settings)
            require(read_provider(config, "cpa-gui")[1] == settings.direct_base)
        check("Recovery after interrupted desktop session", recovery)

        def external_edit():
            routing.enable(settings)
            text, current = read_provider(config, settings.provider)
            external = "http://127.0.0.1:9999/v1"
            atomic_write(config, replace_base(text, settings.provider, current, external))
            try:
                routing.restore(settings)
            except ValueError:
                require(read_provider(config, settings.provider)[1] == external)
            else:
                raise AssertionError()
            store.journal_path.unlink()
            atomic_write(config, original_text)
        check("Preserve external provider changes", external_edit)

        def legacy_restore():
            text, current = read_provider(config, settings.provider)
            atomic_write(config, replace_base(text, settings.provider, current, settings.proxy_base))
            routing.enable(settings)
            routing.restore(settings)
            require(read_provider(config, settings.provider)[1] == settings.direct_base)
        check("Restore original WorkBuddy 8318 routing", legacy_restore)

        def pattern_test():
            require(model_matches("GC-glm-5.3", ["gc-*"]))
            require(model_matches("glm-5", ["glm-?"]))
            require(not model_matches("vision-model", settings.models))
        check("Model wildcard rules and case handling", pattern_test)

        def settings_test():
            store.save(settings)
            require(store.load() == settings)
            for invalid in (Settings(upstream="http://user:pass@localhost:8317"),
                            Settings(upstream="http://127.0.0.1:8318"), Settings(upstream="http://127.0.0.1:8317/v1")):
                try:
                    invalid.validate()
                except ValueError:
                    continue
                raise AssertionError()
        check("Portable settings and loop/credential validation", settings_test)

        ocr = OCR()
        check("Bundled ONNX models recognize actual image text", lambda: require("123456" in ocr.selftest()))
        image = Image.new("RGB", (1000, 180), "white")
        ImageDraw.Draw(image).text((35, 40), "OCR TEST 123456", font=ImageFont.load_default(size=64), fill="black")
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        image_url = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

        upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        upstream.daemon_threads = True
        threading.Thread(target=upstream.serve_forever, daemon=True).start()
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        settings = Settings(upstream=f"http://127.0.0.1:{upstream.server_port}", listen_port=port, codex_config=str(config))
        server = ProxyServer(settings, ocr)
        try:
            server.start()
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", timeout=30, trust_env=False) as client:
                check("Loopback service health", lambda: require(client.get("/__ocr_proxy_health").json()["app"] == "ocr-proxy-desktop"))

                def responses():
                    payload = {"model": "GC-demo", "input": [{"role": "user", "content": [{"type": "input_image", "image_url": image_url}]}]}
                    response = client.post("/v1/responses?tag=one&tag=two", json=payload, headers={"Authorization": "Bearer LOCAL_TEST_PLACEHOLDER"})
                    result = response.json()
                    part = result["payload"]["input"][0]["content"][0]
                    require(response.status_code == 201 and response.headers["x-upstream"] == "preserved")
                    require(part["type"] == "input_text" and "123456" in part["text"])
                    require(result["path"] == "/v1/responses?tag=one&tag=two")
                    require(result["authorization"] == "Bearer LOCAL_TEST_PLACEHOLDER")
                check("Responses image conversion, query, auth and status forwarding", responses)

                def chat():
                    payload = {"model": "glm-test", "messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": image_url}}]}]}
                    result = client.post("/v1/chat/completions", json=payload).json()
                    part = result["payload"]["messages"][0]["content"][0]
                    require(part["type"] == "text" and "123456" in part["text"])
                check("Chat Completions image conversion", chat)

                def passthrough():
                    body = json.dumps({"model": "vision-test", "messages": [{"type": "image_url", "image_url": image_url}]}, indent=3).encode()
                    response = client.post("/v1/chat/completions", content=body)
                    require(base64.b64decode(response.json()["raw"]) == body)
                check("Unmatched model body and images remain byte exact", passthrough)

                def streaming():
                    started = time.monotonic()
                    with client.stream("POST", "/v1/responses", json={"model": "GC-demo", "stream": True}) as response:
                        events = response.iter_lines()
                        require(next(events) == 'data: {"delta":"first"}')
                        require(time.monotonic() - started < 0.45)
                        require("data: [DONE]" in list(events))
                check("SSE arrives incrementally and preserves DONE", streaming)

                def compressed():
                    response = client.post("/v1/compressed", json={"model": "vision-test"})
                    require(response.headers["content-encoding"] == "gzip" and response.json()["payload"]["model"] == "vision-test")
                check("Compressed upstream response integrity", compressed)

                def bad_images():
                    for url in ("data:image/png;base64,%%%%", "https://example.invalid/private.png"):
                        response = client.post("/v1/responses", json={"model": "GC-demo", "input": [{"type": "input_image", "image_url": url}]})
                        require(response.status_code == 422 and response.json()["error"]["type"] == "ocr_error")
                check("Invalid and disabled remote images fail clearly", bad_images)

                check("Cross-origin browser requests rejected", lambda: require(client.post("/v1/responses", headers={"Origin": "https://example.invalid"}).status_code == 403))

                def port_conflict():
                    duplicate = ProxyServer(settings, ocr)
                    try:
                        duplicate.start()
                    except ValueError:
                        require(server.running)
                        return
                    duplicate.stop()
                    raise AssertionError()
                check("Port conflicts leave existing service intact", port_conflict)

                upstream.shutdown()
                upstream.server_close()
                # Existing keep-alive connection is closed explicitly via an isolated port.
                original_upstream = settings.upstream
                with socket.socket() as refused:
                    refused.bind(("127.0.0.1", 0))
                    settings.upstream = f"http://127.0.0.1:{refused.getsockname()[1]}"
                    check("Unavailable upstream returns actionable 502", lambda: require(client.post("/v1/responses", json={"model": "vision-test"}).status_code == 502))
                settings.upstream = original_upstream
        except Exception as exc:
            records.append({"check": "Proxy integration infrastructure", "passed": False, "error_type": type(exc).__name__})
        finally:
            server.stop()
            upstream.server_close()
        check("Graceful server shutdown", lambda: require(not server.running))

    report = {"version": VERSION, "passed": all(r["passed"] for r in records), "checks": records,
              "scope": "Isolated files, generated OCR image and mock upstream; no real Codex config or paid API modified/called."}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(verify_bundle(Path(sys.argv[1])))
