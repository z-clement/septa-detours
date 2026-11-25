"""Clean free-text fields (locations, reason) into ``CleanText | None``."""


def clean_text(raw: str) -> str | None:
    r"""Trim and collapse whitespace; blank input means "not given".

    Args:
        raw: A raw API string, e.g. ``"Construction "`` or ``""``.

    Returns:
        The text with leading/trailing whitespace removed and every inner
        run of whitespace replaced by one space, or ``None`` if nothing is
        left. The result always satisfies ``model.CleanText``.

    Examples (from fixtures):
        ``"Construction "`` -> ``"Construction"``;
        ``"22nd  &  Chestnut"`` -> ``"22nd & Chestnut"``;
        ``""`` -> ``None``; ``"   "`` -> ``None``.

    Inner runs collapse because they are typing slips (9 of the fixture
    locations/reasons have them), and match/ must compare street names
    without caring about spacing. Nothing is lost: ``SourceText`` keeps the
    original. ``str.split()`` splits on any Unicode whitespace (tabs,
    newlines, non-breaking spaces), the same set ``CleanText``'s ``\S``
    rejects at the ends, so a result can never fail that check.

    Blank is not an error, so this never raises: a blank ``location_end``
    is normal (19 of 140 real entries).
    """
    return " ".join(raw.split()) or None
