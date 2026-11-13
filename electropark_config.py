"""
ElectroPark Ontario - generateur de jeu de donnees d'exploitation (fictif)
Projet CESI - MKR Corp. / C.E.S. International - industry

Simule 12 mois d'exploitation du hub logistique (2027-03-01 -> 2028-02-29),
calibre sur les contraintes chiffrees du Terms of Reference :
  - 200-350 vehicules/jour
  - sejour moyen 2,5-4 jours
  - capacite 900-1200 vehicules
  - autosuffisance energetique visee 60-80 % (1 MWc photovoltaique)
  - bornes AC 22 kW et DC 50-150 kW
  - -20 degC (hiver) a +30 degC (ete), neige et cycles gel-degel

Conventions de sortie : ISO 8601, separateur virgule, decimal point, UTF-8.
"""

import csv
import datetime as dt
import math
import random
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)
random.seed(20270301)

# ---------------------------------------------------------------- cadrage
OPS_START = dt.date(2027, 3, 1)       # capacite operationnelle atteinte
OPS_END = dt.date(2028, 2, 29)        # 366 jours (2028 bissextile)
PRELOAD_START = dt.date(2027, 2, 14)  # pre-remplissage du parc
CAL_START = dt.date(2027, 1, 1)
CAL_END = dt.date(2028, 3, 31)

PV_PEAK_KWP = 1000.0                  # 1 MWc
BESS_CAPACITY_KWH = 2000.0            # 2 MWh
BESS_POWER_KW = 500.0
BESS_MIN_SOC, BESS_MAX_SOC = 0.10, 0.95

MONTHS_EN = ["January", "February", "March", "April", "May", "June", "July",
             "August", "September", "October", "November", "December"]
DAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ------------------------------------------------- referentiel climatique
# Hamilton / sud de l'Ontario : temperature moyenne mensuelle (degC)
TEMP_AVG = {1: -5.5, 2: -4.5, 3: 0.5, 4: 7.5, 5: 14.0, 6: 19.0,
            7: 22.0, 8: 21.0, 9: 17.0, 10: 10.5, 11: 4.0, 12: -2.0}
# Productible photovoltaique moyen (kWh/kWc/jour), conditions ontariennes
PV_DAILY = {1: 1.6, 2: 2.5, 3: 3.4, 4: 4.2, 5: 4.7, 6: 5.0,
            7: 5.0, 8: 4.5, 9: 3.8, 10: 2.6, 11: 1.5, 12: 1.2}
# Probabilite de chute de neige par mois
SNOW_PROB = {1: 0.42, 2: 0.38, 3: 0.22, 4: 0.06, 5: 0.0, 6: 0.0,
             7: 0.0, 8: 0.0, 9: 0.0, 10: 0.02, 11: 0.16, 12: 0.38}

# --------------------------------------------------- tarification Ontario
# Structure Time-of-Use de l'Ontario Energy Board.
# Prix : grille hiver 2026-2027 (9,1 / 14,6 / 18,9) et grille ete 2026
# (9,8 / 15,7 / 20,3), reconduits sur l'exercice simule.
TARIFF = {
    "winter": {"off": 9.1, "mid": 14.6, "on": 18.9},
    "summer": {"off": 9.8, "mid": 15.7, "on": 20.3},
}


def tariff_season(d):
    """Saison tarifaire OEB : hiver du 1er novembre au 30 avril."""
    return "winter" if (d.month >= 11 or d.month <= 4) else "summer"


def tariff_period(d, hour, is_holiday):
    """Periode tarifaire. Weekends et jours feries : off-peak toute la journee."""
    if d.weekday() >= 5 or is_holiday:
        return "off"
    if tariff_season(d) == "winter":
        # on-peak matin et soir, mid-peak en journee
        if 7 <= hour < 11 or 17 <= hour < 19:
            return "on"
        if 11 <= hour < 17:
            return "mid"
        return "off"
    # ete : on-peak en milieu de journee
    if 11 <= hour < 17:
        return "on"
    if 7 <= hour < 11 or 17 <= hour < 19:
        return "mid"
    return "off"


