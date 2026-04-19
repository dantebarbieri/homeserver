#!/usr/bin/env bash
# End-to-end smoke-test for the local-model swap.
# Exits non-zero on any failure. Auto-rollback in Phase 2 keys off the exit code.
#
# Usage:
#   ./smoke-test.sh before   # expects pre-swap state  (qwen3.5:27b on pc)
#   ./smoke-test.sh after    # expects post-swap state (Unsloth Qwen 3.6 tag on pc)
#
# Secrets are always sourced on the host that owns them; never piped to the
# local shell. SSH aliases 'pc', 'server', 'pi' must be pre-configured.

set -u

MODE="${1:-}"
if [[ "$MODE" != "before" && "$MODE" != "after" ]]; then
  echo "usage: $0 {before|after}" >&2
  exit 2
fi

BEFORE_TAG='qwen3.5:27b'
AFTER_TAG='hf.co/unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF:UD-Q4_K_XL'
EXPECT_TAG="$BEFORE_TAG"
[[ "$MODE" == "after" ]] && EXPECT_TAG="$AFTER_TAG"

FAIL=0
step() { printf '\n== %s ==\n' "$1"; }
ok()   { printf '  ✅ %s\n' "$1"; }
bad()  { printf '  ❌ %s\n' "$1"; FAIL=1; }
skip() { printf '  ⚠️  SKIP: %s\n' "$1"; }

# -----------------------------------------------------------------------------
step "1/5  ollama list on pc — expect $EXPECT_TAG"
OLLAMA_LIST="$(ssh -o BatchMode=yes pc 'ollama list' 2>&1)" || {
  bad "ssh pc 'ollama list' failed: $OLLAMA_LIST"
}
if printf '%s\n' "$OLLAMA_LIST" | grep -qF "$EXPECT_TAG"; then
  ok "pc has $EXPECT_TAG"
else
  bad "pc missing $EXPECT_TAG"
  printf '%s\n' "$OLLAMA_LIST" | sed 's/^/    /'
fi

# -----------------------------------------------------------------------------
step "2/5  LiteLLM /v1/models via llmrouter (tier resolution)"
# The litellm container doesn't expose port 4000 on the host, so query it from
# inside the container network. Use the llmrouter upstream path:
# llmrouter exposes /v1/models that enumerates tier names.
MODELS_JSON="$(ssh -o BatchMode=yes server 'bash -s' <<'REMOTE' 2>&1
set -eu
ENV_FILE=/srv/homeserver/docker/.env
KEY=$(awk -F= '/^LLMROUTER_API_KEY=/{sub(/^[^=]+=/,""); gsub(/^["'\''"]|["'\''"]$/,""); print; exit}' "$ENV_FILE")
[[ -z "$KEY" ]] && { echo "no LLMROUTER_API_KEY in $ENV_FILE" >&2; exit 1; }
curl -fsS https://llmrouter.danteb.com/v1/models -H "Authorization: Bearer $KEY"
REMOTE
)" || { bad "llmrouter /v1/models fetch failed"; printf '%s\n' "$MODELS_JSON" | sed 's/^/    /'; MODELS_JSON=""; }

# Also confirm litellm itself (deeper check): use python inside the litellm container
# (curl isn't installed there, but python3 is — the healthcheck uses urllib).
LITELLM_MODELS_JSON="$(ssh -o BatchMode=yes server 'bash -s' <<'REMOTE' 2>&1
set -eu
ENV_FILE=/srv/homeserver/docker/.env
KEY=$(awk -F= '/^LITELLM_MASTER_KEY=/{sub(/^[^=]+=/,""); gsub(/^["'\''"]|["'\''"]$/,""); print; exit}' "$ENV_FILE")
[[ -z "$KEY" ]] && { echo "no LITELLM_MASTER_KEY" >&2; exit 1; }
docker exec -e KEY="$KEY" litellm python3 -c "
import urllib.request, os, sys
bearer = 'Bearer ' + os.environ['KEY']
req = urllib.request.Request('http://localhost:4000/v1/models', headers={'Authorization': bearer})
sys.stdout.write(urllib.request.urlopen(req, timeout=5).read().decode())
"
REMOTE
)" || { bad "litellm /v1/models (via docker exec python) failed"; printf '%s\n' "$LITELLM_MODELS_JSON" | sed 's/^/    /'; LITELLM_MODELS_JSON=""; }

for want in qwen-local qwen-local-thinking claude-haiku claude-sonnet; do
  if printf '%s' "$LITELLM_MODELS_JSON" | grep -q "\"$want\""; then
    ok "LiteLLM advertises '$want'"
  else
    bad "LiteLLM missing '$want'"
  fi
done

