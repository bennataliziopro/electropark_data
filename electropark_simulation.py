"""Simulation d'exploitation : flux vehicules, recharge, energie, occupation."""

import datetime as dt
import math
import random
from collections import defaultdict

from electropark_config import (
    BESS_CAPACITY_KWH, BESS_MAX_SOC, BESS_MIN_SOC, BESS_POWER_KW, CARRIERS,
    HOLIDAYS, MODELS, OPS_END, OPS_START, PRELOAD_START, PV_DAILY,
    PV_PEAK_KWP, SNOW_PROB, TARIFF, TEMP_AVG, ZONES, build_dim_carrier,
    build_dim_charger, build_dim_date, build_dim_vehicle_model,
    build_dim_zone, daterange, iso, tariff_period, tariff_season, write_csv,
)

random.seed(20270301)

# Saisonnalite de la production usine (cycles de production, conges de juillet)
PROD_SEASON = {1: 0.95, 2: 1.00, 3: 1.06, 4: 1.08, 5: 1.08, 6: 1.05,
               7: 0.70, 8: 0.95, 9: 1.10, 10: 1.12, 11: 1.08, 12: 0.85}
SITE_CAPACITY = 1200           # places physiques, cf. dim_zone
SATURATION_THRESHOLD = 0.82    # au-dela, les arrivees sont bridees
MAX_FILL = 0.83                # parc operationnel maximal : les zones de transit
                               # ne sont pas substituables aux blocs de stockage
BASE_ARRIVALS = 295            # arrivees un jour ouvre standard
SATURDAY_FACTOR = 0.55
DWELL_MEAN = 2.7               # vise ~3,0 j observes apres surcout hivernal (ToR : 2,5-4)

MODEL_CODES = [m[0] for m in MODELS]
MODEL_WEIGHTS = [m[6] for m in MODELS]
MODEL_BATTERY = {m[0]: m[3] for m in MODELS}
MODEL_PLANT = {m[0]: m[7] for m in MODELS}
CARRIER_CODES = [c[0] for c in CARRIERS]
CARRIER_WEIGHTS = [c[6] for c in CARRIERS]

STORAGE_ZONES = ["Z-A", "Z-B", "Z-C"]
STORAGE_CAP = {z[0]: z[3] for z in ZONES}

# Profil horaire de la recharge : pilotage favorisant le solaire et l'off-peak
CHARGE_PROFILE = ([0.030] * 6            # 0h-5h   nuit off-peak
                  + [0.025, 0.020, 0.020, 0.020]   # 6h-9h  arrivees
                  + [0.075] * 7          # 10h-16h pic solaire
                  + [0.020, 0.020]       # 17h-18h on-peak hiver, bride
                  + [0.035] * 5)         # 19h-23h reprise off-peak
_tot = sum(CHARGE_PROFILE)
CHARGE_PROFILE = [p / _tot for p in CHARGE_PROFILE]

# Profil horaire de la consommation du site (eclairage, batiments, IT, HVAC)
SITE_PROFILE = ([0.025] * 6 + [0.045] * 4 + [0.055] * 7 + [0.050] * 2 + [0.030] * 5)
_tot = sum(SITE_PROFILE)
SITE_PROFILE = [p / _tot for p in SITE_PROFILE]


def is_operating(d):
    return d.weekday() != 6 and d not in HOLIDAYS


def daylight_hours(d):
    """Duree du jour a Hamilton (43 degN), approximation sinusoidale."""
    doy = d.timetuple().tm_yday
    return 12.15 - 3.1 * math.cos(2 * math.pi * (doy - 10) / 365.25)


def weather(d):
    """Temperature et enneigement du jour."""
    base = TEMP_AVG[d.month]
    nxt = TEMP_AVG[d.month % 12 + 1]
    frac = (d.day - 1) / 30.0
    avg = base + (nxt - base) * frac + random.gauss(0, 3.2)
    # Vagues de froid : episodes de quelques jours par hiver ontarien
    if d.month in (12, 1, 2) and random.random() < 0.09:
        avg -= random.uniform(5.0, 9.0)
    amp = random.uniform(4.0, 7.5)
    snow = 0.0
    if random.random() < SNOW_PROB[d.month]:
        snow = round(random.expovariate(1 / 4.0) + 0.5, 1)
    # Bornage sur la plage climatique retenue au ToR : -20 degC / +30 degC
    t_min = max(-21.5, avg - amp)
    t_max = min(31.5, avg + amp)
    return round(avg, 1), round(t_min, 1), round(t_max, 1), snow


