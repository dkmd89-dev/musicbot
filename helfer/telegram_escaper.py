from pathlib import Path
from typing import Union, List
from telegram.helpers import escape_markdown


def escape_script_for_telegram(file: Union[str, Path]) -> str:
    """
    Lies eine Datei und escapt deren Inhalt vollständig für Telegram (MarkdownV2).
    """
    content = Path(file).read_text(encoding="utf-8")
    return escape_markdown(content, version=2)


def escape_script_chunks(file: Union[str, Path], chunk_size: int = 3900) -> List[str]:
    """
    Lies eine Datei, escapt den Inhalt für Telegram (MarkdownV2)
    und teilt ihn in Telegram-kompatible Chunks.
    Nutzt ```-Codeblöcke für Telegram-Kompatibilität.
    """

    escaped = escape_script_for_telegram(file)

    block_prefix = "```\n"
    block_suffix = "\n```"

    overhead = len(block_prefix) + len(block_suffix)
    safe_chunk_size = chunk_size - overhead

    chunks = [
        f"{block_prefix}{escaped[i:i + safe_chunk_size]}{block_suffix}"
        for i in range(0, len(escaped), safe_chunk_size)
    ]
    return chunks


def escape_text_chunks(text: str, chunk_size: int = 3900) -> List[str]:
    """
    Escapt einen gegebenen Text (String) für Telegram (MarkdownV2)
    und teilt ihn in Telegram-kompatible Chunks mit ```-Codeblöcken.
    """

    escaped = escape_markdown(text, version=2)

    block_prefix = "```\n"
    block_suffix = "\n```"

    overhead = len(block_prefix) + len(block_suffix)
    safe_chunk_size = chunk_size - overhead

    chunks = [
        f"{block_prefix}{escaped[i:i + safe_chunk_size]}{block_suffix}"
        for i in range(0, len(escaped), safe_chunk_size)
    ]
    return chunks


def save_escaped_script(file: Union[str, Path], output_dir: Path) -> Path:
    """
    Speichert die escapte Datei als neue Textdatei im angegebenen Ordner.
    """
    escaped_text = escape_script_for_telegram(file)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{Path(file).stem}_escaped.txt"
    output_path.write_text(escaped_text, encoding="utf-8")
    return output_path
