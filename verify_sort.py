#!/usr/bin/env python3
"""Catch same-template mix-ups that a timestamp-only sort can't see.

intake.py groups by capture-time gaps, which is blind to content: two products
shot back-to-back read the same to it, and two different products that share a
manufacturer's box template (same layout, same age circle, same mascot — only
the printed subtitle differs) look identical to a human doing a quick glance
too. This asks the local vision model what product name/title is actually
printed in each photo, then flags any folder where that text disagrees.

    python verify_sort.py                  # scan input/, report only
    python verify_sort.py --apply           # also auto-split clear-cut cases
    OLLAMA_VLM=qwen3-vl:8b-instruct-q4_K_M python verify_sort.py

Findings are cached to --cache (default verify_cache.json) so a re-run only
processes new/changed photos — safe to stop and resume on a large catalog.

--apply only ever splits a folder into two (never merges, never guesses a
name) — a clean split just needs the boundary between two different printed
titles, which auto-splitting can't get more wrong than leaving it alone would.
Ambiguous cases (three+ texts, or a title that only shows up once) are always
left for --apply to skip and the report to flag.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

import ollama

INPUT_DIR = "input"
CACHE_PATH = "verify_cache.json"
MODEL = os.environ.get("OLLAMA_VLM", "qwen3-vl:8b-instruct-q4_K_M")
VALID = (".jpg", ".jpeg", ".png", ".webp")
SKIP_NO_INTAKE_RECORD = True  # folders with no product.json AND no raw_footages

PROMPT = (
    "Look at this single product photo. If it shows retail packaging/box with a "
    "product name, title, or series name printed on it, reply with ONLY that "
    "exact printed text (as short as possible). If it shows the unboxed product "
    "with no legible product name/title text visible anywhere, reply with "
    "exactly: NONE"
)


def file_hash(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def load_cache(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_cache(path, cache):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, indent=2)


def extract_text(path, cache):
    key = file_hash(path)
    if key in cache:
        return cache[key]
    try:
        resp = ollama.chat(
            model=MODEL,
            messages=[{"role": "user", "content": PROMPT, "images": [path]}],
            options={"temperature": 0.1, "num_ctx": 4096},
        )
        text = resp["message"]["content"].strip()
    except Exception as exc:  # noqa: BLE001 — keep the scan alive
        text = f"__ERROR__:{exc}"
    cache[key] = text
    return text


def normalize(text):
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def same_title(a, b):
    """Loose match: most words in the shorter title appear in the longer one.

    Tolerates the model paraphrasing the same printed text slightly
    differently between photos (case, punctuation, a dropped word) without
    tolerating a genuinely different product name.
    """
    wa, wb = set(normalize(a).split()), set(normalize(b).split())
    if not wa or not wb:
        return False
    shorter, longer = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    overlap = len(shorter & longer) / len(shorter)
    return overlap >= 0.6


def cluster_texts(texts):
    """Group a list of (filename, text) into distinct-title clusters, NONE ignored."""
    clusters = []  # list of {"title": str, "files": [...]}
    for fn, text in texts:
        if text == "NONE" or text.startswith("__ERROR__"):
            continue
        for c in clusters:
            if same_title(c["title"], text):
                c["files"].append(fn)
                break
        else:
            clusters.append({"title": text, "files": [fn]})
    return clusters


def scan(input_dir, cache):
    folders = sorted(d for d in os.listdir(input_dir) if os.path.isdir(os.path.join(input_dir, d)))
    flagged = []
    for i, d in enumerate(folders, 1):
        dpath = os.path.join(input_dir, d)
        photos = sorted(f for f in os.listdir(dpath) if f.lower().endswith(VALID))
        if not photos:
            continue
        texts = []
        for fn in photos:
            text = extract_text(os.path.join(dpath, fn), cache)
            texts.append((fn, text))
        save_cache(CACHE_PATH, cache)
        clusters = cluster_texts(texts)
        print(f"[{i}/{len(folders)}] {d}: {len(photos)} photos, "
              f"{len(clusters)} distinct title(s)" + (" *** MISMATCH ***" if len(clusters) > 1 else ""))
        if len(clusters) > 1:
            flagged.append((d, clusters))
    return flagged


def apply_split(input_dir, flagged):
    """Auto-split only the unambiguous case: exactly 2 title clusters, each
    with 2+ supporting photos (one photo of noise isn't enough evidence)."""
    applied, skipped = [], []
    for d, clusters in flagged:
        if len(clusters) != 2 or min(len(c["files"]) for c in clusters) < 2:
            skipped.append((d, "not a clean 2-way split — needs manual review"))
            continue
        dpath = os.path.join(input_dir, d)
        keep, move = sorted(clusters, key=lambda c: -len(c["files"]))
        new_dir = os.path.join(input_dir, f"{d}__SPLIT-REVIEW-{normalize(move['title'])[:20].replace(' ', '-')}")
        os.makedirs(new_dir, exist_ok=True)
        moved_files = set()
        for fn in move["files"]:
            src = os.path.join(dpath, fn)
            if not os.path.exists(src):
                continue
            shutil.move(src, os.path.join(new_dir, fn))
            moved_files.add(fn)
        applied.append((d, new_dir, moved_files))
    return applied, skipped


def main():
    global CACHE_PATH
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=INPUT_DIR, help="folder of product folders to verify (default input/)")
    ap.add_argument("--cache", default=CACHE_PATH, help="extraction cache path (default verify_cache.json)")
    ap.add_argument("--apply", action="store_true",
                    help="auto-split unambiguous 2-title mismatches into a *__SPLIT-REVIEW-* folder")
    args = ap.parse_args()
    CACHE_PATH = args.cache
    cache = load_cache(CACHE_PATH)

    flagged = scan(args.dir, cache)

    print(f"\n{len(flagged)} folder(s) flagged with disagreeing printed titles.\n")
    for d, clusters in flagged:
        print(f"  {d}:")
        for c in clusters:
            print(f"    \"{c['title']}\" -> {c['files']}")

    if not flagged:
        print("Nothing to do.")
        return 0

    if not args.apply:
        print("\nRe-run with --apply to auto-split the unambiguous (exactly 2 titles, "
              "2+ photos each) cases. Everything else needs a manual look.")
        return 0

    applied, skipped = apply_split(args.dir, flagged)
    print("\nApplied:")
    for d, new_dir, files in applied:
        print(f"  {d}: moved {sorted(files)} -> {new_dir}/ (rename both folders once you confirm the split)")
    if skipped:
        print("\nSkipped (needs manual review):")
        for d, reason in skipped:
            print(f"  {d}: {reason}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
