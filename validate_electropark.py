"""Recette du jeu de donnees d'exploitation : ce que Power BI verra."""
import csv
import re
from collections import defaultdict
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ok = True


def load(name):
    with open(DATA / name, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def check(label, cond, detail=""):
    global ok
    ok = ok and bool(cond)
    print(f"  [{'OK ' if cond else 'KO '}] {label}{'  -> ' + detail if detail else ''}")


def num(v):
    return float(v) if v not in ("", None) else 0.0


date_t = load("dim_date.csv")
zone_t = load("dim_zone.csv")
charger_t = load("dim_charger.csv")
model_t = load("dim_vehicle_model.csv")
carrier_t = load("dim_carrier.csv")
flow = load("fact_vehicle_flow.csv")
occ = load("fact_zone_occupancy_daily.csv")
chg = load("fact_charging_daily.csv")
energy = load("fact_energy_hourly.csv")
site = load("fact_site_daily.csv")

print("Volumetrie")
for n, t, exp in [("dim_zone", zone_t, 8), ("dim_charger", charger_t, 60),
                  ("dim_vehicle_model", model_t, 5), ("dim_carrier", carrier_t, 6),
                  ("fact_energy_hourly", energy, 366 * 24),
                  ("fact_zone_occupancy_daily", occ, 366 * 8),
                  ("fact_site_daily", site, 366),
                  ("fact_charging_daily", chg, 366 * 60)]:
    check(f"{n} = {exp} lignes", len(t) == exp, str(len(t)))

print("\nUnicite des cles de dimension")
check("dim_date[Date]", len({r["Date"] for r in date_t}) == len(date_t))
check("dim_zone[ZoneCode]", len({r["ZoneCode"] for r in zone_t}) == len(zone_t))
check("dim_charger[ChargerID]", len({r["ChargerID"] for r in charger_t}) == len(charger_t))
check("dim_vehicle_model[ModelCode]", len({r["ModelCode"] for r in model_t}) == len(model_t))
check("dim_carrier[CarrierCode]", len({r["CarrierCode"] for r in carrier_t}) == len(carrier_t))
check("fact_vehicle_flow[VehicleID]", len({r["VehicleID"] for r in flow}) == len(flow))

print("\nIntegrite referentielle (relations Power BI)")
dates = {r["Date"] for r in date_t}
zones = {r["ZoneCode"] for r in zone_t}
models = {r["ModelCode"] for r in model_t}
carriers = {r["CarrierCode"] for r in carrier_t}
chargers = {r["ChargerID"] for r in charger_t}

check("flow.ModelCode -> dim_vehicle_model", not {r["ModelCode"] for r in flow} - models)
check("flow.CarrierCode -> dim_carrier", not {r["CarrierCode"] for r in flow} - carriers)
check("flow.StorageZone -> dim_zone", not {r["StorageZone"] for r in flow} - zones)
check("flow.ArrivalDate -> dim_date", not {r["ArrivalDate"] for r in flow} - dates)
check("flow.DepartureDate -> dim_date", not {r["DepartureDate"] for r in flow} - dates)
check("occupancy.ZoneCode -> dim_zone", not {r["ZoneCode"] for r in occ} - zones)
check("occupancy.Date -> dim_date", not {r["Date"] for r in occ} - dates)
check("charging.ChargerID -> dim_charger", not {r["ChargerID"] for r in chg} - chargers)
check("charging.Date -> dim_date", not {r["Date"] for r in chg} - dates)
check("energy.Date -> dim_date", not {r["Date"] for r in energy} - dates)
check("site.Date -> dim_date", not {r["Date"] for r in site} - dates)

print("\nFormats")
bad = []
for tbl, rows, cols in [("flow", flow, ["ArrivalDate", "DepartureDate"]),
                        ("occ", occ, ["Date"]), ("chg", chg, ["Date"]),
                        ("energy", energy, ["Date"]), ("site", site, ["Date"]),
                        ("date", date_t, ["Date"])]:
    for r in rows:
        for c in cols:
            if r[c] and not ISO.match(r[c]):
                bad.append(f"{tbl}.{c}={r[c]}")
check("dates au format ISO AAAA-MM-JJ", not bad, str(bad[:3]))
check("Hour borne 0-23", all(0 <= int(r["Hour"]) <= 23 for r in energy))
check("aucune virgule decimale", not any(
    "," in r["EnergyChargedKWh"] for r in flow))

print("\nCoherence physique")
caps = {r["ZoneCode"]: int(r["CapacityVehicles"]) for r in zone_t}
over = [(r["Date"], r["ZoneCode"], r["OccupancyPct"]) for r in occ
        if float(r["OccupancyPct"]) > 100.0]
check("aucune zone au-dela de sa capacite", not over, str(over[:3]))
check("capacite totale = 1200 places", sum(caps.values()) == 1200, str(sum(caps.values())))
check("surface totale = 20 000 m2",
      sum(int(r["SurfaceM2"]) for r in zone_t) == 20000,
      str(sum(int(r["SurfaceM2"]) for r in zone_t)))
check("SoC depart > SoC arrivee",
      all(float(r["SoCDeparturePct"]) > float(r["SoCArrivalPct"]) for r in flow))
check("depart posterieur a l'arrivee",
      all(r["DepartureDate"] > r["ArrivalDate"] for r in flow))

print("\nBilan energetique horaire  (PV + import + decharge = charge + stockage + export)")
worst = 0.0
for r in energy:
    left = num(r["PVProductionKWh"]) + num(r["GridImportKWh"]) + num(r["BESSDischargeKWh"])
    right = (num(r["TotalLoadKWh"]) + num(r["BESSChargeKWh"]) + num(r["PVExportedKWh"]))
    worst = max(worst, abs(left - right))
check("equilibre a chaque heure", worst < 0.05, f"ecart max {worst:.4f} kWh")
check("TotalLoad = recharge + site",
      all(abs(num(r["TotalLoadKWh"]) - num(r["ChargingLoadKWh"])
              - num(r["SiteLoadKWh"])) < 0.02 for r in energy))
soc = [float(r["BESSStateOfChargePct"]) for r in energy]
check("etat de charge du stockage entre 10 et 95 %",
      min(soc) >= 9.9 and max(soc) <= 95.1,
      f"min {min(soc):.1f} % / max {max(soc):.1f} %")

print("\nCoherence croisee entre tables")
occ_by_day = defaultdict(int)
for r in occ:
    occ_by_day[r["Date"]] += int(r["VehiclesPresent"])
diff = [(r["Date"], occ_by_day[r["Date"]], int(r["VehiclesOnSite"])) for r in site
        if abs(occ_by_day[r["Date"]] - int(r["VehiclesOnSite"])) > 3]
check("somme des zones = parc du site (+/-3 arrondis)", not diff, str(diff[:3]))

arr_by_day = defaultdict(int)
for r in flow:
    arr_by_day[r["ArrivalDate"]] += 1
diff2 = [r["Date"] for r in site if arr_by_day[r["Date"]] != int(r["VehiclesIn"])]
check("arrivees du flux = VehiclesIn du site", not diff2, str(diff2[:3]))

e_chg = sum(num(r["EnergyDeliveredKWh"]) for r in chg)
e_hour = sum(num(r["ChargingLoadKWh"]) for r in energy)
check("energie delivree par les bornes = charge horaire",
      abs(e_chg - e_hour) / e_hour < 0.001,
      f"{e_chg / 1000:,.0f} MWh vs {e_hour / 1000:,.0f} MWh")

cost_site = sum(num(r["EnergyCostCAD"]) for r in site)
cost_hour = sum(num(r["EnergyCostCAD"]) for r in energy)
check("facture journaliere = facture horaire",
      abs(cost_site - cost_hour) / cost_hour < 0.001,
      f"{cost_site:,.0f} vs {cost_hour:,.0f} CAD")

print("\nContraintes du Terms of Reference")
op_days = sum(1 for r in site if int(r["VehiclesIn"]) > 0)
arr = sum(int(r["VehiclesIn"]) for r in site) / op_days
dwell = [float(r["AvgDwellDays"]) for r in site if r["AvgDwellDays"]]
check("200-350 vehicules par jour", 200 <= arr <= 350, f"{arr:.0f}")
check("sejour moyen 2,5-4 jours", 2.5 <= sum(dwell) / len(dwell) <= 4.0,
      f"{sum(dwell) / len(dwell):.2f} j")
check("capacite 900-1200 vehicules", 900 <= sum(caps.values()) <= 1200)
powers = {float(r["PowerKW"]) for r in charger_t}
check("bornes AC 22 kW et DC 50-150 kW", powers == {22.0, 50.0, 100.0, 150.0},
      str(sorted(powers)))
tmin = min(float(r["TempMinC"]) for r in site)
tmax = max(float(r["TempMaxC"]) for r in site)
check("amplitude thermique conforme au ToR (-20 / +30 degC)",
      -22 <= tmin <= -18 and 28 <= tmax <= 32, f"{tmin:.1f} / {tmax:.1f} degC")
check("chutes de neige concentrees en hiver",
      all(float(r["SnowfallCm"]) == 0 for r in site
          if r["Date"][5:7] in ("06", "07", "08")))

load = sum(num(r["EnergyConsumedKWh"]) for r in site)
imp = sum(num(r["GridImportKWh"]) for r in site)
ss = 100 * (load - imp) / load
print(f"\n  [i  ] autosuffisance annuelle : {ss:.1f} %  (objectif ToR 60-80 %)")
print("        ecart assume : c'est le constat que le tableau de bord doit porter")

print("\n" + ("RECETTE OK" if ok else "RECETTE EN ECHEC"))
