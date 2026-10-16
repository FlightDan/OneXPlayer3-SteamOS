"""Single-window GTK 3 desktop frontend; privileged work stays in the service.

GTK is loaded only when launching the desktop UI. CLI operations and release
verification therefore do not depend on a graphical session or PyGObject.
"""
import os
import threading

from .display_language import detect_language


TEXT = {
    'zh': {
        'app': 'OXP3 修复与更新', 'overview': '概览', 'repairs': '修复与插件',
        'recovery': '恢复', 'settings': '设置', 'intro': '管理这台掌机的项目修复、插件与更新。',
        'check': '检查项目更新', 'refresh': '刷新系统状态', 'browse': '查看最新功能',
        'import': '导入本地维护包', 'choose': '选择签名维护包', 'open': '导入', 'cancel': '取消',
        'empty': '查看最新项目功能，或导入已下载的签名维护包。',
        'selection': '点选需要的功能；必需依赖会在预检时自动加入。',
        'review': '检查所选更改', 'download': '仅下载维护包', 'tool': '仅更新维护工具',
        'back': '返回选择', 'apply': '应用这些更改', 'confirm': '确认并继续',
        'confirm_apply': '应用上方已检查的更改？接下来会请求系统授权。',
        'confirm_rollback': '回退上次项目更新？恢复前会检查已有事务和文件。',
        'confirm_restore': '恢复所选组件的安装前原状？其他组件保持现状。',
        'confirm_recover': '恢复中断的操作？工具将依据保存的事务记录处理。',
        'working': '正在处理，请稍候…', 'mutating': '正在修改系统。请保持窗口开启，等待操作完成。',
        'wait_close': '系统操作尚未结束。请等待完成后再关闭窗口。',
        'error': '操作未完成', 'retry': '重试', 'done': '操作完成',
        'pick': '请先选择至少一个修复或插件。', 'blocked': '查看下方不兼容原因后，返回调整选择。',
        'recovery_intro': '先读取当前状态，再选择需要恢复的组件。',
        'rollback': '回退上次更新', 'restore': '恢复所选组件', 'recover': '恢复中断操作',
        'logs': '查看操作记录', 'load': '读取已安装组件',
        'daily': '每日检查项目更新', 'daily_detail': '发现更新时提示，由你决定是否下载和安装。',
        'channel': '项目更新通道', 'stable': '稳定版', 'beta': '稳定版与 Beta',
        'save': '保存设置', 'preferences': '读取当前设置', 'selected': '已选 {count} 项',
        'none': '尚未选择', 'offline': '本地维护包',
        'scope': '只管理本项目的修复与插件，不升级 SteamOS。',
        'review_intro': '检查依赖、保留组件与不兼容原因，再决定是否应用。',
        'download_hint': '下载所选组件及其依赖，保留供离线使用。下载不会安装任何组件。',
        'tool_hint': '只更新维护工具，保留现有修复和插件。',
        'no_items': '当前没有可选择的组件。可重试检查更新，或导入本地维护包。',
        'load_bundle': '选择此维护包中的组件',
        'ready': '就绪', 'review_count': '检查更改（{count}）',
        'show_installed': '显示已安装（{count}）',
        'hidden_installed': '已安装项目已隐藏。可打开上方开关重新选择。',
    },
    'en': {
        'app': 'OXP3 repairs & updates', 'overview': 'Overview', 'repairs': 'Repairs & plugins',
        'recovery': 'Recovery', 'settings': 'Settings', 'intro': 'Manage project repairs, plugins and updates for this handheld.',
        'check': 'Check project updates', 'refresh': 'Refresh system status', 'browse': 'Browse latest features',
        'import': 'Import local bundle', 'choose': 'Choose a signed maintenance bundle', 'open': 'Import', 'cancel': 'Cancel',
        'empty': 'Browse the latest project features, or import a signed maintenance bundle.',
        'selection': 'Tap the features you need. Preflight adds their required dependencies.',
        'review': 'Review selected changes', 'download': 'Download only', 'tool': 'Update tool only',
        'back': 'Back to selection', 'apply': 'Apply these changes', 'confirm': 'Confirm and continue',
        'confirm_apply': 'Apply the reviewed changes above? System authorization follows.',
        'confirm_rollback': 'Roll back the last project update? Saved transactions and files are checked first.',
        'confirm_restore': 'Restore the selected components to their original state? Other components stay as they are.',
        'confirm_recover': 'Recover the interrupted operation using its saved transaction record?',
        'working': 'Working. Please wait…', 'mutating': 'Changing the system. Keep this window open until the operation finishes.',
        'wait_close': 'A system operation is still running. Wait for completion before closing the window.',
        'error': 'Operation did not finish', 'retry': 'Retry', 'done': 'Operation complete',
        'pick': 'Select at least one repair or plugin first.', 'blocked': 'Read the compatibility reasons below, then go back to adjust your selection.',
        'recovery_intro': 'Read the current status, then select components to restore.',
        'rollback': 'Roll back last update', 'restore': 'Restore selected', 'recover': 'Recover interrupted task',
        'logs': 'View operation history', 'load': 'Read installed components',
        'daily': 'Check project updates daily', 'daily_detail': 'Updates are announced. You decide when to download and install.',
        'channel': 'Project update channel', 'stable': 'Stable', 'beta': 'Stable and Beta',
        'save': 'Save settings', 'preferences': 'Read current settings', 'selected': '{count} selected',
        'none': 'Nothing selected', 'offline': 'Local maintenance bundle',
        'scope': 'Manages this project’s repairs and plugins. Does not upgrade SteamOS.',
        'review_intro': 'Review dependencies, retained components and compatibility before applying.',
        'download_hint': 'Save selected components and dependencies for offline use. Downloading installs no components.',
        'tool_hint': 'Update the maintenance tool while keeping existing repairs and plugins.',
        'no_items': 'No components are available to select. Retry the update check or import a local bundle.',
        'load_bundle': 'Choose components in this bundle',
        'ready': 'Ready', 'review_count': 'Review ({count})',
        'show_installed': 'Show installed ({count})',
        'hidden_installed': 'Installed items are hidden. Use the switch above to select them again.',
    },
}

