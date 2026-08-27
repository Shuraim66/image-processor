#!/usr/bin/env python3
"""One entry point for the catalog pipeline.

Each stage keeps its own argparse interface — they are used directly often
enough that collapsing them into one parser would cost more than it buys. This
just routes to them, so `toycat build --sku X` and `python gallery_pipeline.py
--sku X` are the same command with the same flags.
"""

import sys

# stage -> (module, one-line help). Order is the order you run them in.
STAGES = {
    "sort": ("intake", "group an unsorted shoot into input/<SKU>/ folders"),
    "analyze": ("analyzer", "photos -> product.json (local VLM)"),
    "scenes": ("scenes", "generate the background plates"),
    "specs": ("specs", "size data and the missing-measurement report"),
    "build": ("gallery_pipeline", "render the listing gallery"),
    "export": ("shopify_export", "write the Shopify import CSV"),
}


def usage(to=sys.stderr):
    print("usage: toycat <stage> [options]\n\nstages:", file=to)
    width = max(len(s) for s in STAGES)
    for name, (_, blurb) in STAGES.items():
        print(f"  {name:<{width}}  {blurb}", file=to)
    print("\nEvery stage takes --help for its own options.", file=to)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] in ("-h", "--help"):
        usage(sys.stdout if argv else sys.stderr)
        return 0 if argv else 2
    stage = argv[0]
    if stage not in STAGES:
        print(f"toycat: unknown stage '{stage}'\n", file=sys.stderr)
        usage()
        return 2

    module_name = STAGES[stage][0]
    # The stage parses sys.argv itself, so hand it a clean one.
    sys.argv = [f"toycat {stage}"] + argv[1:]
    module = __import__(module_name)
    return module.main() or 0


if __name__ == "__main__":
    sys.exit(main())
