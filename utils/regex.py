import re

ILLEGAL_CHARS_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1F]')
FEAT_NOTATION_PATTERN = re.compile(r"\s*\(feat\.\s+([^)]+)\)")
EXTRA_SPACES_PATTERN = re.compile(r"\s+")
ALBUM_PATTERNS = [
    re.compile(r"Album:\s*(.*?)\s*$", re.IGNORECASE),
    re.compile(r"\[Album\]\s*(.*?)\s*$", re.IGNORECASE),
    re.compile(r"\(Album\)\s*(.*?)\s*$", re.IGNORECASE),
]
