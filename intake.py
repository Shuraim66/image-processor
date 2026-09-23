#!/usr/bin/env python3
"""Group an unsorted pile of photos into per-product folders.

Drop a whole shoot into one directory and this proposes which photos belong to
which product, so you never create a folder or rename a file by hand.

Grouping is by capture time. Measured against a hand-checked 28-photo shoot,
the capture-time gap found 6 of 7 product boundaries; asking the VLM whether two
photos showed the same item scored 2 of 6, and a cheap visual distance 3 of 5.
Neither was worth its cost, and both failed in the dangerous direction — merging
two different products. Time only ever fails the *safe* way: it splits one
product in two when you paused mid-shoot, which `--merge` fixes in one flag and
the contact sheet makes obvious.

Phones frequently save the same shot twice under two names (e.g. a HEIC that
got converted to both `IMG_1234.jpg` and `IMG_1234.jpg.jpeg`), so files are
deduplicated by content before clustering — otherwise every shot would count,
and get copied, twice.

So this proposes and you confirm; it writes nothing without --apply.

    python intake.py raw_footages/
    python intake.py raw_footages/ --apply --merge 4,5 --name 1=TUMBLER-MOCHA
"""

import argparse
import datetime
import hashlib
import os
import re
import shutil
import sys

from PIL import Image, ImageDraw

VALID = (".jpg", ".jpeg", ".png", ".webp", ".heic")

# A pause longer than this between shots reads as "moved on to the next product".
# Within a product the gaps ran 3-40 s; between products, 70-133 s.
DEFAULT_GAP = 60

# IMG_20260825_223945.jpg and friends — a filename timestamp is as trustworthy as
# EXIF here and survives the re-encoding that strips EXIF.
NAME_TS = re.compile(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})[-_ ]?(\d{2})[-_.]?(\d{2})[-_.]?(\d{2})")


def photo_time(path):
    """Capture time: EXIF first, then the filename, then the file's own mtime."""
    try:
        exif = Image.open(path).getexif()
        for tag in (36867, 36868, 306):        # DateTimeOriginal, Digitized, ModifyDate
            if exif.get(tag):
                return datetime.datetime.strptime(str(exif[tag]), "%Y:%m:%d %H:%M:%S")
    except Exception:                          # noqa: BLE001 — unreadable EXIF is normal
        pass
    m = NAME_TS.search(os.path.basename(path))
    if m:
        try:
            return datetime.datetime(*(int(g) for g in m.groups()))
        except ValueError:
            pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(path))


def _content_hash(path, chunk=1 << 16):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def discover(folder):
    """Every unique photo in `folder`, oldest first.

    A phone-exported shoot often has the same photo saved twice under two
    names (`IMG_1234.jpg` and `IMG_1234.jpg.jpeg` are byte-identical here);
    those collapse to a single shot, keeping the shorter/first name.
    """
    if not os.path.isdir(folder):
        raise FileNotFoundError(f"'{folder}' is not a directory")
    paths = sorted(
        p for p in (os.path.join(folder, f) for f in os.listdir(folder))
        if os.path.isfile(p) and p.lower().endswith(VALID))
    seen = {}
    for p in paths:
        seen.setdefault(_content_hash(p), p)
    shots = [(photo_time(p), p) for p in seen.values()]
    return sorted(shots)


def cluster(shots, gap=DEFAULT_GAP):
    """Split the shot list wherever the camera sat idle longer than `gap`."""
    groups, current, prev = [], [], None
    for when, path in shots:
        if prev is not None and (when - prev).total_seconds() > gap:
            groups.append(current)
            current = []
        current.append((when, path))
        prev = when
    if current:
        groups.append(current)
    return groups


def merge(groups, pairs):
    """Fold the listed 1-based group numbers into their lower-numbered neighbour."""
    absorbed = set()
    for a, b in pairs:
        for n in (a, b):
            if not 1 <= n <= len(groups):
                raise ValueError(f"--merge names group {n}, but there are {len(groups)}")
        absorbed.add(max(a, b))
        groups[min(a, b) - 1] = groups[min(a, b) - 1] + groups[max(a, b) - 1]
    return [g for i, g in enumerate(groups, 1) if i not in absorbed]


