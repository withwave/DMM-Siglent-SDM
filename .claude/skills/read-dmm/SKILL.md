---
name: read-dmm
description: Read the live DMM measurement. Use for "지금 mA", "현재 측정값", "what does the meter say", etc.
---

```bash
curl -sf -m 3 http://192.168.0.153:8000/api/reading.txt
```

Returns one line, e.g. `+2.1997 mA  DCI Manual(0.2)`. Quote it verbatim.

JSON variant: `/api/reading` returns `{value, mode, range, prefix, min, max}` — `value` is SI base unit (A, V, Ω, …).
