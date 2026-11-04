# Toolchain and runtime dependencies
- Windows is the only supported operating system. Python >=3.13 in `pyproject.toml`; `.python-version` selects 3.13, matching Windows packaging CI.
- Two dependency routes coexist: project dependencies + `uv.lock` for uv; `requirements.txt` for pip and Windows CI. Do not assume lockfile edits affect the pip-based release workflow.
- Backend: Flask/Jinja2; image work: Pillow, pillow-heif (registered on processor package import), NumPy; logging: Loguru; project TOML loading: tomli.
- `pystray` is declared in project dependencies but absent from requirements.txt; assess which installation path a dependency change must support.
- Frontend is one Jinja HTML template with Alpine.js, Tailwind CDN, Ace JSON editor and Toastify loaded from CDNs. No Node package manifest or frontend build pipeline; a fully offline backend does not imply offline UI asset availability.
- EXIF metadata comes from the bundled external `./exiftool/exiftool.exe`, not a Python package. No system PATH lookup or executable fallback.
- Config INI is read and written explicitly as UTF-8; retain this for Chinese template names under Windows' default GBK locale.
- Windows CI installs requirements + PyInstaller, builds `build_win_pkg.spec`, then adds external config/project metadata and downloaded ExifTool. Spec bundles HTML templates.
