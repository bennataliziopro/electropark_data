"""Energie horaire, recharge par borne, indicateurs journaliers, ecriture."""

import datetime as dt
import math
import random
from collections import defaultdict

from electropark_config import (
    BESS_CAPACITY_KWH, BESS_MAX_SOC, BESS_MIN_SOC, BESS_POWER_KW, CHARGER_SPEC,
    OPS_END, OPS_START, PV_DAILY, PV_PEAK_KWP, TARIFF, ZONES,
    build_dim_carrier, build_dim_charger, build_dim_date,
    build_dim_vehicle_model, build_dim_zone, daterange, iso, tariff_period,
    tariff_season, write_csv, HOLIDAYS,
)
from electropark_simulation import (
    CHARGE_PROFILE, SITE_PROFILE, build_occupancy, daylight_hours,
    is_operating, simulate_vehicles, weather,
)

random.seed(20270301)

# Consommation du site hors recharge (kWh/jour) : chauffage l'hiver,
# climatisation et eclairage reduit l'ete
SITE_LOAD_BASE = {1: 2900, 2: 2800, 3: 2300, 4: 1850, 5: 1650, 6: 1750,
                  7: 1900, 8: 1850, 9: 1600, 10: 1750, 11: 2250, 12: 2750}

# Intensite carbone du reseau ontarien (gCO2e/kWh) selon la periode tarifaire :
# le gaz est a la marge aux heures de pointe
CARBON_BY_PERIOD = {"off": 45.0, "mid": 85.0, "on": 165.0}


def pv_hourly(d, snow_cm, snow_cover):
    """Production photovoltaique horaire (kWh) et couverture neigeuse residuelle."""
    daily = PV_DAILY[d.month] * PV_PEAK_KWP
    # Nebulosite : distribution centree sur 1,0 (PV_DAILY est deja une moyenne),
    # mode sur les journees claires, longue queue vers les journees couvertes
    daily *= random.triangular(0.20, 1.45, 1.35)
    if snow_cm > 1.0:
        snow_cover = 1.0                         # panneaux couverts
    if snow_cover > 0:
        daily *= (1.0 - 0.85 * snow_cover)
        snow_cover = max(0.0, snow_cover - random.uniform(0.25, 0.6))

    dl = daylight_hours(d)
    sunrise, sunset = 12.0 - dl / 2, 12.0 + dl / 2
    raw = []
    for h in range(24):
        c = h + 0.5
        if sunrise < c < sunset:
            raw.append(math.sin(math.pi * (c - sunrise) / dl) ** 2)
        else:
            raw.append(0.0)
    s = sum(raw) or 1.0
    return [daily * r / s for r in raw], snow_cover


