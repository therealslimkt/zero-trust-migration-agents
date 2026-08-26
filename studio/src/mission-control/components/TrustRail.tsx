import { StatusPill } from './StatusPill';
import { CONNECTION_LABEL, CONNECTION_TONE } from './presentation';
import type { Tone } from './presentation';
import type { ConnectionStatus, LaneSummary, RunState } from './types';

interface TrustRailProps {
  summaries: LaneSummary[];
  runState?: RunState;
  connection: ConnectionStatus;
}

interface RailNode {
  id: string;
  step: string;
  detail: string;
  tone: Tone;
  status: string;
}

const REPORTED_STATES: RunState[] = [
  'inventorying',
  'redacting',
  'planning',
  'awaiting_approval',
  'approved',
  'executing',
  'verifying',
  'completed',
  'failed',
];

function countWithEvidence(summaries: LaneSummary[], kind: string): number {
  return summaries.filter((summary) => summary.evidence.some((reference) => reference.kind === kind)).length;
}

function tally(count: number, total: number): Tone {
  if (count === 0) return 'neutral';
  return count === total ? 'positive' : 'progress';
}

function approvalNode(runState?: RunState): { tone: Tone; status: string; detail: string } {
  switch (runState) {
    case 'awaiting_approval':
      return { tone: 'attention', status: 'Awaiting decision', detail: 'One human decision covers all three lanes' };
    case 'approved':
    case 'executing':
    case 'verifying':
    case 'completed':
      return { tone: 'positive', status: 'Approved', detail: 'Decision recorded against the portfolio digest' };
    case 'cancelled':
      return { tone: 'critical', status: 'Rejected', detail: 'Portfolio decision blocked execution' };
    case 'failed':
      return { tone: 'critical', status: 'Blocked', detail: 'Portfolio failed before or during execution' };
    default:
      return { tone: 'neutral', status: 'Not requested', detail: 'Opens once every lane has a validated plan' };
  }
}

export function TrustRail({ summaries, runState, connection }: TrustRailProps) {
  const total = summaries.length;
  const reporting = summaries.filter(
    (summary) => summary.lane?.state !== undefined && REPORTED_STATES.includes(summary.lane.state),
  ).length;
  const redacted = countWithEvidence(summaries, 'redaction_report');
  const planned = summaries.filter((summary) => Boolean(summary.lane?.planDigest)).length;
  const dispatched = countWithEvidence(summaries, 'dataflow_job');
  const landed = countWithEvidence(summaries, 'bigquery_table');
  const approval = approvalNode(runState);
  const hostnames = summaries
    .map((summary) => summary.lane?.hostname || summary.presentation.hostname)
    .filter((hostname): hostname is string => Boolean(hostname));

  const nodes: RailNode[] = [
    {
      id: 'sources',
      step: 'Private legacy sources',
      detail: hostnames.length
        ? `${hostnames.join(' · ')} over Tailscale MagicDNS`
        : 'Tailscale MagicDNS reaches each ERP host; no public exposure',
      tone: connection === 'live' && reporting > 0 ? tally(reporting, total) : CONNECTION_TONE[connection],
      status: reporting > 0 ? `${reporting} of ${total} reporting` : CONNECTION_LABEL[connection],
    },
    {
      id: 'edge',
      step: 'Edge redaction · local Gemma',
      detail: 'Decode and protection run on private hardware; raw records stay put',
      tone: tally(redacted, total),
      status: redacted > 0 ? `${redacted} of ${total} redaction reports` : 'No reports yet',
    },
    {
      id: 'plan',
      step: 'Gemini 3.5 planning · Vertex AI',
      detail: 'Transform plans are generated from protected metadata only',
      tone: tally(planned, total),
      status: planned > 0 ? `${planned} of ${total} plan digests` : 'No plans yet',
    },
    {
      id: 'approval',
      step: 'Portfolio approval gate',
      detail: approval.detail,
      tone: approval.tone,
      status: approval.status,
    },
    {
      id: 'dataflow',
      step: 'Dataflow trusted execution',
      detail: 'Jobs appear only when the control plane emits real job evidence',
      tone: tally(dispatched, total),
      status: dispatched > 0 ? `${dispatched} of ${total} jobs evidenced` : 'Pending approval evidence',
    },
    {
      id: 'bigquery',
      step: 'BigQuery destination',
      detail: 'Tables are claimed only against verified table evidence',
      tone: tally(landed, total),
      status: landed > 0 ? `${landed} of ${total} tables evidenced` : 'Pending verified writes',
    },
  ];

  return (
    <section className="mc-rail-section" aria-labelledby="mc-rail-heading">
      <h2 className="mc-section-heading" id="mc-rail-heading">
        Trusted path
      </h2>
      <ol className="mc-rail">
        {nodes.map((node) => (
          <li className="mc-rail__node" key={node.id}>
            <p className="mc-rail__step">{node.step}</p>
            <StatusPill tone={node.tone} label={node.status} size="sm" />
            <p className="mc-rail__detail">{node.detail}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
