#!/bin/bash
set -euo pipefail
exec /bin/bash "$(dirname "$0")/provision-ai-forwarding.sh" whisper "$@"
