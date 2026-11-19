"""参数历史只保存本次操作涉及的照片或工作区样式"""

from dataclasses import replace

from PySide6.QtGui import QUndoCommand, QUndoStack

from .state import STYLE_FIELDS


class ParameterChange(QUndoCommand):
    def __init__(self, history, kind, paths, before, after):
        super().__init__()
        self.history = history
        self.kind, self.paths = kind, paths
        self.before, self.after = before, after
        self.gesture = history.group or history.gesture
        self.first = True

    def id(self):
        return 1 if self.gesture is not None else -1

    def mergeWith(self, other):
        if (self.kind, self.paths, self.gesture) != (other.kind, other.paths, other.gesture):
            return False
        self.after = other.after
        self.setObsolete(self.before == self.after)
        return True

    def undo(self):
        self.history.restore(self.kind, self.paths, self.before)

    def redo(self):
        if self.first:
            self.first = False
        else:
            self.history.restore(self.kind, self.paths, self.after)


class ParameterHistory:
    def __init__(self, window):
        self.window = window
        self.stack = QUndoStack(window)
        self.stack.setUndoLimit(100)
        self.gesture = None
        self.group = None

    def begin_group(self):
        self.group = object()

    def finish_group(self):
        self.group = None

    def snapshot(self, kind, paths):
        window = self.window
        if not paths:
            return ({key: getattr(window.settings, key) for key in STYLE_FIELDS},
                    window.state.active_template, window._drafts.copy())
        read = window.state.metadata_for if kind == 'metadata' else window.state.style_for
        return {path: read(path) for path in paths}

    def run(self, kind, paths, change, *args):
        paths = tuple(paths)
        before = self.snapshot(kind, paths)
        result = change(*args)
        after = self.snapshot(kind, paths)
        if before != after:
            self.stack.push(ParameterChange(self, kind, paths, before, after))
        return result

    def restore(self, kind, paths, values):
        window = self.window
        if not paths:
            settings, template, drafts = values
            window.state.set_active_template(template)
            window.settings = replace(window.settings, **settings)
            window._drafts = drafts.copy()
            window._workspace_changed()
            window._style_preview_changed()
        elif kind == 'metadata':
            window.state.update_metadata({window.state.photo_key(path): fields for path, fields in values.items()})
            window._show_photo_fields(force=True)
        else:
            window.state.restore_styles(values)
