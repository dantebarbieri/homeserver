# Local model-assisted queue maintenance

Lidarr, Radarr and Sonarr keep their existing deterministic rules. Unresolved
imports and orphaned dead torrents can then consult the Studio's local Ollama
model. This is bounded triage and recovery, not an autonomous coding agent.
Bazarr is not part of this layer: it already uses Studio Whisper, has a
different API/retry lifecycle, and subtitle rewriting needs separate quality
evaluation.

## Authority and safeguards

The model chooses from actions that the helper has independently established
are eligible. It cannot supply paths, IDs, API requests, shell commands or
settings. There is no model-controlled `ManualImport`, file deletion, edition
switch, profile override, monitoring change, service restart or code execution.
Existing deterministic blocklisting/removal rules are unchanged.
Native scans can still perform normal policy-approved imports/upgrades; the
model cannot force a rejected replacement.

| Action | Independent conditions and effect |
|---|---|
| Retry import | A complete download, unchanged queue group, one known library identity and an existing path below the download roots. Submit the app's native `DownloadedAlbumsScan`, `DownloadedMoviesScan` or `DownloadedEpisodesScan`; native rejection rules still apply. |
| Refresh metadata | The same complete-download/identity gates. Refresh only the queued artist, movie or series, not a model-guessed replacement. |
| Recheck torrent | The client reports missing files; an orphan also needs exact-hash app history. Ask qBittorrent to verify bytes, without moving files or changing its category. |
| Remove imported orphan | Absent from the **fully paginated** app queue, still dead, a recheck already attempted and finished, exact-hash successful import history after its grab, and a complete library copy whose files physically exist. Remove only the torrent entry with `deleteFiles=false`; do not blocklist an already-imported release. |
| Review | Keep normal deduplicated attention handling. Never pretend an unresolved case is fixed. |

Known disk/permission, quality/profile, language and conflicting-identity
failures veto model-driven import retries before inference. The model still
sees untrusted titles/messages, so schema validation and fresh pre-execution
checks are required even when it appears to resist prompt injection.
Library completeness does not establish that an old import was the correct
edition; the orphan action therefore never changes the library.

Each helper makes at most three model calls per 30-minute cycle by default,
with a 60-second request timeout, 4096 context tokens, 128 output tokens,
thinking disabled and one-minute model keep-alive. Ollama serializes inference
and loads only one model. This is not a combined-load guarantee with Whisper.
`ARR_AI_MAX_CALLS` permits 1-6 calls and `ARR_AI_TIMEOUT` 5-120 seconds.
Unchanged review/shadow decisions and per-download model failures (timeouts,
invalid or HTTP-error responses) back off for six hours. An unreachable model
endpoint (tunnel starting, Studio asleep or rebooting) only skips the rest of
that cycle, without a per-download cooldown, so recovery resumes on the next
cycle. A model failure stops further inference for that cycle, but leaves
the normal maintenance rules and attention notifications available.

`/state/ai.json` records model, policy version, evidence fingerprint, decision,
attempted actions, native command ID when known and verification status.
Attempts are recorded **before** a mutating request, so a timeout or restart
does not repeat an uncertain request. At most two actions are attempted per
download while its record is retained (14 days). A submitted action is not a
successful import: later queue/client observations establish recovery.
Native work gets at least a minute to settle, and active checks/commands are
waited on for at most an hour; unresolved/exhausted cases remain visible.
The full helper is not read-only in `shadow`: only its **AI layer** is.
Use `DRY=1` as well when exercising the full maintenance engine without writes.

## Model selection

The first evaluation used ten synthetic, read-only cases: transient failures
in Lidarr/Radarr, Sonarr metadata, quality rejection, permissions, disk full,
an initial orphan recheck, a confirmed imported orphan, version mismatch and
an instruction embedded in a release title.

| Model/configuration | Expected action choices |
|---|---|
| `qwen3:8b`, thinking off, without code vetoes | 6/10 |
| `qwen3:8b`, thinking on, 2048 output tokens, without code vetoes | 7/10 |
| `qwen3:8b`, thinking off, with code vetoes | 10/10 |
| `qwen3.5:9b-q4_K_M`, thinking off, without code vetoes | 10/10 |

