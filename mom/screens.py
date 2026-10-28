"""Keyboard-focused DOS dialogs, VV viewer, and lazy MCD tree."""
from __future__ import annotations
from pathlib import Path
import re
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, DirectoryTree, Input, Label, Static, OptionList
from textual.widgets.option_list import Option
from textual.widget import Widget
from .display import fit, safe


class Prompt(ModalScreen[str | None]):
    def __init__(self, title: str, value: str = "", *, changed=None):
        super().__init__()
        self.title_text, self.value, self.changed = title, value, changed

    def compose(self) -> ComposeResult:
        with Vertical(classes="dialog"):
            yield Label(self.title_text, markup=False)
            yield Input(value=self.value, id="answer")
            with Horizontal(classes="buttons"):
                yield Button("확인", variant="primary", id="ok")
                yield Button("취소", id="cancel")

    def on_mount(self):
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed):
        if self.changed:
            self.changed(event.value)

    def on_input_submitted(self):
        self.dismiss(self.query_one(Input).value)

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(self.query_one(Input).value if event.button.id == "ok" else None)

    def on_key(self, event: events.Key):
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class Choice(ModalScreen[str | None]):
    def __init__(self, title: str, message: str, options=None):
        super().__init__()
        self.title_text, self.message = title, message
        self.options = options or [("ok", "확인"), ("cancel", "취소")]

    def compose(self):
        with Vertical(classes="dialog"):
            yield Label(self.title_text, classes="dialog-title", markup=False)
            with VerticalScroll(classes="message-scroll"):
                yield Static(self.message, markup=False)
            if len(self.options) > 3:
                yield OptionList(*(Option(label, id=key) for key, label in self.options))
            else:
                with Horizontal(classes="buttons"):
                    for key, label in self.options:
                        yield Button(label, id=key, variant="error" if key == "delete" else "default")

    def on_mount(self):
        if len(self.options) > 3:
            self.query_one(OptionList).focus()
        else:
            self.query(Button).last().focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected):
        self.dismiss(event.option.id)

    def on_button_pressed(self, event: Button.Pressed):
        self.dismiss(event.button.id)

    def on_key(self, event: events.Key):
        if event.key == "escape":
            event.stop()
            self.dismiss(None)


class ViewerBody(Widget):
    can_focus = True

    def __init__(self, text: str):
        super().__init__(id="vv-body")
        self.lines = text.splitlines() or [""]
        self.top = 0
        self.horizontal = 0
        self.query_text = ""
        self.matches: list[int] = []
        self.match_index = -1

    def render(self):
        width, height = self.size
        number_width = len(str(len(self.lines)))
        result = Text()
        pattern = re.compile(re.escape(self.query_text), re.IGNORECASE) if self.query_text else None
        for row in range(height):
            index = self.top + row
            if row:
                result.append("\n")
            if index >= len(self.lines):
                result.append(fit("~", width), style="#008855")
                continue
            result.append(f"{index + 1:>{number_width}} │ ", style="#55ffff")
            line = safe(self.lines[index].expandtabs(4))[self.horizontal:]
            visible = fit(line, max(0, width - number_width - 3))
            styled = Text(visible, style="#55ff55")
            if pattern:
                for match in pattern.finditer(visible):
                    styled.stylize("#0000aa on #ffff55", match.start(), match.end())
            result.append_text(styled)
        return result

    def scroll(self, amount: int):
        self.top = max(0, min(self.top + amount, max(0, len(self.lines) - self.size.height)))
        self.refresh()

    def search(self, query: str):
        self.query_text = query
        self.matches = [i for i, line in enumerate(self.lines) if query.casefold() in line.casefold()] if query else []
        self.match_index = -1
        self.next_match(1)

    def next_match(self, step: int):
        if self.matches:
            self.match_index = (self.match_index + step) % len(self.matches)
            self.top = min(self.matches[self.match_index], max(0, len(self.lines) - self.size.height))
        self.refresh()


