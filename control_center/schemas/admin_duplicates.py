# control_center/schemas/admin_duplicates.py
# -*- coding: utf-8 -*-
"""Schemas für die Duplikat-Cache-Verwaltung im Control Center
(Web-Paritäts-Backlog 4b) - dünn, nur die für die UI nötigen Felder."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DuplicateCacheStatsResponse(BaseModel):
    url_entries: int
    content_entries: int
    oldest_entry: Optional[str] = None
    newest_entry: Optional[str] = None


class ClearDuplicateCacheRequest(BaseModel):
    # Explizite Bestätigung (Gegenstück zum Telegram-Bestätigungsdialog).
    confirm: bool = False


class ClearDuplicateCacheResponse(BaseModel):
    url_entries_removed: int
    content_entries_removed: int
    deleted_files: list[str]
