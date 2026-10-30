"""What is removed before a model sees text: personal data (masked) and instruction-like lines
(quarantined). Quarantined lines are kept for the person reviewing the case, never sent to a model."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .. import settings


@dataclass
class Cleaned:
    text: str
    masked: dict[str, int] = field(default_factory=dict)
    quarantined: list[str] = field(default_factory=list)


class Guard:
    def __init__(self, cfg: dict[str, Any] | None = None) -> None:
        g = cfg or settings.gateway()["guardrails"]
        self.mask = {k: re.compile(v) for k, v in g["mask"].items()}
        self.markers = [re.compile(m, re.IGNORECASE) for m in g["injection_markers"]]
        self.max_chars = g["max_input_chars"]

    def clean(self, text: str) -> Cleaned:
        out = Cleaned(text="")
        kept = []
        for line in text.splitlines():
            if any(m.search(line) for m in self.markers):
                out.quarantined.append(line)
                kept.append("<quarantined/>")
            else:
                kept.append(line)
        t = "\n".join(kept)
        for name, rx in self.mask.items():
            t, n = rx.subn(f"[{name}]", t)
            if n:
                out.masked[name] = out.masked.get(name, 0) + n
        out.text = t[: self.max_chars]
        return out

    def clean_inputs(self, inputs: dict[str, Any], fields: tuple[str, ...]) -> tuple[dict[str, Any], Cleaned]:
        total = Cleaned(text="")
        res = dict(inputs)
        for f in fields:
            if isinstance(res.get(f), str):
                c = self.clean(res[f])
                res[f] = c.text
                total.quarantined += c.quarantined
                for k, v in c.masked.items():
                    total.masked[k] = total.masked.get(k, 0) + v
        return res, total
