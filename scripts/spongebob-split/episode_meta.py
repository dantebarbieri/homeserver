"""Title and duration lookup for SpongeBob episode segments.

Combines data from the old timecode CSV (canonical for S1-S5 standard
episodes) with hardcoded fallbacks for specials (S00) and out-of-range
episodes the user catalogued.
"""

from __future__ import annotations

from dataclasses import dataclass

import lib


# Hardcoded titles for episodes NOT in the old CSV (S00 specials,
# S07+, and any S2-S5 segments the user references that the old CSV
# lacked). Source: user notes column in mapping_s{N}.csv +
# Wikipedia/Fandom for cross-reference where ambiguous.
SPECIAL_TITLES: dict[tuple[int, int], str] = {
    (0, 1): "The SpongeBob Christmas Special",
    (0, 2): "Party Pooper Pants",
    (0, 3): "The Sponge Who Could Fly",
    (0, 4): "Ugh",
    (0, 5): "Christmas Who",
    (0, 6): "Have You Seen This Snail",
    (0, 7): "Dunces and Dragons",
    (0, 8): "Special 8 (Unknown Title)",
    (0, 9): "Atlantis SquarePantis",
    (0, 10): "Pest of the West",
    (0, 11): "What Ever Happened to SpongeBob",
    # S07 episode referenced from S05 mapping (Goo Goo Gas).
    (7, 9): "Goo Goo Gas",
}


@dataclass(frozen=True)
class EpisodeMeta:
    season: int
    episode: int
    title: str
    # Old-CSV segment duration in seconds. None if not catalogued.
    old_duration_s: float | None


def _build_old_lookup() -> dict[tuple[int, int], EpisodeMeta]:
    rows = lib.load_old_csv()
    out: dict[tuple[int, int], EpisodeMeta] = {}
    for r in rows:
        # t_start=None in the old CSV means "start of file" (= 0).
        # t_end=None means "end of file" - we don't know the old file's
        # total duration so the segment's true duration is unknown.
        # When t_end is known, the duration is (t_end - (t_start or 0)).
        if r.t_end is None:
            dur: float | None = None
        else:
            t_start = r.t_start if r.t_start is not None else 0.0
            dur = max(0.0, r.t_end - t_start)
        out[(r.season, r.episode)] = EpisodeMeta(
            season=r.season,
            episode=r.episode,
            title=r.title,
            old_duration_s=dur,
        )
    return out


_OLD = _build_old_lookup()


def lookup_episode(season: int, episode: int) -> EpisodeMeta:
    """Return EpisodeMeta for (season, episode). Falls back to specials map
    or to a placeholder title."""
    if (season, episode) in _OLD:
        return _OLD[(season, episode)]
    if (season, episode) in SPECIAL_TITLES:
        return EpisodeMeta(
            season=season,
            episode=episode,
            title=SPECIAL_TITLES[(season, episode)],
            old_duration_s=None,
        )
    return EpisodeMeta(
        season=season,
        episode=episode,
        title=f"S{season:02d}E{episode:02d} (Unknown Title)",
        old_duration_s=None,
    )