def easter(year):
    """Dimanche de Paques (algorithme de Butcher), pour le Vendredi saint."""
    a, b, c = year % 19, year // 100, year % 100
    d_, e = b // 4, b % 4
    f, g = (b + 8) // 25, (b - (b + 8) // 25 + 1) // 3
    h = (19 * a + b - d_ - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def nth_weekday(year, month, weekday, n):
    d = dt.date(year, month, 1)
    d += dt.timedelta(days=(weekday - d.weekday()) % 7)
    return d + dt.timedelta(weeks=n - 1)


def holidays(year):
    """Jours feries de l'Ontario."""
    vic = dt.date(year, 5, 25)
    while vic.weekday() != 0:
        vic -= dt.timedelta(days=1)
    return {
        dt.date(year, 1, 1),                      # New Year's Day
        nth_weekday(year, 2, 0, 3),               # Family Day
        easter(year) - dt.timedelta(days=2),      # Good Friday
        vic,                                      # Victoria Day
        dt.date(year, 7, 1),                      # Canada Day
        nth_weekday(year, 8, 0, 1),               # Civic Holiday
        nth_weekday(year, 9, 0, 1),               # Labour Day
        nth_weekday(year, 10, 0, 2),              # Thanksgiving
        dt.date(year, 12, 25),                    # Christmas Day
        dt.date(year, 12, 26),                    # Boxing Day
    }


HOLIDAYS = holidays(2027) | holidays(2028)


def season_of(d):
    m = d.month
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4, 5):
        return "Spring"
    if m in (6, 7, 8):
        return "Summer"
    return "Fall"


def iso(d):
    return d.isoformat() if d else ""


def daterange(a, b):
    d = a
    while d <= b:
        yield d
        d += dt.timedelta(days=1)


def write_csv(name, rows, fieldnames=None):
    path = OUT / name
    fn = fieldnames or list(rows[0].keys())
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fn, delimiter=",",
                           lineterminator="\n", quoting=csv.QUOTE_MINIMAL)
        w.writeheader()
        w.writerows(rows)
    print(f"  {name:32s} {len(rows):7d} lignes  {path.stat().st_size / 1024:9.1f} Ko")


# =========================================================== DIMENSIONS
ZONES = [
    # code,  nom,                      type,        capacite, surface, recharge, type borne, couvert
    ("Z-IN", "Reception & Inspection", "Reception",   60,  1300, 0, "None",        1),
    ("Z-A",  "Storage Block A",        "Storage",    325,  4650, 0, "None",        0),
    ("Z-B",  "Storage Block B",        "Storage",    325,  4650, 0, "None",        0),
    ("Z-C",  "Storage Block C",        "Storage",    235,  3350, 0, "None",        1),
    ("Z-AC", "AC Charging Area",       "Charging",    85,  1700, 1, "AC 22 kW",    0),
    ("Z-DC", "DC Fast Charging Bay",   "Charging",    40,   900, 1, "DC 50-150 kW", 1),
    ("Z-OUT", "Dispatch & Loading",    "Dispatch",    70,  2000, 0, "None",        0),
    ("Z-QR", "Quarantine & Rework",    "Quarantine",  60,  1450, 0, "None",        1),
]

MODELS = [
    # code,     nom,                   segment,          batterie, longueur, emprise, part, usine
    ("MKR-U1", "MKR Urba",            "City car",        42, 3.95,  7.1, 0.28, "Hamilton"),
    ("MKR-U2", "MKR Urba Long Range", "City car",        54, 3.95,  7.1, 0.22, "Hamilton"),
    ("MKR-V1", "MKR Volt S",          "Compact sedan",   65, 4.45,  8.2, 0.24, "Hamilton"),
    ("MKR-C1", "MKR Cargo L",         "Light van",       78, 4.90,  9.8, 0.16, "Hamilton"),
    ("MKR-C2", "MKR Cargo XL",        "Van",             92, 5.40, 11.2, 0.10, "Windsor"),
]

