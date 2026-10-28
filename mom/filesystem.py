"""Filesystem state and operations, without UI dependencies."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
import shutil
import stat
import tempfile
from typing import Callable


@dataclass(frozen=True)
class Entry:
    name: str
    key: str
    is_dir: bool = False
    size: int = 0
    mtime: float = 0
    executable: bool = False
    link: bool = False
    parent: bool = False

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix.lower()

    @property
    def date(self) -> str:
        try:
            return datetime.fromtimestamp(self.mtime).strftime("%y-%m-%d") if self.mtime else "        "
        except (ValueError, OSError, OverflowError):
            return "????????"


def listing(path: Path) -> list[Entry]:
    result = [Entry("..", "..", True, parent=True)]
    with os.scandir(path) as items:
        for item in items:
            try:
                info = item.stat(follow_symlinks=False)
                directory = item.is_dir()
                result.append(Entry(item.name, item.name, directory,
                                    0 if directory else info.st_size, info.st_mtime,
                                    bool(info.st_mode & 0o111) and not directory,
                                    item.is_symlink()))
            except OSError:
                result.append(Entry(item.name, item.name, link=item.is_symlink()))
    return result


@dataclass
class PanelState:
    path: Path
    entries: list[Entry] = field(default_factory=list)
    cursor: int = 0
    marked: set[str] = field(default_factory=set)
    sort_by: str = "name"
    reverse: bool = False
    archive: object | None = None
    prefix: str = ""
    generation: int = 0

    @property
    def current(self) -> Entry | None:
        return self.entries[self.cursor] if self.entries else None

    @property
    def location(self) -> str:
        return f"{self.archive.path}!/{self.prefix}" if self.archive else str(self.path)

    def install(self, entries: list[Entry]) -> None:
        current = self.current.key if self.current else None
        parents = [e for e in entries if e.parent]
        directories = [e for e in entries if e.is_dir and not e.parent]
        files = [e for e in entries if not e.is_dir]
        def key(e):
            value = {"name": e.name.casefold(), "extension": e.suffix,
                     "size": e.size, "time": e.mtime}[self.sort_by]
            return value, e.name.casefold()
        self.entries = parents + sorted(directories, key=key, reverse=self.reverse) + sorted(files, key=key, reverse=self.reverse)
        self.marked.intersection_update(e.key for e in entries if not e.parent)
        self.cursor = next((i for i, e in enumerate(self.entries) if e.key == current),
                           min(self.cursor, max(0, len(self.entries) - 1)))

    def selected(self) -> list[Entry]:
        return [e for e in self.entries if not e.parent and
                (e.key in self.marked if self.marked else e == self.current)]

    def mark(self) -> None:
        if self.current and not self.current.parent:
            key = self.current.key
            self.marked.symmetric_difference_update({key})
            self.cursor = min(len(self.entries) - 1, self.cursor + 1)

    def jump(self, prefix: str) -> None:
        prefix = prefix.casefold()
        if prefix:
            start = (self.cursor + 1) % max(1, len(self.entries))
            for offset in range(len(self.entries)):
                i = (start + offset) % len(self.entries)
                if self.entries[i].name.casefold().startswith(prefix):
                    self.cursor = i
                    return


def expanded(value: str, base: Path) -> Path:
    path = Path(value).expanduser()
    return Path(os.path.abspath(path if path.is_absolute() else base / path))


def lexists(path: Path) -> bool:
    return os.path.lexists(path)


def remove(path: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        path.unlink()
    else:
        shutil.rmtree(path)


def validate_transfer(source: Path, target: Path) -> None:
    src, dst = source.resolve(), target.resolve()
    if src == dst:
        raise ValueError("원본과 대상이 같습니다.")
    if source.is_dir() and not source.is_symlink() and dst.is_relative_to(src):
        raise ValueError("디렉터리 자신의 하위로 복사·이동할 수 없습니다.")
    if src.is_relative_to(dst):
        raise ValueError("원본의 상위 디렉터리를 덮어쓸 수 없습니다.")
    if not target.parent.is_dir():
        raise ValueError(f"대상 부모 디렉터리가 없습니다: {target.parent}")


def transfer(source: Path, target: Path, *, move: bool = False, overwrite: bool = False) -> None:
    """Stage copies before replacing existing data; preserve links rather than following them."""
    validate_transfer(source, target)
    if lexists(target) and not overwrite:
        raise FileExistsError(str(target))
    stage = Path(tempfile.mkdtemp(prefix=".mom-", dir=target.parent))
    staged, backup = stage / "new", stage / "old"
    try:
        if not move:
            if source.is_symlink():
                staged.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
            elif source.is_dir():
                shutil.copytree(source, staged, symlinks=True)
            elif stat.S_ISREG(source.stat().st_mode):
                shutil.copy2(source, staged)
            else:
                raise ValueError("특수 파일은 복사하지 않습니다.")
        if lexists(target):
            target.rename(backup)
        try:
            if move:
                shutil.move(str(source), str(target))
            else:
                staged.rename(target)
        except BaseException:
            if lexists(backup):
                if lexists(target):
                    remove(target)
                backup.rename(target)
            raise
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def decode_text(data: bytes, *, truncated: bool = False) -> tuple[str, str]:
    if b"\x00" in data[:8192]:
        raise ValueError("바이너리 파일입니다. VV는 텍스트 파일만 지원합니다.")
    for encoding in ("utf-8-sig", "cp949"):
        try:
            # Incremental decoding tolerates a partial character at the read limit.
            import codecs
            text = codecs.getincrementaldecoder(encoding)().decode(data, final=not truncated)
            return text, "UTF-8" if encoding == "utf-8-sig" else "CP949 (추정)"
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace"), "UTF-8 (대체 문자 포함)"


PREVIEW_LIMIT = 8 * 1024 * 1024


def read_text(path: Path) -> tuple[str, str, bool]:
    if not path.is_file():
        raise ValueError("일반 텍스트 파일을 선택하세요.")
    with path.open("rb") as stream:
        data = stream.read(PREVIEW_LIMIT + 1)
    truncated = len(data) > PREVIEW_LIMIT
    text, encoding = decode_text(data[:PREVIEW_LIMIT], truncated=truncated)
    return text, encoding, truncated


def system_info(path: Path) -> tuple[int | None, str]:
    try:
        free = shutil.disk_usage(path).free
    except OSError:
        free = None
    try:
        import psutil
        memory = psutil.virtual_memory()
        from .display import human
        ram = f"{human(memory.available)} / {human(memory.total)}"
    except Exception:
        ram = "N/A"
    return free, ram
