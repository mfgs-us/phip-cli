# Examples

Runnable shell scripts that mirror the [TUTORIAL](../TUTORIAL.md).

| File | What it shows |
|---|---|
| `quickstart.sh` | Zero-to-measurement-pushed in one script. Uses an ephemeral `$PHIP_HOME` so it doesn't touch your real config. |
| `transducer_session.sh` | Realistic fUS bench session: rig + instrument + element registration, pre/post-poling sweeps with attached screenshot, lifecycle transition, bundle pack + verify. |

Both assume a phip-server running locally on `:8080`:

```bash
git clone https://github.com/mfgs-us/phip-server
cd phip-server && PHIP_AUTHORITY=tutorial.local docker compose up -d
```
