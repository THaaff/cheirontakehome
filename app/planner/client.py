"""The planner entrypoint: ``plan_query`` and the OpenAI Structured-Outputs call.

This is the only module in the whole system that talks to an LLM. The flow is
deliberately narrow — one structured-output call, plus at most one retry — so the
planner behaves like a constrained classifier, not an open-ended agent:

1. Guard: a live call needs ``OPENAI_API_KEY``; absent, raise a clean
   :class:`PlanningError` (never at import — only when a call is attempted).
2. Call ``responses.parse`` with :class:`PlannerOutput` as the target at
   ``temperature=0`` for deterministic classification.
3. Detect refusals, length cutoffs, and empty parses up front and convert each to
   a :class:`PlanningError`.
4. Map the constraint-light :class:`PlannerOutput` into the real
   :class:`AnalysisPlan`, where every contract validator runs. On a
   ``ValidationError`` retry exactly once, feeding the error back as a correction;
   a second failure is a clean :class:`PlanningError`.
"""

from __future__ import annotations

from openai import AsyncOpenAI, LengthFinishReasonError, OpenAIError
from openai.types.responses import EasyInputMessageParam, ResponseInputItemParam
from pydantic import ValidationError

from app.contracts import AnalysisPlan, Settings, VisualizationRequest

from .errors import PlanningError
from .prompt import build_input
from .schema import PlannerOutput

_client: AsyncOpenAI | None = None


def _get_client(settings: Settings) -> AsyncOpenAI:
    """Return the process-wide async OpenAI client, building it on first use.

    Lazily constructed (never at import, so a missing key can't fail import) and
    cached at module scope so a long-running server reuses one connection pool
    across requests instead of leaking one per call. Tests monkeypatch this whole
    function, so the cache never interferes with them.
    """
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def aclose() -> None:
    """Close and drop the cached client, if any, for clean shutdown.

    Long-running callers can leave the singleton to live for the process; one-shot
    drivers (the eval ``--live`` runner) call this in a ``finally`` so the event
    loop closes without leaving the connection pool open.
    """
    global _client
    if _client is not None:
        await _client.close()
        _client = None


def _extract_refusal(resp: object) -> str | None:
    """Return the refusal text if the model refused, else ``None``.

    Tolerant of both real ``ParsedResponse`` objects and lightweight fakes:
    walks ``output[].content[]`` looking for a part of ``type == "refusal"``.
    """
    for item in getattr(resp, "output", None) or []:
        for part in getattr(item, "content", None) or []:
            if getattr(part, "type", None) == "refusal":
                return str(getattr(part, "refusal", "") or "")
    return None


def _check_response(resp: object) -> PlannerOutput:
    """Turn a raw parsed response into a ``PlannerOutput`` or a ``PlanningError``.

    Checks status/refusal *before* trusting ``output_parsed`` because the
    Responses API can mark a response ``incomplete`` (length cutoff) or carry a
    refusal content part with no parsed object.
    """
    if getattr(resp, "status", None) == "incomplete":
        details = getattr(resp, "incomplete_details", None)
        reason = getattr(details, "reason", None)
        raise PlanningError(
            "planner response was truncated before completion",
            reason="length",
            details={"incomplete_reason": reason},
        )

    refusal = _extract_refusal(resp)
    if refusal is not None:
        raise PlanningError(
            "planner model refused the request",
            reason="refusal",
            details={"refusal": refusal},
        )

    parsed = getattr(resp, "output_parsed", None)
    if not isinstance(parsed, PlannerOutput):
        raise PlanningError(
            "planner returned no parseable structured output",
            reason="empty",
        )
    return parsed


async def _call_model(
    client: AsyncOpenAI, model: str, messages: list[ResponseInputItemParam]
) -> PlannerOutput:
    """Make one structured-output call and validate the transport-level result."""
    try:
        resp = await client.responses.parse(
            model=model,
            input=messages,
            text_format=PlannerOutput,
            temperature=0,
        )
    except LengthFinishReasonError as exc:
        raise PlanningError(
            "planner response hit the output length limit",
            reason="length",
        ) from exc
    except OpenAIError as exc:
        raise PlanningError(
            f"OpenAI API error during planning: {exc}",
            reason="api_error",
        ) from exc
    return _check_response(resp)


def _map_to_plan(parsed: PlannerOutput) -> AnalysisPlan:
    """Map a constraint-light ``PlannerOutput`` into the validated ``AnalysisPlan``.

    ``exclude_none=True`` drops nullable Nones (``series``, ``group_by``, …) and
    the omitted-default fields (``time_granularity``, ``measure``) so the IR
    defaults apply, while real values and empty lists pass through — so every
    contract constraint (operation matrix, ``SeriesSpec`` min length, network
    bounds) runs for real. May raise ``pydantic.ValidationError``.
    """
    return AnalysisPlan.model_validate(parsed.model_dump(exclude_none=True))


def _correction_messages(
    parsed: PlannerOutput, error: ValidationError
) -> list[ResponseInputItemParam]:
    """Build the assistant-echo + user-correction turns for the single retry."""
    echo: ResponseInputItemParam = EasyInputMessageParam(
        role="assistant", content=parsed.model_dump_json()
    )
    correction: ResponseInputItemParam = EasyInputMessageParam(
        role="user",
        content=(
            "That plan failed validation against the analysis schema:\n"
            f"{error}\n"
            "Return a corrected PlannerOutput that includes every field the chosen "
            "operation requires (e.g. `comparison` needs both `group_by` and a "
            "`series` with at least two values; `geographic_distribution` needs "
            "`group_by = country`)."
        ),
    )
    return [echo, correction]


async def plan_with_output(
    request: VisualizationRequest, settings: Settings
) -> tuple[PlannerOutput, AnalysisPlan]:
    """Run the full planning flow, returning both the raw model output and the plan.

    Identical control flow to :func:`plan_query` (guard, one call, one retry), but
    also returns the validated-mappable :class:`PlannerOutput`. The eval harness
    uses the raw output to *record* deterministic replay fixtures; ``plan_query``
    discards it. Raises :class:`PlanningError` on any failure.
    """
    if not settings.openai_api_key:
        raise PlanningError(
            "OPENAI_API_KEY is not set; live planning requires an API key",
            reason="missing_api_key",
        )

    client = _get_client(settings)
    messages = build_input(request)

    parsed = await _call_model(client, settings.planner_model, messages)
    try:
        return parsed, _map_to_plan(parsed)
    except ValidationError as first_error:
        retry_messages = [*messages, *_correction_messages(parsed, first_error)]
        parsed_retry = await _call_model(client, settings.planner_model, retry_messages)
        try:
            return parsed_retry, _map_to_plan(parsed_retry)
        except ValidationError as second_error:
            raise PlanningError(
                "planner output failed contract validation after one retry",
                reason="validation",
                details={
                    "first_error": str(first_error),
                    "second_error": str(second_error),
                },
            ) from second_error


async def plan_query(request: VisualizationRequest, settings: Settings) -> AnalysisPlan:
    """Plan a natural-language query into a validated :class:`AnalysisPlan`.

    Raises :class:`PlanningError` (stage = ``planning``) on a missing key, a
    refusal, a length cutoff, an empty/parse failure, an upstream API error, or a
    plan that still fails contract validation after one retry. Never returns a
    fabricated or partially-valid plan.
    """
    _, plan = await plan_with_output(request, settings)
    return plan
