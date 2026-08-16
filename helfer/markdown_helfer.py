# helfer/markdown_helfer.py (VERBESSERTE VERSION)
# -*- coding: utf-8 -*-
"""
🔧 VERBESSERTE Markdown-V2 Helper mit korrektem Escaping
Behebt alle MarkdownV2-Parsing-Fehler
"""

import re


def escape_md_v2(text: str) -> str:
    """
    VOLLSTÄNDIG KORRIGIERTE Escape-Funktion für Telegram MarkdownV2

    Escaped ALLE reservierten Zeichen in der korrekten Reihenfolge.
    Basiert auf der offiziellen Telegram MarkdownV2-Spezifikation.
    """
    if not text:
        return ""

    # Konvertiere zu String falls nötig
    text = str(text)

    # VOLLSTÄNDIGE Liste aller reservierten Zeichen für MarkdownV2
    # Reihenfolge ist KRITISCH - Backslash MUSS zuerst escaped werden!
    replacements = [
        ("\\", "\\\\"),  # Backslash MUSS zuerst
        ("_", "\\_"),
        ("*", "\\*"),
        ("[", "\\["),
        ("]", "\\]"),
        ("(", "\\("),
        (")", "\\)"),
        ("~", "\\~"),
        ("`", "\\`"),
        (">", "\\>"),
        ("#", "\\#"),
        ("+", "\\+"),
        ("-", "\\-"),  # BINDESTRICHE escapen
        ("=", "\\="),
        ("|", "\\|"),
        ("{", "\\{"),
        ("}", "\\}"),
        (".", "\\."),  # PUNKT - das war ein Hauptproblem!
        ("!", "\\!"),
        (",", "\\,"),  # KOMMA
        (":", "\\:"),  # DOPPELPUNKT
        (";", "\\;"),  # SEMIKOLON
    ]

    # Wende Replacements in korrekter Reihenfolge an
    for char, escaped in replacements:
        text = text.replace(char, escaped)

    return text


def safe_escape_for_telegram(text: str) -> str:
    """
    Alias für escape_md_v2 - für Kompatibilität mit bestehenden Importen
    """
    return escape_md_v2(text)


def remove_unwanted_backslashes(text: str) -> str:
    """
    Entfernt unerwünschte Backslashes, die nicht für Markdown-Escaping benötigt werden
    """
    if not text:
        return ""

    text = str(text)

    # Behalte nur die Backslashes, die für Markdown-Sonderzeichen benötigt werden
    markdown_chars = [
        "_",
        "*",
        "[",
        "]",
        "(",
        ")",
        "~",
        "`",
        ">",
        "#",
        "+",
        "-",
        "=",
        "|",
        "{",
        "}",
        ".",
        "!",
        ",",
        ":",
        ";",
    ]

    # Ersetze alle Backslashes, die nicht vor Markdown-Sonderzeichen stehen
    result = ""
    i = 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text):
            # Wenn der Backslash vor einem Markdown-Sonderzeichen steht, behalten
            if text[i + 1] in markdown_chars:
                result += text[i] + text[i + 1]
                i += 2
            else:
                # Backslash entfernen, nur das nächste Zeichen behalten
                result += text[i + 1]
                i += 2
        else:
            result += text[i]
            i += 1

    return result


def md_bold(text: str) -> str:
    """
    Macht einen Text in MarkdownV2-Syntax fett, nachdem er escaped wurde.
    """
    # Escaping ist NICHT nötig, da der Text bereits außerhalb escaped werden sollte
    # oder bereits escaped ist. Bold-Tags umschließen den bereits escapten Text.
    return f"*{text}*"


def md_code(text: str) -> str:
    """
    Formatiert einen Text als MarkdownV2-Inline-Code.

    Für Code-Blöcke müssen nur Backticks escaped werden.
    """
    # Nur Backticks escapen für Inline-Code
    text_without_backticks = text.replace("`", "\\`")
    return f"`{text_without_backticks}`"


def md_italic(text: str) -> str:
    """
    Macht einen Text in MarkdownV2-Syntax kursiv.
    """
    return f"_{text}_"


def md_underline(text: str) -> str:
    """
    Unterstreicht einen Text in MarkdownV2-Syntax.
    """
    return f"__{text}__"


def md_strikethrough(text: str) -> str:
    """
    Durchstreicht einen Text in MarkdownV2-Syntax.
    """
    return f"~{text}~"


def md_spoiler(text: str) -> str:
    """
    Macht einen Text zu einem Spoiler in MarkdownV2-Syntax.
    """
    return f"||{text}||"


def md_code_block(text: str, language: str = "") -> str:
    """
    Formatiert einen Text als MarkdownV2-Code-Block.

    Args:
        text: Der Code-Text
        language: Optionale Sprache für Syntax-Highlighting
    """
    if language:
        return f"```{language}\n{text}\n```"
    else:
        return f"```\n{text}\n```"


def md_link(text: str, url: str) -> str:
    """
    Erstellt einen MarkdownV2-Link.

    Args:
        text: Der anzuzeigende Text (wird escaped)
        url: Die URL (wird escaped)
    """
    escaped_text = escape_md_v2(text)
    escaped_url = escape_md_v2(url)
    return f"[{escaped_text}]({escaped_url})"