def build_energy(energy_by_day, weather_by_day):
    rows = []
    soc = BESS_CAPACITY_KWH * 0.5
    snow_cover = 0.0
    daily_summary = {}

    for d in daterange(OPS_START, OPS_END):
        charge_total = energy_by_day.get(d, 0.0)
        site_total = SITE_LOAD_BASE[d.month] * random.uniform(0.93, 1.07)
        if not is_operating(d):
            site_total *= 0.72                   # site au ralenti le dimanche
        pv, snow_cover = pv_hourly(d, weather_by_day[d][3], snow_cover)
        is_hol = d in HOLIDAYS
        season = tariff_season(d)

        day_pv = day_imp = day_exp = day_load = day_cost = day_co2 = 0.0
        for h in range(24):
            ch = charge_total * CHARGE_PROFILE[h]
            st = site_total * SITE_PROFILE[h]
            load = ch + st
            prod = pv[h]
            period = tariff_period(d, h, is_hol)
            price = TARIFF[season][period]

            net = prod - load
            bess_c = bess_d = export = imp = 0.0
            if net > 0:
                bess_c = min(net, BESS_POWER_KW,
                             max(0.0, BESS_MAX_SOC * BESS_CAPACITY_KWH - soc) / 0.95)
                soc += bess_c * 0.95
                export = net - bess_c
            else:
                deficit = -net
                room = max(0.0, soc - BESS_MIN_SOC * BESS_CAPACITY_KWH)
                avail = min(deficit, BESS_POWER_KW, room * 0.95)
                # on preserve le stock pour les heures cheres
                bess_d = avail if (period == "on" or soc > 0.62 * BESS_CAPACITY_KWH) \
                    else avail * 0.35
                soc -= bess_d / 0.95
                imp = deficit - bess_d

            carbon = CARBON_BY_PERIOD[period] * (1.25 if season == "winter" else 0.90)
            carbon *= random.uniform(0.9, 1.1)
            self_cons = prod - export
            cost = imp * price / 100.0
            co2_avoided = self_cons * carbon / 1000.0

            rows.append({
                "Date": iso(d), "Hour": h,
                "PVProductionKWh": round(prod, 2),
                "PVSelfConsumedKWh": round(self_cons, 2),
                "PVExportedKWh": round(export, 2),
                "ChargingLoadKWh": round(ch, 2),
                "SiteLoadKWh": round(st, 2),
                "TotalLoadKWh": round(load, 2),
                "BESSChargeKWh": round(bess_c, 2),
                "BESSDischargeKWh": round(bess_d, 2),
                "BESSStateOfChargePct": round(100.0 * soc / BESS_CAPACITY_KWH, 1),
                "GridImportKWh": round(imp, 2),
                "TariffPeriod": {"off": "Off-peak", "mid": "Mid-peak",
                                 "on": "On-peak"}[period],
                "EnergyPriceCentsPerKWh": price,
                "EnergyCostCAD": round(cost, 2),
                "GridCarbonIntensityGCO2PerKWh": round(carbon, 1),
                "CO2AvoidedKg": round(co2_avoided, 3),
            })
            day_pv += prod
            day_imp += imp
            day_exp += export
            day_load += load
            day_cost += cost
            day_co2 += co2_avoided

        daily_summary[d] = {
            "pv": day_pv, "import": day_imp, "export": day_exp,
            "load": day_load, "cost": day_cost, "co2": day_co2,
            "charge": charge_total, "site": site_total,
        }
    return rows, daily_summary


def build_charging_daily(energy_by_day):
    """Repartition de l'energie delivree sur les bornes."""
    chargers = build_dim_charger()
    ac = [c for c in chargers if c["ChargerType"] == "AC"]
    dc = [c for c in chargers if c["ChargerType"] == "DC"]
    rows = []

    for d in daterange(OPS_START, OPS_END):
        total = energy_by_day.get(d, 0.0)
        pools = [(ac, 0.70, 17.0), (dc, 0.30, 22.0)]   # part, kWh/session moyen
        for pool, share, kwh_sess in pools:
            pool_energy = total * share
            weights = [random.uniform(0.75, 1.25) for _ in pool]
            wsum = sum(weights) or 1.0
            for c, w in zip(pool, weights):
                e = pool_energy * w / wsum
                sessions = max(0, int(round(e / kwh_sess)))
                hours = e / c["PowerKW"] if c["PowerKW"] else 0.0
                # Indisponibilites : maintenance et pannes
                fault = 1 if random.random() < (0.012 if c["ChargerType"] == "DC"
                                                else 0.006) else 0
                down = round(random.uniform(1.5, 9.0), 1) if fault else 0.0
                rows.append({
                    "Date": iso(d),
                    "ChargerID": c["ChargerID"],
                    "SessionsCount": sessions,
                    "EnergyDeliveredKWh": round(e, 2),
                    "OccupiedHours": round(hours, 2),
                    "AvgSessionMinutes": round(hours * 60 / sessions, 1) if sessions else "",
                    "DowntimeHours": down,
                    "FaultCount": fault,
                    "AvailabilityPct": round(100.0 * (24.0 - down) / 24.0, 1),
                })
    return rows