The tested 6.6 GB GGUF variant is selected explicitly. On this Studio,
`qwen3.5:9b` selected a 7.6 GB runtime variant which answered ordinary chat
but returned HTTP 501 ("structured output is unavailable") for the required
JSON schema. Do not substitute that alias without repeating the evaluation.
These cases do not measure general intelligence, import-mapping accuracy or
future failure rates. Model category labels are diagnostic, not confidence
scores or authorization.

Live read-only evaluation exposed another requirement: historical import
failures must be shown with their later successful completion, and a complete
library must not be confused with a healthy torrent client. The final prompt
and chronological evidence passed 12/12 raw cases (the original ten plus two
history/recheck regressions). All nine real missing-file orphans received a
recheck recommendation; only eight had sufficient library proof for possible
subsequent removal. A live canary's recheck restored its seeding state, with
the library file's SHA-256 unchanged; no removal was needed.

Run the opt-in evaluation from a trusted checkout in a container that can
reach the private endpoint:

```sh
python docker/tests/evaluate_arr_ai.py
python docker/tests/evaluate_arr_ai.py --raw
python -B -m unittest discover -s docker/tests -p 'test_arr_maint*.py'
```

`--raw` omits deterministic diagnostic vetoes to measure model judgment.
Neither evaluation invokes a media/download API.

## Transport and rollout

See [Studio AI transport](../../macos/ai/README.md#ollama-transport).
The `studio-ollama` service is an SSH local forward, not a public HTTP server.
It shares `arr-ai` only with the three helpers. No ports are published.
Its independent `_arrmaint` identity can forward only to Studio
`127.0.0.1:11434`, with no shell/session, other destination or admin access.
The existing Bazarr/Whisper key and account retain their separate permissions.

The main Compose project reserves `10.253.240.16/29` for this network.
Do not start a category file as a separate Compose project.

1. Provision the dedicated transport and pull the tested model on Studio.
2. Add `arr-ai` to the production `COMPOSE_PROFILES` value, preserving existing
   profiles. Set `ARR_AI_MODE=shadow` in `docker/.env`.
3. From the main Compose entry point, build `studio-ollama lidarr-maint`, then
   recreate only `studio-ollama lidarr-maint radarr-maint sonarr-maint`.
   All helpers use the same `arr-maint` image.
4. Verify the tunnel's health and model evaluation, and inspect real queue
   recommendations. Then set `ARR_AI_MODE=auto` and recreate the three helpers.

`AI:` logs record the proposed action; `ACTION: ... submitted` is not a
success claim. `AI VERIFIED:` means a later observation no longer finds the
download blocked/dead, not necessarily that an import completed.
Attention messages never include media names or model output.

Rollback: set `ARR_AI_MODE=off` and recreate only the three helpers. The
deterministic engine remains available if Studio is down. Stop `studio-ollama`
and remove `arr-ai` from `COMPOSE_PROFILES` if retiring the connection.
Keep `ai.json` when rolling back so uncertain attempts are not forgotten.
Never restore a whole old `.env` over unrelated newer changes. The nightly
update rebuilds `arr-maint` from `main`, so a code rollback must be a reverted
commit; `arr-maint:rollback-pre-ai` is only the one-off pre-integration image.

After a recreate, the helpers' first cycle can start before the tunnel has
connected; that cycle skips the model and the next one uses it.

## Production status

Since 2026-11-14 production runs `ARR_AI_MODE=auto` with the `arr-ai` profile
enabled. Its first cycle rechecked three missing-file Lidarr orphans: two
resumed seeding and one resumed downloading its missing remainder. The other
orphans proceed at three model calls per cycle. Radarr and Sonarr queues were
empty, so their paths are covered by unit, contract and model tests rather
than live repairs.

Dante disabled the cloud "Lidarr queue watch" schedule when this went into
`auto`. It can still be run manually for code-defect investigation, which this
fixed-action local layer does not perform.