# -----------------------------------------------------------------------------
step "3/5  llmrouter end-to-end — trivial prompt via qwen-local"
TRIVIAL_JSON="$(ssh -o BatchMode=yes server 'bash -s' <<'REMOTE' 2>&1
set -eu
ENV_FILE=/srv/homeserver/docker/.env
KEY=$(awk -F= '/^LLMROUTER_API_KEY=/{sub(/^[^=]+=/,""); gsub(/^["'\''"]|["'\''"]$/,""); print; exit}' "$ENV_FILE")
[[ -z "$KEY" ]] && { echo "no LLMROUTER_API_KEY" >&2; exit 1; }
curl -fsS https://llmrouter.danteb.com/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen-local","messages":[{"role":"user","content":"Reply with the single word OK and nothing else."}],"max_tokens":8,"temperature":0}'
REMOTE
)" || { bad "llmrouter trivial request failed"; printf '%s\n' "$TRIVIAL_JSON" | sed 's/^/    /'; TRIVIAL_JSON=""; }

# Parse content without heredoc/stdin conflict: write JSON to a temp file.
TRIVIAL_TMP="$(mktemp)"
printf '%s' "$TRIVIAL_JSON" > "$TRIVIAL_TMP"
CONTENT="$(python3 -c '
import json, sys
try:
    with open(sys.argv[1]) as f: j = json.load(f)
    print(j["choices"][0]["message"].get("content") or "")
except Exception as e:
    print(f"<parse-error: {e}>")
' "$TRIVIAL_TMP" 2>/dev/null)"
rm -f "$TRIVIAL_TMP"

if [[ -n "$CONTENT" && "$CONTENT" != "<parse-error"* ]]; then
  ok "qwen-local replied: $(printf '%s' "$CONTENT" | tr '\n' ' ' | cut -c1-80)"
else
  bad "qwen-local gave no usable content"
  printf '%s\n' "$TRIVIAL_JSON" | sed 's/^/    /'
fi

# -----------------------------------------------------------------------------
step "4/5  tool-call round-trip — one-tool schema via qwen-local"
TOOL_JSON="$(ssh -o BatchMode=yes server 'bash -s' <<'REMOTE' 2>&1
set -eu
ENV_FILE=/srv/homeserver/docker/.env
KEY=$(awk -F= '/^LLMROUTER_API_KEY=/{sub(/^[^=]+=/,""); gsub(/^["'\''"]|["'\''"]$/,""); print; exit}' "$ENV_FILE")
[[ -z "$KEY" ]] && { echo "no LLMROUTER_API_KEY" >&2; exit 1; }
curl -fsS https://llmrouter.danteb.com/v1/chat/completions \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model":"qwen-local",
    "messages":[{"role":"user","content":"What is the weather in Dallas right now? Use the tool."}],
    "tools":[{
      "type":"function",
      "function":{
        "name":"get_weather",
        "description":"Get the current weather for a city.",
        "parameters":{"type":"object","properties":{"city":{"type":"string"}},"required":["city"]}
      }
    }],
    "tool_choice":"auto",
    "max_tokens":128,
    "temperature":0
  }'
REMOTE
)" || { bad "tool-call request failed"; printf '%s\n' "$TOOL_JSON" | sed 's/^/    /'; TOOL_JSON=""; }

TOOL_TMP="$(mktemp)"
printf '%s' "$TOOL_JSON" > "$TOOL_TMP"
TOOL_OK="$(python3 - "$TOOL_TMP" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as f: j = json.load(f)
    msg = j["choices"][0]["message"]
    tc = msg.get("tool_calls") or []
    content = (msg.get("content") or "")
    if isinstance(tc, list) and len(tc) >= 1 and isinstance(tc[0], dict) \
        and tc[0].get("function", {}).get("name") == "get_weather":
        print("OK:structured_tool_call")
    elif "get_weather" in content and "{" in content:
        print(f"BAD:json_in_content:{content[:120]}")
    else:
        print(f"BAD:no_tool_call:msg={json.dumps(msg)[:200]}")
except Exception as e:
    print(f"BAD:parse_error:{e}")
PY
)"
rm -f "$TOOL_TMP"

case "$TOOL_OK" in
  OK:*) ok "structured tool_call received: get_weather()" ;;
  *)    bad "tool-call malformed: $TOOL_OK"
        printf '%s\n' "$TOOL_JSON" | sed 's/^/    /' ;;
esac

# -----------------------------------------------------------------------------
step "5/5  OpenClaw gateway health on pi (best-effort)"
HEALTH_OUT="$(ssh -o BatchMode=yes pi 'sudo -n -iu openclaw -- openclaw health 2>&1 || echo __SUDO_FAIL__' 2>&1)"
if printf '%s' "$HEALTH_OUT" | grep -q '__SUDO_FAIL__'; then
  skip "non-interactive sudo -iu openclaw unavailable; check 'openclaw health' manually from the openclaw shell"
elif printf '%s' "$HEALTH_OUT" | grep -qiE 'healthy|ok|ready'; then
  ok "openclaw health: $(printf '%s' "$HEALTH_OUT" | tr '\n' ' ' | cut -c1-120)"
else
  bad "openclaw health unexpected output"
  printf '%s\n' "$HEALTH_OUT" | sed 's/^/    /'
fi

# -----------------------------------------------------------------------------
echo
if (( FAIL )); then
  echo "SMOKE-TEST FAILED ($MODE mode)" >&2
  exit 1
fi
echo "SMOKE-TEST PASSED ($MODE mode)"
exit 0
