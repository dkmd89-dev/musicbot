# utils/singleton.py
"""
Singleton-Mixin für schwere Komponenten.
Verhindert mehrfache Initialisierung von Caches, Mappings und Connections.
"""

import logging

logger = logging.getLogger(__name__)


class SingletonMixin:
    """Mixin für Komponenten, die nur EINMAL initialisiert werden sollen."""

    _instances = {}

    def __new__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__new__(cls)
            cls._instances[cls] = instance
            instance._initialized = False
        return cls._instances[cls]

    def __init__(self, *args, **kwargs):
        if self._initialized:
            return  # ✅ Bereits initialisiert → nichts tun
        # Erster Aufruf: Normale Initialisierung
        self._do_init(*args, **kwargs)
        self._initialized = True

    def _do_init(self, *args, **kwargs):
        """Muss von Subklassen überschrieben werden."""
        raise NotImplementedError("Subklassen müssen _do_init implementieren")
