"""Clean free-text fields (locations, reason) into ``CleanText | None``."""


def clean_text(raw: str) -> str | None:
    """Strip surrounding whitespace; blank input means "not given".

    Args:
        raw: A raw API string, e.g. ``"Construction "`` or ``""``.

    Returns:
        The stripped text, or ``None`` if nothing is left. The result always
        satisfies ``model.CleanText``.

    Examples (from fixtures):
        ``"Construction "`` -> ``"Construction"``;
        ``""`` -> ``None``; ``"   "`` -> ``None``.

    Blank is not an error, so this never raises: a blank ``location_end``
    is normal (19 of 140 real entries).
    """
    # TODO: decide whether inner runs of whitespace collapse to one space
    #   ("22nd  &  Chestnut", route 7 #1). CleanText allows them either way.
    #   Collapsing helps match/ compare street names; keeping them is more
    #   faithful (SourceText keeps the original regardless).
    raise NotImplementedError
