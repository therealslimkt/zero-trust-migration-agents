from __future__ import annotations

import unittest

from agent_runtime.collaboration import (
    MAX_INTAKE_ROUNDS,
    CollaborationViolation,
    IntakeDraft,
    IntakeInterrupt,
    IntakeResponse,
    IntakeState,
    IntakeStatus,
    SourceFamily,
    SourceInstance,
    resume_intake,
    start_intake,
)


class CollaborationIntakeTests(unittest.TestCase):
    def test_task_intake_pauses_and_resumes_the_same_session(self):
        state = start_intake(
            intake_id="intake_01",
            run_id="run_intake",
            session_id="ses_intake",
        )
        self.assertIs(state.status, IntakeStatus.WAITING)
        self.assertEqual(state.interrupt.missing_fields, ("objective", "sources"))

        resumed = resume_intake(
            state,
            IntakeResponse(
                interrupt_id=state.interrupt.interrupt_id,
                session_id="ses_intake",
                objective="Migrate sanitized JDE metadata.",
                sources=(
                    SourceInstance(
                        source_instance_id="src_jde", family=SourceFamily.JDE
                    ),
                ),
            ),
        )
        self.assertIs(resumed.status, IntakeStatus.COMPLETE)
        self.assertEqual(resumed.session_id, state.session_id)
        self.assertEqual(resumed.intent.session_id, state.session_id)
        self.assertEqual(resumed.revision, 1)

    def test_partial_resume_issues_a_new_interrupt_without_losing_prior_input(self):
        state = start_intake(
            intake_id="intake_02",
            run_id="run_intake",
            session_id="ses_intake",
            draft=IntakeDraft(objective="Inspect the source."),
        )
        resumed = resume_intake(
            state,
            IntakeResponse(
                interrupt_id=state.interrupt.interrupt_id,
                session_id=state.session_id,
            ),
        )
        self.assertIs(resumed.status, IntakeStatus.WAITING)
        self.assertEqual(resumed.draft.objective, "Inspect the source.")
        self.assertEqual(resumed.interrupt.missing_fields, ("sources",))
        self.assertNotEqual(resumed.interrupt.interrupt_id, state.interrupt.interrupt_id)

    def test_cross_session_or_stale_interrupt_resume_is_rejected(self):
        state = start_intake(
            intake_id="intake_03",
            run_id="run_intake",
            session_id="ses_original",
        )
        with self.assertRaisesRegex(CollaborationViolation, "intake_session_mismatch"):
            resume_intake(
                state,
                IntakeResponse(
                    interrupt_id=state.interrupt.interrupt_id,
                    session_id="ses_other",
                ),
            )
        with self.assertRaisesRegex(CollaborationViolation, "intake_interrupt_mismatch"):
            resume_intake(
                state,
                IntakeResponse(
                    interrupt_id="intake_03:stale",
                    session_id=state.session_id,
                ),
            )

    def test_completed_intake_cannot_be_resumed(self):
        state = start_intake(
            intake_id="intake_04",
            run_id="run_intake",
            session_id="ses_intake",
            draft=IntakeDraft(
                objective="Inspect JDE.",
                sources=(
                    SourceInstance(source_instance_id="src_jde", family=SourceFamily.JDE),
                ),
            ),
        )
        self.assertIs(state.status, IntakeStatus.COMPLETE)
        with self.assertRaisesRegex(CollaborationViolation, "intake_not_waiting"):
            resume_intake(
                state,
                IntakeResponse(interrupt_id="intake_04:r0", session_id="ses_intake"),
            )

    def test_incomplete_intake_fails_closed_after_three_rounds(self):
        state = start_intake(
            intake_id="intake_bounded",
            run_id="run_intake",
            session_id="ses_intake",
        )
        for round_number in range(1, MAX_INTAKE_ROUNDS + 1):
            state = resume_intake(
                state,
                IntakeResponse(
                    interrupt_id=state.interrupt.interrupt_id,
                    session_id=state.session_id,
                ),
            )
            expected = (
                IntakeStatus.WAITING
                if round_number < MAX_INTAKE_ROUNDS
                else IntakeStatus.FAILED
            )
            self.assertIs(state.status, expected)
        self.assertEqual(state.revision, MAX_INTAKE_ROUNDS)
        self.assertEqual(state.failure_code, "intake_round_limit")
        self.assertIsNone(state.interrupt)
        with self.assertRaisesRegex(CollaborationViolation, "intake_not_waiting"):
            resume_intake(
                state,
                IntakeResponse(
                    interrupt_id="intake_bounded:r3",
                    session_id=state.session_id,
                ),
            )

    def test_forged_interrupt_and_state_construction_is_rejected(self):
        with self.assertRaisesRegex(CollaborationViolation, "intake_missing_field"):
            IntakeInterrupt(
                interrupt_id="intake_forged:r0",
                session_id="ses_intake",
                missing_fields=("approval",),
                prompt="Provide approval.",
            )
        with self.assertRaisesRegex(
            CollaborationViolation, "duplicate_intake_missing_field"
        ):
            IntakeInterrupt(
                interrupt_id="intake_forged:r0",
                session_id="ses_intake",
                missing_fields=("sources", "sources"),
                prompt="Provide sources.",
            )

        state = start_intake(
            intake_id="intake_forged",
            run_id="run_intake",
            session_id="ses_intake",
        )
        forged_interrupt = IntakeInterrupt(
            interrupt_id=state.interrupt.interrupt_id,
            session_id="ses_attacker",
            missing_fields=state.interrupt.missing_fields,
            prompt=state.interrupt.prompt,
        )
        with self.assertRaisesRegex(
            CollaborationViolation, "intake_interrupt_session_binding"
        ):
            IntakeState(
                intake_id=state.intake_id,
                run_id=state.run_id,
                session_id=state.session_id,
                revision=state.revision,
                status=IntakeStatus.WAITING,
                draft=state.draft,
                interrupt=forged_interrupt,
            )
        forged_prompt = IntakeInterrupt(
            interrupt_id=state.interrupt.interrupt_id,
            session_id=state.session_id,
            missing_fields=state.interrupt.missing_fields,
            prompt="Provide a production approval instead.",
        )
        with self.assertRaisesRegex(CollaborationViolation, "intake_prompt_binding"):
            IntakeState(
                intake_id=state.intake_id,
                run_id=state.run_id,
                session_id=state.session_id,
                revision=state.revision,
                status=IntakeStatus.WAITING,
                draft=state.draft,
                interrupt=forged_prompt,
            )
        with self.assertRaisesRegex(CollaborationViolation, "intake_complete_state"):
            IntakeState(
                intake_id="intake_forged",
                run_id="run_intake",
                session_id="ses_intake",
                revision=0,
                status=IntakeStatus.COMPLETE,
                draft=IntakeDraft(),
            )
        with self.assertRaisesRegex(CollaborationViolation, "intake_revision"):
            IntakeState(
                intake_id="intake_forged",
                run_id="run_intake",
                session_id="ses_intake",
                revision=MAX_INTAKE_ROUNDS + 1,
                status=IntakeStatus.FAILED,
                draft=IntakeDraft(),
                failure_code="intake_round_limit",
            )

    def test_draft_and_response_validate_content_and_duplicate_sources(self):
        source = SourceInstance(source_instance_id="src_jde", family=SourceFamily.JDE)
        with self.assertRaisesRegex(CollaborationViolation, "duplicate_intake_source"):
            IntakeDraft(objective="Inspect.", sources=(source, source))
        with self.assertRaisesRegex(
            CollaborationViolation, "duplicate_intake_response_source"
        ):
            IntakeResponse(
                interrupt_id="intake_validation:r0",
                session_id="ses_intake",
                sources=(source, source),
            )
        with self.assertRaisesRegex(
            CollaborationViolation, "intake_response_objective"
        ):
            IntakeResponse(
                interrupt_id="intake_validation:r0",
                session_id="ses_intake",
                objective="x" * 2001,
            )


if __name__ == "__main__":
    unittest.main()
