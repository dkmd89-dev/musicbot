# control_center/schemas/mapping_admin.py
# -*- coding: utf-8 -*-
"""
Schemas für die Mapping-Administration im Control Center.

Dünne Abbildung von services/mapping_admin.py (ChannelGenreEntry /
ChannelGenrePlan / ChannelGenreSaveResult) — keine eigene Fachlogik.
M1 deckt nur channel-genre ab; weitere Mapping-IDs folgen in M2.
"""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from services.mapping_admin import (
    ChannelGenreEntry,
    ChannelGenrePlan,
    ChannelGenreSaveResult,
    GenreAliasEntry,
    GenreAliasPlan,
    GenreAliasSaveResult,
    GenreOverrideEntry,
    GenreOverridePlan,
    GenreOverrideSaveResult,
    GenreFilterPlan,
    GenreFilterSaveResult,
    SpecialChannelCategory,
    SpecialChannelPlan,
    SpecialChannelSaveResult,
)


class ChannelGenreEntrySchema(BaseModel):
    key: str
    primary: str
    secondary: List[str]
    description: Optional[str] = None


class ChannelGenreListResponse(BaseModel):
    mapping_id: str
    entries: List[ChannelGenreEntrySchema]
    count: int
    bot_reload_required: bool = True


class ChannelGenreGetResponse(BaseModel):
    mapping_id: str
    channel: str
    exists: bool
    entry: Optional[ChannelGenreEntrySchema] = None
    etag: str


class ChannelGenreBody(BaseModel):
    primary: str
    secondary: List[str] = Field(default_factory=list)
    description: Optional[str] = None


class ChannelGenreSaveBody(ChannelGenreBody):
    etag: str


class ChannelGenrePreviewResponse(BaseModel):
    mapping_id: str
    channel: str
    key: str
    change: str
    existing: Optional[ChannelGenreEntrySchema] = None
    primary: str
    secondary: List[str]
    description: Optional[str] = None
    primary_changed: bool
    added: List[str]
    removed: List[str]
    warnings: List[str]
    etag: str


class ChannelGenreSaveResponse(ChannelGenrePreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


def entry_to_schema(entry: Optional[ChannelGenreEntry]) -> Optional[ChannelGenreEntrySchema]:
    if entry is None:
        return None
    return ChannelGenreEntrySchema(
        key=entry.key, primary=entry.primary, secondary=list(entry.secondary),
        description=entry.description,
    )


def plan_to_preview(
    mapping_id: str, channel: str, plan: ChannelGenrePlan,
) -> ChannelGenrePreviewResponse:
    return ChannelGenrePreviewResponse(
        mapping_id=mapping_id,
        channel=channel,
        key=plan.key,
        change=plan.change,
        existing=entry_to_schema(plan.existing),
        primary=plan.primary,
        secondary=list(plan.secondary),
        description=plan.description,
        primary_changed=plan.primary_changed,
        added=list(plan.added),
        removed=list(plan.removed),
        warnings=list(plan.warnings),
        etag=plan.etag,
    )


SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot lädt channel_genre.yaml beim "
    "Start: die Änderung wirkt für neue Downloads erst nach einem Bot-Neustart."
)
SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def save_to_response(
    mapping_id: str, channel: str, plan: ChannelGenrePlan, result: ChannelGenreSaveResult,
) -> ChannelGenreSaveResponse:
    base = plan_to_preview(mapping_id, channel, plan)
    return ChannelGenreSaveResponse(
        **base.model_dump(),
        written=result.written, unchanged=result.unchanged, new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=SAVE_MESSAGE_WRITTEN if result.written else SAVE_MESSAGE_UNCHANGED,
    )

# ── Genre-Alias (M2) ─────────────────────────────────────────────────


class GenreAliasEntrySchema(BaseModel):
    key: str
    canonical: str


class GenreAliasListResponse(BaseModel):
    mapping_id: str
    entries: List[GenreAliasEntrySchema]
    count: int
    bot_reload_required: bool = True
    warnings: List[str] = Field(default_factory=list)


class GenreAliasGetResponse(BaseModel):
    mapping_id: str
    key: str
    exists: bool
    entry: Optional[GenreAliasEntrySchema] = None
    etag: str


class GenreAliasBody(BaseModel):
    canonical: str


class GenreAliasSaveBody(GenreAliasBody):
    etag: str


class GenreAliasPreviewResponse(BaseModel):
    mapping_id: str
    key: str
    change: str
    existing: Optional[GenreAliasEntrySchema] = None
    canonical: str
    canonical_changed: bool
    warnings: List[str] = Field(default_factory=list)
    etag: str
    comment_warning: Optional[str] = None


