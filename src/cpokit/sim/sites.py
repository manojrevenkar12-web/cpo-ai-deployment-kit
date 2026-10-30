"""An acquired charging network's site export: what the new owner receives (a spreadsheet with
Italian headers, written by many hands, and a few sites described only in a commissioning
protocol), and what each location really is (truth)."""

from __future__ import annotations

from typing import Any

import numpy as np

from .world import Network, rng

COMUNI = [
    ("Milano", "MI", "20121", 45.4642, 9.1900),
    ("Bergamo", "BG", "24121", 45.6983, 9.6773),
    ("Brescia", "BS", "25121", 45.5416, 10.2118),
    ("Verona", "VR", "37121", 45.4384, 10.9916),
    ("Padova", "PD", "35121", 45.4064, 11.8768),
    ("Torino", "TO", "10121", 45.0703, 7.6869),
    ("Novara", "NO", "28100", 45.4469, 8.6219),
    ("Bologna", "BO", "40121", 44.4949, 11.3426),
    ("Modena", "MO", "41121", 44.6471, 10.9252),
    ("Trento", "TN", "38121", 46.0748, 11.1217),
]
VIE = ["Via Emilia", "Viale Lombardia", "Strada Statale 11", "Via dell'Industria", "Corso Europa", "Via Autostrada",
       "Area di Servizio Brianza Nord", "Via Monte Rosa"]
CONNECTOR_WORDS = {
    "IEC_62196_T2_COMBO": ["CCS2", "CCS", "Combo 2", "CCS Combo"],
    "IEC_62196_T2": ["Tipo 2", "Type 2", "Mennekes", "T2"],
    "CHADEMO": ["CHAdeMO", "Chademo"],
}
WEEKDAYS_IT = ["lun", "mar", "mer", "gio", "ven", "sab", "dom"]


