"""工作区菜单、快捷键和主工具栏"""

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QAction, QActionGroup, QKeySequence
from PySide6.QtWidgets import QMenu, QSizePolicy, QStyle, QToolBar, QToolButton, QWidget

from .i18n import bind, set_language
from .theme import set_theme, theme, theme_notifier


class WorkspaceActions:
    def _action(self, text, callback, shortcut=None, icon=None, checkable=False):
        """统一菜单和工具栏使用的动作及快捷键"""
        action = QAction(text, self)
        action.setCheckable(checkable)
        if icon is not None:
            action.setIcon(self.style().standardIcon(icon))
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.triggered.connect(callback)
        return action

    def _build_actions(self):
        icons = QStyle.StandardPixmap
        self.add_action = self._action("添加照片", self._pick_photos, "Ctrl+O", icons.SP_FileIcon)
        self.directory_action = self._action("输入目录", self._pick_folder, "Ctrl+Shift+O", icons.SP_DirOpenIcon)
        self.output_dir_action = self._action("输出目录", self._choose_output, "Ctrl+Shift+D", icons.SP_DirIcon)
        self.refresh_action = self._action("刷新目录", self._refresh_directories, "F5", icons.SP_BrowserReload)
        self.export_action = self._action("导出照片", self._export, "Ctrl+R", icons.SP_ArrowDown)
        self.cancel_action = self._action("取消导出", self._cancel_export, "Escape", icons.SP_MediaStop)
        self.save_action = self._action("保存设置", self._save_config, "Ctrl+S", icons.SP_DialogSaveButton)
        self.reset_action = self._action("重置设置", self._reset_config, icon=icons.SP_BrowserReload)
        self.new_template_action = self._action("新建空白预设", self._new_template, "Ctrl+N", icons.SP_FileIcon)
        self.copy_template_action = self._action("另存为预设", self._copy_template, "Ctrl+Shift+S", icons.SP_DialogSaveButton)
        self.edit_template_action = self._action("高级源码…", self._edit_template, "Ctrl+E", icons.SP_FileDialogDetailedView)
        self.footer_action = self._action("组合底部信息…", self._show_style_tab, "Ctrl+Shift+E", icons.SP_FileDialogContentsView)
        self.metadata_action = self._action("编辑照片信息…", self._show_metadata_tab, "Ctrl+I", icons.SP_FileDialogInfoView)
        self.metadata_batch_action = self._action("编辑选中照片信息…", self._show_metadata_tab, icon=icons.SP_FileDialogListView)
        self.original_action = self._action("对照原图", self._view_changed, "Ctrl+Tab", checkable=True)
        self.lock_action = self._action("锁定设置", self._set_locked, checkable=True)
        self.metadata_action.setToolTip("编辑当前照片的水印信息，原片保持不变（Ctrl+I）")
        self.footer_action.setToolTip("自由组合水印字段、顺序和分隔符（Ctrl+Shift+E）")
        self.edit_template_action.setToolTip("编辑完整 JSON / Jinja 模板（Ctrl+E）")
        file_menu = QMenu("文件(&F)", self)
        for action in (self.add_action, self.directory_action, self.output_dir_action, self.refresh_action):
            file_menu.addAction(action)
        file_menu.addSeparator()
        file_menu.addAction(self.metadata_action)
        file_menu.addSeparator()
        file_menu.addAction(self.save_action)
        file_menu.addAction(self.reset_action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("打开输出目录", self._open_output))
        file_menu.addAction(self.export_action)
        file_menu.addAction(self.cancel_action)
        file_menu.addSeparator()
        file_menu.addAction(self._action("退出", self.close, "Alt+F4"))
        template_menu = QMenu("模板(&T)", self)
        for action in (self.new_template_action, self.copy_template_action, self.footer_action, self.edit_template_action):
            template_menu.addAction(action)
        view_menu = QMenu("查看(&V)", self)
        view_menu.addAction(self.original_action)
        self.filmstrip_action = self._action('显示胶片带', self._toggle_filmstrip, checkable=True)
        view_menu.addAction(self.filmstrip_action)
        view_menu.addAction(self.lock_action)
        view_menu.addAction(self._action("错误详情…", self._show_error_details))
        self.language_menu = view_menu.addMenu("语言")
        self.language_actions = {}
        group = QActionGroup(self)
        for code, title in (("zh_CN", "中文"), ("en_US", "英文")):
            action = self._action(title, lambda checked=False, value=code: set_language(value), checkable=True)
            group.addAction(action)
            self.language_menu.addAction(action)
            self.language_actions[code] = action
        self.theme_menu = view_menu.addMenu("主题")
        self.theme_actions = {}
        themes = QActionGroup(self)
        for code, title in (("dark", "深色"), ("light", "浅色")):
            action = self._action(title, lambda checked=False, value=code: set_theme(value), checkable=True)
            themes.addAction(action)
            action.setChecked(theme() == code)
            self.theme_menu.addAction(action)
            self.theme_actions[code] = action
        self.theme_menu.addSeparator()
        self.appearance_action = self._action('外观与主题设置…', self._show_appearance_settings)
        self.theme_menu.addAction(self.appearance_action)
        theme_notifier.theme_changed.connect(self._theme_changed)
        view_menu.addSeparator()
        self.about_action = self._action("关于", self._show_about)
        view_menu.addAction(self.about_action)
        self.toolbar = QToolBar("常用操作")
        self.toolbar.setObjectName("workspaceToolbar")
        self.toolbar.setMovable(False)
        self.toolbar.setMaximumHeight(32)
        self.toolbar.setStyleSheet('QToolBar { padding: 0px 6px; spacing: 4px; } '
                                   'QToolButton { min-height: 18px; padding: 0px 6px; }')
        self.toolbar.setIconSize(QSize(16, 16))
        for menu in (file_menu, template_menu, view_menu):
            self._menu_button(menu)
        self.toolbar.addSeparator()
        self.toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.undo_action = self._action("撤销", self.history.stack.undo, "Ctrl+Z", icons.SP_ArrowBack)
        self.redo_action = self._action("重做", self.history.stack.redo, "Ctrl+Y", icons.SP_ArrowForward)
        self.history.stack.canUndoChanged.connect(self._update_actions)
        self.history.stack.canRedoChanged.connect(self._update_actions)
        for action in (self.add_action, self.directory_action, self.output_dir_action):
            self.toolbar.addAction(action)
        self.toolbar.addSeparator()
        for action in (self.undo_action, self.redo_action):
            self.toolbar.addAction(action)
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.toolbar.addWidget(spacer)
        self.addToolBar(self.toolbar)

    def _menu_button(self, menu):
        button = bind(QToolButton(), menu.title())
        button.setMenu(menu)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.toolbar.addWidget(button)

    def _theme_changed(self, code):
        self.theme_actions[code].setChecked(True)

    def _toggle_theme(self):
        set_theme('light' if theme() == 'dark' else 'dark')

    def _show_appearance_settings(self):
        from .appearance import AppearanceDialog
        dialog = getattr(self, '_appearance_dialog', None)
        if dialog is None:
            dialog = AppearanceDialog(self)
            dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
            dialog.finished.connect(lambda _: setattr(self, '_appearance_dialog', None))
            self._appearance_dialog = dialog
        dialog.open()
        dialog.raise_()
        dialog.activateWindow()