CSS = b'''
window.oxp3 { background: #20252d; color: #f2f4f7; }
.oxp3 decoration { margin: 0; padding: 0; border: 0; box-shadow: none; }
.oxp3 { font-family: "Noto Sans CJK SC", "Noto Sans", sans-serif; font-size: 18px; }
.oxp3 headerbar { background: #252c36; color: #f2f4f7; box-shadow: none; }
.oxp3 headerbar { min-height: 36px; padding: 4px 8px; }
.oxp3 headerbar button { min-width: 32px; min-height: 28px; padding: 4px; margin: 0; }
.oxp3 .navigation { background: #181e26; padding: 12px; }
.oxp3 .brand { font-size: 26px; font-weight: 700; color: #f2f4f7; }
.oxp3 .heading { font-size: 24px; font-weight: 700; color: #f2f4f7; }
.oxp3 .section-heading { font-size: 18px; font-weight: 600; }
.oxp3 .detail { font-size: 14px; }
.oxp3 .muted { color: #b9c5d5; }
.oxp3 button { min-height: 32px; padding: 8px 14px; border-radius: 9px;
  background: #303b49; color: #f2f4f7; border: 1px solid #4b5c70; box-shadow: none; }
.oxp3 button:hover { background: #3b4b60; }
.oxp3 button:active { background: #455c78; }
.oxp3 button:focus, .oxp3 checkbutton:focus { outline: 3px solid #90bfff; outline-offset: 2px; }
.oxp3 button:disabled { background: #292f39; color: #94a0b1; border-color: #394451; }
.oxp3 button.primary { background: #2876d4; color: #ffffff; border-color: #488fea; font-weight: 600; }
.oxp3 button.primary:hover { background: #3385e7; }
.oxp3 button.primary:disabled { background: #304963; color: #b5c1ce; border-color: #40576e; }
.oxp3 button.nav { border-color: transparent; background: transparent; padding: 8px; }
.oxp3 button.nav.active { background: #294565; border-color: #4c78a8; color: #ffffff; }
.oxp3 .notice { background: #28384a; border-radius: 9px; padding: 10px; color: #edf3fa; }
.oxp3 .warning { background: #493d27; color: #ffe5b0; }
.oxp3 .failure { background: #4b3037; color: #ffe2e7; }
.oxp3 .success { background: #243e35; color: #d0f3df; }
.oxp3 .component-row { padding: 6px 8px; border-bottom: 1px solid #3b4655; }
.oxp3 checkbutton { color: #f2f4f7; padding: 4px; }
.oxp3 checkbutton check { min-width: 28px; min-height: 28px; margin-right: 16px;
  border-radius: 5px; background: #202a36; border: 2px solid #8c9eb5; }
.oxp3 checkbutton check:checked { background: #2876d4; color: white; border-color: #80b9ff; }
.oxp3 checkbutton:disabled { color: #b7c1d0; }
.oxp3 .facts { padding: 12px 0; border-bottom: 1px solid #3b4655; }
.oxp3 .operation { background: #181e26; padding: 12px 24px; }
.oxp3 progressbar trough { min-height: 5px; border: 0; background: #394451; }
.oxp3 progressbar progress { min-height: 5px; border: 0; background: #65a8ff; }
.oxp3 scrolledwindow { border: 0; background: transparent; }
.oxp3 scrollbar slider { min-width: 10px; min-height: 48px; background: #74849a; border-radius: 6px; }
.oxp3 switch { min-height: 38px; min-width: 76px; }
.oxp3 switch:checked { background: #2876d4; }
'''


