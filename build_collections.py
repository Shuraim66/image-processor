#!/usr/bin/env python3
"""Build store_collections.csv -- the store's smart collections, in the developer's
collections.csv format -- from their original export (collections_dev.csv) and the
current catalog.

What it changes from the developer's sample file:
  * removes the sample brand collections that none of our products are in
  * adds the storefront's "What They Love" chips (one per play tag, store_taxonomy.PLAY_CHIPS)
    and a few subcategory collections that group what a Type collection doesn't
  * recounts product_count from the handoff CSVs (ready + draft), and fills in empty
    SEO titles/descriptions, descriptions and URLs

Also writes store_collections_changes.csv: one row per collection saying what changed and
anything the store owner still has to decide.

    python build_collections.py            (after export_pending.py, so both CSVs are current)
"""
import csv
import re

import store_taxonomy as st

DEV_CSV = "collections_dev.csv"
OUT_CSV = "store_collections.csv"
CHANGES_CSV = "store_collections_changes.csv"
HANDOFF = ("shopify_import_ready.csv", "shopify_import_draft.csv")
STORE_URL = "https://the-toy-gift-shop-cy0w57r4.myshopify.com/collections/"

CHIPS = [  # (handle, play tag, description) -- the chip label is store_taxonomy.PLAY_CHIPS[tag]
    ("learning", "learning", "Toys that teach while they play: letters, numbers, Quran and Arabic learning, "
                             "busy boards and first science kits."),
    ("building", "build", "Blocks, magnetic building sets, track sets and things to make and put together."),
    ("pretending", "pretend", "Make-up sets, kitchens and appliances, doctor and tool kits, figures, "
                              "animals and dress-up for role play."),
    ("cars-racing", "vehicles", "Remote control cars, drift cars, die-cast models, trucks, trains and drones."),
    ("games-arcade", "games", "Board and card games for the family, plus arcade-style games: claw machines, "
                              "basketball shooters, pinball and hammer games."),
    ("outdoors-bubbles", "outdoor", "Bubble guns and machines, water guns, blasters, swim gear, drones and "
                                    "other toys for the garden, park and beach."),
    ("squishy-fidget", "squishy", "Squishies and fidget toys to squeeze, stretch and squish."),
    ("arts-crafts", "arts_crafts", "Paint sets, drawing and doodle mats, and bead and jewellery-making kits."),
    ("musical-toys-chip", "music", "Toy pianos, xylophones, drums and other musical instruments."),
]
BRANDS = [  # (handle, title, description) -- confirmed genuine/licensed brands (2026-09-25); a
           # rule "vendor equals X" against the product's real Vendor field, same as Hot Wheels/LEGO
    ("intex", "Intex", "Genuine Intex swim and pool gear."),
    ("schylling", "Schylling", "Genuine Schylling toys, including NeeDoh."),
    ("maisto", "Maisto", "Genuine Maisto die-cast model vehicles."),
    ("uno", "UNO", "The genuine UNO card game, every edition we carry."),
    ("monopoly", "Monopoly", "The genuine Monopoly board game."),
    ("jenga", "Jenga", "The genuine Jenga block-stacking game."),
    ("catan", "Catan", "The genuine Catan board game."),
]
SUBS = [  # (handle, title, [sub tags] (OR), description)
    ("makeup-beauty-sets", "Makeup & Beauty Sets", ["Makeup Sets"],
     "Toy make-up cases and beauty sets for pretend play."),
    ("kitchen-appliance-play", "Kitchen & Appliance Play", ["Mini Appliances", "Cleaning Play Sets"],
     "Pretend kitchen appliances, irons, kettles and cleaning sets."),
    ("arcade-games", "Arcade Games", ["Arcade Games"],
     "Claw machines, basketball shooters, pinball, punch and hammer games, and handheld consoles."),
    ("drones", "Drones", ["Drones"], "Remote control drones for children and beginners."),
    ("die-cast-cars", "Die-Cast Cars & Models", ["Die-Cast Cars"],
     "Die-cast metal cars, trucks, bikes and models."),
    ("baby-activity-toys", "Baby Activity Toys", ["Baby Activity Toys"],
     "Busy boards, stackers, activity phones and steering wheels for babies and toddlers."),
    ("bubble-toys", "Bubble Toys", ["Bubble Toys"], "Bubble guns and bubble machines."),
    ("dinosaur-toys", "Dinosaur Toys", ["Dinosaur Toys"], "Walking, roaring and light-up dinosaur toys."),
    ("night-lights-gadgets", "Night Lights & Gadgets", ["Night Lights", "Gadgets"],
     "Character night lights, lamps, kids' watches and other gadgets."),
]
# written only where the developer's file left the field empty
DESCRIPTIONS = {
    "action-figures-characters": "Action figures, character figure sets and collectible figures.",
    "animal-dinosaur-toys": "Animal figures, walking and dancing animal toys, and dinosaurs.",
    "arts-crafts-creative-toys": "Painting sets, bead and jewellery kits, drawing toys and doodle mats.",
    "baby-care-pretend-accessories": "Pretend baby-care accessories for doll play.",
    "baby-toddler-toys": "Rattles, busy boards, stackers and activity toys for babies and toddlers.",
    "battle-action-play": "Gel blasters, dart blasters and superhero wrist launchers.",
    "board-games": "Family board and card games: UNO, Monopoly, Ludo, Sequence, Jenga and more.",
    "building-construction-toys": "Building blocks and magnetic building sets.",
    "card-tabletop-games": "Card and tabletop games.",
    "cars-vehicles": "Die-cast cars, trucks, planes and vehicle play sets.",
    "collectibles-miniatures": "Collectible models and miniatures.",
    "doll-houses-pretend-homes": "Doll houses and pretend homes.",
    "dolls-doll-play": "Dolls and doll play sets.",
    "dress-up-costumes": "Dress-up and costume sets.",
    "educational-toys": "Learning laptops, tablets, sound books, number trains and early-learning toys.",
    "fantasy-magic-toys": "Magic wands, crowns and light-up swords.",
    "musical-toys": "Toy pianos, xylophones, drums and musical baby toys.",
    "novelty-fun-toys": "Fun and novelty toys, gadgets, night lights and gifts.",
    "outdoor-toys": "Bubble toys and outdoor play.",
    "party-toys-favors": "Party toys and favours.",
    "plush-stuffed-toys": "Plush and stuffed toys.",
    "pretend-play-role-play": "Make-up sets, mini appliances, doctor sets, tool kits and role-play toys.",
    "puzzles": "Puzzles for children.",
    "rc-remote-control-toys": "Remote control cars, trucks, trains and drones.",
    "ride-on-toys": "Ride-on toys.",
    "robots-electronic-toys": "Robots, kids' cameras and electronic arcade games.",
    "scooters-bikes-tricycles": "Scooters, bikes and tricycles.",
    "sensory-fidget-toys": "Squishies and fidget toys.",
    "sports-toys": "Sports and target games.",
    "stem-science-toys": "Science experiment sets and STEM kits.",
    "water-beach-toys": "Water guns, swim gear and bath and beach toys.",
    "age-0-1": "Toys suitable from birth to 12 months.", "age-1-3": "Toys for toddlers aged 1 to 3.",
    "age-3-5": "Toys for children aged 3 to 5.", "age-5-8": "Toys for children aged 5 to 8.",
    "age-8-plus": "Toys and games for children aged 8 and up.",
    "best-sellers": "Our most popular toys.",
    "big-gifts": "Bigger gifts over Rs. 5,000.",
    "gift-ready-under-1000": "Gift-ready toys under Rs. 1,000.",
    "gifts-under-1000": "Toys under Rs. 1,000.", "gifts-under-2500": "Toys under Rs. 2,500.",
    "gifts-under-5000": "Toys under Rs. 5,000.",
    "new-in": "The newest toys in the shop.",
    "occasion-azadi": "Gifts for Independence Day, 14 August.",
    "occasion-birthday": "Birthday gifts for children of every age.",
    "occasion-eid": "Eid gifts for children.",
    "occasion-new-baby": "Gifts for a new baby: rattles, activity toys and first toys.",
    "occasion-ramadan": "Board and card games for the whole family.",
    "occasion-return-gift": "Small toys for return gifts and party favours.",
    "the-edit": "Toys we pick out.",
    "toys-for-boys": "Toys for boys.", "toys-for-girls": "Toys for girls.",
    "hot-wheels": "Hot Wheels die-cast cars.", "lego": "LEGO building sets.",
}
# vendor collections to keep even with 0 products right now -- the user is sourcing these
# brands next (2026-09-25); the other 6 sample brand collections (Bestway, Hasbro, Mega Bloks,
# Melissa & Doug, NERF, Tiny Land) stay removed as not on the roadmap
KEEP_EMPTY_VENDORS = {"hot-wheels", "lego"}


