# phip-cli (`phip`)

[![CI](https://github.com/mfgs-us/phip-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/mfgs-us/phip-cli/actions/workflows/ci.yml)
[![spec](https://img.shields.io/badge/spec-v0.1.0--draft-blue)](https://github.com/mfgs-us/phip)

`phip` — the command-line interface for the
[Physical Information Protocol](https://github.com/mfgs-us/phip).
Talks to [phip-server](https://github.com/mfgs-us/phip-server),
manages local identities and remotes, and exposes the protocol
primitives (sign/verify/hash/canonicalize/URI-parse) as plumbing
commands. Built on
[phip-py](https://github.com/mfgs-us/phip-py); one Python
implementation of the protocol primitives, used everywhere.

> **Status:** `0.0.1` alpha. Mirrors the v0.1.0-draft spec. Expect
> breaking changes.

## Install

```bash
pip install git+https://github.com/mfgs-us/phip-cli
phip --help
```

## 60-second tour

```bash
# Spin up a local phip-server (separate repo)
git clone https://github.com/mfgs-us/phip-server
cd phip-server && docker compose up -d
cd ..

# Init identity + register the local server, then register your key
# with that server so subsequent pushes can be verified
phip init --remote http://localhost:8080 --authority localhost
phip key register

# Inspect state
phip whoami
phip remote list
phip key list

# Hit the server
phip meta
phip query parts --type component --table

# Build, sign, and create an object
phip event new \
  --phip-id phip://localhost/parts/widget-001 \
  --type created \
  --payload '{"object_type":"component","state":"concept"}' > widget.json
phip event sign widget.json > widget.signed.json
phip create widget.signed.json

# Append a measurement: file -> blob -> signed event -> push, in one shot
phip log phip://localhost/parts/widget-001 ./tek_sweep.csv \
  --metric freq_response --value 2.5e6 --unit Hz --rig bench-2

# Read it back, formatted
phip show phip://localhost/parts/widget-001 --table

# Re-walk the entire chain client-side and re-validate signatures
phip verify phip://localhost/parts/widget-001

# Pack a portable, signed bundle of one object's full history
# (drop on GitHub Pages → anyone can `phip bundle verify` it offline)
phip bundle pack phip://localhost/parts/widget-001 --out widget.phip-bundle
```

## Commands

### Setup

| Command | What it does |
|---|---|
| `phip init [--remote URL] [--authority X]` | Create `~/.phip/`, generate a key, optionally register a remote |
| `phip whoami` | Show the current default identity + remote |

### Identities

| Command | What it does |
|---|---|
| `phip key generate <name> --authority X` | Generate a new Ed25519 keypair |
| `phip key list` | List local identities |
| `phip key show <name>` | Print JWK + URI |
| `phip key use <name>` | Set the default identity |
| `phip key register [name] [--remote X]` | Push the bootstrap actor event for an identity to a remote (required before any other PUSH from that key can be verified) |

### Remotes

| Command | What it does |
|---|---|
| `phip remote add <name> <url> [--token X] [--authority Y]` | Register a phip-server endpoint |
| `phip remote list` | List remotes |
| `phip remote show <name>` | Show one remote's config (token redacted) |
| `phip remote rm <name>` | Delete a remote |
| `phip remote use <name>` | Set the default remote |

### Server integration

| Command | What it does |
|---|---|
| `phip meta` | `GET /.well-known/phip/meta` |
| `phip get <phip-uri>` | `GET /resolve/...` — current state + history tail |
| `phip history <phip-uri> [--all]` | Paginated event history; `--all` walks every page |
| `phip show <phip-uri> [--all]` | Formatted, human-readable history view |
| `phip create <event-file>` | `POST /objects/{namespace}` for a `created` event |
| `phip push <event-file>` | `POST /push/{namespace}/{local_id}` for any other event |
| `phip log <phip-uri> <file> --metric M [...]` | Composite: hash blob → upload → fetch head → sign measurement → push, all in one command |
| `phip query <namespace> [--type/--state/--prefix]` | `POST /query/{namespace}` |
| `phip verify <phip-uri>` | Fetch full chain, re-walk + re-validate every signature client-side |
| `phip blob put <file>` | Hash + upload a file; prints sha256 |
| `phip blob get <sha256> [--out FILE]` | Download a blob |

Event files can be `-` to read from stdin (useful in pipes).

Every read-side command (`get`, `history`, `query`, `meta`, `show`)
takes `--format json|yaml|table`, with `--yaml` and `--table` as
shorthand. Default is `json`.

### Bundles (offline, federation-ready)

| Command | What it does |
|---|---|
| `phip bundle pack <phip-uri> [...] --out FILE` | Fetch one or more objects + full history from the remote, sign as producer, write a self-contained `.phip-bundle` |
| `phip bundle unpack <FILE>` | Print bundle manifest + contents |
| `phip bundle verify <FILE>` | Full integrity check (manifest signature + every event chain link + every event signature), no network required |

The "publish a transducer's full provenance alongside a paper" workflow:

```bash
phip bundle pack phip://acme.example/elements/transducer-047 \
    --out site/transducer-047.phip-bundle
# scp / git push site/ → anywhere static
# Reader runs: phip bundle verify transducer-047.phip-bundle
```

### Plumbing

| Command | What it does |
|---|---|
| `phip event new --phip-id X --type T --payload JSON` | Build an unsigned event scaffold |
| `phip event sign <file>` | Sign with the default identity (or `--key NAME`) |
| `phip event verify <file>` | Verify a signature against a known JWK |
| `phip event hash <file>` | Compute the canonical event hash |
| `phip uri parse <uri>` | Parse a `phip://` URI to JSON |
| `phip uri format --authority/--namespace/--local-id` | Build a `phip://` URI |
| `phip canonicalize <file>` | JCS-canonicalize (RFC 8785) a JSON document |

## Storage layout

```
~/.phip/
├── config.json              # default identity + default remote
├── keys/<name>.json         # Ed25519 keypairs (chmod 600 on POSIX)
└── remotes.json             # registered phip-server endpoints
```

The CLI is stateless beyond this directory. Override the location
with `PHIP_HOME=/some/path` for tests or alternate profiles.

## Why Python and not Go?

The architecture originally envisioned `phip-cli` in Go for a static
binary. We changed direction:

- The stack is Python end-to-end (`phip-py`, `phip-server`).
  Re-implementing canonicalization, Ed25519 signing, and chain
  validation in Go would mean two sources of truth for the
  primitives and a perpetual cross-language sync tax.
- The first user of this CLI (the maintainer) is on a laptop with
  Python already installed; a static Go binary isn't pulling weight.
- If a static binary becomes useful later (operators packaging
  appliances, embedded targets), `pyinstaller` produces one from
  this codebase. The Go rewrite was hypothetically motivated.

## License

Apache 2.0.

## Repository

[github.com/mfgs-us/phip-cli](https://github.com/mfgs-us/phip-cli) ·
[spec](https://github.com/mfgs-us/phip) ·
[phip-py](https://github.com/mfgs-us/phip-py) ·
[phip-server](https://github.com/mfgs-us/phip-server)
