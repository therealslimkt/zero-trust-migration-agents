from __future__ import annotations

import unittest

from agent_runtime.collaboration import (
    CollaborationViolation,
    IntakeDraft,
    IntakeResponse,
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


if __name__ == "__main__":
    unittest.main()