# ===================================================== 1. FLUX VEHICULES
def simulate_vehicles():
    vehicles, vid = [], 0
    snow_memory = {}
    stock = defaultdict(int)       # parc present par date, mis a jour au fil de l'eau

    for d in daterange(PRELOAD_START, OPS_END):
        if not is_operating(d):
            continue
        n = BASE_ARRIVALS * PROD_SEASON[d.month]
        if d.weekday() == 5:
            n *= SATURDAY_FACTOR
        if d < OPS_START:                      # montee en charge progressive
            n *= 0.75

        # Regulation des flux : a l'approche de la saturation, le hub temporise
        # les arrivees en concertation avec l'usine plutot que de deborder.
        limit = SATURATION_THRESHOLD * SITE_CAPACITY
        hard_cap = MAX_FILL * SITE_CAPACITY
        projected = stock[d] + n
        if projected > limit:
            over = (projected - limit) / max(1.0, hard_cap - limit)
            n *= max(0.20, 1.0 - 0.85 * over)
        n = min(n, max(0.0, hard_cap - stock[d]))

        n = max(0, int(random.gauss(n, n * 0.08)))

        for _ in range(n):
            vid += 1
            model = random.choices(MODEL_CODES, MODEL_WEIGHTS)[0]
            battery = MODEL_BATTERY[model]
            winter = d.month in (12, 1, 2, 3)

            # Duree de sejour : loi gamma tronquee, allongee en hiver
            dwell = random.gammavariate(6.5, DWELL_MEAN / 6.5)
            if winter:
                dwell += random.uniform(0.2, 0.9)
            dwell = max(1.0, min(9.0, dwell))
            dwell_days = int(round(dwell))
            departure = d + dt.timedelta(days=dwell_days)

            # Controle qualite en sortie de ligne
            rework = random.random() < 0.018
            if rework:
                departure += dt.timedelta(days=random.randint(2, 5))
                zone = "Z-QR"
            else:
                zone = random.choices(STORAGE_ZONES,
                                      [STORAGE_CAP[z] for z in STORAGE_ZONES])[0]

            soc_in = round(random.uniform(24, 46), 1)
            soc_out = round(random.uniform(55, 66), 1)
            if soc_out <= soc_in:
                soc_out = soc_in + 12.0

            # Energie cote borne = energie batterie / rendement de charge
            eff = 0.80 if winter else 0.92
            energy = (soc_out - soc_in) / 100.0 * battery / eff
            if winter:                          # maintien thermique au stockage
                energy += 0.8 * dwell_days

            # Ponctualite d'expedition : degradee par la neige
            sn = snow_memory.get(departure, None)
            if sn is None:
                sn = 1 if random.random() < SNOW_PROB[departure.month] else 0
                snow_memory[departure] = sn
            late_p = 0.14 if sn else 0.045
            on_time = 0 if random.random() < late_p else 1

            vehicles.append({
                "VehicleID": f"MKR{vid:06d}",
                "ModelCode": model,
                "OriginPlant": MODEL_PLANT[model],
                "ArrivalDate": iso(d),
                "DepartureDate": iso(departure),
                "DwellDays": dwell_days if not rework else (departure - d).days,
                "StorageZone": zone,
                "CarrierCode": random.choices(CARRIER_CODES, CARRIER_WEIGHTS)[0],
                "SoCArrivalPct": soc_in,
                "SoCDeparturePct": soc_out,
                "EnergyChargedKWh": round(energy, 2),
                "InspectionResult": "Rework" if rework else "Pass",
                "OnTimeDispatch": on_time,
            })

            dd = d
            while dd <= departure:
                stock[dd] += 1
                dd += dt.timedelta(days=1)
    return vehicles


# ============================================ 2. OCCUPATION PAR ZONE / JOUR
def build_occupancy(vehicles):
    """Stock instantane moyen par zone. Les zones de transit (reception,
    recharge, expedition) accueillent un flux : leur stock moyen vaut
    flux x duree de passage / amplitude horaire d'exploitation."""
    OPEN_HOURS = 14.0
    present = defaultdict(int)       # date -> vehicules presents
    arrivals = defaultdict(int)
    departures = defaultdict(int)
    zone_stock = defaultdict(lambda: defaultdict(int))   # date -> zone -> n
    energy_day = defaultdict(float)

    for v in vehicles:
        a = dt.date.fromisoformat(v["ArrivalDate"])
        dep = dt.date.fromisoformat(v["DepartureDate"])
        arrivals[a] += 1
        departures[dep] += 1
        energy_day[a] += v["EnergyChargedKWh"]
        d = a
        while d <= dep:
            if OPS_START <= d <= OPS_END:
                present[d] += 1
                if v["StorageZone"] == "Z-QR":
                    zone_stock[d]["Z-QR"] += 1
            d += dt.timedelta(days=1)

    rows = []
    for d in daterange(OPS_START, OPS_END):
        n_in, n_out = arrivals[d], departures[d]
        transit = {
            "Z-IN": n_in * 2.0 / OPEN_HOURS,      # inspection ~2 h
            "Z-OUT": n_out * 2.5 / OPEN_HOURS,    # chargement camion ~2,5 h
            "Z-AC": n_in * 0.70 * 1.2 / OPEN_HOURS,
            "Z-DC": n_in * 0.30 * 0.5 / OPEN_HOURS,
        }
        qr = zone_stock[d]["Z-QR"]
        total = present[d]
        rest = max(0, total - sum(transit.values()) - qr)
        cap_sum = sum(STORAGE_CAP[z] for z in STORAGE_ZONES)

        day = {}
        for z, val in transit.items():
            day[z] = int(round(min(val, STORAGE_CAP[z])))
        day["Z-QR"] = qr
        for z in STORAGE_ZONES:
            day[z] = int(round(rest * STORAGE_CAP[z] / cap_sum))

        for z in [zz[0] for zz in ZONES]:
            n = day.get(z, 0)
            cap = STORAGE_CAP[z]
            rows.append({
                "Date": iso(d), "ZoneCode": z, "VehiclesPresent": n,
                "VehiclesIn": n_in if z == "Z-IN" else "",
                "VehiclesOut": n_out if z == "Z-OUT" else "",
                "OccupancyPct": round(100.0 * n / cap, 1),
            })
    return rows, present, arrivals, departures, energy_day
