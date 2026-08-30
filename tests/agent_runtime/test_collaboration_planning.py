from __future__ import annotations

import unittest

from agent_runtime.collaboration import (
    ADVISOR_PROFILES,
    ANALYST_BY_FAMILY,
    SOURCE_ANALYST_PROFILES,
    AgentMode,
    CollaborationViolation,
    Portfolio,
    SourceFamily,
    SourceInstance,
    build_eligible_team,
    plan_dispatch,
)


FAMILIES = tuple(SourceFamily)


def portfolio(width: int) -> Portfolio:
    return Portfolio(
        run_id="run_collaboration",
        session_id="ses_collaboration",
        objective="Interpret the selected sanitized source metadata.",
        sources=tuple(
            SourceInstance(source_instance_id=f"src_{index}", family=family)
            for index, family in enumerate(FAMILIES[:width], start=1)
        ),
    )


class CollaborationPlanningTests(unittest.TestCase):
    def test_registry_has_seven_profiled_analysts_and_four_advisors(self):
        self.assertEqual(len(SOURCE_ANALYST_PROFILES), 7)
        self.assertEqual(
            {profile.source_family for profile in SOURCE_ANALYST_PROFILES},
            set(SourceFamily),
        )
        self.assertTrue(
            all(profile.mode is AgentMode.SINGLE_TURN for profile in SOURCE_ANALYST_PROFILES)
        )
        self.assertEqual(
            {profile.specialist_id for profile in ADVISOR_PROFILES},
            {"scout", "maven", "prisma", "jetty_advisor"},
        )

    def test_one_to_seven_source_portfolios_select_only_matching_analysts(self):
        for width in range(1, 8):
            with self.subTest(width=width):
                value = portfolio(width)
                team = build_eligible_team(value)
                expected = tuple(ANALYST_BY_FAMILY[source.family] for source in value.sources)
                self.assertEqual(
                    tuple(profile.specialist_id for profile in team.profiles), expected
                )
                plan = plan_dispatch(team, selected_specialist_ids=expected)
                self.assertEqual(len(plan.requests), width)
                self.assertEqual(
                    tuple(request.source_instance_ids[0] for request in plan.requests),
                    tuple(source.source_instance_id for source in value.sources),
                )

    def test_atlas_can_select_permitted_advisor_subset_without_extra_dispatch(self):
        team = build_eligible_team(
            portfolio(2),
            permitted_advisor_ids=frozenset(
                {"scout", "maven", "prisma", "jetty_advisor"}
            ),
        )
        analysts = tuple(sorted(team.required_analyst_ids))
        selected = (*analysts, "maven", "jetty_advisor")
        plan = plan_dispatch(team, selected_specialist_ids=selected)
        self.assertEqual(plan.selected_specialist_ids, selected)
        self.assertNotIn("scout", {request.specialist_id for request in plan.requests})
        self.assertNotIn("prisma", {request.specialist_id for request in plan.requests})
        self.assertEqual(
            {request.specialist_id for request in plan.requests}, set(selected)
        )

    def test_unselected_or_unpermitted_specialists_fail_closed(self):
        team = build_eligible_team(portfolio(1))
        analyst = next(iter(team.required_analyst_ids))
        with self.assertRaisesRegex(
            CollaborationViolation, "unauthorized_specialist_selection"
        ):
            plan_dispatch(team, selected_specialist_ids=(analyst, "maven"))
        with self.assertRaisesRegex(CollaborationViolation, "unknown_advisor"):
            build_eligible_team(
                portfolio(1), permitted_advisor_ids=frozenset({"vale"})
            )

    def test_every_selected_source_requires_its_analyst(self):
        team = build_eligible_team(portfolio(2))
        selected = tuple(sorted(team.required_analyst_ids))
        with self.assertRaisesRegex(CollaborationViolation, "missing_source_analyst"):
            plan_dispatch(team, selected_specialist_ids=selected[:1])

    def test_duplicate_source_or_selected_specialist_is_rejected(self):
        source = SourceInstance(source_instance_id="src_duplicate", family=SourceFamily.JDE)
        with self.assertRaisesRegex(CollaborationViolation, "duplicate_source_instance"):
            Portfolio(
                run_id="run_duplicate",
                session_id="ses_duplicate",
                objective="test duplicates",
                sources=(source, source),
            )
        team = build_eligible_team(portfolio(1))
        analyst = next(iter(team.required_analyst_ids))
        with self.assertRaisesRegex(
            CollaborationViolation, "duplicate_selected_specialist"
        ):
            plan_dispatch(team, selected_specialist_ids=(analyst, analyst))


if __name__ == "__main__":
    unittest.main()