def build_site_daily(vehicles, present, arrivals, departures, weather_by_day,
                     daily_summary):
    dwell_sum = defaultdict(float)
    dwell_n = defaultdict(int)
    ontime = defaultdict(int)
    rework = defaultdict(int)
    out_n = defaultdict(int)

    for v in vehicles:
        dep = dt.date.fromisoformat(v["DepartureDate"])
        if OPS_START <= dep <= OPS_END:
            dwell_sum[dep] += v["DwellDays"]
            dwell_n[dep] += 1
            ontime[dep] += v["OnTimeDispatch"]
        arr = dt.date.fromisoformat(v["ArrivalDate"])
        if OPS_START <= arr <= OPS_END:
            out_n[arr] += 1
            if v["InspectionResult"] == "Rework":
                rework[arr] += 1

    cap_total = sum(z[3] for z in ZONES)
    rows = []
    for d in daterange(OPS_START, OPS_END):
        t_avg, t_min, t_max, snow = weather_by_day[d]
        s = daily_summary[d]
        n_out = departures[d]
        n_in = arrivals[d]
        self_suf = 100.0 * (s["load"] - s["import"]) / s["load"] if s["load"] else 0.0
        rows.append({
            "Date": iso(d),
            "TempAvgC": t_avg, "TempMinC": t_min, "TempMaxC": t_max,
            "SnowfallCm": snow,
            "VehiclesIn": n_in,
            "VehiclesOut": n_out,
            "VehiclesOnSite": present[d],
            "OccupancyPct": round(100.0 * present[d] / cap_total, 1),
            "AvgDwellDays": round(dwell_sum[d] / dwell_n[d], 2) if dwell_n[d] else "",
            "OnTimeDispatchPct": round(100.0 * ontime[d] / dwell_n[d], 1) if dwell_n[d] else "",
            "InspectionPassRatePct": round(100.0 * (out_n[d] - rework[d]) / out_n[d], 1)
                                     if out_n[d] else "",
            "IncidentCount": 1 if random.random() < (0.16 if snow > 0 else 0.06) else 0,
            "SnowClearingHours": round(snow * random.uniform(1.1, 2.3), 1) if snow else 0.0,
            "StaffOnSite": int(round(42 + n_in * 0.085 + (6 if snow > 0 else 0)))
                           if is_operating(d) else 12,
            "EnergyProducedKWh": round(s["pv"], 1),
            "EnergyConsumedKWh": round(s["load"], 1),
            "GridImportKWh": round(s["import"], 1),
            "EnergyCostCAD": round(s["cost"], 2),
            "SelfSufficiencyPct": round(self_suf, 1),
            "CO2AvoidedKg": round(s["co2"], 1),
        })
    return rows


