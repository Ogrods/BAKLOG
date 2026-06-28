import re

from shared.library_noise import should_auto_hide_gog_title

_PROMO_SUFFIX_RES = (
    re.compile("\\s*-\\s*Amazon Luna\\s*$", re.IGNORECASE),
    re.compile("\\s*-\\s*Amazon Prime\\s*$", re.IGNORECASE),
    re.compile("\\s*-\\s*Prime Giveaway\\s*$", re.IGNORECASE),
)
_YEAR_QUALIFIER_RE = re.compile("\\s*\\(\\d{4}\\)\\s*$")
_EDITION_VARIANT_SUBTITLE_RE = re.compile(
    "\\b(edition|deluxe|upgrade|complete|musical|trilogy|collection|pack|bundle|goty|definitive|remastered|remaster|ultimate)\\b",
    re.IGNORECASE,
)
_PACK_REGISTRY = (
    (
        re.compile("^Silver Box Classics$", re.IGNORECASE),
        ("Heroes of the Lance", "Dragons of Flame", "War of the Lance", "Shadow Sorcerer"),
    ),
    (
        re.compile("^Forgotten Realms: The Archives - Collection One$", re.IGNORECASE),
        (
            "Eye of the Beholder",
            "Eye of the Beholder II: The Legend of Darkmoon",
            "Eye of the Beholder III: Assault on Myth Drannor",
        ),
    ),
    (
        re.compile("^Forgotten Realms: The Archives - Collection Two$", re.IGNORECASE),
        (
            "Pool of Radiance",
            "Curse of the Azure Bonds",
            "Hillsfar",
            "Secret of the Silver Blades",
            "Pools of Darkness",
            "Gateway to the Savage Frontier",
            "Treasures of the Savage Frontier",
        ),
    ),
    (
        re.compile("^Forgotten Realms: The Archives - Collection Three$", re.IGNORECASE),
        ("Dungeon Hack", "Menzoberranzan"),
    ),
    (
        re.compile("^Alone in the Dark: The Trilogy 1\\+2\\+3$", re.IGNORECASE),
        ("Alone in the Dark 1", "Alone in the Dark 2", "Alone in the Dark 3"),
    ),
)


def should_skip_gog_title(name):
    return should_auto_hide_gog_title(name)


def has_promo_suffix(name):
    return any(pat.search(name or "") for pat in _PROMO_SUFFIX_RES)


def canonical_gog_title(name):
    out = name or ""
    for pat in _PROMO_SUFFIX_RES:
        out = pat.sub("", out)
    return out.strip()


def norm_gog_title(name):
    return re.sub("[^a-z0-9]", "", (name or "").lower())


def dedupe_key(name):
    base = _YEAR_QUALIFIER_RE.sub("", canonical_gog_title(name))
    return norm_gog_title(base)


def _subtitle_after_colon(name):
    if ":" not in name:
        return ""
    return name.split(":", 1)[1].strip()


def subtitle_looks_like_edition_variant(name):
    sub = _subtitle_after_colon(name)
    return bool(sub and _EDITION_VARIANT_SUBTITLE_RE.search(sub))


def barren_group_key(name):
    if ":" in name and subtitle_looks_like_edition_variant(name):
        return norm_gog_title(name.split(":", 1)[0])
    return dedupe_key(name)


def _row_name(row):
    return str(row.get("name") or "")


def row_is_metadata_barren(row):
    return not (row.get("header_image") or "").strip() and (not row.get("genres"))


def collapse_promo_suffix_dupes(rows):
    clean_norms = set()
    for row in rows:
        name = _row_name(row)
        if not has_promo_suffix(name):
            clean_norms.add(norm_gog_title(name))
    out = []
    kept_promo_norms = set()
    for row in rows:
        name = _row_name(row)
        if not has_promo_suffix(name):
            out.append(row)
            continue
        canonical = canonical_gog_title(name)
        norm = norm_gog_title(canonical)
        if norm in clean_norms or norm in kept_promo_norms:
            continue
        out.append({**row, "name": canonical})
        kept_promo_norms.add(norm)
    return out


def collapse_pack_dupes(rows, *, pack_component_keys=None, owned_release_keys=None):
    norms_present = {norm_gog_title(_row_name(r)) for r in rows}
    out = []
    for row in rows:
        canonical = canonical_gog_title(_row_name(row))
        drop = False
        rk = row.get("release_key")
        if rk and pack_component_keys and owned_release_keys and (rk in pack_component_keys):
            components = pack_component_keys[rk]
            if components and components.issubset(owned_release_keys):
                drop = True
        if not drop:
            for pack_pat, components in _PACK_REGISTRY:
                if not pack_pat.match(canonical):
                    continue
                if all(norm_gog_title(c) in norms_present for c in components):
                    drop = True
                break
        if not drop:
            out.append(row)
    return out


def collapse_metadata_barren_dupes(rows):
    groups = {}
    for row in rows:
        groups.setdefault(barren_group_key(_row_name(row)), []).append(row)
    out = []
    for row in rows:
        grp = groups[barren_group_key(_row_name(row))]
        if len(grp) > 1 and row_is_metadata_barren(row) and any(not row_is_metadata_barren(other) for other in grp):
            continue
        out.append(row)
    return out


def apply_gog_name_filters(rows, **pack_kw):
    rows = collapse_promo_suffix_dupes(rows)
    rows = collapse_pack_dupes(rows, **pack_kw)
    return collapse_metadata_barren_dupes(rows)


def filter_gog_game_rows(games):
    return apply_gog_name_filters(games)
