import { useEffect, useId, useRef, useState } from 'react';
import { StatusPill } from './StatusPill';
import { RUN_STATE_LABEL, RUN_STATE_TONE } from './presentation';
import type { PortfolioDecisionInput, RunState } from './types';

export interface DecisionSubmission {
  status: 'idle' | 'submitting' | 'submitted' | 'error';
  decision?: 'approve' | 'reject';
  digest?: string;
  message?: string;
}

interface ApprovalGateProps {
  digest?: string;
  /** Comes straight from `canApprove(view)`; the UI never widens it. */
  approvalAllowed: boolean;
  /** Human-readable restatement of what the view shows, used only for explanation. */
  blockedReasons: string[];
  runState?: RunState;
  defaultApprover: string;
  submission: DecisionSubmission;
  onSubmit: (input: Omit<PortfolioDecisionInput, 'planDigest'>) => void;
}

/** From `contracts/schemas/approval-request.schema.json#decidedBy`. */
const APPROVER_PATTERN = /^[A-Za-z0-9][A-Za-z0-9@._ -]*$/;

export function ApprovalGate({
  digest,
  approvalAllowed,
  blockedReasons,
  runState,
  defaultApprover,
  submission,
  onSubmit,
}: ApprovalGateProps) {
  const [confirming, setConfirming] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [approver, setApprover] = useState(defaultApprover);
  const [reason, setReason] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const approverRef = useRef<HTMLInputElement>(null);
  const groupId = useId();
  const blockedId = `${groupId}-blocked`;
  const digestId = `${groupId}-digest`;

  useEffect(() => {
    if (confirming) approverRef.current?.focus();
  }, [confirming]);

  const busy = submission.status === 'submitting';

  function decide(decision: 'approve' | 'reject') {
    if (!digest) {
      setFormError('No portfolio digest is published, so no decision can be bound to it.');
      return;
    }
    if (!approvalAllowed) {
      setFormError('The decision gate is closed for this portfolio.');
      return;
    }
    const decidedBy = approver.trim();
    if (!decidedBy) {
      setFormError('Enter the identity recording this decision.');
      approverRef.current?.focus();
      return;
    }
    if (!APPROVER_PATTERN.test(decidedBy)) {
      setFormError('Identity may use letters, digits, spaces, and @ . _ - only, and must start with a letter or digit.');
      approverRef.current?.focus();
      return;
    }
    if (!acknowledged) {
      setFormError('Confirm that you have reviewed this exact digest.');
      return;
    }
    setFormError(null);
    onSubmit({ decision, decidedBy, reason: reason.trim() || undefined });
    setConfirming(false);
    setAcknowledged(false);
  }

  return (
    <section className="mc-panel mc-approval" aria-labelledby={`${groupId}-heading`}>
      <div className="mc-panel__head">
        <h2 className="mc-section-heading" id={`${groupId}-heading`}>
          Portfolio approval
        </h2>
        <StatusPill
          tone={runState ? RUN_STATE_TONE[runState] : 'neutral'}
          label={runState ? RUN_STATE_LABEL[runState] : 'No state'}
          size="sm"
        />
      </div>

      <p className="mc-approval__intro">
        One decision covers all three lanes and is bound to the exact plan digest below. Nothing executes until
        it is recorded.
      </p>

      <div className="mc-approval__digest">
        <h3 className="mc-block-heading" id={digestId}>
          Portfolio plan digest
        </h3>
        {digest ? (
          <code className="mc-digest" aria-labelledby={digestId}>
            {digest}
          </code>
        ) : (
          <p className="mc-muted">Not published yet. The control plane has not sealed a portfolio digest.</p>
        )}
      </div>

      {!approvalAllowed && blockedReasons.length > 0 ? (
        <div className="mc-approval__blocked" id={blockedId}>
          <h3 className="mc-block-heading">Blocked by</h3>
          <ul className="mc-reasons">
            {blockedReasons.map((entry) => (
              <li key={entry}>{entry}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {submission.status === 'submitted' ? (
        <p className="mc-approval__result" role="status">
          {submission.decision === 'reject' ? 'Rejection' : 'Approval'} sent for digest{' '}
          <span className="mc-mono">{submission.digest}</span>. The lanes update when the control plane emits the
          resulting events.
        </p>
      ) : null}

      {submission.status === 'error' ? (
        <p className="mc-approval__error" role="alert">
          Decision was not recorded: {submission.message}
        </p>
      ) : null}

      {!confirming ? (
        <button
          className="mc-button mc-button--primary"
          type="button"
          disabled={!approvalAllowed || busy}
          aria-describedby={!approvalAllowed && blockedReasons.length > 0 ? blockedId : undefined}
          onClick={() => {
            setFormError(null);
            setConfirming(true);
          }}
        >
          {busy ? 'Sending decision…' : 'Review portfolio decision'}
        </button>
      ) : (
        <div className="mc-confirm" role="group" aria-labelledby={`${groupId}-confirm-heading`}>
          <h3 className="mc-block-heading" id={`${groupId}-confirm-heading`}>
            Confirm decision
          </h3>

          <label className="mc-field" htmlFor={`${groupId}-approver`}>
            <span className="mc-field__label">Recorded by</span>
            <input
              className="mc-input"
              id={`${groupId}-approver`}
              name="decidedBy"
              ref={approverRef}
              type="text"
              autoComplete="off"
              maxLength={120}
              required
              value={approver}
              onChange={(event) => setApprover(event.target.value)}
            />
          </label>

          <label className="mc-field" htmlFor={`${groupId}-reason`}>
            <span className="mc-field__label">Reason (optional)</span>
            <textarea
              className="mc-input mc-input--area"
              id={`${groupId}-reason`}
              name="reason"
              rows={2}
              maxLength={500}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
          </label>

          <label className="mc-check" htmlFor={`${groupId}-ack`}>
            <input
              className="mc-check__box"
              id={`${groupId}-ack`}
              type="checkbox"
              checked={acknowledged}
              onChange={(event) => setAcknowledged(event.target.checked)}
            />
            <span>
              I have reviewed digest <span className="mc-mono">{digest}</span> and authorise this decision for all
              three sources.
            </span>
          </label>

          {formError ? (
            <p className="mc-approval__error" role="alert">
              {formError}
            </p>
          ) : null}

          <div className="mc-confirm__actions">
            <button
              className="mc-button mc-button--primary"
              type="button"
              disabled={!approvalAllowed || !acknowledged || busy}
              onClick={() => decide('approve')}
            >
              Approve portfolio
            </button>
            <button
              className="mc-button mc-button--danger"
              type="button"
              disabled={!approvalAllowed || !digest || !acknowledged || busy}
              onClick={() => decide('reject')}
            >
              Reject portfolio
            </button>
            <button
              className="mc-button mc-button--quiet"
              type="button"
              onClick={() => {
                setConfirming(false);
                setAcknowledged(false);
                setFormError(null);
              }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