class GenreAliasSaveResponse(GenreAliasPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


COMMENT_LOSS_WARNING = (
    "Kommentarzeilen in genre_aliases.yaml gehen beim Speichern verloren "
    "(bekannte Einschraenkung des YAML-Rewrites)."
)


def genre_alias_entry_to_schema(entry: Optional[GenreAliasEntry]) -> Optional[GenreAliasEntrySchema]:
    if entry is None:
        return None
    return GenreAliasEntrySchema(key=entry.key, canonical=entry.canonical)


def genre_alias_plan_to_preview(
    mapping_id: str, key: str, plan: GenreAliasPlan,
) -> GenreAliasPreviewResponse:
    return GenreAliasPreviewResponse(
        mapping_id=mapping_id,
        key=plan.key,
        change=plan.change,
        existing=genre_alias_entry_to_schema(plan.existing),
        canonical=plan.canonical,
        canonical_changed=plan.canonical_changed,
        warnings=list(plan.warnings),
        etag=plan.etag,
        comment_warning=COMMENT_LOSS_WARNING if plan.change != "unchanged" else None,
    )


GENRE_ALIAS_SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot laedt genre_aliases.yaml beim "
    "Start: die Aenderung wirkt fuer neue Downloads erst nach Bot-Neustart."
)
GENRE_ALIAS_SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def genre_alias_save_to_response(
    mapping_id: str, key: str, plan: GenreAliasPlan, result: GenreAliasSaveResult,
) -> GenreAliasSaveResponse:
    base = genre_alias_plan_to_preview(mapping_id, key, plan)
    return GenreAliasSaveResponse(
        **base.model_dump(),
        written=result.written,
        unchanged=result.unchanged,
        new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=(
            GENRE_ALIAS_SAVE_MESSAGE_WRITTEN if result.written
            else GENRE_ALIAS_SAVE_MESSAGE_UNCHANGED
        ),
    )

# ── Genre-Override (M3) ──────────────────────────────────────────────


class GenreOverrideEntrySchema(BaseModel):
    key: str
    override: str


class GenreOverrideListResponse(BaseModel):
    mapping_id: str
    entries: List[GenreOverrideEntrySchema]
    count: int
    bot_reload_required: bool = True
    warnings: List[str] = Field(default_factory=list)


class GenreOverrideGetResponse(BaseModel):
    mapping_id: str
    key: str
    exists: bool
    entry: Optional[GenreOverrideEntrySchema] = None
    etag: str


class GenreOverrideBody(BaseModel):
    override: str


class GenreOverrideSaveBody(GenreOverrideBody):
    etag: str


class GenreOverridePreviewResponse(BaseModel):
    mapping_id: str
    key: str
    change: str
    existing: Optional[GenreOverrideEntrySchema] = None
    override: str
    override_changed: bool
    warnings: List[str] = Field(default_factory=list)
    etag: str
    comment_warning: Optional[str] = None


class GenreOverrideSaveResponse(GenreOverridePreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


GENRE_OVERRIDE_COMMENT_WARNING = (
    "Kommentarzeilen in genre_overrides.yaml gehen beim Speichern verloren "
    "(bekannte Einschraenkung des YAML-Rewrites)."
)


def genre_override_entry_to_schema(
    entry: Optional[GenreOverrideEntry],
) -> Optional[GenreOverrideEntrySchema]:
    if entry is None:
        return None
    return GenreOverrideEntrySchema(key=entry.key, override=entry.override)


def genre_override_plan_to_preview(
    mapping_id: str, key: str, plan: GenreOverridePlan,
) -> GenreOverridePreviewResponse:
    return GenreOverridePreviewResponse(
        mapping_id=mapping_id,
        key=plan.key,
        change=plan.change,
        existing=genre_override_entry_to_schema(plan.existing),
        override=plan.override,
        override_changed=plan.override_changed,
        warnings=list(plan.warnings),
        etag=plan.etag,
        comment_warning=(
            GENRE_OVERRIDE_COMMENT_WARNING if plan.change != "unchanged" else None
        ),
    )


GENRE_OVERRIDE_SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot laedt genre_overrides.yaml beim "
    "Start: die Aenderung wirkt fuer neue Downloads erst nach Bot-Neustart."
)
GENRE_OVERRIDE_SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def genre_override_save_to_response(
    mapping_id: str, key: str, plan: GenreOverridePlan, result: GenreOverrideSaveResult,
) -> GenreOverrideSaveResponse:
    base = genre_override_plan_to_preview(mapping_id, key, plan)
    return GenreOverrideSaveResponse(
        **base.model_dump(),
        written=result.written,
        unchanged=result.unchanged,
        new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=(
            GENRE_OVERRIDE_SAVE_MESSAGE_WRITTEN if result.written
            else GENRE_OVERRIDE_SAVE_MESSAGE_UNCHANGED
        ),
    )

# ── Genre-Filter (M4) — Liste ────────────────────────────────────────


class GenreFilterListResponse(BaseModel):
    mapping_id: str
    values: List[str]
    count: int
    etag: str
    warnings: List[str] = Field(default_factory=list)
    bot_reload_required: bool = True


class GenreFilterBody(BaseModel):
    values: List[str]


class GenreFilterSaveBody(GenreFilterBody):
    etag: str


