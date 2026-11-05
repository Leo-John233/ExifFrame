# Commands
Run in project root.

## Current Windows environment
- User-supplied existing Conda environment: `D:/miniconda3/envs/Python3.13`. Reuse it; do not create a project .venv or use the WindowsApps Python alias.
- Interpreter: `& 'D:/miniconda3/envs/Python3.13/python.exe' --version`.
- Native workspace: `& 'D:/miniconda3/envs/Python3.13/python.exe' main.py` (sets working directory automatically).
- Legacy browser entry: `& 'D:/miniconda3/envs/Python3.13/python.exe' web_server.py`.
- Native startup/shutdown smoke check: `& 'D:/miniconda3/envs/Python3.13/python.exe' main.py --smoke-test`.
- Default URL is configured in config/config.ini: `http://localhost:15050`; web_server.py opens a browser when debug is false.
- Dependency installation, when needed for a development task: `& 'D:/miniconda3/envs/Python3.13/python.exe' -m pip install -r requirements.txt`. Installation changes this external environment; onboarding only inspected it.
- EXIF-backed processing also requires `exiftool/exiftool.exe` and its distribution support files.
- Machine-specific Serena guidance is in `.serena/project.local.yml`, which is excluded by `.serena/.gitignore`.

## uv route (optional, not the selected local environment)
- `uv sync`; `uv run python web_server.py`.
- Creates/uses a separate managed environment; prefer the user-supplied Conda interpreter for this machine.
- Keep in mind the pip CI dependency path described in `mem:tech_stack`.

## Windows packaging
- Prepare the official NumPy wheel: `python -m pip download --only-binary=:all: --no-deps --dest build/wheels numpy==2.5.2`.
- `python build_support/build_windows.py` builds `dist/single/ExifFrame.exe`; templates, fonts, logos, static assets, project metadata and full ExifTool are embedded. The script verifies the pinned wheel and temporarily installs it under build without changing the Python environment.
- `python build_support/build_windows.py --onedir` creates a fresh directory under `dist/onedir`; distribute the entire printed directory. New builds do not overwrite prior user configs or photos.
- Prepare `exiftool` with an executable and adjacent `exiftool_files` before building; CI downloads ExifTool and uses pinned `build_support/requirements-windows.txt`. Existing `dist/ExifFrame` is not replaced.
- The single-file app stores user configuration under `%LOCALAPPDATA%/ExifFrame`; preserve it across updates.

## Windows file inspection
- `Get-ChildItem -Force` includes hidden files; `Get-Content -LiteralPath <path>` handles spaces/non-ASCII names.
- For validation commands and checks: `mem:task_completion`.
