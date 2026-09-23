#!/usr/bin/env python3
"""Store tags and collections for a product.

Collections on the live store are smart rules ("type equals X", "tag equals age:3-5",
"variant_price less_than 2500 AND type not_equals Add-on"). Rather than guessing which
collections a product lands in, this evaluates those rules from the shop's own export,
so the CSV's `collections` column is what Shopify will compute.

    python store_taxonomy.py --type "Cars & Vehicles" --tags age:5-8 occasion:eid --price 1499
"""

import argparse
import csv
import os
import re
import sys

COLLECTIONS_CSV = os.environ.get("STORE_COLLECTIONS_CSV",
                                 os.path.expanduser("~/Downloads/collections.csv"))
RULE = re.compile(r'(\w+)\s+(equals|not_equals|less_than|greater_than)\s+"([^"]*)"')

# category -> (play tag, default subcategory). Play tags are the store's own five.
PLAY_SUB = {
    "Cars & Vehicles": ("vehicles", "Die-Cast Cars"),
    "RC & Remote Control Toys": ("vehicles", "RC Vehicles"),
    "Scooters, Bikes & Tricycles": ("outdoor", "Ride-Ons"),
    "Outdoor Toys": ("outdoor", "Outdoor Play"),
    "Water & Beach Toys": ("outdoor", "Water Play"),
    "Sports Toys": ("outdoor", "Sports Sets"),
    "Board Games": ("games", "Family Board Games"),
    "Card & Tabletop Games": ("games", "Card Games"),
    "Puzzles": ("games", "Puzzles"),
    "Building & Construction Toys": ("build", "Building Blocks"),
    "STEM & Science Toys": ("build", "STEM Kits"),
    "Educational Toys": ("build", "Learning Toys"),
    "Baby & Toddler Toys": ("pretend", "Baby Toys"),
    "Pretend Play & Role Play": ("pretend", "Role Play Sets"),
    "Dolls & Doll Play": ("pretend", "Fashion Dolls"),
    "Doll Houses & Pretend Homes": ("pretend", "Doll Houses"),
    "Baby Care & Pretend Accessories": ("pretend", "Pretend Accessories"),
    "Arts, Crafts & Creative Toys": ("build", "Art Sets"),
    "Musical Toys": ("pretend", "Musical Instruments"),
    "Plush & Stuffed Toys": ("pretend", "Plush Toys"),
    "Animal & Dinosaur Toys": ("pretend", "Animal Figures"),
    "Action Figures & Characters": ("pretend", "Action Figures"),
    "Robots & Electronic Toys": ("games", "Electronic Toys"),
    "Sensory & Fidget Toys": ("games", "Fidget Toys"),
    "Novelty & Fun Toys": ("games", "Novelty Toys"),
    "Fantasy & Magic Toys": ("pretend", "Magic & Dress-Up"),
    "Party Toys & Favors": ("games", "Party Favours"),
    "Collectibles & Miniatures": ("vehicles", "Collectibles"),
    "Dress-Up & Costumes": ("pretend", "Dress-Up"),
    "Battle & Action Play": ("games", "Battle Play"),
    "Ride-On Toys": ("outdoor", "Ride-Ons"),
    "Building & Construction Toys": ("build", "Building Blocks"),
    "Drinkware": ("games", "Tumblers"),      # gift item, not a toy — kept out of the age collections
}
NON_TOY_TYPES = {"Drinkware", "Add-on"}
# a more specific subcategory (and sometimes a better type) when the wording is clear.
# (regex over the product name + what the photos show) -> (subcategory, type override or None)
SUB_OVERRIDES = [
    (r"refrigerator|fridge|washing machine|vacuum|kettle|\biron\b|dishwasher|hand mixer|appliance",
     ("Mini Appliances", "Pretend Play & Role Play")),
    (r"cleaning kit|mop|broom|little helper", ("Cleaning Play Sets", "Pretend Play & Role Play")),
    (r"makeup|cosmetic|nail polish|vanity|hair styling|beauty", ("Makeup Sets", "Pretend Play & Role Play")),
    (r"arcade|pinball|claw game|power punch|hammer game|shooting machine|handheld game|game console",
     ("Arcade Games", "Robots & Electronic Toys")),
    (r"bubble", ("Bubble Toys", "Outdoor Toys")),
    (r"squishy|squish|mochi|fidget|squeeze", ("Squishies", "Sensory & Fidget Toys")),
    (r"night light|lamp", ("Night Lights", "Novelty & Fun Toys")),
    (r"neck fan|\bfan\b", ("Gadgets", "Novelty & Fun Toys")),
    (r"tumbler|travel mug|insulated mug|sipper", ("Tumblers", "Drinkware")),
    (r"lego|duplo|mega bloks|brick", ("Brick Sets", "Building & Construction Toys")),
    (r"building block|block building|blocks set|block set|magnetic block|magnetic world|construction set",
     ("Building Blocks", "Building & Construction Toys")),
    (r"swimming pool|inflatable pool|kiddie pool|paddling pool|\bpool\b", ("Pools", "Water & Beach Toys")),
    (r"goggle|swim cap|swim ring|snorkel|armband", ("Swim Gear", "Water & Beach Toys")),
    (r"goggle|swim ring|float\b|armband|snorkel", ("Swim Gear", "Water & Beach Toys")),
    (r"diecast|die-cast|model car", ("Die-Cast Cars", None)),
    (r"\brc\b|remote control", ("RC Vehicles", "RC & Remote Control Toys")),
    (r"drone|quadcopter", ("Drones", "RC & Remote Control Toys")),
    (r"busy board|montessori|stacker|activity", ("Baby Activity Toys", "Baby & Toddler Toys")),
    (r"piano|xylophone|keyboard|drum", ("Musical Instruments", "Musical Toys")),
    (r"art set|painting|drawing|marker|crayon|colou?ring", ("Art Sets", "Arts, Crafts & Creative Toys")),
    (r"action figure|figurine", ("Action Figures", "Action Figures & Characters")),
    (r"dinosaur|dino\b", ("Dinosaur Toys", "Animal & Dinosaur Toys")),
    (r"plush|stuffed|teddy", ("Plush Toys", "Plush & Stuffed Toys")),
]


