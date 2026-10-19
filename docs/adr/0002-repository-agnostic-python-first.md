# ADR 0002: Repository-Agnostic Product, Python-First Parser

- Status: Accepted for V0/V1.
- Date: 2026-10-17

## Context

RepoLens is intended to analyze user-selected Git repositories, not one tutorial or knowledge-base repository. Supporting every language immediately would make parsing, evaluation, and provenance hard to validate. The workspace contains `all-in-rag` and `AgentGuide` as personal learning references; they must not become hidden product dependencies.

## Decision

Define repository identity and report/evidence contracts independently of language. Start V1 with Python AST plus Markdown and Git metadata. Isolate parsing behind adapters. Use the in-project synthetic Taskboard fixture for V0 contract checks, then select public real-world repositories for V1 evaluation after license and snapshot review.

## Consequences

- Python-first describes implementation order, not the product's eventual repository scope.
- Unsupported languages must be reported as unsupported/partially indexed rather than silently treated as plain text with complete structural coverage.
- Generalization claims require real-repository evaluation; passing the synthetic fixture is insufficient.
- The personal learning repositories are not copied, indexed, or required by this project.
