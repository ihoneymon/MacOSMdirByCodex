"""MacOSMdir MOM — Textual application and command orchestration."""
from __future__ import annotations
import asyncio
from datetime import datetime
import os
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
from rich.text import Text
from textual import events, work
from textual.binding import Binding
from textual.app import App, ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static
from .archives import Archive, supported
from .display import fit, human, safe, ARCHIVE
from .filesystem import (PanelState, expanded, lexists, listing, read_text,
                         remove, system_info, transfer, validate_transfer)
from .screens import Choice, Prompt, TreeScreen, Viewer
from .widgets import FilePanel

HELP = """MacOSMdir MOM · Mdir III에서 영감을 받은 독립 구현

↑↓ 항목 이동 / ←→ 페이지 이동 / PgUp·PgDn 페이지 / Home·End 처음·끝
Enter 폴더·압축 열기 / 텍스트 보기 / 실행 확인
Backspace 상위 / Space·Insert 선택(*) 후 다음 항목
Tab 1단 ↔ 2단 / Ctrl+←·→ 활성 패널 / Ctrl+R 새로고침
/ 이름 접두사 점프 / Alt+문자 첫 글자 점프

C·F5 복사(압축에서는 추출) / M·F6 이동 / F2 이름변경
D·Delete·F8 영구 삭제(확인) / K·F7 폴더 생성
V·F3 VV 텍스트 뷰어 / F4 외부 편집기
A 정렬(이름·확장자·크기·시간, 오름·내림)
T·F9 MCD 디렉터리 트리 / Q·F10 종료
Esc 모달·압축 닫기, 파일 화면에서는 종료

VV: / 검색, n·N 다음·이전, ←→ 가로 이동, Esc·Q 닫기
ZIP/TAR: 읽기 전용 탐색, C·F5 추출. 링크·위험 경로는 제외.
선택 크기는 일반 파일 크기의 합입니다. 디렉터리는 재귀 집계하지 않습니다.
심볼릭 링크는 @ 표시. 복사·이동 시 링크 자체를 보존합니다.
삭제는 휴지통을 거치지 않습니다. 다중 작업은 부분 완료될 수 있습니다.
작업은 항목 사이에서 취소됩니다. 실행 중인 단일 파일 작업은 완료까지 기다립니다.

최소 60×18, 권장 120×32. macOS의 F키는 Fn 조합이 필요할 수 있습니다.
Alt 조합이 전달되지 않는 터미널에서는 /를 사용하세요.
표시 폭은 유니코드 셀 기준입니다. 터미널 글꼴의 이모지 폭 설정도 일치해야 합니다.
"""

CSS = """
Screen { background: #0000aa; color: #aaaaaa; }
#brand { height: 3; border: double #ffffff; color: #ffff55; background: #000088; padding: 0 1; }
#workspace { height: 1fr; }
FilePanel { width: 1fr; height: 1fr; border: double #55ffff; background: #0000aa; }
FilePanel:focus { border: double #ffffff; }
#summary { width: 27; height: 1fr; border: double #55ffff; padding: 0 1; color: #55ffff; }
#status { height: 3; border-top: double #55ffff; color: #ffffff; padding: 0 1; }
#keybar { height: 2; background: #00aaaa; color: #000000; }
#too-small { display: none; height: 1fr; content-align: center middle; color: #ffff55; }
ModalScreen { align: center middle; background: #000033 65%; }
.dialog { width: 76; max-width: 95%; height: auto; max-height: 90%; padding: 1 2; background: #0000aa; border: double #ffffff; }
.dialog Label { height: auto; margin-bottom: 1; color: #ffff55; }
.dialog-title { text-style: bold; }
.message-scroll { height: auto; max-height: 22; }
.dialog Static { height: auto; color: #ffffff; }
.dialog OptionList { height: auto; max-height: 10; background: #000055; color: #ffff55; }
Input { background: #000055; color: #ffffff; border: solid #55ffff; }
Input:focus { border: solid #ffff55; }
.buttons { height: auto; align-horizontal: right; margin-top: 1; }
Button { min-width: 10; margin-left: 1; background: #005555; color: #ffffff; }
Button:focus { background: #00aaaa; color: #000000; text-style: bold; }
#viewer { width: 96%; height: 94%; border: double #55ff55; background: #000033; }
#vv-title { height: 2; background: #005555; color: #ffffff; }
#vv-body { height: 1fr; color: #55ff55; }
#vv-status { height: 2; background: #005555; color: #ffff55; }
#tree-dialog { width: 90%; height: 90%; border: double #55ffff; padding: 1; background: #0000aa; }
#tree-dialog Label { height: auto; color: #ffff55; }
#tree-path { height: 1; }
DirectoryTree { height: 1fr; background: #0000aa; color: #55ffff; }
DirectoryTree > .tree--cursor { background: #00aaaa; color: #000000; }
"""


