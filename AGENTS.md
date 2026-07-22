# Agent instructions for rosetta

Instructions for any AI coding agent (Claude Code, Codex, OpenCode, etc.) working in this repository.

## Before you start

Read [`skills/rosetta/SKILL.md`](skills/rosetta/SKILL.md) before writing or modifying code that uses rosetta. It is the authoritative quick reference for the public API, product catalog, data conventions, credentials, and caching behavior, with deeper detail in `skills/rosetta/references/`. If your harness supports Agent Skills natively, load the skill instead of re-deriving the API from source.

## Keep the docs and skill in sync — this is a hard requirement

The skill is a snapshot of the source. Any change that alters observable behavior MUST update the matching documentation **in the same PR**:

| If you change... | You must update... |
|---|---|
| `fetch()` / `assemble()` signatures, defaults, or behavior | `skills/rosetta/SKILL.md` + `skills/rosetta/references/api.md` |
| `catalog.yaml` (add/remove/deprecate products, variables, adapters) | `skills/rosetta/references/products.md` |
| `normalize.py` (renames, unit conversions, pipeline order) | `skills/rosetta/references/data-conventions.md` (+ `plotting.md` if dims/units/orientation guarantees change) |
| Caching (`_CACHE_VERSION`, cache keys, env vars, nuthatch config) | `skills/rosetta/references/troubleshooting.md` |
| Credentials/adapters (new source, auth flow, rate limits) | `skills/rosetta/references/products.md` + `troubleshooting.md` |
| Anything user-facing | `README.md` if it covers the topic |

Also update `skills/rosetta/examples/` if a change breaks or obsoletes an example. If you are unsure whether a change is documented, grep `skills/` and `README.md` for the function, product id, or parameter you touched — stale docs are treated as bugs.

## Repo conventions

- Package layout: `src/rosetta/` (import name `rosetta`, distribution `accord-rosetta`). Python ≥ 3.12, `uv` for dependency management.
- Tests: `pytest` for the unit suite; markers `integration`, `cds`, `network` gate live-network tests. New behavior needs tests.
- Caching lives only in `fetch._fetch_raw_cached` — never add `@cache` decorators inside adapters. Bump `_CACHE_VERSION` when adapter logic or normalization changes output.
- The catalog is declarative: prefer adding/adjusting `catalog.yaml` entries over special-casing code paths.
