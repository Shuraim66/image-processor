"""State machines and controlled vocabularies (spec 11, 33, 35, 54, 68).

These enums are the shared vocabulary for every later phase. Nothing here
performs work; it exists so that no stage can invent an ad-hoc status string.
"""

from __future__ import annotations

from enum import StrEnum


class ImageState(StrEnum):
    """Lifecycle of a single catalog image (spec 68)."""

    QUEUED = "QUEUED"
    PROCESSING = "PROCESSING"
    DOWNLOADING = "DOWNLOADING"
    POST_PROCESSING = "POST_PROCESSING"
    VALIDATING = "VALIDATING"
    PASS = "PASS"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


TERMINAL_IMAGE_STATES: frozenset[ImageState] = frozenset(
    {ImageState.PASS, ImageState.REVIEW_REQUIRED, ImageState.FAILED}
)

#: An image may only be treated as done-and-good in this state.
SUCCESS_IMAGE_STATES: frozenset[ImageState] = frozenset({ImageState.PASS})


class ProductState(StrEnum):
    """Final state of a product (spec 68)."""

    COMPLETED = "COMPLETED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    FAILED = "FAILED"


class Provenance(StrEnum):
    """Where a product fact came from (spec 11).

    There is deliberately no AI_GUESS member. A fact the model inferred but
    cannot see is UNKNOWN.
    """

    VERIFIED_FROM_PHOTOS = "VERIFIED_FROM_PHOTOS"
    USER_PROVIDED = "USER_PROVIDED"
    UNKNOWN = "UNKNOWN"


class ImageStatus(StrEnum):
    """Outcome of validating one input photograph (spec 9)."""

    OK = "OK"
    #: Byte-identical to an image already seen in this scan.
    DUPLICATE = "DUPLICATE"
    UNSUPPORTED_FORMAT = "UNSUPPORTED_FORMAT"
    UNREADABLE = "UNREADABLE"
    CORRUPT = "CORRUPT"
    TOO_SMALL = "TOO_SMALL"
    TOO_LARGE = "TOO_LARGE"
    #: A HEIC/HEIF file with no decoder installed. Fixable, not the file's fault.
    DECODER_MISSING = "DECODER_MISSING"


#: Statuses whose images may be used as product references. A corrupt file is
#: never uploaded (spec 9).
USABLE_IMAGE_STATUSES: frozenset[ImageStatus] = frozenset(
    {ImageStatus.OK, ImageStatus.DUPLICATE}
)


class TimestampSource(StrEnum):
    """Where a capture time came from. EXIF is trusted; mtime is a weak signal."""

    EXIF_ORIGINAL = "EXIF_ORIGINAL"
    EXIF_DIGITIZED = "EXIF_DIGITIZED"
    EXIF_MODIFIED = "EXIF_MODIFIED"
    FILE_MTIME = "FILE_MTIME"
    NONE = "NONE"


class GroupingLabel(StrEnum):
    """Relationship the grouping engine assigns to an image (spec 8)."""

    DUPLICATE = "DUPLICATE"
    NEAR_DUPLICATE = "NEAR_DUPLICATE"
    AMBIGUOUS = "AMBIGUOUS"
    UNASSIGNED = "UNASSIGNED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


class ImageSlot(StrEnum):
    """The six-image catalog standard (spec 54). GiftHero is NOT in the preset."""

    CATALOG_HERO = "catalog_hero"
    WHITE_BACKGROUND = "white_background"
    PACKSHOT = "packshot"
    DETAIL = "detail"
    LIFESTYLE = "lifestyle"
    FEATURE_CARD = "feature_card"


#: Canonical ordering of the standard catalog set.
CATALOG_SLOT_ORDER: tuple[ImageSlot, ...] = (
    ImageSlot.CATALOG_HERO,
    ImageSlot.WHITE_BACKGROUND,
    ImageSlot.PACKSHOT,
    ImageSlot.DETAIL,
    ImageSlot.LIFESTYLE,
    ImageSlot.FEATURE_CARD,
)

#: Output filenames are owned by Python, never by ChatGPT (spec 44).
CANONICAL_FILENAMES: dict[ImageSlot, str] = {
    ImageSlot.CATALOG_HERO: "01-catalog-hero.webp",
    ImageSlot.WHITE_BACKGROUND: "02-white-background.webp",
    ImageSlot.PACKSHOT: "03-packshot.webp",
    ImageSlot.DETAIL: "04-detail.webp",
    ImageSlot.LIFESTYLE: "05-lifestyle.webp",
    ImageSlot.FEATURE_CARD: "06-feature-card.webp",
}


class QCStatus(StrEnum):
    """Result of a QC check (spec 33-35)."""

    PASS = "PASS"
    FAIL = "FAIL"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    SKIPPED = "SKIPPED"


class BrandingStatus(StrEnum):
    """Watermark outcome (spec 30, 31). Failure is never silent."""

    APPLIED = "APPLIED"
    FAILED_BRANDING = "FAILED_BRANDING"
    FAIL_BRAND_ASSET = "FAIL_BRAND_ASSET"


class PackshotStatus(StrEnum):
    """Packshot availability (spec 20). Packaging is never invented."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


#: Returned by the scene selector when nothing in the library fits (spec 52).
NO_COMPATIBLE_BACKGROUND = "NO_COMPATIBLE_BACKGROUND"
