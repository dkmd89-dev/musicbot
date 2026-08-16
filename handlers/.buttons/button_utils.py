def remove_backslashes(text: str) -> str:
    """
    Entfernt Backslashes aus einem gegebenen Text.
    Wird verwendet, um z. B. Markdown- oder HTML-Sonderzeichen zu bereinigen.
    """
    if isinstance(text, str):
        return text.replace("\\", "")
    return str(text)


def get_description_with_emoji_key(key: str, command_descriptions: dict) -> str:
    """
    Versucht, eine Beschreibung aus command_descriptions zu finden,
    auch wenn der Schlüssel ein Emoji enthält.
    """
    desc = command_descriptions.get(key, "")
    if desc:
        return desc
    for cmd_desc_key, desc_val in command_descriptions.items():
        if cmd_desc_key.endswith(f" {key}") or cmd_desc_key == key:
            return desc_val
    return ""