def main():
    print("ElectroPark Ontario - jeu de donnees d'exploitation (fictif)")
    print(f"Periode simulee : {OPS_START} -> {OPS_END}\n")

    vehicles = simulate_vehicles()
    occupancy, present, arrivals, departures, energy_raw = build_occupancy(vehicles)

    # La recharge s'etale sur le jour d'arrivee et le lendemain : cela remplit
    # les dimanches, ou le site ne recoit pas de vehicule mais charge toujours.
    energy_by_day = defaultdict(float)
    for d, e in energy_raw.items():
        energy_by_day[d] += e * 0.6
        energy_by_day[d + dt.timedelta(days=1)] += e * 0.4

    weather_by_day = {d: weather(d) for d in daterange(OPS_START, OPS_END)}
    energy_rows, daily_summary = build_energy(energy_by_day, weather_by_day)
    charging_rows = build_charging_daily(energy_by_day)
    site_rows = build_site_daily(vehicles, present, arrivals, departures,
                                 weather_by_day, daily_summary)

    # On ne publie que les vehicules concernes par la periode d'exploitation
    vehicles_out = [v for v in vehicles
                    if dt.date.fromisoformat(v["DepartureDate"]) >= OPS_START]

    write_csv("dim_date.csv", build_dim_date())
    write_csv("dim_zone.csv", build_dim_zone())
    write_csv("dim_charger.csv", build_dim_charger())
    write_csv("dim_vehicle_model.csv", build_dim_vehicle_model())
    write_csv("dim_carrier.csv", build_dim_carrier())
    write_csv("fact_vehicle_flow.csv", vehicles_out)
    write_csv("fact_zone_occupancy_daily.csv", occupancy)
    write_csv("fact_charging_daily.csv", charging_rows)
    write_csv("fact_energy_hourly.csv", energy_rows)
    write_csv("fact_site_daily.csv", site_rows)

    # ---------------------------------------------------------- synthese
    n_days = len(site_rows)
    tot_in = sum(r["VehiclesIn"] for r in site_rows)
    avg_present = sum(r["VehiclesOnSite"] for r in site_rows) / n_days
    op_days = sum(1 for d in daterange(OPS_START, OPS_END) if is_operating(d))
    dwell = [r["AvgDwellDays"] for r in site_rows if r["AvgDwellDays"] != ""]
    load = sum(r["EnergyConsumedKWh"] for r in site_rows)
    pv = sum(r["EnergyProducedKWh"] for r in site_rows)
    imp = sum(r["GridImportKWh"] for r in site_rows)
    cost = sum(r["EnergyCostCAD"] for r in site_rows)
    co2 = sum(r["CO2AvoidedKg"] for r in site_rows)

    print(f"\n  Synthese sur {n_days} jours ({op_days} jours d'exploitation)")
    print(f"    Vehicules traites          : {tot_in:>12,}")
    print(f"    Arrivees / jour ouvre      : {tot_in / op_days:>12,.0f}   [ToR : 200-350]")
    print(f"    Sejour moyen               : {sum(dwell) / len(dwell):>12,.2f} j [ToR : 2,5-4]")
    print(f"    Capacite installee         : {1200:>12,}   [ToR : 900-1200]")
    print(f"    Parc present (moyenne)     : {avg_present:>12,.0f}")
    print(f"    Occupation moyenne         : {100 * avg_present / 1200:>12,.1f} %")
    print(f"    Consommation totale        : {load / 1000:>12,.0f} MWh")
    print(f"    Production PV              : {pv / 1000:>12,.0f} MWh")
    print(f"    Import reseau              : {imp / 1000:>12,.0f} MWh")
    print(f"    Autosuffisance             : {100 * (load - imp) / load:>12,.1f} % [ToR : 60-80]")
    print(f"    Productible PV             : {pv / 1000:>12,.0f} kWh/kWc")
    print(f"    Facture electricite        : {cost:>12,.0f} CAD")
    print(f"    CO2 evite                  : {co2 / 1000:>12,.1f} t")

    # Saturation : aucune zone ne doit depasser sa capacite physique
    from electropark_config import ZONES as _Z
    caps = {z[0]: z[3] for z in _Z}
    worst = {}
    for r in occupancy:
        z = r["ZoneCode"]
        if r["OccupancyPct"] > worst.get(z, (0,))[0]:
            worst[z] = (r["OccupancyPct"], r["Date"])
    print("\n  Occupation maximale par zone")
    for z, (pct, day) in sorted(worst.items(), key=lambda kv: -kv[1][0]):
        flag = "  << DEPASSEMENT" if pct > 100 else ""
        print(f"    {z:6s} {pct:6.1f} %  (cap. {caps[z]:4d})  le {day}{flag}")

    peak = max(r["VehiclesOnSite"] for r in site_rows)
    print(f"\n    Parc maximal observe       : {peak:>12,}   (capacite 1200)")

    # Autosuffisance mensuelle : l'objectif du ToR n'est atteint qu'une partie
    # de l'annee, c'est le constat central que le tableau de bord doit porter
    by_month = {}
    for r in site_rows:
        m = r["Date"][:7]
        a, b = by_month.get(m, (0.0, 0.0))
        by_month[m] = (a + r["EnergyConsumedKWh"] - r["GridImportKWh"],
                       b + r["EnergyConsumedKWh"])
    print("\n  Autosuffisance mensuelle (cible ToR : 60-80 %)")
    line = "    "
    for m in sorted(by_month):
        pct = 100 * by_month[m][0] / by_month[m][1]
        line += f"{m[5:]}:{pct:4.0f}%  "
    print(line)


if __name__ == "__main__":
    main()