class MomApp(App):
    TITLE = "MacOSMdir MOM"
    CSS = CSS
    ENABLE_COMMAND_PALETTE = False
    BINDINGS = [Binding("ctrl+c", "quit", "종료", priority=True)]

    def __init__(self, path: Path):
        super().__init__()
        self._ui_ready = False
        self.panels = [PanelState(path), PanelState(path)]
        self.active = 0
        self.dual = False
        self.busy = False
        self.cancel_operation = False
        self.loading: set[int] = set()
        self.message = "MOM에 오신 것을 환영합니다 · F1 도움말"
        self.free: int | None = None
        self.ram = "N/A"
        self.last_directory = path

    @property
    def state(self):
        return self.panels[self.active]

    def compose(self) -> ComposeResult:
        yield Static(id="brand")
        yield Static("터미널을 60열 × 18행 이상으로 늘려주세요.\nCtrl+C / Q 종료", id="too-small")
        with Horizontal(id="workspace"):
            yield FilePanel(self.panels[0], 0)
            yield FilePanel(self.panels[1], 1)
            yield Static(id="summary")
        yield Static(id="status")
        yield Static(id="keybar")

    def on_mount(self):
        self._ui_ready = True
        self.set_layout()
        for state in self.panels:
            self.browse(state, state.path)
        self.query_one("#panel-0").focus()
        self.set_interval(5, self.update_system)
        self.update_system()

    def on_resize(self, event: events.Resize):
        self.call_after_refresh(self.set_layout)

    async def on_key(self, event: events.Key):
        if len(self.screen_stack) == 1 and (self.size.width < 60 or self.size.height < 18):
            if event.key in ("q", "Q", "escape", "f10"):
                self.action_quit()
                event.stop()

    def set_layout(self):
        if not self._ui_ready:
            return
        self.query_one("#panel-1").display = self.dual
        self.query_one("#summary").display = not self.dual and self.size.width >= 118
        small = self.size.width < 60 or self.size.height < 18
        self.query_one("#too-small").display = small
        self.query_one("#workspace").display = not small
        self.redraw()

    def redraw(self):
        if not self._ui_ready:
            return
        state = self.state
        self.last_directory = state.path
        mode = "DUAL" if self.dual else "SINGLE"
        self.query_one("#brand", Static).update(Text(fit(
            f" MOM  MacOSMdir  │  {mode}  │  {state.sort_by} {'↓' if state.reverse else '↑'}  │  {datetime.now():%H:%M}  · F1 도움말",
            max(1, self.size.width - 6))))
        for i, panel in enumerate(self.query(FilePanel)):
            panel.border_title = Text(f" {'▶' if i == self.active else ' '} {safe(panel.state.location)} ")
            panel.refresh()
        selected = [e for e in state.entries if e.key in state.marked]
        count, size = len(selected), sum(e.size for e in selected if not e.is_dir)
        free = human(self.free) if self.free is not None else "N/A"
        status = Text(fit(f"Path: {safe(state.location)}", max(1, self.size.width - 2)))
        status.append("\n" + fit(f"선택 {count}개 / {human(size)} · Free {free} · RAM {self.ram} │ {self.message}", max(1, self.size.width - 2)))
        self.query_one("#status", Static).update(status)
        entry = state.current
        summary = Text(" SYSTEM / DISK\n\n", style="bold #ffff55")
        summary.append(f"Free  {free}\nRAM   {self.ram}\n\n", style="#55ffff")
        summary.append(f"{len(state.entries) - bool(state.entries)}개 항목\n선택  {count}개\n크기  {human(size)}\n\n", style="#ffffff")
        if entry:
            summary.append(f"{safe(entry.name)}\n\n{'<DIR>' if entry.is_dir else human(entry.size)}\n{entry.date}\n", style="#55ffff")
        summary.append("\nTab  1단 ↔ 2단\n/    빠른 점프\nA    정렬\nSpace 선택\n\nMacOSMdir MOM\nDOS spirit. Modern shell.", style="#aaaaaa")
        self.query_one("#summary", Static).update(summary)
        if self.size.width >= 140:
            keys = "F1 도움말 │ F2 이름변경 │ F3 VV │ F4 편집 │ F5 복사 │ F6 이동 │ F7 폴더생성 │ F8 삭제 │ F9 MCD │ F10 종료"
        else:
            keys = "F1 도움말  F2 이름  F3 VV  F4 편집  F5 복사\nF6 이동    F7 폴더  F8 삭제 F9 MCD   F10 종료"
        self.query_one("#keybar", Static).update(Text(keys, style="bold #000000 on #00aaaa"))

    def say(self, message: str):
        self.message = safe(message)
        self.redraw()

    def error(self, error):
        self.push_screen(Choice("MOM · 오류", safe(error), [("ok", "확인")]))
        self.say(str(error))

    @work(group="directory", exit_on_error=False)
    async def load_directory(self, state, path, archive, prefix, reset, generation):
        try:
            entries = await asyncio.to_thread(archive.listing, prefix) if archive else await asyncio.to_thread(listing, path)
            if state.generation != generation:
                return
            if reset:
                state.entries, state.cursor, state.marked = [], 0, set()
            state.path, state.archive, state.prefix = path, archive, prefix
            state.install(entries)
            if archive and archive.blocked:
                self.say(f"안전하지 않은 압축 항목 {archive.blocked}개 제외")
        except Exception as error:
            if state.generation == generation:
                self.error(error)
        finally:
            if state.generation == generation:
                self.loading.discard(id(state))
            self.redraw()
            self.update_system()

    def browse(self, state, path, archive=None, prefix="", *, reset=False):
        state.generation += 1
        self.loading.add(id(state))
        self.load_directory(state, path, archive, prefix, reset, state.generation)

    def reload(self):
        for state in self.panels:
            self.browse(state, state.path, state.archive, state.prefix)

    @work(group="system", exclusive=True, exit_on_error=False)
    async def update_system(self):
        path = self.state.path
        self.free, self.ram = await asyncio.to_thread(system_info, path)
        self.redraw()

    async def handle_key(self, key: str, character: str | None = None):
        state = self.state
        command = (character or key).lower()
        if self.busy:
            if key == "escape":
                self.cancel_operation = True
                self.say("취소 요청 · 현재 항목 완료 후 중단합니다")
            else:
                self.say("파일 작업 중 · Esc로 항목 사이에서 취소")
            return
        if command == "q" or key == "f10":
            self.action_quit()
            return
        if key == "escape":
            if state.archive:
                self.browse(state, state.path, reset=True)
            else:
                self.action_quit()
            return
        if key == "tab":
            self.dual = not self.dual
            if not self.dual:
                self.active = 0
            self.set_layout()
            self.query_one(f"#panel-{self.active}").focus()
            return
        if key in ("ctrl+left", "ctrl+right") and self.dual:
            self.active = 0 if key == "ctrl+left" else 1
            self.query_one(f"#panel-{self.active}").focus()
            self.update_system()
            return
        if key == "f1":
            self.push_screen(Choice("MOM 도움말", HELP, [("ok", "닫기")]))
            return
        if id(state) in self.loading:
            self.say("디렉터리 읽는 중…")
            return
        panel = self.query_one(f"#panel-{self.active}", FilePanel)
        _, columns, rows = panel.geometry()
        if key in ("up", "down", "left", "right", "pageup", "pagedown", "home", "end"):
            moves = {"up": -1, "down": 1, "left": -rows, "right": rows,
                     "pageup": -rows * columns, "pagedown": rows * columns,
                     "home": -len(state.entries), "end": len(state.entries)}
            state.cursor = max(0, min(len(state.entries) - 1, state.cursor + moves[key]))
        elif key in ("space", "insert"):
            state.mark()
        elif key == "backspace":
            self.go_parent()
        elif key == "enter":
            await self.open_current()
        elif key.startswith("alt+") and len(key) == 5:
            state.jump(key[-1])
        elif key in ("slash", "/") or character == "/":
            self.push_screen(Prompt("빠른 점프 · 이름의 첫 글자", changed=lambda value: self.jump(state, value)))
        elif command in ("c", "m", "d", "k", "v", "a", "t") or key in ("delete", "f2", "f3", "f4", "f5", "f6", "f7", "f8", "f9"):
            action = {"f2": "rename", "f3": "v", "f4": "edit", "f5": "c", "f6": "m", "f7": "k", "f8": "d", "delete": "d", "f9": "t"}.get(key, command)
            await self.command(action)
        elif key == "ctrl+r":
            self.reload()
        self.redraw()

    def jump(self, state, value):
        state.jump(value)
        self.redraw()

    def go_parent(self):
        state = self.state
        if state.archive:
            if state.prefix:
                parent = str(PurePosixPath(state.prefix).parent)
                self.browse(state, state.path, state.archive, "" if parent == "." else parent, reset=True)
            else:
                self.browse(state, state.path, reset=True)
        else:
            self.browse(state, state.path.parent, reset=True)

    async def open_current(self):
        state, entry = self.state, self.state.current
        if not entry:
            return
        if entry.parent:
            self.go_parent()
        elif not state.archive and entry.suffix == ".app" and sys.platform == "darwin":
            self.confirm_execute(state.path / entry.name)
        elif entry.is_dir:
            if state.archive:
                self.browse(state, state.path, state.archive, entry.key, reset=True)
            else:
                self.browse(state, state.path / entry.name, reset=True)
        elif state.archive:
            self.open_viewer(state, entry)
        elif supported(state.path / entry.name):
            self.open_archive(state, state.path / entry.name)
        elif entry.suffix in ARCHIVE:
            self.error("이 압축 형식은 탐색을 지원하지 않습니다. ZIP/TAR 계열을 사용하세요.")
        elif entry.executable or entry.suffix in {".exe", ".com", ".bat", ".cmd", ".sh"}:
            self.confirm_execute(state.path / entry.name)
        else:
            self.open_viewer(state, entry)

    @work(group="preview", exclusive=True, exit_on_error=False)
    async def open_viewer(self, state, entry):
        try:
            result = await asyncio.to_thread(state.archive.read_text, entry.key) if state.archive else await asyncio.to_thread(read_text, state.path / entry.name)
            self.push_screen(Viewer(entry.name, *result))
        except Exception as error:
            self.error(error)

    @work(group="archive", exclusive=True, exit_on_error=False)
    async def open_archive(self, state, path):
        self.say("압축 목차 읽는 중…")
        generation = state.generation
        try:
            archive = await asyncio.to_thread(Archive, path)
            if state.generation == generation and state.path == path.parent:
                self.browse(state, path.parent, archive, reset=True)
        except Exception as error:
            self.error(error)

    async def command(self, action):
        state, entry = self.state, self.state.current
        if action == "v":
            if entry and not entry.is_dir:
                self.open_viewer(state, entry)
            return
        if action == "t":
            self.push_screen(TreeScreen(state.path), lambda path: self.browse(state, path, reset=True) if path else None)
            return
        if action == "a":
            self.push_screen(Choice("정렬", "디렉터리 우선 · .. 고정", [
                ("name", "이름"), ("extension", "확장자"), ("size", "크기"),
                ("time", "시간"), ("reverse", "역순")]), lambda value: self.set_sort(state, value))
            return
        if state.archive and action != "c":
            self.error("압축 내부는 읽기 전용입니다. C/F5로 추출할 수 있습니다.")
            return
        if action == "k":
            self.push_screen(Prompt("새 디렉터리 이름"), lambda value: self.mkdir(state, value))
        elif action == "edit":
            if entry and not entry.is_dir and not entry.parent:
                self.external_edit(state.path / entry.name)
        elif action == "rename":
            if entry and not entry.parent:
                self.push_screen(Prompt("이름 변경", entry.name), lambda value: self.rename(state, entry, value))
        elif action == "d":
            entries = state.selected()
            if entries:
                message = "휴지통을 거치지 않고 영구 삭제합니다.\n\n" + "\n".join(safe(e.name) for e in entries[:20])
                if len(entries) > 20:
                    message += f"\n… 외 {len(entries) - 20}개"
                self.push_screen(Choice(f"{len(entries)}개 영구 삭제", message, [("delete", "영구 삭제"), ("cancel", "취소")]),
                                 lambda answer: self.start_delete(state, entries) if answer == "delete" else None)
        elif action in ("c", "m"):
            entries = state.selected()
            if not entries:
                return
            other = self.panels[1 - self.active]
            default = str(other.path if self.dual else state.path)
            label = "압축 추출 대상 폴더" if state.archive else ("복사" if action == "c" else "이동") + " 대상 경로 (여러 항목은 기존 폴더)"
            self.push_screen(Prompt(label, default), lambda value: self.prepare_transfer(state, entries, value, action == "m"))

    def set_sort(self, state, value):
        if value == "reverse":
            state.reverse = not state.reverse
        elif value:
            state.sort_by = value
        state.install(state.entries)
        self.redraw()

    @work(group="file-operation", exclusive=True, exit_on_error=False)
    async def mkdir(self, state, value):
        if not value:
            return
        try:
            await asyncio.to_thread(expanded(value, state.path).mkdir)
            self.say("폴더 생성 완료")
            self.reload()
        except Exception as error:
            self.error(error)

    def rename(self, state, entry, value):
        if not value or value == entry.name:
            return
        if value in (".", "..") or "/" in value or "\\" in value or Path(value).name != value:
            self.error("새 이름은 경로가 아닌 단일 이름이어야 합니다.")
            return
        self.prepare_transfer(state, [entry], str(state.path / value), True, exact=True)

    def start_delete(self, state, entries):
        self.busy = True
        self.cancel_operation = False
        self.delete_entries(state.path, entries)

    @work(group="file-operation", exit_on_error=False)
    async def delete_entries(self, base, entries):
        errors, completed = [], 0
        try:
            for i, entry in enumerate(entries, 1):
                if self.cancel_operation:
                    break
                self.say(f"삭제 {i}/{len(entries)}: {entry.name} · Esc 취소")
                try:
                    await asyncio.to_thread(remove, base / entry.name)
                    completed += 1
                except Exception as error:
                    errors.append(f"{entry.name}: {error}")
        finally:
            self.finish_operation(completed, errors)

    def prepare_transfer(self, state, entries, value, move, exact=False):
        if value:
            self.busy = True
            self.cancel_operation = False
            self.perform_transfer(state.path, state.archive, entries, expanded(value, state.path), move, exact)

    @work(group="file-operation", exit_on_error=False)
    async def perform_transfer(self, base, archive, entries, destination, move, exact):
        errors, completed = [], 0
        try:
            is_directory = await asyncio.to_thread(destination.is_dir)
            if archive and not is_directory:
                raise ValueError("추출 대상은 기존 디렉터리여야 합니다.")
            if len(entries) > 1 and not is_directory:
                raise ValueError("여러 항목의 대상은 기존 디렉터리여야 합니다.")
            for i, entry in enumerate(entries, 1):
                if self.cancel_operation:
                    break
                self.say(f"{'추출' if archive else '이동' if move else '복사'} {i}/{len(entries)}: {entry.name} · Esc 취소")
                target = destination / entry.name if is_directory and not exact else destination
                try:
                    if not archive:
                        await asyncio.to_thread(validate_transfer, base / entry.name, target)
                    overwrite = False
                    if await asyncio.to_thread(lexists, target):
                        warning = "\n기존 파일을 덮어쓰고 폴더의 다른 파일은 유지합니다." if archive else "\n폴더 덮어쓰기는 기존 폴더 전체를 교체합니다."
                        answer = await self.push_screen_wait(Choice("대상이 이미 있습니다", safe(target) + warning,
                                                                  [("overwrite", "덮어쓰기"), ("skip", "건너뛰기"), ("cancel", "취소")]))
                        if answer == "skip":
                            continue
                        if answer != "overwrite":
                            self.cancel_operation = True
                            break
                        overwrite = True
                    if archive:
                        await asyncio.to_thread(archive.extract, [entry.key], destination, overwrite=overwrite,
                                                progress=lambda msg: self.call_from_thread(self.say, msg))
                    else:
                        await asyncio.to_thread(transfer, base / entry.name, target, move=move, overwrite=overwrite)
                    completed += 1
                except Exception as error:
                    errors.append(f"{entry.name}: {error}")
        except Exception as error:
            errors.append(str(error))
        finally:
            self.finish_operation(completed, errors)

    def finish_operation(self, completed, errors):
        self.busy = False
        self.say(f"{'취소됨 · ' if self.cancel_operation else ''}{completed}개 완료 / {len(errors)}개 실패")
        self.reload()
        if errors:
            self.push_screen(Choice("작업 결과 · 부분 완료 가능", "\n".join(safe(e) for e in errors[:30]), [("ok", "확인")]))

    def confirm_execute(self, path):
        self.push_screen(Choice("프로그램 실행", f"{safe(path)}\n이 프로그램을 실행하시겠습니까?", [("run", "실행"), ("cancel", "취소")]),
                         lambda answer: self.external_run(path) if answer == "run" else None)

    def external_run(self, path):
        if sys.platform == "darwin" and path.suffix.lower() == ".app":
            args = ["open", str(path)]
        elif os.name == "nt" and path.suffix.lower() in {".cmd", ".bat"}:
            self.error("Windows 배치 파일은 터미널에서 직접 실행하세요. MOM에서는 자동 실행하지 않습니다.")
            return
        elif os.name != "nt" and path.suffix.lower() in {".exe", ".com"}:
            self.error("이 실행 파일은 현재 OS에서 직접 실행할 수 없습니다.")
            return
        elif path.suffix.lower() == ".sh" and not os.access(path, os.X_OK):
            args = ["/bin/sh", str(path)]
        else:
            args = [str(path)]
        self.run_external(args, path.parent)

    def external_edit(self, path):
        try:
            editor = os.environ.get("VISUAL") or os.environ.get("EDITOR")
            if editor:
                args = shlex.split(editor, posix=os.name != "nt")
                if os.name == "nt":
                    args = [part.strip('"') for part in args]
                if not args:
                    raise ValueError("VISUAL/EDITOR가 비어 있습니다.")
            else:
                args = ["notepad" if os.name == "nt" else "vi"]
            self.run_external([*args, str(path)], path.parent)
        except ValueError as error:
            self.error(error)

    def run_external(self, args, cwd):
        try:
            with self.suspend():
                result = subprocess.run(args, cwd=cwd, shell=False, check=False)
                if sys.stdin.isatty():
                    input(f"\n[MOM] 종료 코드 {result.returncode} · Enter로 돌아가기 ")
            self.say(f"외부 프로그램 종료: {result.returncode}")
            self.reload()
        except Exception as error:
            self.error(error)

    def action_quit(self):
        if self.busy:
            self.cancel_operation = True
            self.say("작업 완료 후 Q로 종료하세요")
            return
        self.last_directory = self.state.path
        self.exit()
