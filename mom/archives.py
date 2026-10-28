"""Read-only ZIP/TAR VFS and bounded, path-checked extraction."""
from __future__ import annotations
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
import os
import shutil
import stat
import tarfile
import tempfile
import zipfile
from datetime import datetime
from .filesystem import Entry, PREVIEW_LIMIT, decode_text

MAX_MEMBERS = 10_000
MAX_BYTES = 512 * 1024 * 1024


def supported(path: Path) -> bool:
    return path.name.lower().endswith((".zip", ".tar", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar.xz"))


def member_name(name: str) -> str:
    # Backslashes are rejected even on POSIX, so archives behave the same on Windows.
    parts = PurePosixPath(name).parts
    if (not name or "\\" in name or "\x00" in name or name.startswith("/") or
            PureWindowsPath(name).drive or ".." in parts or any(":" in part for part in parts)):
        raise ValueError(f"안전하지 않은 압축 경로: {name!r}")
    result = "/".join(part for part in parts if part != ".")
    if not result:
        raise ValueError("빈 압축 경로")
    return result


@dataclass(frozen=True)
class Member:
    name: str
    original: str
    directory: bool
    size: int
    mtime: float


class Archive:
    def __init__(self, path: Path):
        self.path = path
        self.zip = path.suffix.lower() == ".zip"
        self.members: dict[str, Member] = {}
        self.blocked = 0
        total = 0
        with self.open() as archive:
            source = archive.infolist() if self.zip else archive
            for count, item in enumerate(source, 1):
                if count > MAX_MEMBERS:
                    raise ValueError(f"압축 항목 한도 초과 ({MAX_MEMBERS:,}개)")
                try:
                    name = member_name(item.filename if self.zip else item.name)
                    if self.zip:
                        mode = item.external_attr >> 16
                        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR)):
                            raise ValueError("링크·특수 파일")
                        directory, size = item.is_dir(), item.file_size
                        try:
                            mtime = datetime(*item.date_time).timestamp()
                        except (ValueError, OSError):
                            mtime = 0
                        original = item.filename
                    else:
                        if not (item.isdir() or item.isfile()):
                            raise ValueError("링크·특수 파일")
                        directory, size, mtime, original = item.isdir(), item.size, item.mtime, item.name
                    if name in self.members:
                        raise ValueError("중복 압축 경로")
                    total += size
                    if total > MAX_BYTES:
                        raise OverflowError("압축 해제 크기 한도 초과 (512 MiB)")
                    self.members[name] = Member(name, original, directory, size, mtime)
                except ValueError:
                    self.blocked += 1
        # Never reinterpret an archive file as a parent directory.
        for name in self.members:
            for parent in PurePosixPath(name).parents:
                if str(parent) in self.members and not self.members[str(parent)].directory:
                    raise ValueError("파일과 디렉터리 경로가 충돌하는 압축입니다.")

    def open(self):
        return zipfile.ZipFile(self.path) if self.zip else tarfile.open(self.path, "r:*")

    def listing(self, prefix: str = "") -> list[Entry]:
        prefix = prefix.rstrip("/") + "/" if prefix else ""
        entries: dict[str, Entry] = {}
        for name, item in self.members.items():
            if not name.startswith(prefix) or name == prefix.rstrip("/"):
                continue
            relative = name[len(prefix):]
            first, separator, _ = relative.partition("/")
            directory = bool(separator) or item.directory
            key = prefix + first
            entries[key] = Entry(first, key, directory, 0 if directory else item.size, item.mtime)
        return [Entry("..", "..", True, parent=True), *entries.values()]

    @contextmanager
    def stream(self, archive, member: Member):
        stream = archive.open(member.original) if self.zip else archive.extractfile(member.original)
        if stream is None:
            raise ValueError("이 항목을 읽을 수 없습니다.")
        with stream:
            yield stream

    def read_text(self, key: str):
        member = self.members[key]
        with self.open() as archive, self.stream(archive, member) as stream:
            data = stream.read(PREVIEW_LIMIT + 1)
        truncated = len(data) > PREVIEW_LIMIT
        text, encoding = decode_text(data[:PREVIEW_LIMIT], truncated=truncated)
        return text, encoding, truncated

    def extract(self, keys: list[str], destination: Path, *, overwrite: bool = False,
                progress=lambda value: None) -> None:
        destination = destination.resolve(strict=True)
        if not destination.is_dir():
            raise ValueError("추출 대상 디렉터리가 없습니다.")
        tasks: dict[str, tuple[Member, Path]] = {}
        for key in keys:
            key = member_name(key)
            for name, item in self.members.items():
                if name == key or name.startswith(key + "/"):
                    relative = PurePosixPath(key).name + name[len(key):]
                    target = destination.joinpath(*PurePosixPath(relative).parts)
                    tasks[name] = (item, target)
        def check(target):
            if not target.resolve().is_relative_to(destination):
                raise ValueError("압축 추출 경로 이탈을 차단했습니다.")
            current = target
            while current != destination:
                if current.is_symlink():
                    raise ValueError("추출 경로의 심볼릭 링크를 차단했습니다.")
                current = current.parent
        # Preflight before touching any file.
        for item, target in tasks.values():
            check(target)
            if target.exists() and not (item.directory and target.is_dir()) and not overwrite:
                raise FileExistsError(str(target))
        total = 0
        with self.open() as archive:
            for i, (item, target) in enumerate(tasks.values(), 1):
                check(target)
                if item.directory:
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    check(target)
                    descriptor, temporary = tempfile.mkstemp(prefix=".mom-extract-", dir=target.parent)
                    try:
                        with os.fdopen(descriptor, "wb") as output, self.stream(archive, item) as source:
                            size = 0
                            while chunk := source.read(64 * 1024):
                                total += len(chunk)
                                size += len(chunk)
                                if total > MAX_BYTES or size > item.size:
                                    raise ValueError("실제 압축 해제 크기 한도 초과")
                                output.write(chunk)
                        if size != item.size:
                            raise ValueError("압축 항목 크기가 일치하지 않습니다.")
                        check(target)
                        if target.exists() and not overwrite:
                            raise FileExistsError(str(target))
                        os.replace(temporary, target)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                progress(f"추출 {i}/{len(tasks)}: {item.name}")
