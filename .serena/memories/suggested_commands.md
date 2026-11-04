# Commands
Run in project root.

## Current Windows environment
- User-supplied existing Conda environment: `D:/miniconda3/envs/Python3.13`. Reuse it; do not create a project .venv or use the WindowsApps Python alias.
- Interpreter: `& 'D:/miniconda3/envs/Python3.13/python.exe' --version`.
- Native workspace: `& 'D:/miniconda3/envs/Python3.13/python.exe' main.py` (sets working directory automatically).
- Legacy browser entry: `& 'D:/miniconda3/envs/Python3.13/python.exe' app.py`.
- Native startup/shutdown smoke check: `& 'D:/miniconda3/envs/Python3.13/python.exe' main.py --smoke-test`.
- Default URL is configured in config/config.ini: `http://localhost:15050`; app.py opens a browser when debug is false.
- Dependency installation, when needed for a development task: `& 'D:/miniconda3/envs/Python3.13/python.exe' -m pip install -r requirements.txt`. Installation changes this external environment; onboarding only inspected it.
- EXIF-backed processing also requires `exiftool/exiftool.exe` and its distribution support files.
- Machine-specific Serena guidance is in `.serena/project.local.yml`, which is excluded by `.serena/.gitignore`.

## uv route (optional, not the selected local environment)
- `uv sync`; `uv run python app.py`.
- Creates/uses a separate managed environment; prefer the user-supplied Conda interpreter for this machine.
- Keep in mind the pip CI dependency path described in `mem:tech_stack`.

## Windows packaging
- `& 'D:/miniconda3/envs/Python3.13/python.exe' -m pip install pyinstaller`
- `& 'D:/miniconda3/envs/Python3.13/python.exe' -m PyInstaller ./build_win_pkg.spec`
- Executable generation alone is not the full package: follow `.github/workflows/build_win_pkg.yml` for external config/metadata/resources and ExifTool.

## Windows file inspection
- `Get-ChildItem -Force` includes hidden files; `Get-Content -LiteralPath <path>` handles spaces/non-ASCII names.
- For validation commands and checks: `mem:task_completion`.
