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
- Full photo metadata editing requires `exiftool/exiftool.exe` (or `exiftool(-k).exe`) and its adjacent exiftool_files. Source GUI startup warns when either is missing, then continues with watermark fallback; smoke/verify/frozen launches skip the source-only warning.
- Machine-specific Serena guidance is in `.serena/project.local.yml`, which is excluded by `.serena/.gitignore`.

## uv route (optional, not the selected local environment)
- `uv sync`; `uv run python web_server.py`.
- Creates/uses a separate managed environment; prefer the user-supplied Conda interpreter for this machine.
- Keep in mind the pip CI dependency path described in `mem:tech_stack`.

## Windows packaging
- `python build_support/build_windows.py` builds `build/ExifFrame.exe`; templates, fonts, logos, static assets, project metadata and full ExifTool are embedded. Only the pinned NumPy wheel is downloaded into build/download and reused when present, without repeated checksum scans. ExifTool is read directly from the project's exiftool directory; missing executable/support directory stops the build with instructions to complete it. No ExifTool download or extra cache copy is performed.
- Builds unpack the NumPy wheel directly and run PyInstaller analysis outside the workspace in a unique system temporary directory, then clean dependencies, analysis and staging after success or failure. This avoids pip installation and VS Code watching/analyzing generated Python trees; .vscode/settings.json also excludes build/dist from watching and Python analysis. Cross-drive publication copies into a short-lived sibling staging path before replacing the final cache/output. Download resources, previous output and user configuration are preserved. Child process trees use at most two logical CPUs, below-normal priority, numerical-library threads=1 and a job-wide memory allowance capped at 4 GiB and half available physical/commit memory. Low available memory stops the build; external commands have stage-specific timeouts. The pinned PyInstaller 6.20 build uses CArchive compression level 6 (instead of 9), only inside the builder process, for faster single-file packaging; PYZ stays at its default 6. ExifTool's complete independent runtime is added to the onefile DATA TOC after Analysis, avoiding redundant PE dependency analysis. Do not add file hashes, origin audits or repeated read/write/import checks to normal builds; preserve essential missing-input and safe-publication checks.
- For offline builds, populate `build/download` or pass `--numpy-wheel` with the full path to the pinned official NumPy wheel; this user-provided input is not deleted.
- `python build_support/build_windows.py --onedir` creates a fresh directory under `build/onedir`; distribute the entire printed directory. New builds do not overwrite prior user configs or photos.
- Local builds require the root exiftool directory, intentionally Git-ignored; the build script never fetches ExifTool. The GitHub workflow is the authorized exception: hosted Windows restores a versioned ExifTool cache, or downloads the pinned official Windows archive when missing, and supplies exiftool before invoking the unchanged build script. CI caches pip dependencies and the NumPy wheel separately; the wheel name is read from build_windows.py. A v-prefixed tag or manual workflow_dispatch with required release_tag builds and publishes a GitHub Release with ExifFrame.exe, not an Actions artifact. Existing tags build their resolved commit (including annotated tags); new manual tags use the selected commit and are created only after build/startup succeeds. Repeated runs preserve existing notes/assets and fill missing assets, completing drafts without deleting published files. Release tag groups run serially; only metadata/publish steps receive GH_TOKEN. Prefer the default branch for new manual releases (workflow-file permission restrictions) and cache seeding; tags cannot restore each other's private caches.
- The single-file app stores config beside ExifFrame.exe; preserve that folder across updates. `EXIFFRAME_DATA_DIR` remains an explicit environment override.

## Windows file inspection
- `Get-ChildItem -Force` includes hidden files; `Get-Content -LiteralPath <path>` handles spaces/non-ASCII names.
- For validation commands and checks: `mem:task_completion`.
