# Milestone delivery-report gate

Every implementation milestone must finish with a detailed delivery report.
The report is a mandatory release artifact, not an optional status update.

## Required sequence

1. Fetch `origin` and verify the milestone branch is based on an up-to-date
   local `main`.
2. Implement and integrate the milestone in isolated worktrees.
3. Run the complete milestone and compatibility gates.
4. Write identical `milestone_<number>_delivery_report.md` files in the
   workspace-root and repository `delivered` directories.
5. Commit the repository copy on the milestone integration branch before the
   final milestone merge.
6. Merge the completed milestone into local `main`, push `main` to `origin`,
   and verify zero local/remote divergence.
7. Pause all subsequent milestone work and alert the user that the milestone
   is ready to review and check out.

The pause and review alert must not occur until the delivery report exists and
the local and repository copies are identical.

## Required report contents

Each report must include:

- A plain-language milestone summary and the problem it solves.
- Detailed changes grouped by each promised deliverable.
- Concrete examples of new behavior, interfaces, schemas, commands, or
  failure handling.
- Important files and public API or contract changes.
- Security, compatibility, authority, and data-handling decisions.
- Exact verification commands and results.
- Commit and merge identifiers.
- Known risks, truthful capability labels, and deliberately deferred work.

The report must distinguish implemented behavior from architecture targets,
fixtures, previews, simulated evidence, and live cloud proof.
