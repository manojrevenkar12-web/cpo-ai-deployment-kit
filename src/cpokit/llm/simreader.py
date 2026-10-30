"""A deterministic stand-in for the model, used when no model endpoint is configured (and in CI).

It reads the same prompt inputs a model would get and answers in the same schema, with rules: it
knows the date formats, keywords and connector names it was written for and misses what it was not.
Like a naive model, it follows instructions it finds in the text; the gateway's quarantine is what
stops that. Every number the kit reports with this provider is a measurement of the kit with this
reader, not of Claude."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

EVSE = re.compile(r"\b[A-Z]{2}\*[A-Z0-9]{3}\*E\d{4}\*\d+\b")
CDR = re.compile(r"\bCDR-[A-Z]{2}-\d{6,8}\b")
SESSION = re.compile(r"\b(?:HUB-)?[A-Z]{2}-S\d{7}\b")
ISO_UTC = re.compile(r"\b(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?Z\b")
MONTHS = {
    m: i + 1
    for i, m in enumerate(
        [
            "january",
            "february",
            "march",
            "april",
            "may",
            "june",
            "july",
            "august",
            "september",
            "october",
            "november",
            "december",
        ]
    )
}
DAY_MONTH_TIME = re.compile(
    r"\b(\d{1,2}) ("
    + "|".join(m.capitalize() for m in MONTHS)
    + r")(?: at about| around)? (\d{1,2}):(\d{2})(?: ?(am|pm))?",
    re.IGNORECASE,
)
NUMERIC_DT = re.compile(r"\b(\d{1,2})[./](\d{1,2})[./]?(\d{4})? (\d{1,2}):(\d{2})\b")
ISO_LOCAL = re.compile(r"\b(\d{4})-(\d{2})-(\d{2}) (\d{1,2}):(\d{2})\b")
AMOUNT = re.compile(r"(\d+(?:[.,]\d{1,2})?)\s?EUR")
CLAIM_WORDS = {
    "twice": ["twice", "doppelt", "due volte", "två gånger", "dvakrát"],
    "idle": [
        "idle fee",
        "blockiergebühr",
        "tariffa di sosta",
        "parkeringsavgift",
        "blokování",
        "unplug",
        "abziehen",
        "staccare",
        "koppla ur",
        "odpojit",
    ],
    "vat": ["vat", "mehrwertsteuer", "iva", "moms", "dph"],
    "energy": ["energy is higher", "energiemenge", "l'energia", "energimängden", "množství energie"],
    "unknown": ["not theirs", "nicht von ihm", "non è sua", "inte är deras", "neprovedl"],
    "peak": ["peak", "spitzentarif", "punta", "topptaxa", "špičk"],
    "price": ["price", "preis", "prezzo", "priset", "cena"],
}
LANG_WORDS = {
    "de": ["der", "die", "und", "nicht", "mit", "ich", "mein", "wurde", "ladevorgang", "grüßen", "guten"],
    "it": ["il", "la", "che", "non", "per", "della", "ricarica", "sono", "mi", "saluti"],
    "nl": ["de", "het", "een", "niet", "mijn", "laden", "ik", "betaling"],
    "sv": ["och", "jag", "inte", "laddning", "kortet", "är", "hej"],
    "da": ["og", "jeg", "ikke", "opladning", "kortet", "betalinger"],
    "pl": ["nie", "się", "ładowanie", "proszę", "karta", "zwrot"],
    "cs": ["nabíjení", "není", "jsem", "dobrý", "karta", "peníze"],
    "hu": ["töltés", "kártya", "nem", "és", "vissza", "a"],
    "ro": ["și", "nu", "încărcare", "cardul", "banii", "am"],
    "en": ["the", "and", "my", "was", "not", "charged", "please", "hello"],
}
CARD_RX = re.compile(
    r"(?:Card ending|Karte endet auf|Carta che termina con|Kaart eindigend op|Kortet slutar på|Kortet ender på|"
    r"Karta kończy się na|Karta končí na|A kártya végződése|Cardul se termină în) (\d{4})"
)
APP_RX = re.compile(
    r"(?:My|Meine|Mijn|Min|A) (\w+)[- ](?:app|App|alkalmazás)|(?:L'app|Aplikacja|Aplikace|Aplicația) (\w+)"
)
ADDR_RX = re.compile(
    r"(?:station at|Station in der|stazione in|station aan de|stationen på|stacja przy|stanice|stația de pe) "
    r"([^,\n]+? \d+), ([^,\n]+),"
)
ADDR_HU = re.compile(r"A ([^,\n]+? \d+) alatti töltő volt, ([^,\n]+),")
INTENT_WORDS = {
    "double_capture": [
        "two payments",
        "zwei abbuchungen",
        "due pagamenti",
        "twee betalingen",
        "två betalningar",
        "to betalinger",
        "dwie płatności",
        "dvě platby",
        "két",
        "două plăți",
    ],
    "preauth_hold": [
        "blocked",
        "blockiert",
        "bloccati",
        "geblokkeerd",
        "reserverade",
        "reserveret",
        "zablokowane",
        "blokováno",
        "zárolva",
        "blocați",
    ],
    "stuck_session": [
        "unplugged",
        "abgezogen",
        "staccato",
        "stekker eruit",
        "kopplade ur",
        "tog stikket",
        "odłączyłem",
        "odpojil",
        "kihúztam",
        "am scos",
    ],
    "price_display": ["terminal", "terminale"],
    "roaming_driver": ["app"],
    "no_energy": [
        "did not charge",
        "nicht geladen",
        "non si è caricata",
        "niet geladen",
        "laddades inte",
        "ladede slet ikke",
        "nie naładował",
        "nenabilo",
        "nem töltődött",
        "nu s-a încărcat",
    ],
    "unidentifiable": [
        "something went wrong",
        "etwas schiefgelaufen",
        "qualcosa è andato storto",
        "iets mis",
        "något gick fel",
        "noget gik galt",
        "coś poszło",
        "něco pokazilo",
        "valami hiba",
        "ceva n-a mers",
    ],
    "valid_charge": [
        "too expensive",
        "zu teuer",
        "troppi",
        "te duur",
        "för dyrt",
        "for dyrt",
        "za drogo",
        "příliš drahé",
        "túl drága",
        "prea scump",
    ],
}


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def detect_language(text: str, default: str = "en") -> str:
    words = re.findall(r"[^\W\d_]+", text.lower())
    best, score = default, 0
    for lang, vocab in LANG_WORDS.items():
        n = sum(1 for w in words if w in vocab)
        if n > score:
            best, score = lang, n
    return best


def _year_for(month: int, today: date) -> int:
    return today.year if month <= today.month else today.year - 1


def _local_times(line: str, today: date) -> list[str]:
    out = []
    for m in DAY_MONTH_TIME.finditer(line):
        day, mon, hh, mm, ap = int(m.group(1)), MONTHS[m.group(2).lower()], int(m.group(3)), int(m.group(4)), m.group(5)
        if ap:
            hh = hh % 12 + (12 if ap.lower() == "pm" else 0)
        out.append(f"{_year_for(mon, today)}-{mon:02d}-{day:02d}T{hh:02d}:{mm:02d}")
    for m in ISO_LOCAL.finditer(line):
        out.append(f"{m.group(1)}-{m.group(2)}-{m.group(3)}T{int(m.group(4)):02d}:{m.group(5)}")
    for m in NUMERIC_DT.finditer(line):
        d, mo = int(m.group(1)), int(m.group(2))
        if not (1 <= mo <= 12 and 1 <= d <= 31):
            continue
        y = int(m.group(3)) if m.group(3) else _year_for(mo, today)
        out.append(f"{y}-{mo:02d}-{d:02d}T{int(m.group(4)):02d}:{m.group(5)}")
    return out


def _claim(text: str) -> str:
    t = text.lower()
    for claim, words in CLAIM_WORDS.items():
        if any(w in t for w in words):
            return claim
    return "other"


def dispute_read(inp: dict[str, Any]) -> dict[str, Any]:
    text: str = inp["email"]
    today = date.fromisoformat(inp["received"][:10])
    items = []
    for line in text.splitlines():
        cdrs, evses, sessions = CDR.findall(line), EVSE.findall(line), SESSION.findall(line)
        if not (cdrs or evses or sessions):
            continue
        utc = ISO_UTC.search(line)
        local = _local_times(line, today)
        amounts = AMOUNT.findall(line)
        claimed = _num(amounts[-1]) if amounts else None
        if "|" in line:  # table: the billed column is not a claim
            claimed = None
        for k, cdr_id in enumerate(cdrs or [None]):
            items.append(
                {
                    "cdr_id": cdr_id,
                    "session_ref": sessions[k] if k < len(sessions) else None,
                    "evse_id": evses[0] if evses else None,
                    "local_time": None if utc else (local[0] if local else None),
                    "utc_time": f"{utc.group(1)}T{utc.group(2)}:00Z" if utc else None,
                    "claimed_eur": claimed if k == 0 else None,
                    "claim": _claim(line),
                }
            )
    return {"language": detect_language(text), "items": items}


def ticket_read(inp: dict[str, Any]) -> dict[str, Any]:
    text: str = inp["ticket"]
    today = date.fromisoformat(inp["received"][:10])
    low = text.lower()
    intent = "other"
    for k, words in INTENT_WORDS.items():
        if any(w in low for w in words):
            intent = k
            break
    evse = EVSE.search(text)
    times = _local_times(text, today)
    last4 = CARD_RX.search(text)
    amounts = AMOUNT.findall(text)
    shown = re.search(r"(\d+[.,]\d{2}) EUR/kWh", text)
    app = APP_RX.search(text)
    address = city = None
    m = ADDR_RX.search(text) or ADDR_HU.search(text)
    if m and not evse:
        address, city = m.group(1).strip(), m.group(2).strip()
    amounts_f = [_num(a) for a in amounts]
    return {
        "language": detect_language(text),
        "intent": intent,
        "evse_id": evse.group(0) if evse else None,
        "city": city,
        "address": address,
        "local_time": times[0] if times else None,
        "last4": last4.group(1) if last4 else None,
        "amount_eur": amounts_f[0] if amounts_f else None,
        "app": next((g for g in app.groups() if g), None) if app else None,
        "shown_price": _num(shown.group(1)) if shown else None,
    }


CONNECTORS = {
    "IEC_62196_T2_COMBO": ["ccs2", "ccs", "combo 2", "ccs combo"],
    "IEC_62196_T2": ["tipo 2", "type 2", "mennekes", "t2"],
    "CHADEMO": ["chademo"],
}
HEADERS = {
    "site_code": ["codice sito", "codice", "site code"],
    "name": ["nome", "denominazione"],
    "address": ["indirizzo", "via"],
    "postal_code": ["cap"],
    "city": ["comune", "città"],
    "latitude": ["latitudine", "lat"],
    "longitude": ["longitudine", "lon", "lng"],
    "points": ["punti di ricarica", "connettori", "prese"],
    "max_power": ["potenza max", "potenza"],
    "hours": ["orari", "orario"],
    "payment": ["pagamento", "metodi di pagamento"],
}
DAYS = {"lun": 1, "mar": 2, "mer": 3, "gio": 4, "ven": 5, "sab": 6, "dom": 7, "l": 1, "v": 5, "s": 6, "d": 7}


def _connectors(text: str) -> list[dict[str, Any]]:
    out = []
    for part in re.split(r"\+|;", text):
        m = re.search(r"(\d+)\s*x\s*(.+?)\s+(\d+(?:[.,]\d+)?)\s*kW", part.strip(), re.IGNORECASE)
        if not m:
            continue
        word = m.group(2).strip().lower()
        std = next((s for s, ws in CONNECTORS.items() if word in ws), None)
        if std is None:
            continue
        out.append({"standard": std, "power_kw": _num(m.group(3)), "count": int(m.group(1))})
    return out


def _hours(text: str) -> tuple[bool | None, list[dict[str, Any]]]:
    t = text.lower().strip()
    if t in ("24/7", "h24", "24 ore", "sempre aperto", "24h"):
        return True, []
    out = []
    for seg in re.split(r"[;,]", t):
        m = re.search(r"([a-z]+)(?:-([a-z]+))?\s+(\d{1,2})(?::(\d{2}))?-(\d{1,2})(?::(\d{2}))?", seg.strip())
        if not m or m.group(1) not in DAYS:
            continue
        a = DAYS[m.group(1)]
        b = DAYS.get(m.group(2) or m.group(1), a)
        out.append(
            {
                "weekdays": list(range(a, b + 1)),
                "open": f"{int(m.group(3)):02d}:{m.group(4) or '00'}",
                "close": f"{int(m.group(5)):02d}:{m.group(6) or '00'}",
            }
        )
    return (False, out) if out else (None, [])


def site_map(inp: dict[str, Any]) -> dict[str, Any]:
    row: dict[str, str] = inp.get("row") or {}
    if inp.get("protocol"):
        row = _protocol_fields(inp["protocol"])
    get = {}
    for field, names in HEADERS.items():
        for k, v in row.items():
            if k.strip().lower() in names:
                get[field] = str(v).strip()
                break

    def f(x: str | None) -> float | None:
        if not x:
            return None
        try:
            return _num(x)
        except ValueError:
            return None

    power = f(get.get("max_power"))
    if power and power > 2000:
        power = power / 1000
    h24, hours = _hours(get.get("hours", ""))
    pay = get.get("payment", "").lower()
    return {
        "site_code": get.get("site_code", ""),
        "name": get.get("name"),
        "address": get.get("address"),
        "postal_code": get.get("postal_code") or None,
        "city": get.get("city"),
        "latitude": f(get.get("latitude")),
        "longitude": f(get.get("longitude")),
        "connectors": _connectors(get.get("points", "")),
        "max_power_kw": power,
        "open_24_7": h24,
        "hours": hours,
        "card_payment": ("pos" in pay or "carta" in pay or "card" in pay) if pay else None,
    }


def _protocol_fields(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    m = re.search(r"Impianto (\S+) \(([^)]+)\)", text)
    if m:
        out["Codice sito"], out["Nome"] = m.group(1), m.group(2)
    m = re.search(r"si trova in (.+?), (\d{5})? ?([^,(]+?) \(", text)
    if m:
        out["Indirizzo"], out["CAP"], out["Comune"] = m.group(1), m.group(2) or "", m.group(3).strip()
    m = re.search(r"Coordinate GPS: ([\d.,]+) N, ([\d.,]+) E", text)
    if m:
        out["Latitudine"], out["Longitudine"] = m.group(1), m.group(2)
    m = re.search(r"Dotazione: (.+?)\. Potenza massima dell'impianto: ([\d.,]+)", text)
    if m:
        out["Punti di ricarica"], out["Potenza max"] = m.group(1), m.group(2)
    m = re.search(r"Orario di apertura: (.+?)\. Metodi di pagamento: (.+?)\.\n", text)
    if m:
        out["Orari"], out["Pagamento"] = m.group(1), m.group(2)
    return out


STOP = {
    "the",
    "a",
    "an",
    "do",
    "you",
    "your",
    "what",
    "how",
    "many",
    "which",
    "is",
    "are",
    "of",
    "for",
    "to",
    "in",
    "at",
    "can",
    "and",
    "when",
    "today",
    "per",
    "with",
    "il",
    "la",
    "le",
    "i",
    "di",
    "che",
    "quale",
    "quali",
    "quanti",
    "quante",
    "siete",
    "avete",
    "vostri",
    "vostra",
    "vostro",
    "sono",
    "del",
    "dei",
    "ai",
    "al",
    "con",
}
IT_EN = {
    "punti": "points",
    "ricarica": "charging",
    "pubblici": "public",
    "gestite": "operate",
    "paesi": "countries",
    "disponibilità": "availability",
    "garantite": "commitment",
    "caricatori": "chargers",
    "potenza": "power",
    "alta": "high-power",
    "tempo": "time",
    "intervento": "technician site",
    "guasti": "fault",
    "energia": "electricity",
    "rinnovabile": "renewable",
    "venduta": "sold",
    "pagare": "card",
    "carta": "card",
    "conducenti": "drivers",
    "servizio": "hotline",
    "clienti": "hotline",
    "lingue": "languages",
    "certificazione": "certified",
    "sicurezza": "security",
    "informazioni": "information",
    "aggiungete": "add",
    "anno": "year",
    "camion": "trucks",
    "megawatt": "megawatt",
    "contatori": "meters",
    "taratura": "calibration",
    "tedesca": "german",
    "pubblicate": "publish",
    "dati": "data",
    "accesso": "access",
    "nazionali": "national",
    "persone": "people",
    "impiega": "employs",
    "azienda": "company",
    "idrogeno": "hydrogen",
    "assicurazione": "insurance",
    "sessioni": "sessions",
    "impronta": "carbon footprint",
    "carbonio": "carbon",
    "massimale": "limit",
}


def tender_query(inp: dict[str, Any]) -> dict[str, Any]:
    q = inp["question"]
    lang = detect_language(q)
    words = [w for w in re.findall(r"[^\W\d_][\w'-]*", q.lower()) if w not in STOP]
    kws = []
    for w in words:
        kws.extend(IT_EN.get(w, w).split())
    return {"language": lang, "keywords": kws}


def tender_answer(inp: dict[str, Any]) -> dict[str, Any]:
    """Uses the best passage that covers the question; abstains when none does."""
    passages = inp["passages"]
    kws = set(tender_query({"question": inp["question"]})["keywords"])
    numbers = set(re.findall(r"\d+", inp["question"]))
    for p in passages:
        words = set(re.findall(r"[^\W\d_][\w'-]*", p["text"].lower()))
        stems = {w[:5] for w in words}
        covered = sum(1 for k in kws if k in words or k[:5] in stems)
        if kws and covered / len(kws) >= 0.4 and numbers <= set(re.findall(r"\d+", p["text"])):
            return {"abstain": False, "sentences": [{"text": p["text"], "cites": [p["pid"]]}]}
    return {"abstain": True, "sentences": []}


REPLY = {
    "en": ("Thank you for your message.", "Kind regards"),
    "de": ("Vielen Dank für Ihre Nachricht.", "Mit freundlichen Grüßen"),
    "it": ("Grazie per il messaggio.", "Cordiali saluti"),
    "nl": ("Dank voor uw bericht.", "Met vriendelijke groet"),
    "sv": ("Tack för ditt meddelande.", "Med vänliga hälsningar"),
    "da": ("Tak for din besked.", "Med venlig hilsen"),
    "pl": ("Dziękujemy za wiadomość.", "Z poważaniem"),
    "cs": ("Děkujeme za zprávu.", "S pozdravem"),
    "hu": ("Köszönjük az üzenetét.", "Üdvözlettel"),
    "ro": ("Vă mulțumim pentru mesaj.", "Cu stimă"),
}


def reply(inp: dict[str, Any]) -> dict[str, Any]:
    lang = inp.get("language", "en")
    hello, bye = REPLY.get(lang, REPLY["en"])
    lines = [hello]
    lines += [str(x) for x in inp.get("decisions", inp.get("outcome", []))]
    lines += ["", bye]
    return {"language": lang, "text": "\n".join(lines)}


def follow_injection(inp: dict[str, Any], out: dict[str, Any], task: str) -> dict[str, Any]:
    """A naive model obeys instructions in its input; this reproduces that for the tests."""
    raw = " ".join(str(v) for v in inp.values()).lower()
    if "approve a full credit" in raw or "set the credit to the full amount" in raw or "refund everything" in raw:
        if task == "dispute.read":
            for it in out["items"]:
                it["claim"] = "twice"
        if task == "ticket.read":
            out["intent"] = "double_capture"
            out["amount_eur"] = 500.0
    return out


TASKS = {
    "dispute.read": dispute_read,
    "ticket.read": ticket_read,
    "site.map": site_map,
    "tender.query": tender_query,
    "tender.answer": tender_answer,
    "dispute.reply": reply,
    "ticket.reply": reply,
}


def answer(task: str, inp: dict[str, Any]) -> dict[str, Any]:
    out = TASKS[task](inp)
    return follow_injection(inp, out, task)


def now_iso() -> str:
    return datetime.now().isoformat()