def contact_sheet(groups, out_path, thumb=190):
    """One row per proposed product, so an over-split is visible at a glance."""
    cols = max(len(g) for g in groups)
    head = 26
    sheet = Image.new("RGB", (cols * thumb, len(groups) * (thumb + head)), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    for row, group in enumerate(groups):
        y = row * (thumb + head)
        draw.rectangle([0, y, sheet.width, y + head - 1], fill=(238, 240, 244))
        draw.text((6, y + 7), f"group {row + 1}  ({len(group)} photos)", fill=(20, 22, 30))
        for col, (_, path) in enumerate(group):
            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail((thumb - 8, thumb - 8), Image.LANCZOS)
                sheet.paste(im, (col * thumb + (thumb - im.width) // 2, y + head + 2))
    sheet.save(out_path)
    return out_path


def apply(groups, names, dest, overwrite=False):
    """Copy each group into dest/<name>/ as front.jpg, angle2.jpg, …

    Copies rather than moves: the shoot folder stays untouched, so a wrong
    grouping costs a re-run and not the photos.
    """
    from process_products import store_sku
    written = []
    for i, group in enumerate(groups, 1):
        sku = store_sku(names[i]) if i in names else f"UNNAMED-{i:02d}"
        folder = os.path.join(dest, sku)
        if os.path.isdir(folder) and os.listdir(folder) and not overwrite:
            raise FileExistsError(
                f"'{folder}' already has photos in it. Pass --overwrite to replace them, "
                f"or give this group another name with --name {i}=SKU")
        os.makedirs(folder, exist_ok=True)
        if overwrite:
            for old in os.listdir(folder):
                if old.lower().endswith(VALID):
                    os.remove(os.path.join(folder, old))
        for n, (_, path) in enumerate(group):
            ext = os.path.splitext(path)[1].lower()
            name = f"front{ext}" if n == 0 else f"angle{n + 1}{ext}"
            shutil.copy2(path, os.path.join(folder, name))
        written.append((sku, len(group)))
    return written


def _pairs(values):
    out = []
    for v in values or []:
        try:
            a, b = (int(x) for x in v.split(","))
        except ValueError:
            raise SystemExit(f"--merge wants two group numbers like 4,5 (got '{v}')")
        out.append((a, b))
    return out


def _names(values):
    out = {}
    for v in values or []:
        if "=" not in v:
            raise SystemExit(f"--name wants <group>=<SKU> like 1=TUMBLER-MOCHA (got '{v}')")
        n, sku = v.split("=", 1)
        try:
            out[int(n)] = sku.strip()
        except ValueError:
            raise SystemExit(f"--name wants a group number before '=' (got '{n}')")
    return out


def main():
    ap = argparse.ArgumentParser(
        description="Group an unsorted shoot into per-product folders under input/.")
    ap.add_argument("folder", help="directory holding the unsorted photos")
    ap.add_argument("--gap", type=int, default=DEFAULT_GAP, metavar="SECONDS",
                    help=f"idle time that separates two products (default {DEFAULT_GAP})")
    ap.add_argument("--merge", action="append", metavar="A,B",
                    help="treat groups A and B as one product; repeatable")
    ap.add_argument("--name", action="append", metavar="N=SKU",
                    help="name group N; repeatable. Unnamed groups become UNNAMED-nn")
    ap.add_argument("--sheet", default=None, metavar="PATH",
                    help="where to write the contact sheet (default <folder>/_proposal.png)")
    ap.add_argument("--no-sheet", action="store_true", help="skip the contact sheet")
    ap.add_argument("--dest", default="input", metavar="DIR",
                    help="where product folders are created (default input/)")
    ap.add_argument("--apply", action="store_true",
                    help="actually create the folders (without this, nothing is written)")
    ap.add_argument("--overwrite", action="store_true",
                    help="replace photos in a destination folder that already has some")
    args = ap.parse_args()

    try:
        shots = discover(args.folder)
    except FileNotFoundError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if not shots:
        print(f"No photos in '{args.folder}'.", file=sys.stderr)
        return 1

    groups = cluster(shots, args.gap)
    try:
        groups = merge(groups, _pairs(args.merge))
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    names = _names(args.name)

    print(f"{len(shots)} unique photo(s) -> {len(groups)} product(s), "
          f"splitting on gaps over {args.gap}s\n")
    for i, group in enumerate(groups, 1):
        sku = names.get(i, f"UNNAMED-{i:02d}")
        span = (group[-1][0] - group[0][0]).total_seconds()
        print(f"  {i:2d}. {sku:24s} {len(group)} photos  {group[0][0]:%Y-%m-%d %H:%M:%S}+{span:.0f}s")
        for n, (_, path) in enumerate(group):
            role = "front" if n == 0 else f"angle{n + 1}"
            print(f"        {role:7s} {os.path.basename(path)}")

    if not args.no_sheet:
        sheet = args.sheet or os.path.join(args.folder, "_proposal.png")
        try:
            print(f"\nContact sheet: {contact_sheet(groups, sheet)}")
        except Exception as exc:  # noqa: BLE001 — a sheet is a convenience, not the job
            print(f"\n! could not write the contact sheet ({exc})", file=sys.stderr)

    if not args.apply:
        print("\nNothing written. Check the grouping, then re-run with --apply.")
        print("A product split across two groups? Add --merge 4,5 (repeatable).")
        print("front.jpg is the leftmost photo of each row; if that row opens on a "
              "packaging shot, rename the files after applying.")
        return 0

    try:
        written = apply(groups, names, args.dest, args.overwrite)
    except FileExistsError as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        return 1
    print()
    for sku, n in written:
        print(f"  {args.dest}/{sku}/  {n} photos")
    unnamed = [s for s, _ in written if s.startswith("UNNAMED-")]
    if unnamed:
        print(f"\n! {len(unnamed)} folder(s) still unnamed: {', '.join(unnamed)}",
              file=sys.stderr)
        print("  The folder name becomes the SKU and reaches the Shopify CSV. Rename them, "
              "or re-run with --name.", file=sys.stderr)
    print("\nNext: python3 analyzer.py --all, then "
          "python3 gallery_pipeline.py --bg-provider fal --per-product")
    return 0


if __name__ == "__main__":
    sys.exit(main())
