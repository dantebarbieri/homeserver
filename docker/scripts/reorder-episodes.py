#!/usr/bin/env python3
"""Renumber a show's files into a pinned custom order, by title, never by input numbering.

The order file (see episode-orders/) maps each target SxxExx to a TheTVDB episode
ID and an authoritative title. Every video needs a same-stem NFO whose <title>
identifies it; a TVDB <uniqueid> in that NFO must agree with the order file.

Run on the server (no system python; use nix-shell):
    nix-shell -p python3 --run 'python3 docker/scripts/reorder-episodes.py \\
        docker/scripts/episode-orders/kim-possible.json [--apply --backup DIR]'
    nix-shell -p python3 --run 'python3 docker/scripts/reorder-episodes.py \\
        --restore DIR/manifest.json'
"""

import argparse
import json
import os
import re
import tempfile
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path


VIDEO_EXTENSIONS = {".mkv", ".mp4", ".m4v", ".avi", ".ts"}
EPISODE_NUMBER = re.compile(r"S\d{1,2}E\d{1,3}(?!\d)", re.IGNORECASE)
SLOT = re.compile(r"S(\d{2})E(\d{2,3})")


def normalize(title):
    text = unicodedata.normalize("NFKD", title).casefold()
    return "".join(c for c in text if c.isascii() and c.isalnum())


def load_order(path):
    """-> (order document, {normalized title: (season, episode, title, tvdb_id)})."""
    order = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = {}
    tvdb_ids = set()
    for slot, entry in order["episodes"].items():
        match = SLOT.fullmatch(slot)
        if not match:
            raise ValueError(f"Bad slot in order file: {slot}")
        identity = normalize(entry["title"])
        if identity in targets or entry["tvdb"] in tvdb_ids:
            raise ValueError(f"Duplicate episode in order file: {slot}")
        tvdb_ids.add(entry["tvdb"])
        targets[identity] = (
            int(match[1]), int(match[2]), entry["title"], entry["tvdb"]
        )
    return order, targets


