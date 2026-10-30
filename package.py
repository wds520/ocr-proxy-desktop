from __future__ import annotations
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path
import shutil
import sys
import zipfile

root = Path(__file__).resolve().parent
bundle = root / "dist" / "OCRProxyDesktop"
shutil.copy2(root / "README.md", bundle / "使用说明.md")
shutil.copy2(root / "THIRD_PARTY_NOTICES.md", bundle / "THIRD_PARTY_NOTICES.md")
licenses = bundle / "licenses"
licenses.mkdir(exist_ok=True)
for line in (root / "requirements-runtime.txt").read_text("utf-8").splitlines() + ["pyinstaller==6.19.0"]:
    if "==" not in line:
        continue
    name = line.split("==")[0]
    dist = distribution(name)
    for file in dist.files or []:
        relative = Path(str(file))
        if any(word in str(relative).lower() for word in ("license", "copying", "copyright", "notice")):
            source = Path(dist.locate_file(file))
            if source.is_file():
                target = licenses / name / relative
                # Metadata file lists must not escape the dependency license directory.
                if target.resolve().is_relative_to((licenses / name).resolve()):
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.exists():
    shutil.copy2(python_license, licenses / "Python-LICENSE.txt")
(bundle / "VERSION.json").write_text(json.dumps({"version": "1.0.0", "platform": "Windows x64", "distribution": "portable directory", "python": sys.version.split()[0]}, indent=2), encoding="utf-8")
release = root / "release"
release.mkdir(exist_ok=True)
archive = release / "OCRProxyDesktop-1.0.0-win-x64-portable.zip"
with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for file in sorted(bundle.rglob("*")):
        if file.is_file() and "data" not in file.relative_to(bundle).parts:
            z.write(file, file.relative_to(bundle.parent))
digest = hashlib.sha256(archive.read_bytes()).hexdigest()
(release / (archive.name + ".sha256")).write_text(digest + "  " + archive.name + "\n", encoding="ascii")
print(f"Portable ZIP: {archive}\nSize: {archive.stat().st_size / 1024**2:.1f} MB\nSHA256: {digest}")

