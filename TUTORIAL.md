# phip-cli — Tutorial

End-to-end walkthrough: stand up a server, register an identity,
create an object, log measurements against it, query, verify, and
publish a portable bundle. Everything below is real commands you can
copy-paste.

> **Audience:** anyone running PhIP from the command line. For the
> Python library, see
> [phip-py](https://github.com/mfgs-us/phip-py/blob/main/TUTORIAL.md).

## 0. Install

```bash
pip install git+https://github.com/mfgs-us/phip-cli
# (or `pip install phip-cli` once it's on PyPI)

phip --version
# phip-cli 0.0.1 (phip-py 0.1.0a2)
```

Optional: tab completion. For bash, add to your `.bashrc`:

```bash
eval "$(phip completion bash)"
```

## 1. Stand up a local server

```bash
git clone https://github.com/mfgs-us/phip-server
cd phip-server
PHIP_AUTHORITY=tutorial.local docker compose up -d
```

Sanity-check it:

```bash
curl -sf http://localhost:8080/healthz
# {"status":"ok","authority":"tutorial.local"}
```

## 2. Initialize phip-cli

```bash
phip init --remote http://localhost:8080 --authority tutorial.local
# Initialized phip at /home/you/.phip
#   identity: phip://tutorial.local/keys/default
#   remote:   origin -> http://localhost:8080
```

This creates `~/.phip/` with your keypair, registers the local server
as remote `origin`, and sets it as the default.

## 3. Register your key with the server

This step is easy to forget — without it, the server can't verify
your future PUSHes (it doesn't know your JWK):

```bash
phip key register
# Registered phip://tutorial.local/keys/default on origin
#   head_hash: sha256:...
```

## 4. Set the namespace shorthand (one-time, optional but nice)

```bash
phip config set default_namespace elements
```

Now you can refer to objects by short name (`transducer-047`) instead
of full URIs (`phip://tutorial.local/elements/transducer-047`). Every
URI argument in phip-cli accepts the shorthand.

## 5. Create your first object

```bash
phip object new component transducer-047 \
    --state prototype \
    --notes "PVDF-TrFE batch C, target 2.5 MHz"
# Created phip://tutorial.local/elements/transducer-047
#   type:      component
#   state:     prototype
#   head_hash: sha256:...
```

Read it back:

```bash
phip show transducer-047 --table
```

## 6. Log a measurement

The `log` composite hashes the file, uploads it as a content-addressed
blob, fetches the current chain head from the server, signs a
measurement event, and pushes it. One command:

```bash
# Make a fake CSV to ingest
cat > /tmp/freq_sweep.csv << 'EOF'
freq_hz,mag_db
1000,-1.2
2500,-0.1
4000,-1.8
EOF

phip log transducer-047 /tmp/freq_sweep.csv \
    --metric freq_response \
    --value 2500 --unit Hz \
    --rig bench-2 --instrument tek-mso64 \
    --notes "post-poling, RT"
# Logged freq_response on phip://tutorial.local/elements/transducer-047
#   blob:        sha256:...
#   event:       <uuid>
#   head_hash:   sha256:...
```

Look at the history again:

```bash
phip show transducer-047 --table
# phip://tutorial.local/elements/transducer-047
#   type=component state=prototype events=2
#
#   ts                    type         id        actor                                          ...
#   --------------------  -----------  --------  ---------------------------------------------  ...
#   2026-05-11T...        created      ...       phip://tutorial.local/keys/default             ...
#   2026-05-11T...        measurement  ...       phip://tutorial.local/keys/default             ...
```

## 7. Multiple measurements + drift, querying

Add a second sweep:

```bash
cat > /tmp/freq_sweep_post.csv << 'EOF'
freq_hz,mag_db
1000,-2.1
2500,-0.4
4000,-2.5
EOF

phip log transducer-047 /tmp/freq_sweep_post.csv \
    --metric freq_response \
    --value 2400 --unit Hz \
    --rig bench-2 \
    --notes "after re-poling"

phip query elements --table
# Lists every component you've created in this namespace.

phip history transducer-047 --table
# Full chronological history including both measurements.
```

For computing drift / stats / Cpk over the values, `phip-cli` is
deliberately not in the analysis business — pipe to whatever you
already use:

```bash
# Get every freq_response measurement on this element as JSON
phip history transducer-047 --all | jq '.events[] | select(.type=="measurement") | .payload | {ts: .as_of, v: .value}'
```

## 8. Trust but verify

`phip verify` re-walks the chain client-side and re-validates every
signature against the resolved actor JWK:

```bash
phip verify transducer-047
# phip://tutorial.local/elements/transducer-047
#   events checked: 3
#   events passed:  3
#   OK: chain valid
```

If the server lies about an event, this fails locally.

## 9. Lifecycle transitions

```bash
phip transition transducer-047 --to qualified --reason "passed FAI"
phip show transducer-047
# state will now be "qualified"
```

## 10. Relations between objects

Register a second object — the bench rig — and link it:

```bash
phip object new fixture bench-2 --state deployed
phip relate transducer-047 bench-2 --type located_at
```

## 11. Pack a portable bundle

The bundle is the cheapest form of cross-org PhIP — drop the file on
GitHub Pages or email it, and the receiver can `phip bundle verify`
it offline with no access to your server.

```bash
phip bundle pack transducer-047 --out /tmp/transducer-047.phip-bundle
# Wrote /tmp/transducer-047.phip-bundle (... bytes)
#   authority: tutorial.local
#   objects:   1
#   events:    4
#   producer:  phip://tutorial.local/keys/default

phip bundle unpack /tmp/transducer-047.phip-bundle
phip bundle verify /tmp/transducer-047.phip-bundle
# OK: bundle valid
```

## 12. Capability tokens (multi-actor)

Today phip-server only enforces a single bearer token (`PHIP_WRITE_TOKEN`),
but the protocol layer for capabilities is in place. To mint a
scoped, time-bounded token:

```bash
# Generate a separate identity to grant to
phip key generate bob --authority tutorial.local

# Mint a 24-hour token allowing bob to push measurements on widgets
phip token mint \
    --scope push_measurements \
    --object 'phip://tutorial.local/elements/*' \
    --granted-to phip://tutorial.local/keys/bob \
    --ttl-hours 24

# Decode it
phip token mint --scope read_state --object '*' --granted-to phip://tutorial.local/keys/bob | phip token decode -
```

## 13. Going offline + dry-run

Every write command takes `--dry-run`. Useful for scripting and for
"what would this actually send?":

```bash
phip log transducer-047 /tmp/freq_sweep.csv \
    --metric freq_response --value 2500 --unit Hz \
    --dry-run
# Prints the signed event JSON, makes no HTTP calls.
```

## 14. Plumbing (when you want to do it yourself)

The composite commands wrap these primitives. Use them directly when
you need to script around something unusual:

```bash
phip event new --phip-id phip://x/y/z --type measurement --payload '{"metric":"x"}' \
    | phip event sign - \
    | phip push -

phip canonicalize event.json | sha256sum   # roughly the event hash
phip uri parse phip://acme.example/parts/widget-001 --yaml
```

## 15. Schema validation

Catch malformed events before they hit the server:

```bash
phip schema list
# Validate a single signed event
phip schema validate signed_event.json --schema event
# Validate a full resolved object response
phip schema validate phip_get_output.json --schema object
# Validate a decoded capability token
phip schema validate token.json --schema capability-token
```

The `event` and `object` names are convenience aliases over `core.json`'s
`$defs/event` and the core object itself respectively — both validate
without needing to know JSON Schema `$ref` syntax.

## What's next

- **`examples/`** — copy-paste shell scripts that mirror this tutorial.
- **[phip-py tutorial](https://github.com/mfgs-us/phip-py/blob/main/TUTORIAL.md)** — same workflow as a Python library.
- **[phip-server tutorial](https://github.com/mfgs-us/phip-server/blob/main/TUTORIAL.md)** — running and operating the server.
- **[Spec](https://github.com/mfgs-us/phip)** — normative reference.

## Common gotchas

- **`KEY_NOT_FOUND` on first push?** You forgot `phip key register`. The server can't verify your signature without your actor's JWK.
- **`CHAIN_CONFLICT` on push?** Someone else pushed since you fetched the head. Re-run `phip log` (it re-fetches automatically) or call `phip get <uri>` to see the current head.
- **`OBJECT_EXISTS`?** Trying to `object new` an id that's already been created. Use `transition` to change its state.
- **`MISSING_CAPABILITY`?** The server has `PHIP_WRITE_TOKEN` set but you didn't pass it. Run `phip remote add ... --token X` or `phip token use <token> --remote NAME`.
- **`FOREIGN_NAMESPACE`?** Your event's `phip_id` doesn't match the URL's namespace. Usually a typo in the URI prefix.
