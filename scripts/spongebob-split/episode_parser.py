"""Parses the `actual_episodes` field of mapping_s{N}.csv.

Format:
  - Comma-separated list of tokens, in file order.
  - Each token is either:
      * `<int>`            -> episode in the same season as the mapping CSV
      * `S<MM>-<int>`      -> episode in season MM (zero-padded or not)
  - Order in list = order in file (allows out-of-order labelling).
  - Empty list -> file should be skipped.

Examples (mapping_s5.csv):
  '1,2'            -> [(5,1), (5,2)]
  'S00-1'          -> [(0,1)]
  'S03-3,4'        -> [(3,3), (3,4)]   # both stay in S03
  '32,S05-10'      -> [(4,32), (5,10)]  # file's mapping is in S4
  'S07-9,S05-31'   -> [(7,9), (5,31)]
  '10,9'           -> [(5,10), (5,9)]   # out-of-order
"""

from __future__ import annotations

import re


_TOKEN_RE = re.compile(r"^\s*(?:S(\d{1,2})-)?(\d{1,3})\s*$")


def parse_actual_episodes(
    text: str, default_season: int
) -> list[tuple[int, int]]:
    text = (text or "").strip()
    if not text:
        return []
    out: list[tuple[int, int]] = []
    last_season = default_season
    for raw in text.split(","):
        m = _TOKEN_RE.match(raw)
        if not m:
            raise ValueError(
                f"unparseable actual_episodes token: {raw!r} in {text!r}"
            )
        s_str, e_str = m.groups()
        # User said: "Usually if a season is specified, keep that season
        # for both episodes". Implement by remembering the most recent
        # explicit season prefix within this token list.
        if s_str is not None:
            last_season = int(s_str)
        out.append((last_season, int(e_str)))
    return out


if __name__ == "__main__":
    cases = [
        ("1,2", 5, [(5, 1), (5, 2)]),
        ("S00-1", 2, [(0, 1)]),
        ("S03-3,4", 2, [(3, 3), (3, 4)]),
        ("32,S05-10", 4, [(4, 32), (5, 10)]),
        ("S07-9,S05-31", 5, [(7, 9), (5, 31)]),
        ("10,9", 5, [(5, 10), (5, 9)]),
        ("", 5, []),
        ("S00-11", 5, [(0, 11)]),
    ]
    for text, default, expected in cases:
        got = parse_actual_episodes(text, default)
        assert got == expected, f"{text!r}: expected {expected}, got {got}"
    print("OK")