def refine(category, name, items=()):
    """A closer category + subcategory. The name is checked first; photo labels only
    refine when the name says nothing, so one mislabelled photo can't move a product."""
    for text in (name.lower(), " ".join(items).lower()):
        for pattern, (sub, cat) in SUB_OVERRIDES:
            if re.search(pattern, text):
                return (cat or category), sub
    return category, PLAY_SUB.get(category, ("games", ""))[1]


# Most boxes here print no age at all. Rather than leave the column empty (which drops the
# product out of every age collection), fall back to the minimum age the kind of toy implies —
# small parts, batteries and the skill it takes to use it. A printed age always wins.
DEFAULT_AGE_BY_SUB = {
    "Baby Toys": "18M+", "Baby Activity Toys": "18M+", "Plush Toys": "18M+",
    "Drones": "8+", "RC Vehicles": "5+", "Brick Sets": "6+", "STEM Kits": "8+",
    "Collectibles": "8+", "Arcade Games": "5+", "Battle Play": "5+",
    "Family Board Games": "5+", "Card Games": "5+", "Puzzles": "3+",
    "Swim Gear": "3+", "Pools": "3+",
}
DEFAULT_AGE_BY_TYPE = {
    "Baby & Toddler Toys": "18M+", "Plush & Stuffed Toys": "18M+",
    "RC & Remote Control Toys": "5+", "Board Games": "5+", "Card & Tabletop Games": "5+",
    "Battle & Action Play": "5+", "STEM & Science Toys": "8+",
    "Collectibles & Miniatures": "8+", "Scooters, Bikes & Tricycles": "5+",
    "Ride-On Toys": "18M+",
}
DEFAULT_AGE = "3+"      # small parts and batteries: the floor for everything else


