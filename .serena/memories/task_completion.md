# Completion and validation
- No automated test suite, pytest/unittest runner configuration, formatter, linter, or type-checker configuration was found in the supplied project. CI workflows package releases; they do not define a test gate. Do not report nonexistent checks as passed.
- For Python changes, use the user-supplied local interpreter: `& 'D:/miniconda3/envs/Python3.13/python.exe' -m compileall -q app.py core processor`. Syntax checking does not validate runtime dependencies or image behavior. Environment selection and run commands: `mem:suggested_commands`.
- For behavior/UI changes, run app.py from root using `mem:suggested_commands`; verify the relevant config/template/file operation and browser rendering.
- For pipeline/template changes, process representative copies of photos with ExifTool available; inspect output dimensions, orientation, fonts, logo and image quality. Check progress completion/error/skip behavior for changes affecting batch orchestration; avoid overwriting originals.
- For packaging changes, validate the appropriate release workflow and its resource/ExifTool layout in addition to local execution.
- Report which checks actually ran and any unavailable prerequisite; the checked-out folder may not contain .git, so verify Git availability before relying on diff/status.
- For memory-only updates, verify every referenced memory exists. From project root, `serena memories check` can audit memory references when the Serena CLI is available.
