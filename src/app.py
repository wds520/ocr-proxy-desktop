from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtCore import QObject, QThread, Signal, QTimer, QLockFile, Qt
from PySide6.QtGui import QFont, QIcon, QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTabWidget, QFormLayout, QLineEdit, QSpinBox, QPlainTextEdit,
    QCheckBox, QFileDialog, QMessageBox, QFrame)

from core import Settings, Store, VERSION
from diagnostics import run_diagnostics, safe_url
from engine import OCR, ProxyServer, model_matches


class Worker(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self):
        try:
            self.finished.emit(self.fn(self.progress.emit))
        except (ValueError, OSError) as exc:
            self.failed.emit(str(exc) if isinstance(exc, ValueError) else "文件无法读写，请检查目录权限或配置文件是否被占用。")
        except Exception:
            logging.getLogger("ocr_proxy").error("Operation failed (private exception details omitted)")
            self.failed.emit("操作未完成，请运行自动诊断并检查完整解压情况。")


class Window(QMainWindow):
    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self.settings = store.load()
        self.ocr = OCR()
        self.server = None
        self.thread = None
        self.worker = None
        self.allow_close = False
        self.closing = False
        self.report = ""
        self.actions = []
        self.setWindowTitle("OCR 代理助手 · 便携版")
        self.resize(980, 780)
        self.setMinimumSize(860, 700)
        icon = Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "app.ico"
        if icon.exists():
            self.setWindowIcon(QIcon(str(icon)))
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(30, 24, 30, 18)
        layout.setSpacing(16)
        title_row = QHBoxLayout()
        heading = QLabel("OCR 代理助手")
        heading.setObjectName("heading")
        title_row.addWidget(heading)
        title_row.addStretch()
        badge = QLabel(f"PORTABLE  /  v{VERSION}")
        badge.setObjectName("badge")
        title_row.addWidget(badge)
        layout.addLayout(title_row)
        intro = QLabel("让文本模型读懂图片中的文字。识别在本机完成，再将文字交给模型。")
        intro.setObjectName("muted")
        layout.addWidget(intro)

        card = QFrame()
        card.setObjectName("card")
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(20, 16, 20, 16)
        status_row = QHBoxLayout()
        self.status = QLabel("●  代理未启用")
        self.status.setObjectName("status")
        status_row.addWidget(self.status)
        status_row.addStretch()
        self.toggle = self.button("启用 OCR 代理", self.toggle_proxy, "primary")
        status_row.addWidget(self.toggle)
        card_layout.addLayout(status_row)
        self.address = QLabel()
        self.address.setObjectName("muted")
        self.address.setTextInteractionFlags(Qt.TextSelectableByMouse)
        card_layout.addWidget(self.address)
        layout.addWidget(card)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self.model_tab = QWidget()
        models_layout = QVBoxLayout(self.model_tab)
        models_layout.setContentsMargins(18, 16, 18, 16)
        models_layout.addWidget(QLabel("哪些模型需要先做 OCR？"))
        hint = QLabel("每行一条规则，支持 * 和 ?，忽略大小写。匹配模型的图片转成文字；其余模型保留原始图片。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        models_layout.addWidget(hint)
        self.models = QPlainTextEdit("\n".join(self.settings.models))
        self.models.setPlaceholderText("GC-*\nglm-*\ndeepseek-*")
        models_layout.addWidget(self.models, 1)
        test_row = QHBoxLayout()
        self.model_test = QLineEdit()
        self.model_test.setPlaceholderText("输入模型名称，预览是否匹配，例如 GC-glm-5.3")
        self.match_label = QLabel("等待输入")
        self.model_test.textChanged.connect(self.preview_model)
        test_row.addWidget(self.model_test, 1)
        test_row.addWidget(self.match_label)
        models_layout.addLayout(test_row)
        save_row = QHBoxLayout()
        tip = QLabel("OCR 适合截图文字、报错与文档；图表关系、颜色和画面细节需要视觉模型。")
        tip.setObjectName("muted")
        tip.setWordWrap(True)
        save_row.addWidget(tip, 1)
        save_row.addWidget(self.button("保存设置", self.save))
        models_layout.addLayout(save_row)
        self.tabs.addTab(self.model_tab, "模型规则")

        self.connection_tab = QWidget()
        con_layout = QVBoxLayout(self.connection_tab)
        con_layout.setContentsMargins(18, 16, 18, 16)
        form = QFormLayout()
        form.setVerticalSpacing(16)
        self.upstream = QLineEdit(self.settings.upstream)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(self.settings.listen_port)
        self.remote = QCheckBox("允许下载请求中的远程图片 URL 后识别")
        self.remote.setChecked(self.settings.fetch_remote_images)
        form.addRow("上游服务根地址", self.upstream)
        form.addRow("本地 OCR 端口", self.port)
        agent_row = QWidget()
        agent_layout = QHBoxLayout(agent_row)
        agent_layout.setContentsMargins(0, 0, 0, 0)
        agent_layout.setSpacing(8)
        self.agent_url = QLabel(f"http://127.0.0.1:{self.port.value()}")
        self.agent_url.setObjectName("agentUrl")
        self.agent_url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.copy_url = QPushButton("⧉")
        self.copy_url.setObjectName("copy")
        self.copy_url.setCursor(Qt.PointingHandCursor)
        self.copy_url.setToolTip("复制 Agent 要配置的本地地址")
        self.copy_url.clicked.connect(self.copy_agent_url)
        agent_layout.addWidget(self.agent_url, 1)
        agent_layout.addWidget(self.copy_url)
        form.addRow("Agent base_url", agent_row)
        self.port.valueChanged.connect(self.update_agent_url)
        form.addRow("远程图片", self.remote)
        con_layout.addLayout(form)
        note = QLabel("把 Agent 的 OpenAI 兼容 base_url 指向上方状态卡片中的本地地址，图片即可经本机 OCR 后交给模型。\n"
                      "这里只配置 OCR 中转，不是系统 HTTP / SOCKS 代理；本应用不会修改任何 Agent 的配置。\n"
                      "代理运行期间请保持本应用打开。启用/关闭后，请重开 Agent 会话或重启 Agent。")
        note.setWordWrap(True)
        note.setObjectName("muted")
        con_layout.addWidget(note)
        con_layout.addStretch()
        con_layout.addWidget(self.button("保存设置", self.save), alignment=Qt.AlignRight)
        self.tabs.addTab(self.connection_tab, "连接设置")

        diagnostic_tab = QWidget()
        diag_layout = QVBoxLayout(diagnostic_tab)
        diag_layout.setContentsMargins(18, 16, 18, 16)
        diag_row = QHBoxLayout()
        diag_row.addWidget(self.button("运行自动诊断", self.diagnose, "primary"))
        diag_row.addWidget(self.button("导出诊断报告", self.export))
        diag_row.addStretch()
        diag_row.addWidget(self.button("打开数据目录", self.open_data))
        diag_layout.addLayout(diag_row)
        diag_hint = QLabel("检查配置、端口、上游 HTTP 和本地 OCR 识别。首次加载 OCR 模型可能需要数秒；不调用付费模型。")
        diag_hint.setObjectName("muted")
        diag_hint.setWordWrap(True)
        diag_layout.addWidget(diag_hint)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("点击“运行自动诊断”开始检查。诊断报告不会包含 API 密钥和图片内容。")
        diag_layout.addWidget(self.output, 1)
        self.tabs.addTab(diagnostic_tab, "自动诊断")
        self.message = QLabel("就绪。保存模型规则后，点击“启用 OCR 代理”。")
        self.message.setWordWrap(True)
        self.message.setObjectName("muted")
        layout.addWidget(self.message)
        self.refresh()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2500)

    def button(self, text, fn, kind=""):
        button = QPushButton(text)
        button.setCursor(Qt.PointingHandCursor)
        if kind:
            button.setObjectName(kind)
        button.clicked.connect(fn)
        self.actions.append(button)
        return button

    def collect(self):
        settings = Settings(upstream=self.upstream.text().strip().rstrip("/"), listen_port=self.port.value(),
            models=[line.strip() for line in self.models.toPlainText().splitlines() if line.strip()],
            fetch_remote_images=self.remote.isChecked())
        settings.validate()
        return settings

    def preview_model(self, *_):
        name = self.model_test.text().strip()
        rules = [p.strip() for p in self.models.toPlainText().splitlines() if p.strip()]
        self.match_label.setText("匹配：图片 → 文字" if name and model_matches(name, rules) else ("保留原始图片" if name else "等待输入"))

    def update_agent_url(self, *_):
        self.agent_url.setText(f"http://127.0.0.1:{self.port.value()}")

    def copy_agent_url(self):
        QApplication.clipboard().setText(self.agent_url.text())
        self.message.setText("已复制 Agent base_url，请粘贴到 Agent 配置中。")

    def busy(self, value):
        for button in self.actions:
            button.setEnabled(not value)
        running = bool(self.server and self.server.running)
        self.model_tab.setEnabled(not value and not running)
        self.connection_tab.setEnabled(not value and not running)

    def job(self, fn, done):
        if self.thread and self.thread.isRunning():
            return
        self.busy(True)
        self.thread = QThread(self)
        self.worker = Worker(fn)
        self.worker.moveToThread(self.thread)
        self.thread.started.connect(self.worker.run)
        self.worker.progress.connect(self.output.appendPlainText)
        self.worker.finished.connect(done)
        self.worker.failed.connect(self.error)
        self.worker.finished.connect(self.thread.quit)
        self.worker.failed.connect(self.thread.quit)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.failed.connect(self.worker.deleteLater)
        self.thread.finished.connect(self.finished_job)
        self.thread.start()

    def finished_job(self):
        self.busy(False)
        self.refresh()
        if self.allow_close:
            QTimer.singleShot(0, self.close)

    def error(self, text):
        self.closing = False
        self.message.setText(text)
        QMessageBox.warning(self, "操作未完成", text)

    def save(self):
        try:
            self.settings = self.collect()
            self.store.save(self.settings)
            self.message.setText("设置已保存，下次启用代理时生效。")
            self.refresh()
        except (ValueError, OSError) as exc:
            self.error(str(exc) if isinstance(exc, ValueError) else "无法写入设置文件，请检查目录权限。")

    def toggle_proxy(self):
        if self.server and self.server.running:
            self.stop_proxy()
            return
        try:
            settings = self.collect()
            self.store.save(settings)
        except (ValueError, OSError) as exc:
            self.error(str(exc) if isinstance(exc, ValueError) else "无法保存设置。")
            return
        self.settings = settings
        self.message.setText("正在启动本地 OCR 代理…")

        def start(_):
            server = ProxyServer(settings, self.ocr)
            server.start()
            return server

        def started(server):
            self.server = server
            self.message.setText("代理已启用。请把 Agent 的 base_url 指向本地地址，并重开会话。")

        self.job(start, started)

    def stop_proxy(self):
        self.message.setText("正在结束代理请求…")

        def stop(_):
            if self.server:
                self.server.stop()
            return "代理已关闭。"

        def stopped(message):
            self.server = None
            self.message.setText(message + " 重开 Agent 会话后生效。")
            if self.closing:
                self.allow_close = True

        self.job(stop, stopped)

    def diagnose(self):
        try:
            settings = self.collect()
        except ValueError as exc:
            self.error(str(exc))
            return
        self.tabs.setCurrentIndex(2)
        self.output.clear()
        self.message.setText("诊断进行中，首次加载 OCR 模型可能需要数秒…")
        running = bool(self.server and self.server.running)
        self.busy(True)
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            def emit(line):
                self.output.appendPlainText(line)
                QApplication.processEvents()
            report = run_diagnostics(settings, self.store, self.ocr, running, emit)
            self.report = report
            self.output.setPlainText(report)
            self.message.setText("诊断完成。请查看“失败”和“注意”项目。")
        except Exception:
            logging.getLogger("ocr_proxy").error("Diagnostics failed (private exception details omitted)")
            self.error("诊断未完成，请重试或检查完整解压情况。")
        finally:
            QApplication.restoreOverrideCursor()
            self.busy(False)
            self.refresh()

    def export(self):
        if not self.report:
            self.message.setText("请先运行自动诊断。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出诊断报告", str(self.store.directory / "diagnostics.txt"), "Text files (*.txt)")
        if path:
            try:
                Path(path).write_text(self.report, encoding="utf-8")
                self.message.setText("诊断报告已导出。")
            except OSError:
                self.error("报告导出失败，请选择可写目录。")

    def open_data(self):
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.store.directory)))

    def refresh(self):
        running = bool(self.server and self.server.running)
        self.status.setText("●  代理已启用" if running else "●  代理未启用")
        self.status.setStyleSheet("color: #07795c" if running else "color: #64748b")
        self.toggle.setText("关闭 OCR 代理" if running else "启用 OCR 代理")
        base = f"http://127.0.0.1:{self.settings.listen_port}"
        self.address.setText(f"Agent base_url  →  {base}  →  {safe_url(self.settings.upstream)}")

    def maybe_show_onboarding(self):
        marker = self.store.directory / ".onboarded"
        if marker.exists():
            return
        QMessageBox.information(
            self,
            "欢迎使用 OCR 代理助手",
            "首次使用只需 4 步：\n\n"
            "1. 连接设置：确认“上游服务根地址”（默认已填 gateway.onewo.com/v1）。\n"
            "2. 模型规则：已预填 GC-*、glm-*、deepseek-*，按需修改后点“保存设置”。\n"
            "3. 回到顶部点“启用 OCR 代理”，复制“Agent base_url”旁的 ⧉ 图标。\n"
            "4. 把地址粘贴到你的 Agent（WorkBuddy / opencode / zcode 等）的\n"
            "    OpenAI 兼容 base_url，然后重开 Agent 会话。\n\n"
            "最后可在“自动诊断”页一键检查环境是否就绪。代理运行期间请保持本应用打开。")
        try:
            marker.write_text(VERSION, encoding="utf-8")
        except OSError:
            pass

    def closeEvent(self, event):
        if self.allow_close:
            event.accept()
            return
        if self.thread and self.thread.isRunning():
            self.message.setText("正在处理操作，请完成后再退出。")
            event.ignore()
            return
        if self.server and self.server.running:
            event.ignore()
            self.closing = True
            self.stop_proxy()
        else:
            event.accept()


