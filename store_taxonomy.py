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

# store_collections.csv is built by build_collections.py from the developer's original export
# (collections_dev.csv) -- the ~/Downloads copy was their 24-product sample
_HERE = os.path.dirname(os.path.abspath(__file__))
COLLECTIONS_CSV = os.environ.get("STORE_COLLECTIONS_CSV") or next(
    p for p in (os.path.join(_HERE, "store_collections.csv"), os.path.join(_HERE, "collections_dev.csv"))
    if os.path.exists(p))
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
    # hair TOOLS (dryer/curler/comb) before the makeup rule -- a set with no cosmetics isn't a
    # "Makeup Set" just because it's beauty-adjacent pretend play (found 2026-09-25: the Deluxe
    # Hair Styling Set has a dryer, brush and comb, no makeup at all, and was in Makeup Sets)
    (r"hair (styl|dry|curl)", ("Hair Styling Sets", "Pretend Play & Role Play")),
    (r"makeup|cosmetic|nail polish|vanity|beauty", ("Makeup Sets", "Pretend Play & Role Play")),
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
    (r"drone|quadcopter", ("Drones", "RC & Remote Control Toys")),
    (r"\brc\b|remote control", ("RC Vehicles", "RC & Remote Control Toys")),
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
    # "6M+" is 6 months, not 6 years -- the old ">= 12" guard read it as years and put a
    # 6-month baby stacker under ages 5-8 (TGS-STACKED-CIRCLE-RING, fixed 2026-10-01)
    if months and ("month" in text or "m+" in text):
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


# "What They Love" on the storefront: one chip per play tag, and a product carries every tag it
# fits (a smart collection per chip, rule `tag equals play:<x>`). The first five are the store's
# own; learning and squishy were added 2026-09-25 for the Learning / Squishy & fidget chips.
PLAY_CHIPS = {"learning": "Learning", "build": "Building", "pretend": "Pretending",
              "vehicles": "Cars & racing", "games": "Games & arcade",
              "outdoor": "Outdoors & bubbles", "squishy": "Squishy & fidget",
              # added 2026-09-25: neither belongs under "Learning" -- creative/tactile making and
              # musical/sound play are both real, but distinct, play modes (user: "they don't relate")
              "arts_crafts": "Arts & Crafts", "music": "Musical Toys"}

PLAY_BY_TYPE = {
    "Action Figures & Characters": ["pretend"], "Animal & Dinosaur Toys": ["pretend"],
    "Arts, Crafts & Creative Toys": ["arts_crafts"], "Baby & Toddler Toys": ["learning"],
    "Baby Care & Pretend Accessories": ["pretend"], "Battle & Action Play": ["games", "outdoor"],
    "Board Games": ["games"], "Building & Construction Toys": ["build"],
    "Card & Tabletop Games": ["games"], "Cars & Vehicles": ["vehicles"],
    "Collectibles & Miniatures": ["vehicles"], "Doll Houses & Pretend Homes": ["pretend"],
    "Dolls & Doll Play": ["pretend"], "Dress-Up & Costumes": ["pretend"],
    "Educational Toys": ["learning"], "Fantasy & Magic Toys": ["pretend"],
    "Musical Toys": ["music"], "Novelty & Fun Toys": [], "Outdoor Toys": ["outdoor"],
    "Party Toys & Favors": ["games"], "Plush & Stuffed Toys": ["pretend"],
    "Pretend Play & Role Play": ["pretend"], "Puzzles": ["games", "learning"],
    "RC & Remote Control Toys": ["vehicles"], "Ride-On Toys": ["outdoor", "vehicles"],
    "Robots & Electronic Toys": ["games"], "STEM & Science Toys": ["learning", "build"],
    "Scooters, Bikes & Tricycles": ["outdoor", "vehicles"], "Sensory & Fidget Toys": ["squishy"],
    "Sports Toys": ["outdoor", "games"], "Water & Beach Toys": ["outdoor"], "Drinkware": [],
}
PLAY_BY_SUB = {"Drones": ["outdoor"], "Arcade Games": ["games"], "Squishies": ["squishy"],
               "Fidget Toys": ["squishy"], "Bubble Toys": ["outdoor"], "Stationery Gifts": ["learning"],
               "Die-Cast Cars": ["vehicles"], "Electronic Toys": ["learning"]}
# matched against title + product name + subcategory; each adds its tag
PLAY_WORDS = [
    ("squishy", r"squish|fidget|needoh|stress ?ball|pop ?it|slime|mochi|crackle"),
    ("vehicles", r"\bcars?\b|truck|racing|racer|drift|\btrains?\b|tractor|excavator|forklift|"
                 r"bike|motorcycle|\bjet\b|aeroplane|airplane|helicopter|bumper car|steering wheel|vehicle|railcar"),
    ("outdoor", r"bubble|water gun|water bomb|\bpool\b|swim|beach|kite|\bsand\b|garden|outdoor"),
    ("learning", r"learn|educat|alphabet|\babc\b|number|counting|quran|arabic|phonetic|spelling|"
                 r"montessori|busy (book|board)|shape sorter|clock|flash ?card|\bstem\b|science|experiment|puzzle|"
                 r"study|chess|coding|intellig"),
    ("build", r"block|brick|construct|building (blocks?|sets?|toys?)|assembl|\bdiy\b|3d (printing )?pen|track set"),
    ("games", r"\bgame|arcade|claw|pinball|dart|\buno\b|domino|jenga|ludo|monopoly|tambola|"
              r"pictionary|taboo|sequence|catan|shooting machine|hammer"),
    ("pretend", r"kitchen|make-?up|beauty|hair styling|doctor|\btool|drill|cleaning|\biron\b|appliance|"
                r"dishwasher|fridge|refrigerator|vending|kettle|role play|pretend|costume|wand|crown|tiara|"
                r"sword|\bdoll|telephone|super ?hero|spider"),
]


