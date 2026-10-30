"""The bid team's library (past tender answers, fact sheets, policies, certificates, some in
Italian) and the questions of a new motorway concession tender and EU grant reports.

Facts change over time: an older document can hold a superseded value, and a good answer uses the
newest one. Some questions have no answer in the library at all."""

from __future__ import annotations

from typing import Any

from .world import Network, rng

# fact id -> (topic words, [(valid_from, value_en, value_it)], sentence template en, it)
FACTS: dict[str, dict[str, Any]] = {
    "network_points": {
        "values": [("2025-03-01", "8,000", "8.000"), ("2025-11-15", "8,500", "8.500"), ("2026-05-20", "9,000", "9.000")],
        "en": "The operator runs more than {v} public charging points.",
        "it": "L'operatore gestisce oltre {v} punti di ricarica pubblici.",
        "q_en": "How many public charging points do you operate today?",
        "q_it": "Quanti punti di ricarica pubblici gestite oggi?",
    },
    "countries": {
        "values": [("2024-01-10", "11", "11")],
        "en": "The network spans {v} European countries.",
        "it": "La rete è presente in {v} paesi europei.",
        "q_en": "In how many countries do you operate charging infrastructure?",
        "q_it": "In quanti paesi gestite infrastrutture di ricarica?",
    },
    "uptime": {
        "values": [("2024-06-01", "97%", "97%"), ("2026-02-01", "98.5%", "98,5%")],
        "en": "Our contractual availability commitment for high-power chargers is {v} per year.",
        "it": "Il nostro impegno contrattuale di disponibilità per i caricatori ad alta potenza è del {v} annuo.",
        "q_en": "What availability do you commit to for high-power chargers?",
        "q_it": "Quale disponibilità garantite per i caricatori ad alta potenza?",
    },
    "hpc_response": {
        "values": [("2024-06-01", "24 hours", "24 ore"), ("2026-02-01", "12 hours", "12 ore")],
        "en": "A technician is on site within {v} of a fault at a high-power charger.",
        "it": "Un tecnico interviene in sito entro {v} da un guasto a un caricatore ad alta potenza.",
        "q_en": "What is your on-site response time for faults at high-power chargers?",
        "q_it": "Qual è il tempo di intervento in sito per guasti ai caricatori ad alta potenza?",
    },
    "green_power": {
        "values": [("2024-01-10", "100%", "100%")],
        "en": "{v} of the electricity sold at our chargers is renewable, backed by guarantees of origin.",
        "it": "Il {v} dell'energia venduta presso i nostri caricatori è rinnovabile, con garanzie di origine.",
        "q_en": "What share of the electricity you sell is renewable?",
        "q_it": "Quale quota dell'energia venduta è rinnovabile?",
    },
    "card_payment": {
        "values": [("2025-04-13", "contactless debit and credit card terminals", "terminali contactless per carte di debito e credito")],
        "en": "All new high-power chargers have {v}, as AFIR requires, besides app, RFID and roaming.",
        "it": "Tutti i nuovi caricatori ad alta potenza dispongono di {v}, come richiesto dall'AFIR, oltre ad app, RFID e roaming.",
        "q_en": "Can drivers pay ad hoc by card at your new high-power chargers?",
        "q_it": "I conducenti possono pagare ad hoc con carta presso i nuovi caricatori ad alta potenza?",
    },
    "hotline": {
        "values": [("2024-01-10", "24/7 in the local language of all 11 countries", "24/7 nella lingua locale di tutti gli 11 paesi")],
        "en": "Drivers can reach our hotline {v}.",
        "it": "I conducenti possono contattare il nostro servizio clienti {v}.",
        "q_en": "When and in which languages can drivers reach your hotline?",
        "q_it": "Quando e in quali lingue i conducenti possono contattare il servizio clienti?",
    },
    "iso27001": {
        "values": [("2023-09-01", "ISO/IEC 27001", "ISO/IEC 27001")],
        "en": "Our information security management system is certified to {v}.",
        "it": "Il nostro sistema di gestione della sicurezza delle informazioni è certificato {v}.",
        "q_en": "Which information security certification do you hold?",
        "q_it": "Quale certificazione di sicurezza delle informazioni possedete?",
    },
    "expansion": {
        "values": [("2025-01-15", "800", "800"), ("2026-03-01", "1,000", "1.000")],
        "en": "Together with location partners we add about {v} high-power charging points per year.",
        "it": "Insieme ai partner di localizzazione aggiungiamo circa {v} punti di ricarica ad alta potenza all'anno.",
        "q_en": "How many high-power charging points do you add per year?",
        "q_it": "Quanti punti di ricarica ad alta potenza aggiungete ogni anno?",
    },
    "mcs": {
        "values": [("2025-11-26", "about 330 megawatt charging points at 55 sites by 2028", "circa 330 punti di ricarica in megawatt in 55 siti entro il 2028")],
        "en": "For electric trucks we plan, with partners, {v}.",
        "it": "Per i camion elettrici prevediamo, con i partner, {v}.",
        "q_en": "What are your plans for megawatt charging of trucks?",
        "q_it": "Quali sono i vostri piani per la ricarica in megawatt dei camion?",
    },
    "eichrecht": {
        "values": [("2024-01-10", "calibration-law compliant meters", "contatori conformi alla legge tedesca sulla taratura")],
        "en": "All DC chargers in Germany have {v} with signed meter values.",
        "it": "Tutti i caricatori DC in Germania hanno {v} con valori di misura firmati.",
        "q_en": "Are your meters compliant with German calibration law?",
        "q_it": "I vostri contatori sono conformi alla legge tedesca sulla taratura?",
    },
    "nap": {
        "values": [("2025-04-13", "static and dynamic data to the national access points", "dati statici e dinamici ai punti di accesso nazionali")],
        "en": "We publish {v} as AFIR requires.",
        "it": "Pubblichiamo {v} come richiesto dall'AFIR.",
        "q_en": "Do you publish charger data to national access points?",
        "q_it": "Pubblicate i dati dei caricatori ai punti di accesso nazionali?",
    },
    "staff": {
        "values": [("2025-06-01", "180", "180"), ("2026-04-01", "200", "200")],
        "en": "The company employs more than {v} people.",
        "it": "L'azienda impiega oltre {v} persone.",
        "q_en": "How many people does your company employ?",
        "q_it": "Quante persone impiega la vostra azienda?",
    },
}
UNANSWERABLE = [
    ("Are you certified to ISO 50001 energy management?", "Siete certificati ISO 50001 per la gestione dell'energia?"),
    ("What is the carbon footprint in grams of CO2 per kWh delivered?", "Qual è l'impronta di carbonio in grammi di CO2 per kWh erogato?"),
    ("Do you operate hydrogen refuelling stations?", "Gestite stazioni di rifornimento di idrogeno?"),
    ("What is the limit of your public liability insurance?", "Qual è il massimale della vostra assicurazione di responsabilità civile?"),
    ("How many charging sessions did you serve in Italy last year?", "Quante sessioni di ricarica avete servito in Italia l'anno scorso?"),
]
FILLER = [
    ("en", "Our operations centre monitors every charger around the clock and dispatches field service partners."),
    ("en", "Location partners receive a share of the charging revenue and a monthly statement."),
    ("it", "Il centro operativo monitora ogni caricatore 24 ore su 24 e coordina i partner di assistenza."),
    ("en", "Projects follow the operator's health, safety and environment rules from site survey to commissioning."),
    ("it", "I progetti seguono le regole di salute, sicurezza e ambiente dal sopralluogo al collaudo."),
    ("en", "Tariffs are published per location and shown before the session starts."),
]
DOCS = [  # (doc id, title, date, language, kind)
    ("BID-2024-A22", "Answers to the A22 concession tender", "2024-06-15", "it", "bid"),
    ("BID-2025-NL", "Answers to a Dutch municipal tender", "2025-03-20", "en", "bid"),
    ("FACTS-2025-Q4", "Company fact sheet Q4 2025", "2025-11-20", "en", "factsheet"),
    ("FACTS-2026-Q2", "Company fact sheet Q2 2026", "2026-05-25", "en", "factsheet"),
    ("SLA-2026", "Service levels for high-power charging", "2026-02-01", "en", "policy"),
    ("SLA-2024", "Service levels for high-power charging", "2024-06-01", "en", "policy"),
    ("CERT-ISMS", "Information security certificate summary", "2023-09-10", "en", "certificate"),
    ("AFIR-2025", "AFIR compliance statement", "2025-04-15", "en", "policy"),
    ("MCS-2025", "Megawatt charging project summary", "2025-11-26", "en", "project"),
    ("BID-2025-IT", "Risposte alla gara regionale Lombardia", "2025-12-05", "it", "bid"),
    ("PEOPLE-2025", "Organisation overview 2025", "2025-06-01", "en", "factsheet"),
    ("PEOPLE-2026", "Organisation overview 2026", "2026-04-02", "en", "factsheet"),
    ("PLAN-2025", "Expansion plan 2025", "2025-01-15", "en", "plan"),
    ("PLAN-2026", "Expansion plan 2026", "2026-03-01", "en", "plan"),
]


