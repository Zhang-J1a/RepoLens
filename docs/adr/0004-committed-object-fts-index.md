# ADR 0004: Committed Git Objects and FTS5 for V1.1

- Status: accepted
- Date: 2026-10-17
- Decision owners: RepoLens project

## Context

The first usable milestone must index arbitrary authorized local repositories
without running their code, mutating their checkout, or mixing uncommitted files
into a historical commit view. It also needs stable evidence locators and a
working retrieval path that runs without an API key or external database.

## Decision

- Resolve an explicit local commit/ref and enumerate its tree with fixed Git
  read commands. Read blob bytes from the local object database via
  `git cat-file --batch`; do not check out files or invoke repository tools.
- Disable Git replace refs and lazy fetching; do not use remote URLs to fetch.
  Ingestion indexes committed content only. Dirty and untracked working-tree
  content is intentionally excluded.
- Parse `.py` with Python's `ast`, recording full symbol spans and bounded,
  overlapping evidence chunks. If Python syntax is unsupported, keep a
  clearly-labeled text fallback rather than inventing AST symbols.
- Parse `.md` and `.markdown` with a small heading scanner that ignores fenced
  code. It is not a complete CommonMark implementation.
- Use SQLite and FTS5/BM25; store the exact commit, repository identity, Git blob
  ID, content hash, and repository-relative line spans. Search and evidence
  lookup require an exact snapshot ID.
- Keep the index outside the target checkout and Git directory. Skip symlinks,
  submodules, binary files, unsupported extensions, and non-regular modes.
  Reject snapshots containing non-UTF-8 or unsafe paths. Bound a file to 1 MiB,
  supported source per snapshot to 64 MiB, and the tree to 50,000 entries.
- Keep runtime dependencies in the Python standard library. Do not select an
  embedding provider before measuring a reviewed real-repository FTS baseline.

## Consequences

- The index is deterministic for a fixed local repository root, commit, and
  parser policy. Repository IDs intentionally differ for separate local clones.
- Index rebuild is transactional and idempotent; a failed rebuild preserves the
  previous complete snapshot. Schema changes currently require a new data
  directory; online migrations are not implemented.
- A commit/ref must already be locally available. Missing objects fail without
  implicit network access.
- FTS5 candidates are isolated by snapshot, but BM25 corpus statistics are
  shared by snapshots in the same database. Reproducible retrieval comparisons
  require a fresh database with a fixed snapshot set.
- Only Python/Markdown source is indexed in V1.1. Other languages and Markdown
  extensions are reported as unsupported, not silently represented as covered.
- The pinned Flask smoke run proves the CLI workflow and evidence shape only; it
  makes no retrieval-quality claim.
