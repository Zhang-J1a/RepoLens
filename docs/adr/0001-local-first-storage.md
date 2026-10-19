# ADR 0001: Local-First SQLite Storage

- Status: Accepted for V1, subject to measurement.
- Date: 2026-10-17

## Context

The first usable system must be easy to run on a developer workstation, test offline, and inspect when retrieval is wrong. Early scale and concurrency requirements are unknown. Separate vector, search, cache, and graph services would add operational cost before the data model and retrieval quality are proven.

## Decision

Use SQLite as the initial record store and FTS5 for lexical retrieval. Keep embeddings behind an optional provider/index interface. Store graph relationships in relational tables if and when V4 requires them. Evaluate PostgreSQL/pgvector or a dedicated graph/search service only against measured limitations.

## Consequences

- The initial installation has no database service dependency.
- Transactions, local backups, and deterministic tests remain straightforward.
- Concurrency, corpus size, and vector-query needs may eventually exceed the design; those are migration triggers, not reasons to preemptively add infrastructure.
- FTS5 availability must be checked in supported Python/SQLite builds, with a clear diagnostic if unavailable.