class GenreFilterPreviewResponse(BaseModel):
    mapping_id: str
    change: str
    added: List[str]
    removed: List[str]
    values: List[str]
    warnings: List[str] = Field(default_factory=list)
    etag: str
    comment_warning: Optional[str] = None


class GenreFilterSaveResponse(GenreFilterPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


GENRE_FILTER_COMMENT_WARNING = (
    "Kommentarzeilen in genre_filters.yaml gehen beim Speichern verloren "
    "(bekannte Einschraenkung des YAML-Rewrites)."
)


def genre_filter_plan_to_preview(plan: GenreFilterPlan) -> GenreFilterPreviewResponse:
    return GenreFilterPreviewResponse(
        mapping_id=plan.mapping_id,
        change=plan.change,
        added=list(plan.added),
        removed=list(plan.removed),
        values=list(plan.values),
        warnings=list(plan.warnings),
        etag=plan.etag,
        comment_warning=(
            GENRE_FILTER_COMMENT_WARNING
            if plan.change in ("update", "cleanup")
            else None
        ),
    )


GENRE_FILTER_SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot laedt genre_filters.yaml beim "
    "Start: die Aenderung wirkt fuer neue Downloads erst nach Bot-Neustart."
)
GENRE_FILTER_SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def genre_filter_save_to_response(
    plan: GenreFilterPlan, result: GenreFilterSaveResult,
) -> GenreFilterSaveResponse:
    base = genre_filter_plan_to_preview(plan)
    return GenreFilterSaveResponse(
        **base.model_dump(),
        written=result.written,
        unchanged=result.unchanged,
        new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=(
            GENRE_FILTER_SAVE_MESSAGE_WRITTEN if result.written
            else GENRE_FILTER_SAVE_MESSAGE_UNCHANGED
        ),
    )

# ── Special-Channel (M5) — geordnete Kategorien ──────────────────────


class SpecialChannelCategorySchema(BaseModel):
    name: str
    channels: List[str]


class SpecialChannelListResponse(BaseModel):
    mapping_id: str
    categories: List[SpecialChannelCategorySchema]
    count: int
    etag: str
    warnings: List[str] = Field(default_factory=list)
    bot_reload_required: bool = True


class SpecialChannelBody(BaseModel):
    categories: List[SpecialChannelCategorySchema]


class SpecialChannelSaveBody(SpecialChannelBody):
    etag: str


class SpecialChannelPreviewResponse(BaseModel):
    mapping_id: str
    change: str
    categories: List[SpecialChannelCategorySchema]
    added: List[str]
    removed: List[str]
    warnings: List[str] = Field(default_factory=list)
    etag: str
    comment_warning: Optional[str] = None
    order_change: Optional[str] = None


class SpecialChannelSaveResponse(SpecialChannelPreviewResponse):
    written: bool
    unchanged: bool
    new_etag: str
    bot_reload_required: bool = True
    message: str


SPECIAL_CHANNEL_COMMENT_WARNING = (
    "Kommentarzeilen in special_channel.yaml gehen beim Speichern verloren "
    "(bekannte Einschraenkung des YAML-Rewrites). Die fachliche "
    "Prioritaets-Reihenfolge der Kategorien bleibt erhalten."
)


def special_channel_plan_to_preview(plan: SpecialChannelPlan) -> SpecialChannelPreviewResponse:
    return SpecialChannelPreviewResponse(
        mapping_id=plan.mapping_id,
        change=plan.change,
        categories=[
            SpecialChannelCategorySchema(name=c.name, channels=list(c.channels))
            for c in plan.categories
        ],
        added=list(plan.added),
        removed=list(plan.removed),
        warnings=list(plan.warnings),
        etag=plan.etag,
        order_change=plan.order_change,
        comment_warning=(
            SPECIAL_CHANNEL_COMMENT_WARNING
            if plan.change in ("update", "cleanup")
            else None
        ),
    )


SPECIAL_CHANNEL_SAVE_MESSAGE_WRITTEN = (
    "Mapping gespeichert. Der laufende Bot laedt special_channel.yaml beim "
    "Start: die Aenderung wirkt fuer neue Downloads erst nach Bot-Neustart. "
    "Hinweis: die Runtime merged weiterhin special_channel.yaml mit "
    "Config.SPECIAL_CHANNELS — die Administration verwaltet nur die YAML-Quelle."
)
SPECIAL_CHANNEL_SAVE_MESSAGE_UNCHANGED = "Mapping war bereits identisch — nichts geschrieben."


def special_channel_save_to_response(
    plan: SpecialChannelPlan, result: SpecialChannelSaveResult,
) -> SpecialChannelSaveResponse:
    base = special_channel_plan_to_preview(plan)
    return SpecialChannelSaveResponse(
        **base.model_dump(),
        written=result.written,
        unchanged=result.unchanged,
        new_etag=result.new_etag,
        bot_reload_required=result.written,
        message=(
            SPECIAL_CHANNEL_SAVE_MESSAGE_WRITTEN if result.written
            else SPECIAL_CHANNEL_SAVE_MESSAGE_UNCHANGED
        ),
    )
