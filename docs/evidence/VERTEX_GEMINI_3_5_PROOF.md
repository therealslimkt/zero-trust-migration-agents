# Evidence: Gemini 3.5 executes on Vertex AI

Satisfies the mandatory hackathon requirement *"Gemini 3.5 or newer, accessed through the
Gemini API or Vertex AI"* and P0 submission-gate item 1.

| Field | Value |
| --- | --- |
| Captured (UTC) | `2026-08-31T21:38:29Z` |
| Google Cloud project | `ztm-agent-9049c3` |
| Model | `gemini-3.5-flash` |
| Vertex location | `us` (multi-region) |
| Access path | Vertex AI via `google-antigravity==0.1.14` (`LocalAgentConfig(vertex=True)`) |
| Product call site | `control_plane/gemini_planner.py` → `antigravity_model_call_factory` |

## Reproduce

```bash
venv/bin/python - <<'PY'
import asyncio, os
from google.antigravity import Agent, LocalAgentConfig
async def main():
    cfg = LocalAgentConfig(model="gemini-3.5-flash", vertex=True,
                           project="ztm-agent-9049c3", location="us", tools=[],
                           system_instructions="Reply with exactly the token you are asked for.")
    async with Agent(config=cfg) as a:
        r = await a.chat("Reply with exactly: KERAUN_VERTEX_OK")
        print((await r.text()).strip())
asyncio.run(main())
PY
```

## Recorded output

```text
MODEL: gemini-3.5-flash | LOCATION: us | PROJECT: ztm-agent-9049c3
RESPONSE: KERAUN_VERTEX_OK
```

## Notes

- `gemini-3.5-flash` Standard PayGo is served from the `global`, `us`, and `eu`
  endpoints — **not** `us-central1`. Requests pinned to `us-central1` return 404.
- `gemini-3.5-pro` was not reachable in this project at capture time; the fleet targets
  `gemini-3.5-flash`, which satisfies the "3.5 or newer" requirement.
- Gemini 2.5 would **not** satisfy the requirement and is not used.
