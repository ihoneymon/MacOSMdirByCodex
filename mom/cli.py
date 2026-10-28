"""Console entry point and last-directory bridge to the parent shell."""
import argparse
import os
from pathlib import Path
import sys
import tempfile
from . import __version__


def write_last_directory(filename: Path, directory: Path) -> None:
    """Write raw filesystem bytes without a newline, atomically on the same filesystem."""
    filename = filename.expanduser().absolute()
    descriptor, temporary = tempfile.mkstemp(prefix=".mom-last-", dir=filename.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(os.fsencode(directory))
        os.replace(temporary, filename)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="MacOSMdir MOM · DOS 감성의 터미널 파일 관리자")
    parser.add_argument("path", nargs="?", default=".", help="시작 디렉터리")
    parser.add_argument("--last-dir-file", type=Path, help="정상 종료 후 마지막 실제 경로를 기록할 파일")
    parser.add_argument("--print-last-dir", action="store_true", help="TUI 복구 후 마지막 경로 출력")
    parser.add_argument("--version", action="version", version=f"MacOSMdir MOM {__version__}")
    args = parser.parse_args(argv)
    path = Path(args.path).expanduser().absolute()
    try:
        with os.scandir(path):
            pass
    except OSError as error:
        parser.error(str(error))
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        parser.error("대화형 터미널에서 실행하세요.")
    from .app import MomApp
    app = MomApp(path)
    app.run()
    if app.return_code:
        return app.return_code
    try:
        if args.last_dir_file:
            write_last_directory(args.last_dir_file, app.last_directory)
        if args.print_last_dir:
            print(app.last_directory)
    except OSError as error:
        print(f"MOM: 마지막 경로 기록 실패: {error}", file=sys.stderr)
        return 1
    return 0
