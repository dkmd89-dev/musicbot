# control_center/schemas/navidrome.py
# -*- coding: utf-8 -*-
"""Response-Schema für GET /api/v1/navidrome/status."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class NavidromeStatusResponse(BaseModel):
    connected: bool
    artist_count: Optional[int] = None
