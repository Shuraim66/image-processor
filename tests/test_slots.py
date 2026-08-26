"""The slot vocabulary and the order it imposes on a listing."""

import slots


def test_clean_and_branded_partition_the_catalogue():
    assert set(slots.CLEAN_SLOTS) | set(slots.BRANDED_SLOTS) == set(slots.SLOT_ORDER)
    assert not set(slots.CLEAN_SLOTS) & set(slots.BRANDED_SLOTS)


def test_white_background_is_never_branded():
    """Google Merchant Center disapproves product images carrying a logo, so the
    marketplace main image must stay out of the branded set. This is the test
    that stops a future edit quietly reversing that."""
    assert "white-background" in slots.CLEAN_SLOTS
    assert "white-background" not in slots.BRANDED_SLOTS


def test_sort_key_follows_slot_order_not_alphabet():
    shuffled = ["close-up-detail.webp", "catalog-hero.webp", "white-background.webp"]
    got = [slots.slot_name(f) for f in sorted(shuffled, key=slots.slot_sort_key)]
    assert got == ["catalog-hero", "white-background", "close-up-detail"]
    assert got != sorted(slots.slot_name(f) for f in shuffled)


def test_unknown_slots_sort_last():
    files = ["zzz-custom.webp", "catalog-hero.webp"]
    assert slots.slot_name(sorted(files, key=slots.slot_sort_key)[0]) == "catalog-hero"


def test_slot_names_are_filename_safe():
    for s in slots.SLOT_ORDER:
        assert s == s.lower()
        assert " " not in s and "/" not in s
