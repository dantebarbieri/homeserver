#!/usr/bin/env python3
"""Exercise a local schema-constrained, non-destructive recommendation."""

import json
import urllib.request


schema = {
    "type": "object",
    "properties": {
        "recommendation": {"type": "string", "enum": ["review", "no_action"]},
        "reason": {"type": "string"},
    },
    "required": ["recommendation", "reason"],
    "additionalProperties": False,
}
payload = {
    "model": "qwen3:8b",
    "messages": [
        {
            "role": "user",
            "content": (
                "A maintenance check found an unfamiliar error. Recommend review "
                "rather than taking action. Return JSON matching this schema: "
                + json.dumps(schema)
            ),
        }
    ],
    "format": schema,
    "stream": False,
    "think": False,
    "options": {"temperature": 0, "num_ctx": 4096},
}
request = urllib.request.Request(
    "http://127.0.0.1:11434/api/chat",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
with urllib.request.urlopen(request, timeout=300) as response:
    result = json.load(response)
answer = json.loads(result["message"]["content"])
if (
    not isinstance(answer, dict)
    or set(answer) != {"recommendation", "reason"}
    or answer["recommendation"] != "review"
    or not isinstance(answer["reason"], str)
    or not answer["reason"].strip()
):
    raise ValueError(f"Unexpected recommendation: {answer!r}")
print(json.dumps(answer, ensure_ascii=False))
