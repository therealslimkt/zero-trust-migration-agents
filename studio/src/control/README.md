# Shared Control Contracts

The JSON Schemas in `plan/agents/schemas/` are canonical. `contracts.generated.ts` is the shared TypeScript surface consumed by the orchestrator and Skin Studio.

Do not place product contracts such as `SkinSpec`, `EventIR`, or `CueIR` here. Those belong to the deterministic product pipeline and are frozen separately.
