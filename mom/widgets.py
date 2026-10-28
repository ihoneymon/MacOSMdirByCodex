"""A single-column VGA file grid, rendered only for the visible page."""
from __future__ import annotations
from rich.text import Text
from textual import events
from textual.widget import Widget
from .display import color, fit, human, safe
from .filesystem import PanelState


def format_fields(name, extension, kind, date, width, marker=" "):
    if width >= 40:
        return marker + fit(name, width - 24) + " " + fit(extension, 5) + " " + fit(kind, 7, right=True) + " " + fit(date, 8)
    if width >= 31:
        return marker + fit(name, width - 19) + " " + fit(kind, 8, right=True) + " " + fit(date, 8)
    if width >= 19:
        return marker + fit(name, width - 10) + " " + fit(kind, 8, right=True)
    return marker + fit(name, width - 1)


class FilePanel(Widget):
    can_focus = True

    def __init__(self, state: PanelState, index: int):
        super().__init__(id=f"panel-{index}")
        self.state = state
        self.index = index
        self.columns = 1
        self.rows = 1
        self.page_start = 0

    def geometry(self):
        width = max(1, self.content_size.width)
        columns = 1
        available = max(1, self.content_size.height - 2)
        rows = min(available, max(1, (len(self.state.entries) + columns - 1) // columns))
        return width, columns, rows

    def render(self):
        width, columns, rows = self.geometry()
        self.columns, self.rows = columns, rows
        page_size = rows * columns
        self.page_start = self.state.cursor // page_size * page_size
        widths = [(width - columns + 1) // columns] * columns
        for i in range((width - columns + 1) % columns):
            widths[i] += 1
        result = Text(no_wrap=True, overflow="crop")
        for column, cell_width in enumerate(widths):
            if column:
                result.append("║", style="#55ffff")
            result.append(format_fields("이름" if cell_width >= 40 else "파일명 / 확장자", "확장자", "크기", "날짜", cell_width), style="#0000aa on #55ffff")
        result.append("\n")
        result.append("╬".join("═" * w for w in widths), style="#55ffff")
        for row in range(max(1, self.content_size.height - 2)):
            result.append("\n")
            for column, cell_width in enumerate(widths):
                if column:
                    result.append("║", style="#55ffff")
                index = self.page_start + column * rows + row
                if row >= rows or index >= len(self.state.entries):
                    result.append(" " * cell_width)
                    continue
                entry = self.state.entries[index]
                marked = entry.key in self.state.marked
                cursor = index == self.state.cursor
                style = "bold #ffff55 on #555500" if marked else color(entry)
                if cursor:
                    style = "bold #0000aa on #55ffff" if self.has_focus else "bold #ffffff on #0055aa"
                marker = "*" if marked else " "
                kind = "<DIR>" if entry.is_dir else human(entry.size)
                name = entry.name + ("@" if entry.link else "")
                extension = entry.suffix[1:] if not entry.is_dir else ""
                if cell_width >= 40 and extension:
                    name = entry.name[:-len(entry.suffix)] + ("@" if entry.link else "")
                line = format_fields(name, extension, kind, entry.date, cell_width, marker)
                result.append(fit(line, cell_width), style=style)
        return result

    def on_focus(self):
        self.app.active = self.index
        self.app.redraw()

    async def on_key(self, event: events.Key):
        event.stop()
        event.prevent_default()
        await self.app.handle_key(event.key, event.character)

    def on_click(self, event: events.Click):
        self.focus()
        width, columns, rows = self.geometry()
        x = event.x - 1
        y = event.y - 3
        if y < 0 or y >= rows:
            return
        cell_width = max(1, (width + 1) // columns)
        index = self.page_start + max(0, min(columns - 1, x // (cell_width + 1))) * rows + y
        if index < len(self.state.entries):
            self.state.cursor = index
            self.app.redraw()
            if event.chain >= 2:
                self.app.run_worker(self.app.open_current())

    def on_mouse_scroll_down(self, event):
        self.state.cursor = min(len(self.state.entries) - 1, self.state.cursor + 3)
        self.app.redraw()
        event.stop()

    def on_mouse_scroll_up(self, event):
        self.state.cursor = max(0, self.state.cursor - 3)
        self.app.redraw()
        event.stop()
