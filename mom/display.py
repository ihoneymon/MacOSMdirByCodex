"""Terminal-cell-aware display helpers; filenames are always plain text."""
import unicodedata
import regex
from wcwidth import wcswidth

BLUE = "#0000aa"
CYAN = "#55ffff"


def safe(value: object) -> str:
    return "".join("�" if unicodedata.category(c) in {"Cc", "Cs"} or
                   (unicodedata.category(c) == "Cf" and c != "\u200d") else c
                   for c in str(value))


def fit(value: object, width: int, *, right: bool = False) -> str:
    """Pad or truncate whole graphemes to exactly width terminal cells."""
    width = max(0, width)
    value = safe(value)
    if wcswidth(value) > width:
        budget = max(0, width - 1)
        parts, cells = [], 0
        for part in regex.findall(r"\X", value):
            size = max(0, wcswidth(part))
            if cells + size > budget:
                break
            parts.append(part)
            cells += size
        value = "".join(parts) + ("…" if width else "")
    padding = " " * max(0, width - max(0, wcswidth(value)))
    return padding + value if right else value + padding


def human(size: int) -> str:
    amount = float(size)
    for unit in ("B", "K", "M", "G", "T"):
        if amount < 1024 or unit == "T":
            return f"{amount:.0f}{unit}" if unit == "B" else f"{amount:.1f}{unit}"
        amount /= 1024
    return "?"


SCRIPT = {".bat", ".cmd", ".py", ".js", ".ts", ".ps1", ".rb"}
EXECUTABLE = {".exe", ".com", ".sh", ".app"}
ARCHIVE = {".zip", ".tar", ".gz", ".tgz", ".7z", ".lzh", ".arj", ".bz2", ".xz"}
DOCUMENT = {".txt", ".md", ".doc", ".docx", ".hwp", ".json", ".csv", ".xml", ".yaml", ".toml", ".ini", ".log"}
MEDIA = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp3", ".mp4", ".wav", ".mov", ".svg"}


def color(entry) -> str:
    suffix = entry.suffix
    if suffix == ".app" or suffix in EXECUTABLE:
        return "#55ff55"
    if entry.is_dir:
        return "bold #ffff55"
    if suffix in SCRIPT:
        return "#ffff55"
    if suffix in ARCHIVE:
        return "#ff55ff"
    if suffix in DOCUMENT:
        return CYAN
    if suffix in MEDIA:
        return "#ff5555"
    if entry.executable:
        return "#55ff55"
    return "#aaaaaa"
