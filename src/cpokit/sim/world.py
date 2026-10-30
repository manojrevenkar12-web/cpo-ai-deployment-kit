"""The network: sites, charge points, tariffs with their version history, charging sessions with
meter values and connector status, and how the operator's billing turns a session into a CDR.

Sessions are generated around the cases that need them (the session a dispute is about, and the
other sessions on the same charge point that day), not for the whole network: that keeps a world
small while making every lookup as ambiguous as it is in a real CSMS."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np

from .. import settings

DAY = 86400
CITIES: dict[str, list[tuple[str, float, float]]] = {
    "AT": [("Wien", 48.21, 16.37), ("Graz", 47.07, 15.44), ("Linz", 48.31, 14.29), ("Salzburg", 47.81, 13.05)],
    "CZ": [("Praha", 50.08, 14.44), ("Brno", 49.20, 16.61), ("Plzeň", 49.74, 13.38)],
    "DE": [
        ("Essen", 51.46, 7.01),
        ("München", 48.14, 11.58),
        ("Berlin", 52.52, 13.40),
        ("Hamburg", 53.55, 9.99),
        ("Köln", 50.94, 6.96),
        ("Frankfurt am Main", 50.11, 8.68),
        ("Stuttgart", 48.78, 9.18),
        ("Leipzig", 51.34, 12.37),
        ("Hannover", 52.37, 9.73),
        ("Nürnberg", 49.45, 11.08),
    ],
    "DK": [("København", 55.68, 12.57), ("Aarhus", 56.16, 10.20), ("Odense", 55.40, 10.39)],
    "GB": [("London", 51.51, -0.13), ("Birmingham", 52.49, -1.89), ("Manchester", 53.48, -2.24), ("Leeds", 53.80, -1.55)],
    "HU": [("Budapest", 47.50, 19.04), ("Győr", 47.69, 17.63), ("Debrecen", 47.53, 21.63)],
    "IT": [("Milano", 45.46, 9.19), ("Torino", 45.07, 7.69), ("Bologna", 44.49, 11.34), ("Verona", 45.44, 10.99)],
    "NL": [("Amsterdam", 52.37, 4.90), ("Rotterdam", 51.92, 4.48), ("Utrecht", 52.09, 5.12), ("Eindhoven", 51.44, 5.47)],
    "PL": [("Warszawa", 52.23, 21.01), ("Kraków", 50.06, 19.94), ("Poznań", 52.41, 16.93)],
    "RO": [("București", 44.43, 26.10), ("Cluj-Napoca", 46.77, 23.60), ("Timișoara", 45.76, 21.23)],
    "SE": [("Stockholm", 59.33, 18.07), ("Göteborg", 57.71, 11.97), ("Malmö", 55.60, 13.00)],
}
STREETS = {
    "de": ["Hauptstraße", "Bahnhofstraße", "Industriestraße", "Am Markt", "Ringstraße"],
    "en": ["High Street", "Station Road", "Park Lane", "Mill Road", "Church Street"],
    "it": ["Via Roma", "Via Garibaldi", "Corso Italia", "Via Milano", "Viale Europa"],
    "nl": ["Stationsweg", "Kerkstraat", "Dorpsstraat", "Industrieweg"],
    "sv": ["Storgatan", "Kungsgatan", "Industrigatan", "Järnvägsgatan"],
    "da": ["Vestergade", "Nørregade", "Stationsvej"],
    "pl": ["ul. Długa", "ul. Polna", "ul. Kolejowa"],
    "cs": ["Nádražní", "Hlavní", "Průmyslová"],
    "hu": ["Fő utca", "Kossuth utca", "Petőfi utca"],
    "ro": ["Strada Gării", "Strada Principală", "Bulevardul Unirii"],
}


def org() -> dict[str, Any]:
    return settings.load("org")


def rng(*key: Any) -> np.random.Generator:
    """An independent, reproducible stream per purpose (common random numbers across runs)."""
    h = hashlib.sha256("|".join(map(str, (org()["seed"], *key))).encode()).digest()
    return np.random.default_rng(int.from_bytes(h[:8], "little"))


def epoch(d: date | datetime) -> int:
    if isinstance(d, datetime):
        return int(d.timestamp())
    return int(datetime(d.year, d.month, d.day, tzinfo=UTC).timestamp())


def local(ts: int, tz: str) -> datetime:
    return datetime.fromtimestamp(ts, UTC).astimezone(ZoneInfo(tz))


@dataclass
class TariffVersion:
    tariff_id: str
    valid_from: int
    energy: float
    peak: float
    idle_per_min: float
    idle_grace_min: int


@dataclass
class Evse:
    evse_id: str
    site_id: str
    kind: str  # DC or AC
    kw: int


@dataclass
class Site:
    site_id: str
    country: str
    city: str
    address: str
    lat: float
    lon: float
    tz: str
    vat: float
    lang: str
    evses: list[Evse] = field(default_factory=list)
    tariffs: dict[str, list[TariffVersion]] = field(default_factory=dict)  # kind -> versions by date


@dataclass(eq=False)
class Session:
    session_id: str
    evse_id: str
    site_id: str
    start: int
    stop: int  # end of the transaction (cable unplugged or remote stop)
    charge_end: int  # when energy stopped flowing; idle from here to stop
    energy_wh: int  # true energy, as signed by the meter
    meter_start_wh: int
    meter: list[tuple[int, int]]  # (ts, cumulative Wh) every 5 minutes
    statuses: list[tuple[int, str, str]]  # (ts, status, error_code)
    token: str  # how the driver authorised: card:<last4>, app:<emsp>, rfid:<id>
    lock_fault: bool = False


class Network:
    def __init__(self) -> None:
        cfg = org()
        self.cfg = cfg
        self.t0 = epoch(date.fromisoformat(str(cfg["start"])))
        self.history_start = self.t0 - cfg["history_days"] * DAY
        self.end = self.t0 + cfg["weeks"] * 7 * DAY
        self.sites: dict[str, Site] = {}
        self.evses: dict[str, Evse] = {}
        self.sessions: dict[str, Session] = {}
        self._n_sessions = 0
        self._build_sites()

    # ---- sites and tariffs -------------------------------------------------------------------
    def _build_sites(self) -> None:
        cfg = self.cfg
        net = cfg["network"]
        for cc, c in cfg["countries"].items():
            r = rng("sites", cc)
            for i in range(c["sites"]):
                city, lat, lon = CITIES[cc][int(r.integers(len(CITIES[cc])))]
                sid = f"{cc}-{i + 1:04d}"
                street = STREETS[c["lang"]][int(r.integers(len(STREETS[c["lang"]])))]
                s = Site(
                    sid,
                    cc,
                    city,
                    f"{street} {int(r.integers(1, 180))}",
                    round(lat + r.normal(0, 0.05), 5),
                    round(lon + r.normal(0, 0.07), 5),
                    c["tz"],
                    c["vat"],
                    c["lang"],
                )
                n = int(r.integers(net["evses_per_site"][0], net["evses_per_site"][1] + 1))
                dc = r.random() < net["dc_share"]
                for k in range(n):
                    kind = "DC" if dc else "AC"
                    kw = int(r.choice([150, 300]) if kind == "DC" else 22)
                    e = Evse(f"{cc}*CPO*E{i + 1:04d}*{k + 1}", sid, kind, kw)
                    s.evses.append(e)
                    self.evses[e.evse_id] = e
                kinds = {e.kind for e in s.evses}
                for kind in kinds:
                    t = net["tariffs"][kind]
                    base = TariffVersion(
                        f"T-{sid}-{kind}-v1", self.history_start - 400 * DAY, t["energy"], t["peak"],
                        t["idle_per_min"], t["idle_grace_min"],
                    )
                    versions = [base]
                    ch = net["tariff_change"]
                    if r.random() < ch["share_of_sites"]:
                        up = float(r.uniform(*ch["increase"]))
                        when = self.t0 + int(r.integers(ch["window_days"][0], ch["window_days"][1])) * DAY
                        versions.append(
                            TariffVersion(
                                f"T-{sid}-{kind}-v2", when, round(base.energy + up, 2), round(base.peak + up, 2),
                                base.idle_per_min, base.idle_grace_min,
                            )
                        )
                    s.tariffs[kind] = versions
                self.sites[sid] = s

    def tariff_at(self, site: Site, kind: str, ts: int, early: bool = False) -> TariffVersion:
        """The version valid at ts; with early=True, the next version (a billing bug that applies an
        announced price change before its date)."""
        versions = [v for v in site.tariffs[kind] if v.valid_from <= ts]
        if early:
            later = [v for v in site.tariffs[kind] if v.valid_from > ts]
            if later:
                return later[0]
        return versions[-1]

    def changed_sites(self) -> list[tuple[Site, str, TariffVersion]]:
        return [(s, k, v[-1]) for s in self.sites.values() for k, v in s.tariffs.items() if len(v) > 1]

    # ---- sessions ----------------------------------------------------------------------------
    def new_session(
        self,
        evse: Evse,
        start: int,
        r: np.random.Generator,
        *,
        token: str,
        lock_fault: bool = False,
        idle_min: float | None = None,
        energy_kwh: float | None = None,
    ) -> Session:
        self._n_sessions += 1
        site = self.sites[evse.site_id]
        if energy_kwh is None:
            energy_kwh = float(r.gamma(4.0, 7.0 if evse.kind == "DC" else 3.0))
        power = evse.kw * float(r.uniform(0.35, 0.8)) if evse.kind == "DC" else float(r.uniform(6.5, 11.0))
        minutes = max(5.0, energy_kwh / power * 60)
        if idle_min is None:
            idle_min = float(r.exponential(18 if evse.kind == "DC" else 70))
        charge_end = start + int(minutes * 60)
        stop = charge_end + int(idle_min * 60)
        meter_start = int(r.integers(1_000_000, 90_000_000))
        meter: list[tuple[int, int]] = []
        t = start
        while t < charge_end:
            frac = (t - start) / max(1, charge_end - start)
            meter.append((t, meter_start + int(energy_kwh * 1000 * frac)))
            t += 300
        energy_wh = int(round(energy_kwh * 1000))
        meter.append((charge_end, meter_start + energy_wh))
        statuses = [(start, "Occupied", ""), (start + 5, "Charging", ""), (charge_end, "SuspendedEV", "")]
        if lock_fault:
            statuses.append((charge_end + 120, "Faulted", "ConnectorLockFailure"))
        statuses.append((stop, "Available", ""))
        sid = f"{site.country}-S{self._n_sessions:07d}"
        s = Session(sid, evse.evse_id, site.site_id, start, stop, charge_end, energy_wh, meter_start, meter,
                    statuses, token, lock_fault)
        self.sessions[sid] = s
        return s

    def neighbours(self, s: Session, r: np.random.Generator, n: tuple[int, int] = (3, 8)) -> list[Session]:
        """Other sessions on the same charge point and its neighbours around the same day."""
        evse = self.evses[s.evse_id]
        site = self.sites[evse.site_id]
        out = []
        for _ in range(int(r.integers(n[0], n[1] + 1))):
            e = site.evses[int(r.integers(len(site.evses)))] if r.random() < 0.4 else evse
            start = s.start + int(r.normal(0, 7 * 3600))
            if abs(start - s.start) < 1800 and e is evse:
                start += 3 * 3600
            last4 = f"{int(r.integers(0, 10000)):04d}"
            out.append(self.new_session(e, start, r, token=f"card:{last4}"))
        return out


# ---- the operator's billing (truth side) ---------------------------------------------------------
def peak_energy_wh(s: Session, tz: str | None) -> int:
    """Energy delivered during 17:00-21:00, in local time (tz) or, wrongly, in UTC (tz=None)."""
    total = 0
    prev_t, prev_v = s.meter[0]
    for t, v in s.meter[1:]:
        mid = (prev_t + t) // 2
        hour = (datetime.fromtimestamp(mid, UTC).astimezone(ZoneInfo(tz)) if tz else datetime.fromtimestamp(mid, UTC)).hour
        if 17 <= hour < 21:
            total += v - prev_v
        prev_t, prev_v = t, v
    return total


def bill(net: Network, s: Session, *, tariff_early: bool = False, utc_periods: bool = False,
         vat: float | None = None, energy_wh: int | None = None, idle_on_fault: bool = False,
         stop: int | None = None) -> dict[str, Any]:
    """The CDR the operator should send (no flags), or the one a billing bug produces."""
    evse = net.evses[s.evse_id]
    site = net.sites[s.site_id]
    tv = net.tariff_at(site, evse.kind, s.start, early=tariff_early)
    e_wh = s.energy_wh if energy_wh is None else energy_wh
    peak_wh = peak_energy_wh(s, None if utc_periods else site.tz)
    peak_wh = min(peak_wh, e_wh)
    energy_cost = (e_wh - peak_wh) / 1000 * tv.energy + peak_wh / 1000 * tv.peak
    end = s.stop if stop is None else stop
    idle_min = max(0.0, (end - s.charge_end) / 60 - tv.idle_grace_min)
    idle_cost = 0.0 if (s.lock_fault and not idle_on_fault) else idle_min * tv.idle_per_min
    excl = round(energy_cost, 2) + round(idle_cost, 2)
    rate = site.vat if vat is None else vat
    return {
        "tariff_id": tv.tariff_id,
        "total_energy_kwh": round(e_wh / 1000, 3),
        "peak_energy_kwh": round(peak_wh / 1000, 3),
        "idle_minutes": round(idle_min, 1),
        "energy_cost": round(energy_cost, 2),
        "idle_cost": round(idle_cost, 2),
        "total_cost_excl_vat": round(excl, 2),
        "vat_rate": rate,
        "total_cost_incl_vat": round(excl * (1 + rate), 2),
    }


def floor_hour(ts: int) -> int:
    return ts - ts % 3600


def week_of(net: Network, ts: int) -> int:
    return int(math.floor((ts - net.t0) / (7 * DAY))) + 1


def day_start(ts: int) -> int:
    return ts - ts % DAY


def at(net: Network, week: int, r: np.random.Generator) -> int:
    """A random moment in a given week (UTC), during the day."""
    d = net.t0 + (week - 1) * 7 * DAY + int(r.integers(0, 7)) * DAY
    return d + int(r.integers(6, 21)) * 3600 + int(r.integers(0, 3600))


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def days(n: float) -> timedelta:
    return timedelta(days=n)