class Viewer(ModalScreen):
    def __init__(self, filename: str, text: str, encoding: str, truncated: bool):
        super().__init__()
        self.filename, self.text, self.encoding, self.truncated = filename, text, encoding, truncated

    def compose(self):
        with Vertical(id="viewer"):
            yield Static(Text(f" VV · 보라  {safe(self.filename)}  [{self.encoding}]"), id="vv-title")
            yield ViewerBody(self.text)
            yield Static(id="vv-status")

    def on_mount(self):
        self.query_one(ViewerBody).focus()
        self.update_status()

    def on_resize(self):
        self.call_after_refresh(self.update_status)

    def update_status(self):
        body = self.query_one(ViewerBody)
        percentage = min(100, (body.top + max(1, body.size.height)) * 100 // len(body.lines))
        warning = " · 앞부분 8 MiB만 표시" if self.truncated else ""
        search = f" · 검색 {len(body.matches)}줄" if body.query_text else ""
        self.query_one("#vv-status", Static).update(Text(
            f" {percentage:3}% │ {body.top + 1:,}/{len(body.lines):,}줄 │ / 검색  n/N 다음/이전  Esc 닫기{warning}{search}"))

    def searched(self, query):
        if query is not None:
            self.query_one(ViewerBody).search(query)
        self.update_status()

    def on_key(self, event: events.Key):
        body = self.query_one(ViewerBody)
        key = event.key
        if key in ("escape", "q", "Q"):
            self.dismiss()
        elif key in ("slash", "/"):
            self.app.push_screen(Prompt("VV 검색 · /", body.query_text), self.searched)
        elif key == "n":
            body.next_match(1)
        elif key == "N":
            body.next_match(-1)
        elif key in ("up", "down", "pageup", "pagedown"):
            body.scroll({"up": -1, "down": 1, "pageup": -max(1, body.size.height - 1),
                         "pagedown": max(1, body.size.height - 1)}[key])
        elif key == "home":
            body.top = 0
        elif key == "end":
            body.top = max(0, len(body.lines) - body.size.height)
        elif key == "right":
            body.horizontal += 8
        elif key == "left":
            body.horizontal = max(0, body.horizontal - 8)
        else:
            return
        event.stop()
        event.prevent_default()
        body.refresh()
        self.update_status()


class SafeDirectoryTree(DirectoryTree):
    def filter_paths(self, paths):
        result = []
        for path in paths:
            try:
                if path.is_dir() and not path.is_symlink():
                    result.append(path)
            except OSError:
                continue
        return result

    def render_label(self, node, base_style, style):
        label = super().render_label(node, base_style, style)
        label.plain = safe(label.plain)
        return label


class TreeScreen(ModalScreen[Path | None]):
    def __init__(self, path: Path):
        super().__init__()
        self.path = path

    def compose(self):
        with Vertical(id="tree-dialog"):
            yield Label(" MCD · 디렉터리 트리  ←/→ 접기/펼치기 · Enter 이동 · Esc 닫기")
            yield Static(Text(safe(self.path)), id="tree-path")
            yield SafeDirectoryTree(self.path, id="directory-tree")
            with Horizontal(classes="buttons"):
                yield Button("상위 경로", id="parent")
                yield Button("선택 이동", id="choose")
                yield Button("취소", id="cancel")

    def on_mount(self):
        self.query_one(DirectoryTree).focus()

    async def choose(self, path):
        import asyncio
        try:
            def check():
                with __import__('os').scandir(path) as entries:
                    next(entries, None)
            await asyncio.to_thread(check)
        except OSError as error:
            self.app.push_screen(Choice("접근할 수 없습니다", str(error), [("ok", "확인")]))
            return
        self.dismiss(path)

    async def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected):
        event.stop()
        await self.choose(event.path)

    async def on_button_pressed(self, event: Button.Pressed):
        tree = self.query_one(DirectoryTree)
        if event.button.id == "cancel":
            self.dismiss(None)
        elif event.button.id == "parent":
            self.path = self.path.parent
            tree.path = self.path
            self.query_one("#tree-path", Static).update(Text(safe(self.path)))
            tree.focus()
        elif tree.cursor_node and tree.cursor_node.data:
            await self.choose(tree.cursor_node.data.path)

    def on_key(self, event: events.Key):
        if event.key == "escape":
            event.stop()
            self.dismiss(None)
