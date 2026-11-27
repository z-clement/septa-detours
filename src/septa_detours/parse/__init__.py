"""Parse stage: turn raw alert snapshots into ``DetourNotice`` objects.

Input is a snapshot's bytes exactly as ingest saved them; output is
``model.DetourNotice``. No GTFS knowledge here: tying a notice to routes and
shapes is ``match/``'s job.

Layout:
    ``_api``: private model of the raw API JSON (not shared with any stage).
    ``text``, ``times``, ``direction``, ``hours``: one small pure
        function per field. They raise ``ValueError`` with a reason when
        input can't be parsed.
    ``location``: location text split into street names.
    ``steps``: the turn-by-turn steps of a detour message.
    ``notice``: assembles a ``DetourNotice``, turning each ``ValueError``
        into ``None`` plus an entry in ``issues``.

Rule: never guess. Unparseable or ambiguous input becomes ``None`` and an
issue; ``DetourNotice.status`` then reports ``partial`` or ``unknown``.
"""