def default_age(category, sub=None):
    """The minimum age a product of this kind is sold at, when the box doesn't print one.
    Non-toys (drinkware, add-ons) carry no age tag at all."""
    if category in NON_TOY_TYPES:
        return ""
    return DEFAULT_AGE_BY_SUB.get(sub or "") or DEFAULT_AGE_BY_TYPE.get(category) or DEFAULT_AGE


AGE_BUCKETS = [(0, 1, "0-1"), (1, 3, "1-3"), (3, 5, "3-5"), (5, 8, "5-8"), (8, 99, "8+")]


def age_tag(printed):
    """'18M+' / '3+' / 'ages 5-8' as printed on the box -> the store's age bucket."""
    if not printed:
        return None
    text = printed.lower().replace("years", "").replace("yrs", "")
    months = re.search(r"(\d+)\s*m", text)
    if months and "month" in text or (months and int(months.group(1)) >= 12 and "m+" in text):
        years = int(months.group(1)) / 12
    else:
        nums = [int(n) for n in re.findall(r"\d+", text)]
        if not nums:
            return None
        years = nums[0]
    for lo, hi, tag in AGE_BUCKETS:
        if lo <= years < hi:
            return f"age:{tag}"
    return "age:8+"


def tags_for(category, *, printed_age="", gender="", occasions=("birthday", "eid"),
             features=("new", "gift-ready"), extra_categories=(), sub=None):
    play, default_sub = PLAY_SUB.get(category, ("games", ""))
    sub = sub or default_sub
    tags = [f"play:{play}"]
    if sub:
        tags.append(f"sub:{sub}")
    a = age_tag(printed_age or default_age(category, sub)) if category not in NON_TOY_TYPES else None
    if a:
        tags.append(a)
    tags += [f"occasion:{o}" for o in occasions]
    tags += [f"feature:{f}" for f in features]
    if gender in ("boys", "girls"):
        tags.append(f"gender:{gender}")
    for c in extra_categories:                  # a second category, ready for a tag-based rule
        tags.append("type:" + re.sub(r"[^a-z0-9]+", "-", c.lower()).strip("-"))
    return sorted(set(tags))


def load_collections(path=COLLECTIONS_CSV):
    rows = []
    with open(path, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["type"] == "smart" and r["rule"]:
                rows.append((r["handle"], r["title"], RULE.findall(r["rule"])))
    return rows


def collections_for(category, tags, price=None, collections=None):
    """Handles this product lands in. Price rules are skipped while price is unknown."""
    out, skipped = [], []
    for handle, _title, rules in (collections if collections is not None else load_collections()):
        ok, needs_price = True, False
        for field, op, value in rules:
            if field == "type":
                got = category
            elif field == "tag":
                got = value if value in tags else ""
            elif field == "variant_price":
                needs_price = True
                if price is None:
                    continue
                got = float(price)
                ok = ok and ((op == "less_than" and got < float(value)) or
                             (op == "greater_than" and got > float(value)))
                continue
            elif field == "vendor":
                got = ""
            else:
                got = ""
            ok = ok and ((op == "equals" and got == value) or (op == "not_equals" and got != value))
        if ok and needs_price and price is None:
            skipped.append(handle)
        elif ok:
            out.append(handle)
    return sorted(out), sorted(skipped)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", required=True)
    ap.add_argument("--tags", nargs="*", default=[])
    ap.add_argument("--price", type=float)
    args = ap.parse_args()
    got, pending = collections_for(args.type, args.tags, args.price)
    print("tags:       ", ", ".join(args.tags))
    print("collections:", ", ".join(got))
    if pending:
        print("price-based (once you set a price):", ", ".join(pending))
    return 0


if __name__ == "__main__":
    sys.exit(main())