def build(net: Network, n: int, stream: str, prefix: str = "RRN") -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Returns (export rows, protocol documents, truth per site)."""
    cfg = net.cfg["site_onboarding"]
    d = cfg["defects"]
    r = rng("acquired-sites", stream)
    rows: list[dict[str, Any]] = []
    docs: list[dict[str, Any]] = []
    truth: list[dict[str, Any]] = []
    for i in range(n):
        comune, prov, cap, lat0, lon0 = COMUNI[int(r.integers(len(COMUNI)))]
        lat = round(lat0 + float(r.normal(0, 0.04)), 5)
        lon = round(lon0 + float(r.normal(0, 0.05)), 5)
        code = f"{prefix}{i + 1:04d}"
        name = f"Rete Rapida {comune} {i + 1}"
        address = f"{VIE[int(r.integers(len(VIE)))]} {int(r.integers(1, 250))}"
        dc = r.random() < 0.7
        connectors: list[dict[str, Any]] = []
        if dc:
            kw = int(r.choice([50, 150, 300]))
            n_ccs = int(r.integers(2, 5))
            for _ in range(n_ccs):
                connectors.append({"standard": "IEC_62196_T2_COMBO", "format": "CABLE", "power_type": "DC",
                                   "max_electric_power": kw * 1000})
            if r.random() < 0.25:
                connectors.append({"standard": "CHADEMO", "format": "CABLE", "power_type": "DC",
                                   "max_electric_power": 50000})
        if not dc or r.random() < 0.4:
            for _ in range(int(r.integers(1, 3))):
                connectors.append({"standard": "IEC_62196_T2", "format": "SOCKET", "power_type": "AC_3_PHASE",
                                   "max_electric_power": 22000})
        h24 = r.random() < 0.6
        hours = {"twentyfourseven": True} if h24 else {
            "twentyfourseven": False,
            "regular_hours": [{"weekday": k, "period_begin": "07:00", "period_end": "22:00"} for k in range(1, 6)]
            + [{"weekday": 6, "period_begin": "08:00", "period_end": "20:00"}],
        }
        card = dc and r.random() >= d["no_card_terminal"]
        defects = {k: bool(r.random() < p) for k, p in d.items()}
        if not dc:
            defects["no_card_terminal"] = False
            defects["conflicting_power"] = False
        if dc:
            defects["no_card_terminal"] = not card
        needs = [k for k in ("missing_postal_code", "conflicting_power", "no_card_terminal") if defects[k]]
        loc = {
            "id": f"IT-{code}",
            "name": name,
            "address": address,
            "city": comune,
            "postal_code": None if defects["missing_postal_code"] else cap,
            "country_code": "IT",
            "coordinates": {"latitude": f"{lat:.5f}", "longitude": f"{lon:.5f}"},
            "connectors": connectors,
            "opening_times": hours,
            "card_payment": bool(card or not dc),
        }
        truth.append({"site_code": code, "location": loc, "needs_person": needs, "defects": defects})
        # --- how it was written down
        def num(x: float, nd: int = 5, *, defect: bool = defects["comma_decimal"]) -> str:
            s = f"{x:.{nd}f}"
            return s.replace(".", ",") if defect else s

        la, lo = (lon, lat) if defects["swapped_coordinates"] else (lat, lon)
        groups: dict[tuple[str, int], int] = {}
        for c in connectors:
            key = (c["standard"], c["max_electric_power"] // 1000)
            groups[key] = groups.get(key, 0) + 1
        parts = []
        for (std, kw), n in groups.items():
            word = CONNECTOR_WORDS[std][int(r.integers(len(CONNECTOR_WORDS[std])))] if defects[
                "connector_synonym"] else {"IEC_62196_T2_COMBO": "CCS2", "IEC_62196_T2": "Tipo 2",
                                            "CHADEMO": "CHAdeMO"}[std]
            listed_kw = kw
            if defects["conflicting_power"] and std == "IEC_62196_T2_COMBO":
                listed_kw = int(r.choice([22, 40]))
            parts.append(f"{n}x {word} {listed_kw}kW")
        max_kw = max(c["max_electric_power"] for c in connectors) // 1000
        if h24:
            orari = ["24 ore", "H24", "sempre aperto", "24/7"][int(r.integers(4))] if defects["free_text_hours"] else "24/7"
        else:
            orari = "lun-ven 07:00-22:00, sab 08:00-20:00" if defects["free_text_hours"] else "L-V 07-22; S 08-20"
        pay = "POS contactless, app, RFID" if card else ("app, RFID" if dc else "app, RFID, POS")
        row = {
            "Codice sito": code,
            "Nome": name,
            "Indirizzo": address,
            "CAP": "" if defects["missing_postal_code"] else cap,
            "Comune": comune,
            "Provincia": prov,
            "Latitudine": num(la),
            "Longitudine": num(lo),
            "Punti di ricarica": " + ".join(parts),
            "Potenza max": f"{max_kw * 1000}" if defects["power_in_watts"] else f"{max_kw}",
            "Orari": orari,
            "Pagamento": pay,
            "Note": "",
        }
        if r.random() < cfg["pdf_share"]:
            docs.append({"doc_id": f"VERBALE-{code}", "site_code": code, "text": _protocol(row, r)})
            continue
        rows.append(row)
        if defects["duplicate_row"]:
            dup = dict(row)
            dup["Nome"] = name.upper()
            dup["Note"] = "riga duplicata da migrazione"
            rows.append(dup)
    order = r.permutation(len(rows))
    return [rows[int(k)] for k in order], docs, truth


def _protocol(row: dict[str, str], r: np.random.Generator) -> str:
    return (
        f"VERBALE DI COLLAUDO - Impianto {row['Codice sito']} ({row['Nome']}).\n"
        f"L'impianto si trova in {row['Indirizzo']}, {row['CAP']} {row['Comune']} ({row['Provincia']}). "
        f"Coordinate GPS: {row['Latitudine']} N, {row['Longitudine']} E.\n"
        f"Dotazione: {row['Punti di ricarica']}. Potenza massima dell'impianto: {row['Potenza max']} kW.\n"
        f"Orario di apertura: {row['Orari']}. Metodi di pagamento: {row['Pagamento']}.\n"
        f"Il collaudo è stato eseguito con esito positivo il {int(r.integers(1, 28))}/0{int(r.integers(1, 9))}/2026."
    )
