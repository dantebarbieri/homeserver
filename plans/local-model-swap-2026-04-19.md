# Local model swap — 2026-04-19

## Context

`qwen3.5:27b` on `pc` is consumed via LiteLLM on `server` and `llmrouter` on `server` by OpenClaw on `pi`. The model has a confirmed open Ollama bug ([ollama/ollama#14493](https://github.com/ollama/ollama/issues/14493)) that routes the Qwen-3.5 family through the wrong tool-call parser: tool_calls silently land as text in the `content` field, repetition penalties are ignored, and `</think>` tags aren't closed across multi-turn tool chains. The same issue also affects `qwen3.5:35b-a3b` per community reports. For an MCP-heavy agentic workload this is unacceptable silent degradation.

**Goal:** swap the underlying Ollama model on `pc` for one whose tool-call path is correct in Ollama today; keep the LiteLLM tier names (`qwen-local`, `qwen-local-thinking`) stable so `llmrouter` and OpenClaw need at most a cosmetic label change.

## Host-state inventory (recorded 2026-04-19, read-only)

- **`pc`** — Windows 11, OpenSSH over `cmd.exe`, Ollama **v0.20.2**, RTX 4090 (24 564 MiB total). Current: `qwen3.5:27b`, 17 GB GGUF, digest `7653528ba5cb`, loaded with 8K context using 22 GB VRAM (→ 1 254 MiB free). Model defaults: `temperature=1, top_k=20, top_p=0.95, presence_penalty=1.5`. Ollama modelfile shows `RENDERER qwen3.5 / PARSER qwen3.5` — the pipelines implicated in #14493.
- **`server`** — NixOS, Docker stack. Live `compose.ai.yml` contains `llmrouter` service (the openclaw-repo snapshot lacks it — drift confirmed). Live LiteLLM config at `/srv/docker/data/litellm/config/config.yaml` matches the planning mirror (no drift).
- **`pi`** — Raspberry Pi 4 running OpenClaw as `openclaw` user; addresses models by tier name (`qwen-local`, `qwen-local-thinking`). Zero structural change needed if tier names stay stable; only `name:` labels become stale.

## Second opinion on `~/Programming/openclaw/RESEARCH.md`

Mostly agree on motivation. Disagree on three specifics.

**Agree.** #14493 is real, open, blocking, user-unfixable. Swap is justified.

**Agree.** Qwen3-30B-A3B-Instruct-2507 is the right *family* — lives under the `qwen3` renderer/parser (not `qwen3.5`), mature Hermes-style tool template, first-party Ollama tag exists, Unsloth imatrix GGUFs carry template fixes.

**Disagree #1 — quant choice.** RESEARCH.md recommends Unsloth **UD-Q5_K_XL (21.7 GB)** and claims "32K context, 64K with step-down." On a 24 564 MiB card that math is wrong. The current `qwen3.5:27b` at 17 GB weights loads to **22 GB at 8K context** (confirmed by `ollama ps`). A 21.7 GB Q5 weight file would leave <3 GB for KV + runtime buffers — 32K context is already over-budget. Correct pick for this hardware is **UD-Q4_K_XL (17.7 GB)** — same quality tier as the current Q4_K_M, imatrix-tuned on tool-call data, real KV headroom for 32K at FP16 or ~64K with Q8 KV cache.

**Disagree #2 — think-flag split.** RESEARCH.md sidesteps that **Qwen3-Instruct-2507 does not support thinking mode at all** (per the model card: "supports only non-thinking mode … does not generate `<think></think>` blocks … `enable_thinking=False` no longer required"). The current LiteLLM config's two-entry split (`qwen-local` / `qwen-local-thinking`) uses `extra_body.think: true/false` — a no-op on Instruct-2507. Keeping both entries pointed at Instruct-2507 is architecturally dishonest: `llmrouter` sends "thinking-needed" queries to the `local-thinking` tier, and the local model would answer them without any reasoning lap. Cleaner redesign: keep the tier *name* stable but repoint the thinking tier to `claude-sonnet` at the LiteLLM layer.

**Disagree #3 — missed the newer model.** RESEARCH.md was written 2026-04-18. **Qwen 3.6-35B-A3B** shipped 2026-04-16 with first-day Ollama support (`qwen3.6:35b-a3b-q4_K_M`, 24 GB) and an explicit `ollama launch openclaw --model qwen3.6` endorsement from the Ollama team. Hybrid thinking (would keep the two-entry split working via `chat_template_kwargs.enable_thinking`), scores 73.4% SWE-Bench and 37.0% MCPMark (vs Gemma 4's 18.1%). **Not recommending as primary** because (a) 3 days old — Gemma 4 demonstrated that models 2 weeks post-release still ship with streaming tool-call bugs and 3.3× speed regressions on Ollama, (b) the Ollama library Q4_K_M is 24 GB which leaves ~0 GB for KV cache on a 24 564 MiB card — Unsloth `UD-IQ4_XS` (17.7 GB) is the only sensible fit. **Do recommend as the Plan B runner-up** — same VRAM footprint as the primary, revisit in 2-4 weeks once the community has shaken out bugs.

## Decision

**Revised 2026-04-19 post-Qwen-3.6 attempt:** User first chose Qwen 3.6 over the original Instruct-2507 recommendation, accepting the 3-day-post-release risk for the Ollama-OpenClaw endorsement and hybrid thinking. Execution proved this infeasible on this hardware (detail in *Appendix D*): the architecture (`qwen35moe`) is new, no Ollama-library Qwen 3.6 quant is under 22 GB, the Unsloth UD-IQ4_XS (17.7 GB) crashes on load because Ollama 0.21.0's bundled llama.cpp doesn't parse the Unsloth GGUF's SSM/mmproj layers, and the only runnable Ollama-library tag (`qwen3.6:35b-a3b-q4_K_M`, 23 GB) spilled 13 % to CPU with only 802 MiB free. User then chose Plan B.

**Primary model:** Qwen3-30B-A3B-Instruct-2507, Unsloth imatrix 4-bit dynamic quant.

- **Ollama tag:** `hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL`
- **GGUF size:** 17.7 GB on disk; **measured on pc (2026-04-19)**: loaded 18 GB at 100 % GPU with 5.7 GB VRAM free at 8K context — real headroom for 32K.
- **Architecture:** 30.5B total / 3.3B active (MoE, 128 experts, 8 routed + 1 shared), 48 layers, GQA (32 Q heads / 4 KV heads), native 262K context, Apache 2.0 — internal arch `qwen3moe` (distinct from the new `qwen35moe` in Qwen 3.6 that Ollama 0.21's llama.cpp doesn't parse from Unsloth packaging).
- **Thinking:** not supported per Qwen's model card. The `qwen-local-thinking` LiteLLM tier is therefore redesigned to route directly to `claude-sonnet-4-6` — keeps the tier name stable so `llmrouter` and OpenClaw need no code change.
- **Tool template:** Hermes-style `<tool_call>…</tool_call>` handled by the `qwen3` renderer/parser in Ollama; Unsloth's template fixes are baked into their GGUF (Qwen3-Coder GGUF discussion #10).
- **Measured throughput:** ~187 tok/s decode, ~3000 tok/s prompt eval on the tool-call smoke-test vs ~20–25 tok/s expected for dense qwen3.5:27b (not directly measured this session).

**Runner-up / fallback:** revert to `qwen3.5:27b` (digest `7653528ba5cb…`, still in registry). The original RESEARCH.md-style Qwen 3.6 path remains archived in *Appendix D* as a post-mortem; not re-attempting without Ollama shipping a smaller library quant.

**Deferred until mainline-adopted:** TurboQuant — still llama.cpp-fork-only as of 2026-04; no Ollama support path.

## VRAM budget (RTX 4090, 24 564 MiB total)

Qwen3-30B-A3B: 48 layers × 4 KV heads × 128 head_dim → 2 KB/token/layer KV (FP16).

| Item | FP16 KV | Q8 KV |
|---|---|---|
| Weights (UD-IQ4_XS) | 17.7 GB | 17.7 GB |
| KV @ 32K ctx | ~3.0 GB | ~1.5 GB |
| KV @ 64K ctx | ~6.0 GB | ~3.0 GB |
| Framework overhead (CUDA graphs, attn scratch) | ~1.5 GB | ~1.5 GB |
| **Total @ 32K** | **~22.2 GB ✅** | **~20.7 GB ✅** |
| **Total @ 64K** | **~25.2 GB ❌** | **~22.2 GB ✅** |

**Recommendation:** start at `num_ctx: 32768` with Ollama default FP16 KV — 2.3 GB headroom. To raise to 64K later, set `OLLAMA_KV_CACHE_TYPE=q8_0` in the Ollama service env on pc.

**Why not the official `qwen3.6:35b-a3b-q4_K_M` (24 GB):** it's baked at standard Q4_K_M (~22.1 GB weights), which loads to ~25 GB on a 24 GB card — not enough KV room. Unsloth's UD-IQ4_XS (17.7 GB, imatrix-tuned) is both smaller and higher-quality-per-bit than the default Ollama tag.

## LiteLLM config diff

Target file: `/srv/docker/data/litellm/config/config.yaml` on `server` (mounted read-only into the `litellm` container at `/app/config.yaml`).

Instruct-2507 is **not** hybrid-thinking (per Qwen's model card — "supports only non-thinking mode"). Two-entry split is preserved by tier **name** only: `qwen-local-thinking` is repointed at `claude-sonnet-4-6` at the LiteLLM layer so the llmrouter's "thinking-needed" classifications reach a model that can actually think. `llmrouter` and OpenClaw are unchanged.

```yaml
model_list:
  - model_name: qwen-local
    litellm_params:
      model: ollama_chat/hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL
      api_base: http://192.168.50.180:11434
      keep_alive: -1
      stream: false
      temperature: 0.7
      top_p: 0.8
      top_k: 20
      min_p: 0
      num_ctx: 32768
    model_info:
      supports_function_calling: true

  # "Thinking" tier: Sonnet-backed because Instruct-2507 has no thinking mode.
  # Tier name stays stable so llmrouter + OpenClaw need no code change.
  - model_name: qwen-local-thinking
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
    model_info:
      supports_function_calling: true

  - model_name: claude-haiku
    litellm_params:
      model: anthropic/claude-haiku-4-5-20251001
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: claude-sonnet
    litellm_params:
      model: anthropic/claude-sonnet-4-6
      api_key: os.environ/ANTHROPIC_API_KEY
  - model_name: claude-opus
    litellm_params:
      model: anthropic/claude-opus-4-7
      api_key: os.environ/ANTHROPIC_API_KEY

litellm_settings:
  fallbacks:
    - qwen-local: [claude-haiku, claude-sonnet]
    - qwen-local-thinking: [claude-sonnet, claude-haiku]
    - claude-haiku: [claude-sonnet]
    - claude-opus: [claude-sonnet]
  drop_params: true
  request_timeout: 600

general_settings:
  master_key: os.environ/LITELLM_MASTER_KEY
  database_url: os.environ/DATABASE_URL
```

Key changes vs current file:
- `ollama_chat/` prefix preserved (never `ollama/`).
- Dropped `extra_body.think: true/false` — was a no-op on Instruct-2507 (no thinking mode) and wrong field-name convention for Qwen anyway.
- Added `keep_alive: -1`, `stream: false` — per LiteLLM issues #17954, #12557, #6135.
- Added `supports_function_calling: true` — without it LiteLLM silently downgrades to prompt-injected JSON mode.
- Exact quant tag pinned, no floating `:latest`.
- Qwen's recommended sampling: `temp=0.7, top_p=0.8, top_k=20, min_p=0`.
- `num_ctx: 32768` — fits VRAM (measured 5.7 GB free at 8K → ~2 GB at 32K).
- `qwen-local-thinking` tier now Sonnet-primary at `model_list`; fallbacks augmented with `claude-haiku`.

## llmrouter impact assessment

**No code change required.** `llmrouter.app.py` routes by tier *name*, and both `qwen-local` and `qwen-local-thinking` stay in `TIER_TO_MODEL`. The local-tier fallback still works: if Ollama goes unreachable, `local` still promotes to `sonnet`; `local-thinking` already resolves to Sonnet at the LiteLLM layer so the promotion is a pass-through.

**Deferred (not part of this swap):** the `CLASSIFIER_MODE` heuristic in `app.py` still classifies "secret-keyword" and "ambiguous-but-moderate" as `local-thinking`. After this swap those all hit Sonnet, which is more expensive than the current arrangement claims to be. A follow-up PR can re-tune the heuristic, but it's orthogonal to the immediate tool-call-correctness fix.

## OpenClaw impact assessment

Cosmetic `name:` updates only — model IDs unchanged. Target file: `/home/openclaw/.openclaw/openclaw.json` on `pi`.

```diff
       {
         "id": "qwen-local",
-        "name": "Qwen 3.5 27B (local)",
+        "name": "Qwen3-30B-A3B-Instruct-2507 (local)",
         "reasoning": false,
         ...
       },
       {
         "id": "qwen-local-thinking",
-        "name": "Qwen 3.5 27B (local-thinking)",
+        "name": "Thinking (→ Claude Sonnet)",
         "reasoning": true,
         ...
       },
```

Round-trip path (per `~/Programming/openclaw/HOSTS.md`):
1. Edit the local mirror `~/Programming/openclaw/openclaw.json`.
2. `scp openclaw.json danteb@pi:/tmp/openclaw.json` (normal user account).
3. From the `openclaw` shell on pi: `cp /tmp/openclaw.json ~/.openclaw/openclaw.json && chown openclaw:openclaw $_`.
4. `systemctl --user restart openclaw-gateway`.
5. `openclaw secrets audit` — expect `plaintext=0, unresolved=0`.

## Smoke-test

Script lives alongside this plan at `~/Programming/HomeServer/plans/smoke-test.sh`. Four checks, exits non-zero on any failure. Two modes selected by first arg:

- `./smoke-test.sh before` → expects the current (pre-swap) state, i.e. `qwen3.5:27b` on pc.
- `./smoke-test.sh after` → expects the post-swap state, i.e. the new Unsloth GGUF tag on pc.

Checks:
1. `ssh pc 'ollama list'` — target tag present.
2. `ssh server '... /v1/models ...'` — `qwen-local` and `qwen-local-thinking` resolvable on LiteLLM (secret sourced from server-side `.env`, never piped locally).
3. `ssh server 'curl https://llmrouter.danteb.com/v1/chat/completions ...'` — trivial prompt with `model=qwen-local` returns HTTP 200 with non-empty content.
4. `ssh server 'curl ... qwen-local + tools=[get_weather(city)] ...'` — single-tool schema returns a well-formed `tool_calls` array, not JSON-in-content. (This is the whole point of the swap.)
5. (Best-effort) `ssh pi 'sudo -iu openclaw -- openclaw health'` — if sudo -iu to openclaw is blocked in this environment, the script SKIPs and warns rather than failing.

## Execution order — Phase 2

Destructive / irreversible steps marked ⚠.

1. **Pre-flight.** Run `smoke-test.sh before` on the current stack; confirm baseline green. Append `ollama show qwen3.5:27b` and `ollama list` output to this plan file for rollback reference. Confirm Anthropic fallback healthy (one-word prompt with `model=claude-haiku` via llmrouter returns 200); abort if not.
2. **Pull new model on pc.** `ssh pc 'ollama pull hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS'`. Verify size ≈ 17.7 GB. **Do not delete old model yet** — both on disk is fine.
3. **Model-level smoke test on pc.** `ssh pc 'ollama run hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS "reply OK"'` — expect `OK`. Then a raw one-tool POST to `http://192.168.50.180:11434/api/chat` — expect well-formed `tool_calls`.
4. **VRAM check.** `ssh pc 'nvidia-smi'`. If `memory.free` < 1 GB with new model loaded, abort + rollback before any LiteLLM edit — no KV headroom at production context lengths.
5. ⚠ **Point of no return.** `ssh pc 'ollama rm qwen3.5:27b'`. Record `ollama list` before and after. From here, rollback requires re-pulling the old model.
6. **Edit LiteLLM config.** Read the live file on `server`, apply the diff, write back. Keep `.bak-2026-04-19` on the server for the rollback window. The file at `/srv/docker/data/litellm/config/config.yaml` is not git-tracked; reference mirror at `~/Programming/openclaw/litellm.config.yaml` gets synced separately (step 13).
7. **Restart LiteLLM.** `ssh server 'cd /srv/homeserver/docker && dcr litellm'`. Poll `http://localhost:4000/v1/models` until the new tier resolves, timeout 60 s.
8. **llmrouter.** No change required. (Verified: tier names stable, classifier code path unaffected.)
9. **OpenClaw cosmetic update.** Round-trip `openclaw.json` per the HOSTS.md procedure. Restart `openclaw-gateway`. Run `openclaw secrets audit` — expect `plaintext=0, unresolved=0`.
10. **End-to-end smoke-test.** Run `smoke-test.sh after`. Green → step 12. Red → step 11.
11. ⚠ **Auto-rollback (only if step 10 failed).** Restore LiteLLM `.bak` → `dcr litellm` → `ssh pc 'ollama pull qwen3.5:27b'` → revert openclaw.json → restart gateway → re-run `smoke-test.sh before`. Report failure mode verbatim to the user. **Stop.** Do not try Plan B without explicit user approval.
12. **Burn-in (5 min).** `ssh server 'dcl -s 5m llmrouter'` in one window, `dcl -s 5m litellm` in another. Fire three test prompts through `https://llmrouter.danteb.com`: (a) no-tool trivial completion, (b) one-tool call, (c) two-step tool chain. Each response must have `tool_calls` populated when tools are supplied, not JSON-in-content.
13. **Final report.** Append to this plan file: the deployed Ollama tag + digest, LiteLLM tier names, VRAM usage at idle and under one concurrent request, the three burn-in test outputs verbatim, any warnings or anomalies from the llmrouter/litellm logs. Commit this plan file + smoke-test script + updated snapshot mirrors (`~/Programming/openclaw/compose.ai.yml`, `~/Programming/openclaw/litellm.config.yaml`, `~/Programming/openclaw/openclaw.json`). Do not push.

## Rollback plan

Artifacts to capture at step 1:
- Output of `ssh pc 'ollama show qwen3.5:27b'` (full; digest `7653528ba5cb` already recorded above)
- Output of `ssh pc 'ollama list'`
- `ssh server 'cp /srv/docker/data/litellm/config/config.yaml /srv/docker/data/litellm/config/config.yaml.bak-2026-04-19'`
- `scp danteb@pi:/tmp/openclaw.json.bak-2026-04-19 /Users/danteb/Programming/openclaw/openclaw.json.bak-2026-04-19` (populated via the round-trip procedure before the edit)

Pre-rm verify (step 5 pre-check): `curl -fsS -I https://registry.ollama.ai/v2/library/qwen3.5/manifests/27b` returns 200. If not 200, abort before the `ollama rm`.

Reversal commands (run only from step 11):
```sh
# LiteLLM
ssh server 'mv /srv/docker/data/litellm/config/config.yaml.bak-2026-04-19 /srv/docker/data/litellm/config/config.yaml'
ssh server 'cd /srv/homeserver/docker && dcr litellm'
# Ollama (slow — re-downloads 17 GB)
ssh pc 'ollama pull qwen3.5:27b'
# OpenClaw (via the HOSTS.md round-trip)
scp /Users/danteb/Programming/openclaw/openclaw.json.bak-2026-04-19 danteb@pi:/tmp/openclaw.json
# Then as openclaw on pi: cp /tmp/openclaw.json ~/.openclaw/openclaw.json && chown openclaw:openclaw ~/.openclaw/openclaw.json && systemctl --user restart openclaw-gateway
```

## NTFY watch

During Phase 2 steps 2–12, tail the llmrouter ntfy topic in a separate window:
```sh
curl -s https://ntfy.danteb.com/llmrouter/json | jq -r '[.time, .title, .message] | @tsv'
```
Any "Ollama unreachable" alert between steps 5 and 7 means the swap broke the local tier; don't ignore it while proceeding. (Between step 2 and step 5 the old model is still loaded, so alerts there indicate an unrelated problem.)

## Estimated wall-clock

| Step | Duration |
|---|---|
| `ollama pull` of 17.7 GB at ~50 MB/s over gigabit to pc's Windows disk | ~6 min |
| Model-level smoke tests (basic gen + tool-call round-trip) | ~1 min |
| LiteLLM edit + restart + `/v1/models` poll | ~2 min |
| OpenClaw config round-trip + gateway restart + audit | ~2 min |
| Burn-in (5 min) | 5 min |
| **Total (green path)** | **~16 min** |

Double that budget for contingencies.

## Sources (primary, verified 2026-04-19)

- [ollama/ollama#14493 — Qwen 3.5 27B tool calling completely non-functional](https://github.com/ollama/ollama/issues/14493) — open; confirmed affects `qwen3.5` family incl. `35b-a3b`
- [ollama/ollama#11580](https://github.com/ollama/ollama/issues/11580) — closed; clarifies that `-instruct-2507` is non-thinking by design, not a bug
- [Qwen/Qwen3-30B-A3B-Instruct-2507 model card, HF](https://huggingface.co/Qwen/Qwen3-30B-A3B-Instruct-2507) — non-thinking-only; sampling params
- [unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF, HF](https://huggingface.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF) — UD-Q4_K_XL = 17.7 GB, UD-Q5_K_XL = 21.7 GB, MoE spec, 262K ctx
- [Ollama library — qwen3:30b-a3b-instruct-2507-q4_K_M](https://ollama.com/library/qwen3:30b-a3b-instruct-2507-q4_K_M) — 19 GB official tag
- [Ollama library — qwen3.6:35b-a3b-q4_K_M](https://ollama.com/library/qwen3.6:35b-a3b-q4_K_M) — 24 GB, Apr 16 release
- [unsloth/Qwen3.6-35B-A3B-GGUF, HF](https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF) — UD-IQ4_XS = 17.7 GB; hybrid thinking
- [BerriAI/litellm#11680 + PR #15465](https://github.com/BerriAI/litellm/issues/11680) — `think` param support landed
- [LiteLLM streaming + tool_calls bugs #6135, #7094, #12481, #17954, #12557](https://github.com/BerriAI/litellm/issues/12557) — the `stream: false` / `keep_alive: -1` rationale

---

## Appendix A — Pre-flight capture (Phase 2 step 1)

Captured 2026-04-19 12:14 UTC. Baseline `smoke-test.sh before` **PASSED**. Anthropic `claude-haiku` health check returned `"OK"` via llmrouter.

### `ssh pc 'ollama show qwen3.5:27b'`
```
  Model
    architecture        qwen35
    parameters          27.8B
    context length      262144
    embedding length    5120
    quantization        Q4_K_M
    requires            0.17.1
  Capabilities
    completion, vision, tools, thinking
  Parameters
    presence_penalty    1.5
    temperature         1
    top_k               20
    top_p               0.95
  License: Apache 2.0
```

### `ssh pc 'ollama list'`
```
NAME           ID              SIZE     MODIFIED
qwen3.5:27b    7653528ba5cb    17 GB    12 days ago
```

### `ssh pc 'nvidia-smi'` summary
`NVIDIA GeForce RTX 4090, 24564 MiB total, 22885 MiB used, 1254 MiB free`

### Registry rollback check
`HTTP/2 200` for `https://registry.ollama.ai/v2/library/qwen3.5/manifests/27b`, digest `7653528ba5cba4dd8e19da24aaddc7f4d0b5ecd93571c0825dfd4137958ec06e`.

### Backups in place
- `server:/srv/docker/data/litellm/config/config.yaml.bak-2026-04-19` (written by a short-lived `docker run --rm -v …/config:/edit alpine …` — root ownership, writable via the docker daemon since `sudo-rs` is interactive on server).
- `pi:/tmp/openclaw.json.bak-2026-04-19` (via passwordless sudo on pi, chowned to danteb)
- `~/Programming/openclaw/openclaw.json.bak-2026-04-19` (fetched to mac; sha256 matches both live pi and the planning mirror — all three are identical at swap time).

## Appendix B — Final report (Phase 2 step 13)

**Outcome: PASSED.** Swap completed 2026-04-19 ~12:45 UTC. End-to-end smoke-test green. Three burn-in prompts all returned well-formed `tool_calls` or content without a single anomaly.

### Deployed model
- **Ollama tag:** `hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL`
- **On-disk:** 17 GB, id `dd80cb02246f`
- **Loaded (`ollama ps`):** 19 GB VRAM, 100 % GPU, 32 768 context, `UNTIL Forever`
- **VRAM footprint post-load:** 19 537 MiB used / 4 602 MiB free of 24 564 MiB → ~2 GB of live agent headroom at 32K context, per the pre-plan prediction
- **Measured throughput:** ~187 tok/s decode, ~3 000 tok/s prompt-eval on the tool-call smoke

### LiteLLM tier names deployed
Same five as pre-swap. `qwen-local` → Ollama (new model). `qwen-local-thinking` → `anthropic/claude-sonnet-4-6` (redesigned — Instruct-2507 has no thinking mode). Fallbacks preserved + augmented.

### Burn-in results (three prompts via `https://llmrouter.danteb.com`)

**1. Trivial no-tool** — `"In exactly one sentence, name the chemical symbol of water."`
```
"content": "The chemical symbol of water is H₂O."
usage.completion_tokens = 11, prompt_tokens = 20
```

**2. One-tool call** — weather/time-lookup with `get_time(timezone)` schema:
```json
"tool_calls":[{"function":{"arguments":"{\"timezone\": \"London\"}","name":"get_time"},"id":"call_6z769tp3","type":"function"}]
usage.completion_tokens = 20, prompt_tokens = 142
```

**3. Two-step tool chain** — `get_time` then `convert_time` with tool result threaded back:
- Step 1 returned parallel tool calls for `get_time("Tokyo")` + speculative `convert_time(…,"10:30")`.
- Step 2 (with the Tokyo time `2026-04-19T22:15:00+09:00` fed back as a `role=tool` message) returned `convert_time({source_city:"Tokyo",target_city:"New York",time:"2026-04-19T22:15:00+09:00"})` — the model consumed the tool result correctly.

No response landed JSON-in-content. No unclosed `<think>` tags.

### Logs / anomalies
- `llmrouter` log tail: all 200s, no `fallback=True` on any call, all Ollama `/api/tags` health probes green on 5 s cadence.
- `litellm` log tail: all 200s. No retry cascade.
- NTFY `https://ntfy.danteb.com/llmrouter` — quiet during the 30 min window spanning the swap; no "Ollama unreachable" alerts.
- **Pre-existing OpenClaw config-schema drift** surfaced by `openclaw config validate`: `channels.matrix.autoJoin` is boolean but the newer OpenClaw schema expects a string enum (`"always" | "allowlist" | "off"`), and `channels.matrix` contains an unknown key (likely `configWrites`). These validation errors exist in both the pre-swap and post-swap files — they are *not* introduced by this swap. `openclaw secrets audit` reports `plaintext=0, unresolved=1, shadowed=0, legacy=0`; the single "unresolved" is `[REF_UNRESOLVED] Config is invalid; cannot validate secret references reliably`, a cascade of the schema drift. The gateway nevertheless starts clean and routes requests (verified via systemctl status + successful burn-in). **Recommended follow-up (separate task):** run `openclaw doctor` at a convenient moment, or edit `channels.matrix.autoJoin` to `"allowlist"` and remove the unknown key.

### Ollama on pc
- **Upgrade performed:** 0.20.2 → 0.21.0 (required for Unsloth GGUF arch-support paths; see *Appendix D*). Windows service via NSSM at `C:\nssm\nssm.exe`, logs at `C:\OllamaLogs\ollama-{,error-}log`.
- Only two models on disk now: the new Instruct-2507 GGUF and nothing else — `qwen3.5:27b` removed, Qwen 3.6 blobs removed.

### What to watch in the next 48 h
- Real OpenClaw agent sessions driven from pi — the burn-in used synthetic tool schemas, not live MCP tools.
- `llmrouter` fallback-rate — if it ticks up above a few %, the new model is hitting timeouts or refusing tool calls.
- VRAM usage under a concurrent request (only one-at-a-time tested during burn-in).

### Rollback readiness
Pre-swap state fully captured in Appendix A. Backup `.bak-2026-04-19` files still in place on both server and pi. Old `qwen3.5:27b` pullable from registry (HTTP 200 verified at step 1).

## Appendix D — Qwen 3.6 attempt post-mortem (2026-04-19)

Between Phase 2 step 1 and step 5, I attempted the user's Qwen 3.6 preference before settling on the Instruct-2507 fallback. Chronologically:

1. Ollama 0.20.2 on pc refused to load `hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS` with a generic 500 error. Log: "Failed to start: Unable to init instance: Unspecified error".
2. User approved an Ollama upgrade. `irm https://ollama.com/install.ps1 | iex` via OpenSSH/PowerShell succeeded after first stopping the NSSM-managed `Ollama` Windows service (`Stop-Service Ollama`). New version `0.21.0`.
3. Same "unable to load model" error on 0.21.0. NSSM-routed stderr log (`C:\OllamaLogs\ollama-error.log`) revealed the real cause: `llama_model_load: error loading model: error loading model architecture: unknown model architecture: 'qwen35moe'`. The GGUF contains Mamba/SSM-flavored keys (`qwen35moe.ssm.conv_kernel`, `.state_size`, `.group_count`, `.inner_size`, `.full_attention_interval`) that Ollama 0.21's bundled llama.cpp can't yet parse, plus a separate 902 MB mmproj vision blob.
4. Switched to Ollama's library tag `qwen3.6:35b-a3b-q4_K_M` (23 GB, also `qwen35moe` arch but packaged with renderer/parser metadata Ollama does know). Loaded, but at 13 %/87 % CPU/GPU split (~800 MiB free VRAM) — the 23 GB weights + overhead already over-subscribe the 24 GB card. Tool-calls worked at ~47 tok/s.
5. Ollama library has no smaller 4-bit Qwen 3.6 quant (nvfp4 22 GB requires Blackwell; others are larger).
6. User chose Plan B fallback.

**Artifacts left behind from the attempt:**
- Ollama service on pc upgraded from 0.20.2 → 0.21.0. No rollback planned (0.21 is a superset for current models).
- Both failed Qwen 3.6 blobs removed from pc's Ollama store (`ollama rm` completed cleanly).
- New tool-call smoke evidence captured — confirms well-formed `tool_calls` possible on the 4090 under Ollama 0.21, which informed Instruct-2507 expectations.

**When to revisit Qwen 3.6:** when either (a) Unsloth publishes a GGUF whose architecture Ollama's llama.cpp parses without the SSM/mmproj gate, or (b) Ollama library ships a sub-20 GB Qwen 3.6 quant (e.g. Q3_K_M). Until then the 24 GB card is too tight.

## Appendix C — Manual-fallback design (historical — superseded by Plan B being the active path)

If `qwen3.6:35b-a3b` under the Unsloth UD-IQ4_XS tag produces malformed `tool_calls`, unclosed `<think>` tags, or a noticeable speed regression during the burn-in window — follow this path (requires explicit user approval; **not** automatic):

1. `ssh pc 'ollama pull hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL'` (17.7 GB)
2. `ssh pc 'ollama rm hf.co/unsloth/Qwen3.6-35B-A3B-GGUF:UD-IQ4_XS'` (frees VRAM)
3. Replace LiteLLM `qwen-local` / `qwen-local-thinking` model paths with the Instruct-2507 tag. Since Instruct-2507 has no thinking mode, the `qwen-local-thinking` entry must be repointed to `claude-sonnet`:
   ```yaml
   - model_name: qwen-local
     litellm_params:
       model: ollama_chat/hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL
       api_base: http://192.168.50.180:11434
       keep_alive: -1
       stream: false
       temperature: 0.7
       top_p: 0.8
       top_k: 20
       min_p: 0
       num_ctx: 32768
     model_info:
       supports_function_calling: true

   - model_name: qwen-local-thinking
     litellm_params:
       model: anthropic/claude-sonnet-4-6
       api_key: os.environ/ANTHROPIC_API_KEY
     model_info:
       supports_function_calling: true
   ```
4. Update OpenClaw labels: `"Qwen3-30B-A3B-Instruct-2507 (local)"` and `"Thinking (→ Claude Sonnet)"`.
5. Run `smoke-test.sh after`. If red, roll all the way back to `qwen3.5:27b`.
