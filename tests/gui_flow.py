"""Drive real Qt buttons against an isolated Codex file and mock upstream."""
import json
import socket
import tempfile
import threading
import time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtTest import QTest

from app import Window, STYLE
from core import Settings, Store, atomic_write, read_provider

root = Path(__file__).resolve().parents[1]
app = QApplication([])
app.setStyle("Fusion")
app.setStyleSheet(STYLE)
errors = []
QMessageBox.warning = lambda parent, title, message: errors.append(message)


def wait_for(condition, seconds=40):
    deadline = time.monotonic() + seconds
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("Qt flow timed out")
        app.processEvents()
        time.sleep(0.025)
    app.processEvents()
    assert not errors, errors


class Upstream(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        self.send_response(401)
        self.end_headers()


checks = []
with tempfile.TemporaryDirectory(prefix="ocr-qt-check-") as temp:
    directory = Path(temp)
    upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
    threading.Thread(target=upstream.serve_forever, daemon=True).start()
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = directory / "config.toml"
    base = f"http://127.0.0.1:{upstream.server_port}/v1"
    atomic_write(config, f'model_provider = "cpa-gui"\n[model_providers.cpa-gui]\nbase_url = "{base}"\n')
    store = Store(directory / "data")
    settings = Settings(upstream=f"http://127.0.0.1:{upstream.server_port}", listen_port=port, codex_config=str(config))
    store.save(settings)
    window = Window(store)
    window.show()
    QTest.qWait(500)
    window.model_test.setText("GC-glm-5.3")
    assert "匹配" in window.match_label.text()
    checks.append("Model match preview")

    window.toggle.click()
    wait_for(lambda: not window.thread.isRunning())
    assert window.server.running
    assert read_provider(config, settings.provider)[1] == settings.proxy_base
    assert not window.models.isEnabled()
    checks.append("Enable button switches fixture provider and locks editable settings")
    window.diagnose()
    wait_for(lambda: not window.thread.isRunning(), 60)
    assert "[失败]" not in window.report
    assert "[通过] 本地 OCR 实际识别" in window.report
    assert "HTTP 401" in window.report
    checks.append("Diagnostic button runs actual OCR and explains mock HTTP 401")
    window.grab().save(str(root / "ui-diagnostics.png"))

    window.toggle.click()
    wait_for(lambda: not window.thread.isRunning())
    assert window.server is None
    assert read_provider(config, settings.provider)[1] == base
    assert window.models.isEnabled()
    checks.append("Disable button restores fixture provider and unlocks settings")

    window.toggle.click()
    wait_for(lambda: not window.thread.isRunning())
    window.close()
    wait_for(lambda: not window.isVisible())
    assert read_provider(config, settings.provider)[1] == base
    assert not store.journal_path.exists()
    checks.append("Window close restores provider before process exit")
    upstream.shutdown()
    upstream.server_close()
(root / "verification-ui.json").write_text(json.dumps({"passed": True, "checks": checks, "scope": "Qt buttons, fixture config and mock upstream only"}, ensure_ascii=False, indent=2), encoding="utf-8")
print("PASS: Qt button, diagnostic and close lifecycle checks")
