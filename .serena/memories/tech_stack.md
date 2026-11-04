# Toolchain and runtime dependencies
- Windows is the only supported operating system. Python >=3.13 in `pyproject.toml`; `.python-version` selects 3.13, matching Windows packaging CI.
- Two dependency routes coexist: project dependencies + `uv.lock` for uv; `requirements.txt` for pip and Windows CI. Do not assume lockfile edits affect the pip-based release workflow.
- Backend: Flask/Jinja2; image work: Pillow, pillow-heif (registered on processor package import), NumPy; logging: Loguru; project TOML loading: tomli.
- `pystray` is declared in project dependencies but absent from requirements.txt; assess which installation path a dependency change must support.
- Legacy browser frontend is one Jinja HTML template with Alpine.js, Tailwind CDN, Ace JSON editor and Toastify loaded from CDNs. No Node package manifest or frontend build pipeline; a fully offline backend does not imply offline UI asset availability.
- EXIF lookup is relative to source root / frozen executable directory, supporting exiftool/exiftool.exe and exiftool/exiftool(-k).exe plus adjacent exiftool_files. No PATH lookup. UTF-8 stdin argument streams avoid Windows filename encoding loss; JSON -l aliases preserve original template keys. Pillow fallback applies only when extraction is unavailable.
- Config INI is read and written explicitly as UTF-8; retain this for Chinese template names under Windows' default GBK locale.
- Native UI uses PySide6, declared in requirements and pyproject, resolved in uv.lock. Windows CI builds main.py through build_win_pkg.spec, then adds config, static, pyproject.toml and downloaded ExifTool beside ExifFrame.exe. Assets remain external and replaceable.
- PyInstaller child-process compatibility bootstrap is in build_support/sitecustomize.py; Conda Pillow decoding DLLs are collected explicitly. Native architecture details: `mem:studio/core`.