def _fact_values_on(fact: dict[str, Any], day: str) -> tuple[str, str] | None:
    vals = [v for v in fact["values"] if v[0] <= day]
    return (vals[-1][1], vals[-1][2]) if vals else None


def library(net: Network) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (documents with passages, truth facts)."""
    r = rng("tenders", "library")
    docs = []
    for doc_id, title, day, lang, kind in DOCS:
        passages = []
        facts_here = list(FACTS)
        r.shuffle(facts_here)
        for fid in facts_here[: int(r.integers(4, 9))]:
            v = _fact_values_on(FACTS[fid], day)
            if v is None:
                continue
            text = FACTS[fid][lang].format(v=v[0] if lang == "en" else v[1])
            passages.append({"fact": fid, "text": text})
        for fl, ftext in FILLER:
            if fl == lang and r.random() < 0.6:
                passages.append({"fact": None, "text": ftext})
        r.shuffle(passages)
        docs.append(
            {"doc_id": doc_id, "title": title, "date": day, "lang": lang, "kind": kind,
             "passages": [{"pid": f"{doc_id}#{k + 1}", "text": p["text"]} for k, p in enumerate(passages)],
             "_facts": [p["fact"] for p in passages]}
        )
    # every fact's newest value must be somewhere in the library
    newest_day = {fid: f["values"][-1][0] for fid, f in FACTS.items()}
    for fid, day in newest_day.items():
        holder = [d for d in docs if d["date"] >= day and fid in d["_facts"]]
        if not holder:
            target = min((d for d in docs if d["date"] >= day and d["lang"] == "en"), key=lambda d: d["date"])
            v = FACTS[fid]["values"][-1]
            target["passages"].append({"pid": f"{target['doc_id']}#{len(target['passages']) + 1}",
                                       "text": FACTS[fid]["en"].format(v=v[1])})
            target["_facts"].append(fid)
    for d in docs:
        d.pop("_facts")
    return docs, [{"fact": fid, "values": f["values"]} for fid, f in FACTS.items()]


def questions(net: Network, n: int, weeks: tuple[int, int], stream: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (questions, truth per question)."""
    cfg = net.cfg["tenders"]
    r = rng("tenders", stream)
    qs, truth = [], []
    asof = "2026-10-01"
    for k in range(n):
        lang = "it" if r.random() < 0.45 else "en"
        week = int(r.integers(weeks[0], weeks[1] + 1))
        qid = f"Q-{stream}-{k + 1:04d}"
        if r.random() < cfg["unanswerable_share"]:
            en, it = UNANSWERABLE[int(r.integers(len(UNANSWERABLE)))]
            qs.append({"question_id": qid, "lang": lang, "text": en if lang == "en" else it, "week": week})
            truth.append({"question_id": qid, "answerable": False, "fact": None, "value": None, "stale_values": []})
            continue
        fid = list(FACTS)[int(r.integers(len(FACTS)))]
        f = FACTS[fid]
        v = _fact_values_on(f, asof)
        assert v is not None
        stale = [x[1] for x in f["values"][:-1]] + [x[2] for x in f["values"][:-1]]
        qs.append({"question_id": qid, "lang": lang, "text": f["q_en"] if lang == "en" else f["q_it"], "week": week})
        truth.append({"question_id": qid, "answerable": True, "fact": fid, "value": v[0], "value_it": v[1],
                      "stale_values": stale})
    return qs, truth