def products():
    """One dict per product in the handoff (type, tags, vendor, lowest variant price)."""
    by = {}
    for f in HANDOFF:
        for r in csv.DictReader(open(f, encoding="utf-8", newline="")):
            if r["Title"]:
                by[r["Handle"]] = {"type": r["Type"], "vendor": r["Vendor"], "prices": [],
                                   "tags": [t.strip() for t in r["Tags"].split(",") if t.strip()]}
            if r["Variant Price"]:
                by[r["Handle"]]["prices"].append(float(r["Variant Price"]))
    return list(by.values())


def count(rule, prods):
    conds = st.RULE.findall(rule)
    if not conds:
        return ""
    coll = [("x", "x", conds, " OR " in rule)]
    return sum(1 for p in prods
               if st.collections_for(p["type"], p["tags"], min(p["prices"]), coll, vendor=p["vendor"])[0])


def seo_title(title):
    t = re.sub(r" in Pakistan$", "", title)
    return f"{t} in Pakistan | Toy Gift Shop"


def main():
    dev = list(csv.DictReader(open(DEV_CSV, encoding="utf-8-sig", newline="")))
    fields = list(dev[0].keys())
    prods = products()
    out, changes = [], []

    for r in dev:
        r = dict(r)
        if r["rule"].startswith("vendor equals") and count(r["rule"], prods) == 0 and r["handle"] not in KEEP_EMPTY_VENDORS:
            changes.append({"handle": r["handle"], "change": "removed",
                            "note": "sample brand collection -- none of our products has this vendor"})
            continue
        n = count(r["rule"], prods)
        note = []
        if n != "" and str(n) != r["product_count"]:
            note.append(f"product_count {r['product_count'] or '-'} -> {n}")
        r["product_count"] = str(n) if n != "" else r["product_count"]
        if r["handle"] in KEEP_EMPTY_VENDORS and n == 0:
            note.append("kept empty -- brand not stocked yet, on the roadmap per the user (2026-09-25)")
        for field, value in (("description", DESCRIPTIONS.get(r["handle"], "")),
                             ("seo_description", DESCRIPTIONS.get(r["handle"], "")),
                             ("seo_title", seo_title(r["title"]) if r["handle"] != "frontpage" else ""),
                             ("url", STORE_URL + r["handle"])):
            if not r[field].strip() and value:
                r[field] = value
                note.append(f"{field} filled")
        if n == 0:
            note.append("EMPTY -- no product matches its rule yet")
        out.append(r)
        changes.append({"handle": r["handle"], "change": "updated" if note else "unchanged", "note": "; ".join(note)})

    for handle, tag, desc in CHIPS:
        title = st.PLAY_CHIPS[tag]
        rule = f'tag equals "play:{tag}"'
        out.append({**{f: "" for f in fields}, "handle": handle, "title": title, "type": "smart", "rule": rule,
                    "product_count": str(count(rule, prods)), "sort": "best_selling", "url": STORE_URL + handle,
                    "seo_title": seo_title(title), "seo_description": desc, "description": desc})
        changes.append({"handle": handle, "change": "added",
                        "note": f'"What They Love" chip "{title}" -- point the chip at this collection'})
    for handle, title, subs, desc in SUBS:
        rule = " OR ".join(f'tag equals "sub:{s}"' for s in subs)
        out.append({**{f: "" for f in fields}, "handle": handle, "title": title, "type": "smart", "rule": rule,
                    "product_count": str(count(rule, prods)), "sort": "best_selling", "url": STORE_URL + handle,
                    "seo_title": seo_title(title), "seo_description": desc, "description": desc})
        changes.append({"handle": handle, "change": "added", "note": "subcategory collection (optional, for menus)"})
    for handle, title, desc in BRANDS:
        rule = f'vendor equals "{title}"'
        out.append({**{f: "" for f in fields}, "handle": handle, "title": title, "type": "smart", "rule": rule,
                    "product_count": str(count(rule, prods)), "sort": "best_selling", "url": STORE_URL + handle,
                    "seo_title": seo_title(title), "seo_description": desc, "description": desc})
        changes.append({"handle": handle, "change": "added", "note": "brand collection -- confirmed genuine (2026-09-25)"})

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)
    with open(CHANGES_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["handle", "change", "note"])
        w.writeheader()
        w.writerows(changes)
    by = {}
    for c in changes:
        by[c["change"]] = by.get(c["change"], 0) + 1
    print(f"{OUT_CSV}: {len(out)} collections ({by}) over {len(prods)} products")
    for c in changes:
        if "EMPTY" in c["note"]:
            print(f"  empty: {c['handle']}")


if __name__ == "__main__":
    main()
