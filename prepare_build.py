"""Generate the application icon and record exactly used runtime dependencies."""
from importlib.metadata import version
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent
image = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((4, 4, 252, 252), radius=56, fill="#087e83")
for points in (((48, 84), (48, 48), (84, 48)), ((172, 48), (208, 48), (208, 84)),
               ((48, 172), (48, 208), (84, 208)), ((172, 208), (208, 208), (208, 172))):
    draw.line(points, fill="white", width=12, joint="curve")
draw.text((52, 91), "OCR", font=ImageFont.load_default(size=58), fill="white")
image.save(root / "src" / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
names = ["fastapi", "starlette", "uvicorn", "h11", "httpx", "httpcore", "anyio", "certifi", "idna",
         "pydantic", "pydantic_core", "typing_extensions", "typing_inspection", "annotated_types",
         "rapidocr-onnxruntime", "onnxruntime", "numpy", "opencv-python", "Pillow", "pyclipper", "Shapely",
         "PyYAML", "six", "coloredlogs", "humanfriendly", "flatbuffers", "packaging", "protobuf", "sympy",
         "mpmath", "click", "colorama", "PySide6-Essentials", "shiboken6"]
pins = []
for name in names:
    try:
        pins.append(f"{name}=={version(name)}")
    except Exception:
        pass
(root / "requirements-runtime.txt").write_text("# Windows x64 / Python 3.13; captured from the verified build environment\n" + "\n".join(pins) + "\n", encoding="utf-8")