def play_tags(category, sub="", text=""):
    """Every "What They Love" chip a product fits (see PLAY_CHIPS)."""
    got = list(PLAY_BY_TYPE.get(category, PLAY_SUB.get(category, ("games", ""))[:1]))
    got += PLAY_BY_SUB.get(sub, [])
    blob = f"{text} {sub}".lower()
    got += [tag for tag, pat in PLAY_WORDS if re.search(pat, blob)]
    return sorted(set(got))


def tags_for(category, *, printed_age="", gender="", occasions=("birthday", "eid"),
             features=("new", "gift-ready"), extra_categories=(), sub=None, play=None):
    default_sub = PLAY_SUB.get(category, ("games", ""))[1]
    sub = sub or default_sub
    if play is None:
        play = PLAY_SUB.get(category, ("games", ""))[:1]
    tags = [f"play:{p}" for p in play]
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


def gender_for(category, sub="", text=""):
    """The store's gender:boys / gender:girls tag, only where it's obvious (user, 2026-09-25: "tag by
    clear rules" -- makeup/unicorn/princess -> girls; blasters, RC cars, action figures -> boys;
    everything else untagged). Baby toys and add-ons are never gendered."""
    t = f"{text} {sub}".lower()
    if category in ("Baby & Toddler Toys",) or category in NON_TOY_TYPES:
        return ""
    if sub == "Makeup Sets" or re.search(r"make-?up|unicorn|(?<!prince )princess", t):
        return "girls"
    if category == "Battle & Action Play":
        return "boys"
    if sub == "RC Vehicles" and re.search(r"\bcars?\b|truck|racing|drift|forklift", t) \
            and not re.search(r"stitch|follow me", t):
        return "boys"
    if sub == "Action Figures" and not re.search(
            r"kuromi|cocomelon|pooh|toy story|pony|minecraft|roblox|my world|sonic", t):
        return "boys"
    return ""


# Ramadan family games: real Islamic-content items (Quran/dua/Arabic learning) qualify same as
# board/card/puzzle games; user (2026-09-25): no music, especially, on anything shown for Ramadan
ISLAMIC_PAT = re.compile(r"quran|qur'an|islamic|\bdua\b|duas|arabic|azan|\bnamaz\b|\bsalah\b", re.I)
MUSIC_PAT = re.compile(r"\bmusic\b|\bsong\b|\bsongs\b|melod|\btune\b|\bsings?\b|\bsinging\b", re.I)


def occasions_for(category, age, price, text="", base=("birthday", "eid")):
    """The store's occasion collections, from what a product is (adds to `base`, never removes):
    Ramadan family games, New baby gifts, Return gifts & party favours. `text` (title + description
    + bullet points) drives the Islamic-content and no-music checks for Ramadan."""
    out = list(base)
    if (category in ("Board Games", "Card & Tabletop Games", "Puzzles") or ISLAMIC_PAT.search(text)) \
            and not MUSIC_PAT.search(text):
        out.append("ramadan")
    if age == "0-1" or category == "Baby & Toddler Toys":
        out.append("new-baby")
    if (price and float(price) <= 1000) or category == "Party Toys & Favors":
        out.append("return-gift")
    return list(dict.fromkeys(out))


def load_collections(path=COLLECTIONS_CSV):
    """(handle, title, conditions, disjunctive) per smart collection. Shopify rules are all-AND
    or all-OR ("A OR B"), never mixed."""
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["type"] == "smart" and r["rule"]:
                rows.append((r["handle"], r["title"], RULE.findall(r["rule"]), " OR " in r["rule"]))
    return rows


def collections_for(category, tags, price=None, collections=None, vendor=""):
    """Handles this product lands in. Price rules are skipped while price is unknown."""
    out, skipped = [], []
    for handle, _title, rules, disjunctive in (collections if collections is not None else load_collections()):
        results, needs_price = [], False
        for field, op, value in rules:
            if field == "variant_price":
                needs_price = True
                if price is None:
                    continue
                got = float(price)
                results.append((op == "less_than" and got < float(value)) or
                               (op == "greater_than" and got > float(value)))
                continue
            got = {"type": category, "tag": value if value in tags else "", "vendor": vendor}.get(field, "")
            results.append((op == "equals" and got == value) or (op == "not_equals" and got != value))
        ok = any(results) if disjunctive else all(results)
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
