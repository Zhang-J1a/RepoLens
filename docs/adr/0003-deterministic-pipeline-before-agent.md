# ADR 0003: Deterministic Retrieval Before Agent Orchestration

- Status: Accepted for V0-V2.
- Date: 2026-10-17

## Context

An agent can obscure basic failures in parsing, retrieval, version filtering, and citation validation. Autonomous tool use also increases permission, latency, and evaluation complexity.

## Decision

Implement and evaluate deterministic ingestion, retrieval, evidence assembly, and report validation before introducing an Agent loop. When an Agent is added, it must call a fixed allow-list of read-only tools under explicit step, time, and result budgets.

## Consequences

- V1/V2 can be debugged and measured without model behavior in the loop.
- Agent work is gated on a useful non-Agent pipeline and a concrete requirement deterministic orchestration cannot meet.
- The model may summarize validated evidence but cannot invent tools, widen repository access, or override evidence/version constraints.
