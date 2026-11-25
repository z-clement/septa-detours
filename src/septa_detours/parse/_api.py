"""Private model of the SEPTA alerts API JSON (parse's input format).

Only the fields parse needs are declared; the API's other keys (``isdetour``,
``advisory``, ``last_updated``, ...) are ignored, so new API keys don't break
parsing. Fields stay raw strings: interpreting them is the job of the pure
functions in this package, never of validators here (see CLAUDE.md).

Not part of ``model.py`` on purpose: no other stage may depend on this shape.
"""

from pydantic import BaseModel, ConfigDict


class _ApiModel(BaseModel):
    """Base for raw API models: immutable, strict strings, unknown keys ignored.

    ``extra="ignore"`` (not ``"forbid"`` as in ``model.py``): this mirrors an
    outside format we don't control, so extra keys are expected.
    """

    model_config = ConfigDict(frozen=True, extra="ignore", strict=True)


class ApiDetour(_ApiModel):
    """One item of a route entry's ``detour`` list, verbatim."""

    location_start: str
    location_end: str
    start: str
    end: str
    message: str
    reason: str


class ApiRoute(_ApiModel):
    """One route entry of the API list, verbatim.

    ``route_id`` is the API ID (``"bus_route_21"``), not a GTFS ID. Entries
    with an empty ``detour`` list are normal (most routes, plus system
    entries such as ``"APP"`` and ``"generic"``).
    """

    route_id: str
    mode: str
    detour: tuple[ApiDetour, ...]


def read_snapshot(content: bytes) -> list[ApiRoute]:
    """Validate a raw snapshot's bytes into route entries, in API order.

    Args:
        content: The snapshot file's bytes, exactly as ingest saved them.

    Returns:
        One ``ApiRoute`` per entry in the API list, in the same order.

    Raises:
        pydantic.ValidationError: If the bytes aren't JSON, the top level
            isn't a list, or any entry lacks a declared field. The whole
            snapshot fails, not just the bad entry: a structural change
            means the API changed, and that should be loud.
    """
    # TODO: validate the whole list in one step (hint: pydantic's
    #   TypeAdapter can validate JSON bytes directly into list[ApiRoute]).
    raise NotImplementedError