STYLE = """
QWidget { font-family: 'Microsoft YaHei UI'; font-size: 13px; color: #243449; }
QMainWindow, QTabWidget::pane { background: #f4f7fb; }
QLabel#heading { font-size: 27px; font-weight: 700; color: #162c43; }
QLabel#badge { color: #377a77; background: #e1f2ef; border-radius: 6px; padding: 7px 12px; font-size: 11px; font-weight: 600; }
QLabel#muted { color: #62748a; line-height: 1.6; }
QLabel#status { font-size: 19px; font-weight: 600; }
QFrame#card { background: white; border: 1px solid #dce4ee; border-radius: 12px; }
QPushButton { background: white; border: 1px solid #ccd7e4; border-radius: 7px; padding: 9px 16px; font-weight: 600; }
QPushButton:hover { background: #edf4fa; border-color: #8ba8bf; }
QPushButton#primary { background: #087e83; color: white; border-color: #087e83; }
QPushButton#primary:hover { background: #066a70; }
QPushButton:disabled { color: #95a2b2; background: #e9eef3; border-color: #dce4ee; }
QTabWidget::pane { border: 1px solid #dce4ee; border-radius: 8px; background: white; }
QTabBar::tab { padding: 12px 22px; color: #53677c; background: #eaf0f6; margin-right: 4px; }
QTabBar::tab:selected { color: #087e83; background: white; border-bottom: 3px solid #087e83; font-weight: 700; }
QLineEdit, QSpinBox, QPlainTextEdit { background: #fcfdff; border: 1px solid #ccd7e4; border-radius: 7px; padding: 9px; selection-background-color: #c9eae8; }
QLineEdit:focus, QPlainTextEdit:focus { border: 1px solid #087e83; }
QPlainTextEdit { font-family: 'Consolas', 'Microsoft YaHei UI'; font-size: 13px; }
QCheckBox { spacing: 8px; }
QLabel#agentUrl { font-family: 'Consolas', 'Microsoft YaHei UI'; color: #087e83; font-weight: 600; }
QPushButton#copy { padding: 4px 8px; min-width: 32px; max-width: 32px; max-height: 30px; }
QMessageBox { background: #f7fafd; }
QMessageBox QLabel { color: #243449; font-size: 13px; }
QMessageBox QPushButton { background: #087e83; color: white; border: none; border-radius: 6px; padding: 8px 18px; font-weight: 600; min-width: 88px; }
QMessageBox QPushButton:hover { background: #066a70; }
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path)
    parser.add_argument("--smoke-test", type=Path, help="save UI screenshot and exit, never change agent config")
    parser.add_argument("--verify-bundle", type=Path, help="run isolated integration checks and write report")
    args = parser.parse_args()
    if args.verify_bundle:
        from verify import verify_bundle
        return verify_bundle(args.verify_bundle)
    app = QApplication(sys.argv[:1])
    app.setApplicationName("OCRProxyDesktop")
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 10))
    app.setStyleSheet(STYLE)
    try:
        store = Store(args.data_dir)
        lock = QLockFile(str(store.directory / "app.lock"))
        if not lock.tryLock(100):
            QMessageBox.information(None, "OCR 代理助手", "此便携目录的应用已在运行，请切换到已有窗口。")
            return 1
        handler = RotatingFileHandler(store.directory / "application.log", maxBytes=1024*1024, backupCount=2, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logging.getLogger("ocr_proxy").addHandler(handler)
        logging.getLogger("ocr_proxy").setLevel(logging.INFO)
        window = Window(store)
    except Exception:
        QMessageBox.critical(None, "无法启动", "无法读取便携设置或写入应用目录。请检查 data/settings.json，或把完整应用移到可写目录。")
        return 1
    window.show()
    if args.smoke_test:
        def capture():
            args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            window.grab().save(str(args.smoke_test))
            window.allow_close = True
            window.close()
        QTimer.singleShot(1200, capture)
    else:
        window.maybe_show_onboarding()
    result = app.exec()
    lock.unlock()
    return result


if __name__ == "__main__":
    sys.exit(main())
