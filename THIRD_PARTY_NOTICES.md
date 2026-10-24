# Third-party notices

This desktop application is built on Python, PySide6/Qt, RapidOCR, ONNX Runtime,
FastAPI/Starlette, Uvicorn, HTTPX, NumPy, OpenCV, Pillow and their dependencies.
It adapts the OCR proxy concept and two OpenAI API content formats from the
user's existing WorkBuddy-generated middleware. No original credential,
conversation cache or runtime log is distributed.

Dependency license texts available in the installed wheels are included under
`licenses/`. Exact build versions are recorded in `requirements-runtime.txt`
in the source project. PySide6/Qt are used under their available open-source
licenses (including LGPLv3 for the relevant Qt/PySide components); Qt dynamic
libraries are kept as separate DLLs under `_internal` (and `_internal/PySide6`)
so they remain replaceable.
Corresponding source and license information:

- Qt: https://code.qt.io/ and https://www.qt.io/licensing/open-source-lgpl-obligations
- PySide: https://code.qt.io/cgit/pyside/pyside-setup.git/
- Python: https://www.python.org/downloads/source/
- RapidOCR: https://github.com/RapidAI/RapidOCR
- ONNX Runtime: https://github.com/microsoft/onnxruntime

Build/packaging uses PyInstaller, distributed under GPL with the bootloader
exception; using it does not by itself impose GPL on the packaged application.
Source: https://github.com/pyinstaller/pyinstaller

The package includes OCR models from the installed `rapidocr-onnxruntime`
distribution. Retain the bundled notices with redistributed copies.