def plan(source, targets):
    source = source.resolve()
    videos = sorted(
        p for p in source.glob("*/*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    )
    found = {}
    operations = []
    plex_episodes = []
    for video in videos:
        if video.is_symlink() or video.parent.is_symlink():
            raise ValueError(f"Refusing symlink: {video}")
        nfo = video.with_suffix(".nfo")
        root = ET.parse(nfo).getroot()
        title = root.findtext("title")
        if not title or normalize(title) not in targets:
            raise ValueError(f"Unknown episode title in {nfo}: {title!r}")
        identity = normalize(title)
        if identity in found:
            raise ValueError(f"Duplicate episode: {video} and {found[identity]}")
        found[identity] = video
        season, episode, canonical, tvdb_id = targets[identity]
        for node in root.findall("uniqueid"):
            if node.get("type") == "tvdb" and node.text and node.text.strip() != str(tvdb_id):
                raise ValueError(
                    f"TVDB ID {node.text.strip()} in {nfo} disagrees with "
                    f"{canonical!r} ({tvdb_id}) in the order file"
                )
        match = EPISODE_NUMBER.search(video.stem)
        if not match:
            raise ValueError(f"No episode number: {video}")
        # A combined episode needs an explicit split, not a partial renumber.
        if re.match(r"(?:E\d+|-E?\d+)", video.stem[match.end():], re.IGNORECASE):
            raise ValueError(f"Split combined episode before ordering: {video}")
        new_stem = EPISODE_NUMBER.sub(
            f"S{season:02d}E{episode:02d}", video.stem, count=1
        )
        folder = f"Season {season:02d}" if season else "Specials"
        target_video = source / folder / (new_stem + video.suffix)
        plex_number = f"S{season:02d}E{episode:02d}" if season else f"SP{episode:02d}"
        plex_episodes.append((
            season, episode,
            f"Episode: {plex_number}: {target_video.relative_to(source).as_posix()}",
        ))
        for path in sorted(video.parent.iterdir()):
            if not (
                path.name == video.name
                or path.name.startswith(video.stem + ".")
                or (
                    path.stem == video.stem + "-thumb"
                    and path.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
                )
            ):
                continue
            if path.is_symlink() or not path.is_file():
                raise ValueError(f"Refusing non-regular sidecar: {path}")
            suffix = path.name[len(video.stem):]
            target = source / folder / (new_stem + suffix)
            content = None
            if path == nfo:
                for tag, value in [
                    ("title", canonical), ("season", str(season)),
                    ("episode", str(episode)), ("lockdata", "true"),
                ]:
                    node = root.find(tag)
                    if node is None:
                        node = ET.SubElement(root, tag)
                    node.text = value
                for tag in ("displayseason", "displayepisode"):
                    for node in root.findall(tag):
                        root.remove(node)
                content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
            if path != target or (content is not None and path.read_bytes() != content):
                operations.append((path, target, content))
    missing = set(targets) - set(found)
    if missing:
        raise ValueError("Missing episodes: " + ", ".join(
            targets[identity][2] for identity in sorted(missing)
        ))
    plexmatch = source / ".plexmatch"
    if plexmatch.exists():
        if plexmatch.is_symlink() or not plexmatch.is_file():
            raise ValueError(f"Refusing non-regular Plex match file: {plexmatch}")
        lines = [
            line for line in plexmatch.read_text(encoding="utf-8").splitlines()
            if not line.lower().startswith("episode:")
        ]
        lines.extend(line for _, _, line in sorted(plex_episodes))
        content = ("\n".join(lines) + "\n").encode("utf-8")
        if plexmatch.read_bytes() != content:
            operations.append((plexmatch, plexmatch, content))
    old_paths = {old for old, _, _ in operations}
    destinations = set()
    for old, new, _ in operations:
        if new in destinations or (new.exists() and new not in old_paths):
            raise ValueError(f"Destination already occupied: {new}")
        destinations.add(new)
    return operations


def fingerprint(path):
    stat = path.stat()
    return [stat.st_ino, stat.st_size, stat.st_mtime_ns]


def write_json(path, data):
    temporary = path.with_suffix(".tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def apply(source, backup, operations):
    source = source.resolve()
    backup = backup.resolve()
    if backup == source or source in backup.parents:
        raise ValueError("Backup must be outside the show directory")
    backup.mkdir(parents=True, exist_ok=False)
    journal = {"source": str(source), "state": "prepared", "files": []}
    for number, (old, new, content) in enumerate(operations):
        saved = backup / str(number)
        os.link(old, saved)
        journal["files"].append({
            "old": str(old.relative_to(source)),
            "new": str(new.relative_to(source)),
            "backup": saved.name,
        })
    manifest = backup / "manifest.json"
    write_json(manifest, journal)
    created = []
    removed = []
    try:
        for old, _, _ in operations:
            old.unlink()
            removed.append(old)
        for number, (_, new, content) in enumerate(operations):
            new.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                os.link(backup / str(number), new)
                created.append(new)
            else:
                with new.open("xb") as handle:
                    created.append(new)
                    handle.write(content)
    except OSError:
        for new in reversed(created):
            new.unlink()
        for entry in journal["files"]:
            old = source / entry["old"]
            if old in removed:
                os.link(backup / entry["backup"], old)
        raise
    for entry in journal["files"]:
        entry["fingerprint"] = fingerprint(source / entry["new"])
    journal["state"] = "applied"
    write_json(manifest, journal)
    return manifest


def restore(manifest):
    journal = json.loads(manifest.read_text())
    if journal["state"] != "applied":
        raise ValueError("Only a successfully applied journal can be restored")
    source = Path(journal["source"])
    current = {source / entry["new"] for entry in journal["files"]}
    for entry in journal["files"]:
        path = source / entry["new"]
        if fingerprint(path) != entry["fingerprint"]:
            raise ValueError(f"File changed since ordering: {path}")
        old = source / entry["old"]
        if old.exists() and old not in current:
            raise ValueError(f"Original destination is occupied: {old}")
        if not (manifest.parent / entry["backup"]).is_file():
            raise ValueError(f"Missing backup for {old}")
    with tempfile.TemporaryDirectory(prefix=".reorder-restore-", dir=manifest.parent) as tmp:
        saved = Path(tmp)
        for number, entry in enumerate(journal["files"]):
            os.link(source / entry["new"], saved / str(number))
        removed = []
        created = []
        try:
            for entry in journal["files"]:
                path = source / entry["new"]
                path.unlink()
                removed.append(path)
            for entry in journal["files"]:
                path = source / entry["old"]
                path.parent.mkdir(parents=True, exist_ok=True)
                os.link(manifest.parent / entry["backup"], path)
                created.append(path)
        except OSError:
            for path in reversed(created):
                path.unlink()
            for number, entry in enumerate(journal["files"]):
                path = source / entry["new"]
                if path in removed:
                    os.link(saved / str(number), path)
            raise
    journal["state"] = "restored"
    write_json(manifest, journal)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("order", type=Path, nargs="?", help="episode order JSON")
    parser.add_argument("--source", type=Path,
                        help="show directory (default: the order file's path)")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--restore", type=Path, metavar="MANIFEST")
    args = parser.parse_args()
    if args.restore:
        if args.order or args.source or args.apply or args.backup:
            parser.error("--restore takes only the manifest")
        restore(args.restore)
        print("Restored original filenames and sidecar contents.")
        return
    if not args.order:
        parser.error("an order file is required unless --restore is used")
    order, targets = load_order(args.order)
    source = args.source or Path(order["path"])
    operations = plan(source, targets)
    for old, new, content in operations:
        print(f"{old.name} -> {new.parent.name}/{new.name}"
              + (" [update]" if content is not None else ""))
    if args.apply:
        if not args.backup:
            parser.error("--apply requires a new --backup directory")
        if operations:
            print("Undo manifest:", apply(source, args.backup, operations))
        else:
            print("Already in the pinned order; nothing changed.")
    else:
        print(f"Preview only: {len(operations)} operations; no files changed.")


if __name__ == "__main__":
    main()
