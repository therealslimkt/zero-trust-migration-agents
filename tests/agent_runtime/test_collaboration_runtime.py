from __future__ import annotations

import asyncio
import unittest

from agent_runtime.collaboration import (
    AtlasFinal,
    CollaborationViolation,
    Portfolio,
    SourceFamily,
    SourceInstance,
    SpecialistResult,
    build_eligible_team,
    plan_dispatch,
    run_collaboration,
    validate_atlas_final,
    validate_results,
)


def make_plan(width: int = 3):
    sources = tuple(
        SourceInstance(source_instance_id=f"src_{index}", family=family)
        for index, family in enumerate(tuple(SourceFamily)[:width], start=1)
    )
    value = Portfolio(
        run_id="run_runtime",
        session_id="ses_runtime",
        objective="Profile sanitized metadata.",
        sources=sources,
    )
    team = build_eligible_team(value)
    return plan_dispatch(
        team, selected_specialist_ids=tuple(sorted(team.required_analyst_ids))
    )


def result_for(request, **overrides):
    values = {
        "request_id": request.request_id,
        "run_id": request.run_id,
        "session_id": request.session_id,
        "specialist_id": request.specialist_id,
        "source_instance_ids": request.source_instance_ids,
        "findings": ("Typed sanitized finding.",),
    }
    values.update(overrides)
    return SpecialistResult(**values)


class RecordingDispatcher:
    def __init__(self):
        self.active = 0
        self.maximum_active = 0

    async def dispatch(self, request):
        self.active += 1
        self.maximum_active = max(self.maximum_active, self.active)
        await asyncio.sleep(0.01)
        self.active -= 1
        return result_for(request)


class AtlasOnlySynthesizer:
    async def synthesize(self, synthesis_input):
        return AtlasFinal(
            speaker_id="atlas",
            summary="Atlas combined every typed specialist result.",
            source_instance_ids=tuple(
                source.source_instance_id
                for source in synthesis_input.plan.team.portfolio.sources
            ),
            contributing_specialist_ids=synthesis_input.plan.selected_specialist_ids,
            result_request_ids=tuple(
                result.request_id for result in synthesis_input.results
            ),
        )


class WrongSpeakerSynthesizer(AtlasOnlySynthesizer):
    async def synthesize(self, synthesis_input):
        value = await super().synthesize(synthesis_input)
        return AtlasFinal(
            speaker_id="maven",
            summary=value.summary,
            source_instance_ids=value.source_instance_ids,
            contributing_specialist_ids=value.contributing_specialist_ids,
            result_request_ids=value.result_request_ids,
        )


class HungDispatcher:
    def __init__(self):
        self.calls = 0
        self.cancelled = 0

    async def dispatch(self, request):
        self.calls += 1
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class CountingDispatcher(RecordingDispatcher):
    def __init__(self):
        super().__init__()
        self.calls = 0

    async def dispatch(self, request):
        self.calls += 1
        return await super().dispatch(request)


class FailAndHangDispatcher:
    def __init__(self, failed_request_id):
        self.failed_request_id = failed_request_id
        self.started = 0
        self.cancelled = 0
        self.all_started = asyncio.Event()

    async def dispatch(self, request):
        self.started += 1
        if self.started == 2:
            self.all_started.set()
        await self.all_started.wait()
        if request.request_id == self.failed_request_id:
            raise RuntimeError("provider failed")
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise


class CollaborationRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_fan_in_is_bounded_and_returns_request_order(self):
        plan = make_plan(7)
        dispatcher = RecordingDispatcher()
        outcome = await run_collaboration(
            plan,
            dispatcher=dispatcher,
            synthesizer=AtlasOnlySynthesizer(),
            max_concurrency=3,
        )
        self.assertEqual(dispatcher.maximum_active, 3)
        self.assertEqual(
            tuple(result.request_id for result in outcome.results),
            tuple(request.request_id for request in plan.requests),
        )
        self.assertEqual(outcome.final.speaker_id, "atlas")
        self.assertTrue(outcome.final.final)
        self.assertEqual(outcome.usage.specialist_model_calls, 7)
        self.assertEqual(outcome.usage.atlas_model_calls, 1)
        self.assertEqual(outcome.usage.total_model_calls, 8)
        self.assertEqual(outcome.usage.max_model_calls, 30)

    async def test_atlas_must_be_the_final_speaker(self):
        with self.assertRaisesRegex(CollaborationViolation, "atlas_final_speaker"):
            await run_collaboration(
                make_plan(1),
                dispatcher=RecordingDispatcher(),
                synthesizer=WrongSpeakerSynthesizer(),
            )

    def test_missing_duplicate_or_unauthorized_results_are_rejected(self):
        plan = make_plan(2)
        valid = tuple(result_for(request) for request in plan.requests)
        with self.assertRaisesRegex(CollaborationViolation, "missing_specialist_result"):
            validate_results(plan, valid[:1])
        with self.assertRaisesRegex(CollaborationViolation, "duplicate_specialist_result"):
            validate_results(plan, (valid[0], valid[0]))
        unauthorized = result_for(
            plan.requests[0], request_id="req_unauthorized_maven"
        )
        with self.assertRaisesRegex(
            CollaborationViolation, "unauthorized_specialist_result"
        ):
            validate_results(plan, (unauthorized, *valid[1:]))

    def test_wrong_specialist_source_or_session_is_rejected(self):
        plan = make_plan(1)
        request = plan.requests[0]
        cases = (
            ("result_specialist_mismatch", {"specialist_id": "maven"}),
            ("result_source_mismatch", {"source_instance_ids": ("src_other",)}),
            ("result_context_mismatch", {"session_id": "ses_other"}),
        )
        for code, overrides in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(CollaborationViolation, code):
                    validate_results(plan, (result_for(request, **overrides),))

    def test_synthesis_must_cover_sources_contributors_and_results_exactly(self):
        plan = make_plan(2)
        results = tuple(result_for(request) for request in plan.requests)
        base = AtlasFinal(
            speaker_id="atlas",
            summary="Complete.",
            source_instance_ids=tuple(
                source.source_instance_id for source in plan.team.portfolio.sources
            ),
            contributing_specialist_ids=plan.selected_specialist_ids,
            result_request_ids=tuple(result.request_id for result in results),
        )
        validate_atlas_final(plan, results, base)
        with self.assertRaisesRegex(
            CollaborationViolation, "atlas_final_source_coverage"
        ):
            validate_atlas_final(
                plan,
                results,
                AtlasFinal(
                    speaker_id="atlas",
                    summary="Incomplete.",
                    source_instance_ids=base.source_instance_ids[:1],
                    contributing_specialist_ids=base.contributing_specialist_ids,
                    result_request_ids=base.result_request_ids,
                ),
            )

    async def test_hung_dispatchers_are_cancelled_and_awaited_on_timeout(self):
        dispatcher = HungDispatcher()
        with self.assertRaises(TimeoutError):
            await run_collaboration(
                make_plan(2),
                dispatcher=dispatcher,
                synthesizer=AtlasOnlySynthesizer(),
                max_concurrency=2,
                max_wall_clock_seconds=0.02,
            )
        self.assertEqual(dispatcher.calls, 2)
        self.assertEqual(dispatcher.cancelled, 2)

    async def test_failed_dispatch_cancels_and_awaits_its_sibling(self):
        plan = make_plan(2)
        dispatcher = FailAndHangDispatcher(plan.requests[0].request_id)
        with self.assertRaises(ExceptionGroup):
            await run_collaboration(
                plan,
                dispatcher=dispatcher,
                synthesizer=AtlasOnlySynthesizer(),
                max_concurrency=2,
            )
        self.assertEqual(dispatcher.started, 2)
        self.assertEqual(dispatcher.cancelled, 1)

    async def test_model_call_budget_is_checked_before_dispatch(self):
        plan = make_plan(2)
        dispatcher = CountingDispatcher()
        with self.assertRaisesRegex(
            CollaborationViolation, "collaboration_model_call_budget"
        ):
            await run_collaboration(
                plan,
                dispatcher=dispatcher,
                synthesizer=AtlasOnlySynthesizer(),
                max_model_calls=2,
            )
        self.assertEqual(dispatcher.calls, 0)

    async def test_production_hard_ceilings_cannot_be_configured_higher(self):
        plan = make_plan(1)
        cases = (
            ({"max_concurrency": 5}, "collaboration_concurrency"),
            ({"max_model_calls": 31}, "collaboration_model_call_limit"),
            ({"max_wall_clock_seconds": 1800.1}, "collaboration_wall_clock_limit"),
        )
        for kwargs, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(CollaborationViolation, code):
                    await run_collaboration(
                        plan,
                        dispatcher=RecordingDispatcher(),
                        synthesizer=AtlasOnlySynthesizer(),
                        **kwargs,
                    )


if __name__ == "__main__":
    unittest.main()