def _toolkit():
    import gi
    gi.require_version('Gtk', '3.0')
    from gi.repository import Gtk, Gdk, GLib, Pango
    return Gtk, Gdk, GLib, Pango


class TouchWindow:
    def __init__(self, service, *, language='zh', toolkit=None):
        self.Gtk, self.Gdk, self.GLib, self.Pango = toolkit or _toolkit()
        Gtk = self.Gtk
        self.service, self.language = service, language
        self.text = TEXT[language]
        self.route, self.views, self.selected = 'overview', {}, set()
        self.selections = {}
        self.busy = self.mutating = self.closed = False
        self.reviewing, self.initial_imported = False, False
        self.show_installed = False
        self.retry_task = self.confirm_task = None
        self.actions, self.nav_buttons, self.checks = [], {}, {}
        self.window = Gtk.Window(title=self.text['app'])
        self.window.get_style_context().add_class('oxp3')
        display = self.Gdk.Display.get_default()
        monitor = display.get_primary_monitor() or display.get_monitor(0)
        area = monitor.get_workarea()
        # Workarea is already in GTK logical pixels, including desktop scaling.
        # Reserve space for decorations/panels even on compositors that report
        # the complete monitor as the workarea.
        self.window.set_default_size(min(1120, area.width - 40), min(760, area.height - 112))
        self.window.set_size_request(760, 420)
        self.window.connect('delete-event', self._close)
        self.window.connect('destroy', lambda *_: Gtk.main_quit())
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(self.Gdk.Screen.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        header = Gtk.HeaderBar(title=self.text['app'])
        header.set_show_close_button(True)
        header.set_decoration_layout(':minimize,maximize,close')
        self.window.set_titlebar(header)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.window.add(outer)
        body = Gtk.Box(spacing=0)
        body.set_vexpand(True)
        outer.pack_start(body, True, True, 0)
        self.navigation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.navigation.set_size_request(200, -1)
        self.navigation.set_hexpand(False)
        self.navigation.get_style_context().add_class('navigation')
        body.pack_start(self.navigation, False, False, 0)
        self.navigation.pack_start(self._label('OXP3', 'brand'), False, False, 0)
        self.navigation.pack_start(self._label('SteamOS', 'muted'), False, False, 0)
        spacer = Gtk.Box()
        spacer.set_size_request(-1, 4)
        self.navigation.pack_start(spacer, False, False, 0)
        for route in ('overview', 'repairs', 'recovery', 'settings'):
            button = self._button(self.text[route], lambda _, route=route: self.navigate(route), css='nav')
            button.get_child().set_width_chars(1)
            button.get_child().set_max_width_chars(18)
            self.nav_buttons[route] = button
            self.navigation.pack_start(button, False, False, 0)
        scope = self._label(self.text['scope'], 'muted')
        scope.get_style_context().add_class('detail')
        scope.set_width_chars(1)
        scope.set_max_width_chars(18)
        scope.set_hexpand(False)
        self.navigation.pack_end(scope, False, False, 0)
        self.content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.content.set_margin_start(18)
        self.content.set_margin_end(18)
        self.content.set_margin_top(8)
        self.content.set_margin_bottom(8)
        self.content.set_hexpand(True)
        body.pack_start(self.content, True, True, 0)
        self.heading = self._label(self.text['overview'], 'heading')
        self.content.pack_start(self.heading, False, False, 0)
        self.toolbar = Gtk.Box(spacing=12)
        self.content.pack_start(self.toolbar, False, False, 0)
        self.scroll = Gtk.ScrolledWindow()
        self.scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroll.set_kinetic_scrolling(True)
        self.scroll.set_overlay_scrolling(False)
        self.scroll.set_hexpand(True)
        self.scroll.set_vexpand(True)
        self.page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.page.set_margin_end(8)
        self.scroll.add(self.page)
        self.content.pack_start(self.scroll, True, True, 0)
        self.footer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.content.pack_start(self.footer, False, False, 0)
        self.confirmation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self.confirmation.get_style_context().add_class('notice')
        self.confirmation.get_style_context().add_class('warning')
        self.confirmation.set_no_show_all(True)
        self.confirm_label = self._label('')
        self.confirmation.pack_start(self.confirm_label, False, False, 0)
        controls = Gtk.Box(spacing=12)
        controls.pack_start(self._button(self.text['cancel'], self._cancel_confirm), True, True, 0)
        controls.pack_start(self._button(self.text['confirm'], self._confirm, css='primary'), True, True, 0)
        self.confirmation.pack_start(controls, False, False, 0)
        self.content.pack_start(self.confirmation, False, False, 0)
        self.operation = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.operation.get_style_context().add_class('operation')
        line = Gtk.Box(spacing=12)
        self.spinner = Gtk.Spinner()
        self.spinner.set_size_request(28, 28)
        line.pack_start(self.spinner, False, False, 0)
        self.operation_text = self._label(self.text['ready'])
        line.pack_start(self.operation_text, True, True, 0)
        self.retry_button = self._button(self.text['retry'], self._retry)
        self.retry_button.set_no_show_all(True)
        line.pack_end(self.retry_button, False, False, 0)
        self.operation.pack_start(line, False, False, 0)
        self.progress = Gtk.ProgressBar()
        self.progress.set_no_show_all(True)
        self.operation.pack_start(self.progress, False, False, 0)
        outer.pack_end(self.operation, False, False, 0)
        self._render()
        self.window.show_all()
        self.service.on_progress = lambda message: self.GLib.idle_add(self._progress_message, message)
        self.GLib.idle_add(lambda: (self.perform('overview'), False)[1])

    def _label(self, text, css=None):
        label = self.Gtk.Label(label=str(text))
        label.set_xalign(0)
        label.set_line_wrap(True)
        label.set_line_wrap_mode(self.Pango.WrapMode.WORD_CHAR)
        label.set_max_width_chars(68)
        if css:
            label.get_style_context().add_class(css)
        return label

    def _button(self, text, callback, *, css=None):
        button = self.Gtk.Button()
        button.add(self._label(text))
        button.set_size_request(-1, 52)
        button.connect('clicked', callback)
        if css:
            button.get_style_context().add_class(css)
        return button

    def _clear(self, container):
        for child in container.get_children():
            container.remove(child)

    def _action(self, parent, text, callback, *, primary=False, enabled=True):
        button = self._button(text, callback, css='primary' if primary else None)
        button.set_sensitive(enabled and not self.busy)
        self.actions.append((button, enabled))
        horizontal = parent.get_orientation() == self.Gtk.Orientation.HORIZONTAL
        parent.pack_start(button, horizontal, True, 0)
        return button

    def navigate(self, route):
        if self.busy:
            return
        self._cancel_confirm()
        self.route = route
        self.reviewing = False
        self.selected = set(self.selections.get(route, {item['id'] for item in self.views.get(route, {}).get('items', []) if item.get('selected') and item.get('enabled')}))
        self._render()
        self.scroll.get_vadjustment().set_value(0)
        if route == 'repairs' and self.service.has_source and not self.initial_imported:
            self.initial_imported = True
            self.perform('import', path=str(self.service.source))
        elif route == 'settings' and route not in self.views:
            self.perform('preferences')

    def _render(self):
        Gtk = self.Gtk
        self.actions, self.checks = [], {}
        self._clear(self.toolbar)
        self._clear(self.page)
        self._clear(self.footer)
        for route, button in self.nav_buttons.items():
            context = button.get_style_context()
            context.add_class('active') if route == self.route else context.remove_class('active')
        default_message = {'overview': 'intro', 'repairs': 'empty', 'recovery': 'recovery_intro', 'settings': 'daily_detail'}
        view = self.views.get(self.route, {})
        self.heading.set_text(view.get('heading', self.text[self.route]))
        compact = self.route == 'repairs' and bool(view.get('items')) and not view.get('review')
        message = view.get('message', self.text[default_message[self.route]])
        if not compact or view.get('tone') == 'warning':
            message_label = self._label(message, 'muted')
            if view.get('tone') in ('warning', 'success'):
                message_label.get_style_context().add_class('notice')
                message_label.get_style_context().add_class(view['tone'])
            self.page.pack_start(message_label, False, False, 0)
        facts = [fact for fact in view.get('facts', []) if isinstance(fact, (tuple, list)) and len(fact) == 2]
        if compact and facts:
            self.page.pack_start(self._label('    '.join(str(label) + ': ' + str(value) for label, value in facts), 'muted'), False, False, 0)
            facts = []
        for fact in facts:
            if not isinstance(fact, (tuple, list)) or len(fact) != 2:
                continue
            box = Gtk.Box(spacing=12)
            box.get_style_context().add_class('facts')
            box.pack_start(self._label(fact[0], 'muted'), False, False, 0)
            box.pack_start(self._label(fact[1]), False, False, 0)
            self.page.pack_start(box, False, False, 0)
        if self.route == 'overview':
            self._action(self.toolbar, self.text['check'], lambda _: self.perform('discover', route='repairs'), primary=True)
            self._action(self.toolbar, self.text['refresh'], lambda _: self.perform('status'))
            self._action(self.footer, self.text['browse'], lambda _: self.navigate('repairs'))
        elif self.route == 'repairs':
            self._render_repairs(view)
        elif self.route == 'recovery':
            self._render_recovery(view)
        else:
            self._render_settings(view)
        self.content.show_all()
        self.confirmation.hide()
        self._sensitivity()

    def _render_items(self, items, *, selectable=True):
        for item in items:
            title = item.get('title', item.get('id', ''))
            detail = item.get('detail', '')
            content = self.Gtk.Box(orientation=self.Gtk.Orientation.VERTICAL, spacing=2)
            content.pack_start(self._label(title, 'section-heading'), False, False, 0)
            if detail:
                detail_label = self._label(detail, 'muted')
                detail_label.get_style_context().add_class('detail')
                content.pack_start(detail_label, False, False, 0)
            if selectable:
                row = self.Gtk.CheckButton()
                row.add(content)
                row.set_size_request(-1, 56)
                enabled = bool(item.get('enabled', False))
                row.set_sensitive(enabled and not self.busy)
                row.set_active(item['id'] in self.selected)
                row.connect('toggled', self._toggle, item['id'])
                self.checks[item['id']] = (row, enabled)
            else:
                row = content
            row.get_style_context().add_class('component-row')
            self.page.pack_start(row, False, False, 0)

    def _render_repairs(self, view):
        Gtk = self.Gtk
        if self.reviewing or view.get('review'):
            self.reviewing = True
            self.page.pack_start(self._label(self.text['review_intro'], 'muted'), False, False, 0)
            self._render_items(view.get('items', []), selectable=False)
            row = Gtk.Box(spacing=12)
            self.footer.pack_start(row, False, False, 0)
            self._action(row, self.text['back'], self._back_to_selection)
            self._action(row, self.text['apply'], lambda _: self.protect('apply'), primary=True, enabled=bool(view.get('can_apply')))
            if not view.get('can_apply'):
                self.footer.pack_start(self._label(self.text['blocked'], 'muted'), False, False, 0)
            return
        self._action(self.toolbar, self.text['check'], lambda _: self.perform('discover'), primary=True)
        self._action(self.toolbar, self.text['import'], self._choose_bundle)
        items = view.get('items', [])
        if items:
            installed_count = sum(item.get('installed') is True for item in items)
            filters = Gtk.Box(spacing=12)
            filters.pack_start(self._label(self.text['show_installed'].format(count=installed_count), 'muted'), True, True, 0)
            self.installed_switch = Gtk.Switch()
            self.installed_switch.set_valign(Gtk.Align.CENTER)
            self.installed_switch.set_active(self.show_installed)
            self.installed_switch.connect('notify::active', self._filter_installed)
            filters.pack_end(self.installed_switch, False, False, 0)
            self.page.pack_start(filters, False, False, 0)
            visible = [item for item in items if self.show_installed or item.get('installed') is not True]
            self._render_items(visible)
            if not visible:
                self.page.pack_start(self._label(self.text['hidden_installed'], 'muted'), False, False, 0)
        elif view:
            self.page.pack_start(self._label(self.text['no_items'], 'muted'), False, False, 0)
        if not items and self.service.has_source:
            self._action(self.page, self.text['load_bundle'], lambda _: self.perform('import', path=str(self.service.source)), primary=True)
        row = Gtk.Box(spacing=12)
        row.set_homogeneous(True)
        self.footer.pack_start(row, False, False, 0)
        self.review_button = self._action(row, self.text['review_count'].format(count=len(self.selected)), self._review_selection, primary=True, enabled=bool(items))
        self._action(row, self.text['download'], lambda _: self.perform('download', selected=sorted(self.selected)), enabled=bool(self.service.has_candidate))
        self._action(row, self.text['tool'], lambda _: self.perform('plan', selected=[], tool_only=True), enabled=bool(self.service.has_source or self.service.has_candidate))

    def _render_recovery(self, view):
        Gtk = self.Gtk
        self._action(self.toolbar, self.text['load'], lambda _: self.perform('status'), primary=True)
        self._action(self.toolbar, self.text['logs'], lambda _: self.perform('logs'))
        self._render_items(view.get('items', []))
        self._action(self.footer, self.text['restore'], self._restore_selected, primary=True, enabled=bool(view.get('items')))
        row = Gtk.Box(spacing=12)
        self.footer.pack_start(row, False, False, 0)
        self._action(row, self.text['rollback'], lambda _: self.protect('rollback'))
        self._action(row, self.text['recover'], lambda _: self.protect('recover'))

    def _render_settings(self, view):
        Gtk = self.Gtk
        self._action(self.toolbar, self.text['preferences'], lambda _: self.perform('preferences'))
        row = Gtk.Box(spacing=20)
        row.set_size_request(-1, 72)
        row.pack_start(self._label(self.text['daily']), True, True, 0)
        self.daily = Gtk.Switch()
        self.daily.set_valign(Gtk.Align.CENTER)
        self.daily.set_active(bool(view.get('enabled', True)))
        row.pack_end(self.daily, False, False, 0)
        self.page.pack_start(row, False, False, 0)
        self.page.pack_start(self._label(self.text['channel'], 'section-heading'), False, False, 0)
        self.stable = Gtk.RadioButton.new_with_label_from_widget(None, self.text['stable'])
        self.beta = Gtk.RadioButton.new_with_label_from_widget(self.stable, self.text['beta'])
        for widget in (self.stable, self.beta):
            widget.set_size_request(-1, 64)
            self.page.pack_start(widget, False, False, 0)
        (self.beta if view.get('channel') == 'beta' else self.stable).set_active(True)
        self._action(self.footer, self.text['save'], lambda _: self.perform('settings', enabled=self.daily.get_active(), channel='beta' if self.beta.get_active() else 'stable'), primary=True)

    def _toggle(self, button, name):
        self.selected.add(name) if button.get_active() else self.selected.discard(name)
        self.selections[self.route] = set(self.selected)
        self._selection_count()

    def _filter_installed(self, switch, *_):
        self.show_installed = switch.get_active()
        if not self.show_installed:
            hidden = {item['id'] for item in self.views.get('repairs', {}).get('items', []) if item.get('installed') is True}
            self.selected.difference_update(hidden)
            self.selections['repairs'] = set(self.selected)
        self._render()

    def _selection_count(self):
        if self.route == 'repairs' and hasattr(self, 'review_button'):
            self.review_button.get_child().set_text(self.text['review_count'].format(count=len(self.selected)))

    def _review_selection(self, *_):
        if not self.selected:
            self._notice(self.text['pick'], 'warning')
            return
        self.selection_view = self.views.get('repairs', {})
        self.perform('plan', selected=sorted(self.selected), tool_only=False)

    def _back_to_selection(self, *_):
        self.reviewing = False
        self.views['repairs'] = getattr(self, 'selection_view', {})
        self._render()

    def _restore_selected(self, *_):
        if not self.selected:
            self._notice(self.text['pick'], 'warning')
            return
        self.protect('restore', selected=sorted(self.selected))

    def _choose_bundle(self, *_):
        if self.busy:
            return
        Gtk = self.Gtk
        dialog = Gtk.FileChooserDialog(title=self.text['choose'], transient_for=self.window,
            action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(self.text['cancel'], Gtk.ResponseType.CANCEL, self.text['open'], Gtk.ResponseType.ACCEPT)
        dialog.set_default_size(900, 620)
        file_filter = Gtk.FileFilter()
        file_filter.set_name('OXP3 maintenance (*.tar.gz)')
        file_filter.add_pattern('*.tar.gz')
        dialog.add_filter(file_filter)
        response = dialog.run()
        path = dialog.get_filename() if response == Gtk.ResponseType.ACCEPT else None
        dialog.destroy()
        if path:
            self.perform('import', path=path)

    def protect(self, action, **params):
        if self.busy:
            return
        self.confirm_task = (action, params)
        self.confirm_label.set_text(self.text.get('confirm_' + action, self.text['confirm_apply']))
        self.footer.hide()
        # Gtk ignores show_all() while no-show-all is set. Keep the guard for
        # ordinary page renders, but explicitly reveal this confirmation tree.
        self.confirmation.set_no_show_all(False)
        self.confirmation.show_all()
        self.confirmation.set_no_show_all(True)
        self._sensitivity()

    def _cancel_confirm(self, *_):
        self.confirm_task = None
        self.confirmation.hide()
        self.footer.show()
        self._sensitivity()

    def _confirm(self, *_):
        task = self.confirm_task
        self._cancel_confirm()
        if task:
            self.perform(task[0], **task[1])

    def _notice(self, message, tone='normal'):
        context = self.operation.get_style_context()
        for css in ('warning', 'success', 'failure'):
            context.remove_class(css)
        if tone in ('warning', 'success', 'failure'):
            context.add_class(tone)
        self.operation_text.set_text(str(message))

    def _sensitivity(self):
        blocked = self.busy or self.confirm_task is not None
        for button in self.nav_buttons.values():
            button.set_sensitive(not blocked)
        for button, enabled in self.actions:
            button.set_sensitive(enabled and not blocked)
        for button, enabled in self.checks.values():
            button.set_sensitive(enabled and not blocked)
        if self.route == 'settings' and hasattr(self, 'daily'):
            for widget in (self.daily, self.stable, self.beta):
                widget.set_sensitive(not blocked)
        if self.route == 'repairs' and hasattr(self, 'installed_switch'):
            self.installed_switch.set_sensitive(not blocked)
        self.retry_button.set_sensitive(not blocked)

    def perform(self, action, *, route=None, **params):
        if self.busy or self.closed:
            return
        self.busy = True
        self.mutating = action in self.service.mutating_actions
        self.retry_task = (action, dict(params), route)
        if action == 'plan':
            self.selection_view = self.views.get('repairs', {})
        self.retry_button.hide()
        self.spinner.start()
        self.progress.show()
        self._notice(self.text['mutating'] if self.mutating else self.text['working'])
        self._sensitivity()
        self.GLib.timeout_add(120, self._pulse)
        target_route = route or self.route
        def worker():
            try:
                view, error = self.service.perform(action, **params), None
            except Exception as failure:
                view, error = None, str(failure)
            self.GLib.idle_add(self._completed, action, target_route, view, error)
        threading.Thread(target=worker, name='oxp3-desktop-task', daemon=not self.mutating).start()

    def _pulse(self):
        if not self.busy or self.closed:
            return False
        self.progress.pulse()
        return True

    def _progress_message(self, message):
        if self.busy and not self.closed:
            self._notice(message)
        return False

    def _completed(self, action, route, view, error):
        if self.closed:
            return False
        self.busy = self.mutating = False
        self.spinner.stop()
        self.progress.hide()
        if error:
            self._notice(self.text['error'] + '\n' + error, 'failure')
            self.retry_button.show()
            self._sensitivity()
            return False
        if action == 'settings' and self.retry_task:
            view = dict(view, **{key: value for key, value in self.retry_task[1].items() if key in ('enabled', 'channel')})
        self.retry_task = None
        self.route = route
        self.views[route] = view
        self.reviewing = bool(view.get('review'))
        if action in ('discover', 'import', 'status'):
            self.selected = {item['id'] for item in view.get('items', []) if item.get('selected') and item.get('enabled')}
            self.selections[route] = set(self.selected)
        self._render()
        self.scroll.get_vadjustment().set_value(0)
        self._notice(self.text['done'] if action in self.service.mutating_actions else self.text['ready'],
                     'success' if action in self.service.mutating_actions else 'normal')
        return False

    def _retry(self, *_):
        if not self.retry_task:
            return
        action, params, route = self.retry_task
        if action in self.service.mutating_actions:
            self.protect(action, **params)
        else:
            self.perform(action, route=route, **params)

    def _close(self, *_):
        if self.busy and self.mutating:
            self._notice(self.text['wait_close'], 'warning')
            return True
        self.closed = True
        return False


def run(args):
    language = detect_language()
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        raise RuntimeError('请以桌面用户打开维护工具。' if language == 'zh' else 'Open the maintenance tool as the desktop user, not root.')
    from .desktop_service import DesktopService
    window = TouchWindow(DesktopService(args, language=language), language=language)
    window.Gtk.main()
    return None