def format_as_markdown_v2(text: str, as_code: bool = False) -> str:
    """
    Escapes text and optionally wraps it in a code block for MarkdownV2.

    Diese Funktion ist eine Kombination. Sie stellt sicher, dass der Text immer
    sicher für MarkdownV2 ist.
    """
    if as_code:
        # Bei Code-Blöcken wird der Text nicht escaped, da der MarkdownV2-Parser
        # innerhalb von Code-Blöcken keine Formatierung erwartet.
        return md_code_block(text)
    else:
        # Nur den escaped Text zurückgeben
        return escape_md_v2(text)


def create_progress_bar(percentage: float, length: int = 10) -> str:
    """
    Erstellt eine visuelle Fortschrittsanzeige für Telegram.

    Args:
        percentage: Fortschritt in Prozent (0-100)
        length: Länge der Fortschrittsanzeige in Zeichen

    Returns:
        Escaped Fortschrittsanzeige für MarkdownV2
    """
    if percentage < 0:
        percentage = 0
    elif percentage > 100:
        percentage = 100

    filled = int((percentage / 100) * length)
    empty = length - filled

    bar = "█" * filled + "░" * empty
    return escape_md_v2(f"[{bar}] {percentage:.1f}%")


def format_file_size(size_bytes: int) -> str:
    """
    Formatiert Dateigröße in menschenlesbares Format.

    Args:
        size_bytes: Größe in Bytes

    Returns:
        Formatierte und escaped Größenangabe
    """
    if size_bytes == 0:
        return escape_md_v2("0 B")

    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    size = float(size_bytes)

    while size >= 1024.0 and i < len(size_names) - 1:
        size /= 1024.0
        i += 1

    if i == 0:  # Bytes
        return escape_md_v2(f"{int(size)} {size_names[i]}")
    else:
        return escape_md_v2(f"{size:.1f} {size_names[i]}")


def format_duration(seconds: int) -> str:
    """
    Formatiert Dauer in menschenlesbares Format.

    Args:
        seconds: Dauer in Sekunden

    Returns:
        Formatierte und escaped Zeitangabe
    """
    if seconds < 60:
        return escape_md_v2(f"{seconds}s")
    elif seconds < 3600:  # Unter 1 Stunde
        minutes = seconds // 60
        remaining_seconds = seconds % 60
        return escape_md_v2(f"{minutes}m {remaining_seconds}s")
    else:  # Über 1 Stunde
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return escape_md_v2(f"{hours}h {minutes}m")


def validate_markdown_v2(text: str) -> tuple[bool, str]:
    """
    Validiert MarkdownV2-Text und gibt Hinweise bei Problemen.

    Args:
        text: Der zu validierende MarkdownV2-Text

    Returns:
        (is_valid, error_message)
    """
    try:
        # Grundlegende Validierung
        if not text:
            return True, ""

        # Prüfe auf unescapte reservierte Zeichen
        reserved_chars = r"_*[]()~`>#+=|{}.!-,:;"
        unescaped_pattern = r"(?<!\\)([{}])".format(re.escape(reserved_chars))

        matches = re.findall(unescaped_pattern, text)
        if matches:
            unique_chars = set(matches)
            return (
                False,
                f"Unescapte reservierte Zeichen gefunden: {', '.join(unique_chars)}",
            )

        # Prüfe auf unbalancierte Formatierung
        formatters = ["*", "_", "~", "`"]
        for formatter in formatters:
            count = text.count(formatter)
            if count % 2 != 0:
                return False, f"Unbalancierte Formatierung für '{formatter}'"

        return True, ""

    except Exception as e:
        return False, f"Validierungsfehler: {str(e)}"


# === LEGACY ALIASES FÜR RÜCKWÄRTSKOMPATIBILITÄT ===
def escape_markdown_v2(text: str) -> str:
    """Legacy alias für escape_md_v2"""
    return escape_md_v2(text)


def markdown_escape(text: str) -> str:
    """Legacy alias für escape_md_v2"""
    return escape_md_v2(text)


# === TESTS UND DEBUGGING ===
def test_escaping():
    """Testet die Escape-Funktion mit problematischen Zeichen"""
    test_cases = [
        "Hello World!",
        "Version 2.0 - New Features",
        "100% Success Rate",
        "File (1).txt",
        "User #123",
        "Price: $19.99",
        "Email: user@example.com",
        "Path: C:\\Users\\Test",
        "Markdown: *bold* _italic_ `code`",
        "Special: [](){}|<>#+=-~",
    ]

    print("🧪 Teste Escape-Funktion:")
    for i, test_text in enumerate(test_cases, 1):
        escaped = escape_md_v2(test_text)
        is_valid, error = validate_markdown_v2(escaped)
        status = "✅" if is_valid else "❌"
        print(f"{status} Test {i:2d}: '{test_text}' -> '{escaped}'")
        if not is_valid:
            print(f"    Error: {error}")


if __name__ == "__main__":
    # Führe Tests aus wenn Modul direkt ausgeführt wird
    test_escaping()