CARRIERS = [
    ("CAR-ML", "Maple Logistics",         "Truck", "Ontario",            "Framework", 1, 0.30),
    ("CAR-TC", "TransCan Auto",           "Truck", "Quebec",             "Framework", 2, 0.22),
    ("CAR-GL", "Great Lakes Transport",   "Rail",  "Ontario / Midwest US", "Spot",    3, 0.18),
    ("CAR-PW", "PacWest Carriers",        "Rail",  "British Columbia",   "Framework", 6, 0.14),
    ("CAR-NF", "Northern Fleet Services", "Truck", "Northern Ontario",   "Spot",      2, 0.10),
    ("CAR-AT", "Atlantic Movers",         "Truck", "Maritimes",          "Spot",      4, 0.06),
]

# 48 bornes AC 22 kW + 12 bornes DC (6x50, 4x100, 2x150) = 2 056 kW installes
CHARGER_SPEC = ([("AC", 22.0, "Z-AC", "NordVolt", "Type 2")] * 48
                + [("DC", 50.0, "Z-DC", "NordVolt", "CCS1")] * 6
                + [("DC", 100.0, "Z-DC", "HydroCharge", "CCS1")] * 4
                + [("DC", 150.0, "Z-DC", "HydroCharge", "CCS1")] * 2)


def build_dim_date():
    rows = []
    for d in daterange(CAL_START, CAL_END):
        iso_y, iso_w, iso_dow = d.isocalendar()
        is_hol = d in HOLIDAYS
        rows.append({
            "Date": iso(d),
            "Year": d.year,
            "Quarter": f"{d.year}-Q{(d.month - 1) // 3 + 1}",
            "MonthNumber": d.month,
            "MonthName": MONTHS_EN[d.month - 1],
            "MonthShort": MONTHS_EN[d.month - 1][:3],
            "YearMonth": f"{d.year}-{d.month:02d}",
            "WeekNumber": iso_w,
            "YearWeek": f"{iso_y}-W{iso_w:02d}",
            "DayOfMonth": d.day,
            "DayName": DAYS_EN[iso_dow - 1],
            "DayOfWeekNumber": iso_dow,
            "IsWeekend": 1 if iso_dow >= 6 else 0,
            "IsHoliday": 1 if is_hol else 0,
            "IsOperatingDay": 0 if (iso_dow == 7 or is_hol) else 1,
            "Season": season_of(d),
            "TariffSeason": "Winter" if tariff_season(d) == "winter" else "Summer",
            "IsOperationsPeriod": 1 if OPS_START <= d <= OPS_END else 0,
        })
    return rows


def build_dim_zone():
    return [{
        "ZoneCode": c, "ZoneName": n, "ZoneType": t, "CapacityVehicles": cap,
        "SurfaceM2": s, "HasCharging": hc, "ChargerTypeAvailable": ct,
        "IsCovered": cov,
    } for c, n, t, cap, s, hc, ct, cov in ZONES]


def build_dim_vehicle_model():
    return [{
        "ModelCode": c, "ModelName": n, "Segment": s, "BatteryCapacityKWh": b,
        "LengthM": l, "FootprintM2": f, "ProductionSharePct": round(p * 100, 1),
        "OriginPlant": pl,
    } for c, n, s, b, l, f, p, pl in MODELS]


def build_dim_carrier():
    return [{
        "CarrierCode": c, "CarrierName": n, "TransportMode": m,
        "DestinationRegion": r, "ContractType": ct, "AvgLeadTimeDays": lt,
    } for c, n, m, r, ct, lt, _ in CARRIERS]


def build_dim_charger():
    rows, n_ac, n_dc = [], 0, 0
    for kind, power, zone, maker, conn in CHARGER_SPEC:
        if kind == "AC":
            n_ac += 1
            cid = f"AC-{n_ac:03d}"
        else:
            n_dc += 1
            cid = f"DC-{n_dc:03d}"
        rows.append({
            "ChargerID": cid, "ZoneCode": zone, "ChargerType": kind,
            "PowerKW": power, "Manufacturer": maker, "Connector": conn,
            "CommissioningDate": iso(dt.date(2027, 1, 20) if kind == "DC"
                                     else dt.date(2027, 2, 3)),
        })
    return rows
