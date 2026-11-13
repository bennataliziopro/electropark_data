# ElectroPark Ontario — données de supervision d'exploitation

Source de données partagée pour les tableaux de bord Power BI du projet CESI.

**Client :** MKR Corp. · **Prestataire :** C.E.S. International – industry
**Site :** ElectroPark Ontario — hub logistique de gestion post-production des véhicules
électriques sortant de l'usine MKR de Hamilton.

> ⚠️ **Jeu de données entièrement fictif**, produit par simulation pour un POC pédagogique.
> Aucune donnée réelle de MKR Corp. ni d'un site existant.

---

## 1. À quoi sert ce dépôt

Chaque membre de l'équipe construit **son propre** fichier Power BI (`.pbix`) sur **la même
source**. Le partage se fait au niveau des données, pas des rapports : partager un rapport dans
le Power BI Service exigerait une licence Pro pour chaque personne.

Conséquence pratique : **rien à installer, aucun compte à créer**. Les CSV sont lus en HTTP
anonyme par le connecteur Web de Power BI Desktop.

---

## 2. Ce que les données décrivent

Le site est en exploitation : il reçoit les véhicules en sortie de chaîne, les inspecte, les
recharge partiellement, les stocke quelques jours, puis les remet aux transporteurs vers les
centres de distribution. Les données couvrent **12 mois pleins, du 1ᵉʳ mars 2027 au 29 février
2028** — soit la première année d'exploitation, la mise en service étant prévue pour mars 2027.

Une année entière permet de couvrir la saisonnalité canadienne, que le cahier des charges
désigne comme une contrainte majeure : l'hiver dégrade à la fois la production solaire, le
rendement de charge des batteries et la fluidité des opérations.

### Conformité au cahier des charges

Les paramètres de simulation sont calés sur les contraintes chiffrées du *Terms of Reference*
et du flyer client :

| Contrainte du ToR | Cible | Jeu de données |
|---|---|---|
| Flux de véhicules | 200–350 / jour | **231** par jour d'exploitation |
| Durée de séjour moyenne | 2,5–4 jours | **2,99** jours |
| Capacité totale | 900–1200 véhicules | **1 200** places |
| Surface du site | 20 000 m² | **20 000 m²** |
| Bornes de recharge | AC 22 kW, DC 50–150 kW | 48 × 22 kW, 6 × 50, 4 × 100, 2 × 150 |
| Photovoltaïque | 1 MWc en autoconsommation | **1 MWc**, 1 089 MWh/an |
| Amplitude thermique | −20 °C à +30 °C | **−21,5 °C à +31,5 °C** |
| Autosuffisance énergétique | 60–80 % | **45 %** — voir ci-dessous |

### L'écart d'autosuffisance est volontaire

L'objectif de 60–80 % n'est **pas atteint**, et ce n'est pas une erreur de calibrage : avec
1 MWc en Ontario, le productible annuel plafonne autour de 1 090 MWh face à 2 038 MWh
consommés. Même en autoconsommant la totalité du solaire, le maximum théorique serait de 53 %.

L'objectif n'est donc pas tenable avec le dimensionnement prévu. Le profil mensuel le montre
nettement :

| | Mar | Avr | Mai | Jun | Jul | Aoû | Sep | Oct | Nov | Déc | Jan | Fév |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Autosuffisance | 33 % | 50 % | 73 % | 72 % | **81 %** | 76 % | 68 % | 44 % | 19 % | **13 %** | 17 % | 27 % |

La cible est tenue de mai à septembre et s'effondre en hiver. C'est le constat central que les
tableaux de bord doivent porter — et le flyer client invite explicitement les consultants à
challenger les hypothèses du projet.

---

## 3. Modèle de données

Modèle en étoile, 5 dimensions et 5 tables de faits, articulé autour de `dim_date`.

```
   dim_vehicle_model      dim_carrier            dim_charger      dim_zone
          │                    │                      │            │   │   │
          └────────┬───────────┘                      │            │   │   │
                   ▼                                  ▼            ▼   │   │
          fact_vehicle_flow                  fact_charging_daily       │   │
                   │                                  │                │   │
                   │        fact_zone_occupancy_daily ◄────────────────┘   │
                   │                 │                │                     │
                   │   fact_site_daily   fact_energy_hourly                 │
                   │            │                │                          │
                   └────────────┴────────────────┴──────────────────────────┘
                                        │
                                    dim_date
```

| Table | Lignes | Grain |
|---|---:|---|
| `dim_date` | 456 | un jour |
| `dim_zone` | 8 | une zone du site |
| `dim_charger` | 60 | une borne de recharge |
| `dim_vehicle_model` | 5 | un modèle de véhicule MKR |
| `dim_carrier` | 6 | un transporteur |
| `fact_vehicle_flow` | 70 969 | **un séjour de véhicule** |
| `fact_zone_occupancy_daily` | 2 928 | une zone × un jour |
| `fact_charging_daily` | 21 960 | une borne × un jour |
| `fact_energy_hourly` | 8 784 | **une heure** |
| `fact_site_daily` | 366 | un jour |

Volume total : **7,6 Mo**, dont 5,8 Mo pour `fact_vehicle_flow`.

---

## 4. Dictionnaire de données

### `dim_zone` — les 8 zones du site

| Zone | Libellé | Type | Places | m² |
|---|---|---|---:|---:|
| `Z-IN` | Reception & Inspection | Reception | 60 | 1 300 |
| `Z-A` / `Z-B` | Storage Block A / B | Storage | 325 ch. | 4 650 ch. |
| `Z-C` | Storage Block C (couvert) | Storage | 235 | 3 350 |
| `Z-AC` | AC Charging Area | Charging | 85 | 1 700 |
| `Z-DC` | DC Fast Charging Bay | Charging | 40 | 900 |
| `Z-OUT` | Dispatch & Loading | Dispatch | 70 | 2 000 |
| `Z-QR` | Quarantine & Rework | Quarantine | 60 | 1 450 |

Autres colonnes : `ZoneType`, `HasCharging`, `ChargerTypeAvailable`, `IsCovered`.

### `fact_vehicle_flow` — un séjour de véhicule par ligne

| Colonne | Description |
|---|---|
| `VehicleID` | Identifiant du véhicule — **clé unique** |
| `ModelCode` | → `dim_vehicle_model` |
| `OriginPlant` | Usine d'origine (Hamilton ou Windsor) |
| `ArrivalDate` / `DepartureDate` | → `dim_date` |
| `DwellDays` | Durée de séjour en jours |
| `StorageZone` | → `dim_zone` : zone de stockage principale |
| `CarrierCode` | → `dim_carrier` : transporteur qui enlève le véhicule |
| `SoCArrivalPct` / `SoCDeparturePct` | Niveau de charge batterie à l'arrivée et au départ |
| `EnergyChargedKWh` | Énergie consommée au point de charge |
| `InspectionResult` | `Pass` ou `Rework` (1,9 % des véhicules) |
| `OnTimeDispatch` | 1 si expédié dans la fenêtre prévue, sinon 0 |

Un véhicule arrive autour de 35 % de charge et repart autour de 60 % : le site ne fait pas une
charge complète, il amène les véhicules au niveau requis pour le transport.

### `fact_energy_hourly` — bilan énergétique heure par heure

| Colonne | Description |
|---|---|
| `Date`, `Hour` | → `dim_date` et heure de 0 à 23 |
| `PVProductionKWh` | Production photovoltaïque |
| `PVSelfConsumedKWh` / `PVExportedKWh` | Part autoconsommée / injectée au réseau |
| `ChargingLoadKWh` / `SiteLoadKWh` / `TotalLoadKWh` | Recharge, site, total |
| `BESSChargeKWh` / `BESSDischargeKWh` / `BESSStateOfChargePct` | Batterie stationnaire (2 MWh / 500 kW) |
| `GridImportKWh` | Soutirage réseau |
| `TariffPeriod` | `Off-peak`, `Mid-peak`, `On-peak` |
| `EnergyPriceCentsPerKWh` / `EnergyCostCAD` | Prix et coût du soutirage |
| `GridCarbonIntensityGCO2PerKWh` | Intensité carbone du réseau ontarien à cette heure |
| `CO2AvoidedKg` | Émissions évitées par l'autoconsommation solaire |

Le bilan est équilibré à chaque heure :
`PV + import + décharge batterie = consommation + charge batterie + export`.

### `fact_site_daily` — indicateurs journaliers

Météo (`TempAvgC`, `TempMinC`, `TempMaxC`, `SnowfallCm`), flux (`VehiclesIn`, `VehiclesOut`,
`VehiclesOnSite`, `OccupancyPct`, `AvgDwellDays`), qualité de service (`OnTimeDispatchPct`,
`InspectionPassRatePct`, `IncidentCount`), exploitation (`StaffOnSite`, `SnowClearingHours`)
et synthèse énergétique du jour (`EnergyProducedKWh`, `EnergyConsumedKWh`, `GridImportKWh`,
`EnergyCostCAD`, `SelfSufficiencyPct`, `CO2AvoidedKg`).

### `fact_charging_daily` — activité par borne et par jour

`SessionsCount`, `EnergyDeliveredKWh`, `OccupiedHours`, `AvgSessionMinutes`, `DowntimeHours`,
`FaultCount`, `AvailabilityPct`.

### `fact_zone_occupancy_daily` — occupation par zone et par jour

`VehiclesPresent`, `OccupancyPct`, plus `VehiclesIn` sur `Z-IN` et `VehiclesOut` sur `Z-OUT`.

### `dim_date`, `dim_charger`, `dim_vehicle_model`, `dim_carrier`

`dim_date` couvre du 1ᵉʳ janvier 2027 au 31 mars 2028 et porte `Season`, `TariffSeason`
(saison tarifaire de l'Ontario Energy Board), `IsHoliday` (jours fériés ontariens),
`IsOperatingDay` (le site est fermé le dimanche et les jours fériés) et `IsOperationsPeriod`.

Les cinq modèles de véhicules vont de la citadine 42 kWh au grand utilitaire 92 kWh.

---

## 5. Se connecter depuis Power BI Desktop

**Prérequis :** Power BI Desktop (gratuit). Rien d'autre.

### Étape 1 — récupérer l'URL de base

```
https://raw.githubusercontent.com/<compte>/<repo>/main/data/
```

Pour la vérifier : ouvrir `data/dim_zone.csv` sur GitHub, cliquer **Raw**, copier l'URL de la
barre d'adresse en retirant `dim_zone.csv`. La barre oblique finale doit rester.

### Étape 2 — créer les requêtes

Ouvrir `powerquery/connexion_electropark.m` et suivre les instructions en tête de fichier.
Douze requêtes, dont dix ne font qu'une ligne. Les noms doivent être **exactement** ceux
indiqués : les requêtes se référencent entre elles.

À la première exécution, Power BI demande le mode d'authentification du site : choisir
**Anonyme**.

### Étape 3 — créer les relations

Dans la vue **Modèle**, tracer ces relations **un-à-plusieurs** :

| Depuis (côté 1) | Vers (côté plusieurs) |
|---|---|
| `dim_date[Date]` | `fact_site_daily[Date]` |
| `dim_date[Date]` | `fact_energy_hourly[Date]` |
| `dim_date[Date]` | `fact_charging_daily[Date]` |
| `dim_date[Date]` | `fact_zone_occupancy_daily[Date]` |
| `dim_date[Date]` | `fact_vehicle_flow[ArrivalDate]` |
| `dim_zone[ZoneCode]` | `fact_zone_occupancy_daily[ZoneCode]` |
| `dim_zone[ZoneCode]` | `fact_vehicle_flow[StorageZone]` |
| `dim_charger[ChargerID]` | `fact_charging_daily[ChargerID]` |
| `dim_vehicle_model[ModelCode]` | `fact_vehicle_flow[ModelCode]` |
| `dim_carrier[CarrierCode]` | `fact_vehicle_flow[CarrierCode]` |

`fact_vehicle_flow` porte deux dates. Relier `ArrivalDate` en relation **active** et, si vous
voulez analyser aussi les départs, ajouter une relation **inactive** sur `DepartureDate`,
activée au cas par cas avec `USERELATIONSHIP`.

Enfin : sélectionner `dim_date` → **Outils de table** → **Marquer comme table de dates** →
colonne `Date`. Sans cette étape, les fonctions DAX de time intelligence ne fonctionneront pas.

### Étape 4 — recette

Vérifier le nombre de lignes de chaque table (tableau de la section 3), puis ces totaux sur
l'année complète :

| Indicateur | Valeur attendue |
|---|---|
| `SUM(fact_site_daily[VehiclesIn])` | 70 566 |
| `SUM(fact_site_daily[EnergyConsumedKWh])` | ≈ 2 037 871 kWh |
| `SUM(fact_site_daily[EnergyProducedKWh])` | ≈ 1 088 631 kWh |
| `SUM(fact_site_daily[GridImportKWh])` | ≈ 1 119 982 kWh |
| `SUM(fact_site_daily[EnergyCostCAD])` | ≈ 134 520 CAD |
| `SUM(fact_charging_daily[EnergyDeliveredKWh])` | ≈ 1 299 257 kWh |
| `SUM(fact_charging_daily[SessionsCount])` | 71 192 |
| `AVERAGE(fact_site_daily[OccupancyPct])` | ≈ 62,9 % |

Si ces chiffres tombent, la chaîne complète est validée.

---

## 6. Pièges à connaître

**L'occupation ne se somme pas.** `VehiclesPresent` et `VehiclesOnSite` sont des *stocks* : les
additionner sur plusieurs jours n'a aucun sens. Utiliser `AVERAGE` ou `MAX` sur une période,
jamais `SUM`. C'est la même logique que pour un solde bancaire.

**Un véhicule compte dans plusieurs jours.** `fact_vehicle_flow` a un grain « séjour », pas
« jour ». Pour compter les véhicules présents à une date, passer par
`fact_zone_occupancy_daily` ou `fact_site_daily`, qui sont déjà calculées pour cela.

**Les pourcentages ne se moyennent pas naïvement.** `OnTimeDispatchPct` ou `SelfSufficiencyPct`
sont des ratios journaliers. Pour un taux sur une période, recalculer le ratio des sommes :

```dax
Autosuffisance =
VAR Conso  = SUM ( fact_site_daily[EnergyConsumedKWh] )
VAR Import = SUM ( fact_site_daily[GridImportKWh] )
RETURN
    DIVIDE ( Conso - Import, Conso )
```

**Deux dates dans `fact_vehicle_flow`.** Un filtre de période porte par défaut sur la date
d'arrivée. Pour raisonner sur les départs, utiliser la relation inactive.

---

## 7. Hypothèses et sources

Le jeu est fictif, mais les paramètres physiques et économiques sont calés sur des références
réelles, ce qui rend les ordres de grandeur défendables :

- **Tarification électrique** : structure *Time-of-Use* de l'Ontario Energy Board, avec ses
  plages horaires réelles. En hiver les heures pleines sont le matin et le soir (7 h–11 h et
  17 h–19 h) ; en été elles sont en milieu de journée (11 h–17 h). Prix retenus : 9,1 / 14,6 /
  18,9 ¢/kWh en hiver et 9,8 / 15,7 / 20,3 ¢/kWh en été. Weekends et jours fériés sont en
  heures creuses toute la journée. Ce sont des prix de fourniture, hors acheminement et taxes.
- **Intensité carbone du réseau** : l'Ontario est peu carboné (nucléaire et hydraulique), autour
  de 50 à 75 gCO2e/kWh en moyenne, mais le gaz est à la marge aux heures de pointe. La valeur
  est donc modulée selon la période tarifaire — ce qui explique que le solaire, qui produit en
  journée, évite plus de CO2 que l'intensité moyenne ne le laisserait croire.
- **Productible photovoltaïque** : environ 1 090 kWh/kWc/an, cohérent avec le sud de l'Ontario,
  pertes d'enneigement hivernal comprises.
- **Rendement de charge** : 92 % en saison tempérée, 80 % par temps froid, plus un maintien
  thermique des batteries pendant le stockage hivernal.

Une hypothèse à assumer devant le jury : la grille tarifaire retenue est celle des petits
consommateurs. Un site industriel de cette taille relèverait en pratique d'une tarification
Classe A ou B avec *Global Adjustment*. La structure horaire reste pertinente pour démontrer
l'intérêt du pilotage de charge.

---

## 8. Pistes de tableaux de bord

Quatre angles, correspondant aux attendus du cahier des charges :

1. **Supervision du parc** — occupation par zone et dans le temps, saturation des blocs de
   stockage, durée de séjour, flux entrées/sorties, répartition par modèle et par transporteur.
2. **Infrastructure de recharge** — énergie délivrée, sessions, disponibilité des bornes,
   pannes, répartition AC/DC. Constat à creuser : le taux d'occupation des bornes est de
   **8,9 %**, ce qui interroge le dimensionnement.
3. **Énergie** — courbe de production et de consommation, autosuffisance, rôle de la batterie
   stationnaire, coût du soutirage par période tarifaire. **63 %** du soutirage a lieu en heures
   creuses et **15 %** seulement en heures pleines : le pilotage de charge fonctionne.
4. **RSE** — émissions évitées, autoconsommation, écart à l'objectif d'autosuffisance, sécurité
   (incidents), ponctualité de service, impact de l'hiver sur les opérations.

---

## 9. Régénérer le jeu de données

Le générateur est déterministe (graine fixe) : deux exécutions produisent des fichiers
identiques, donc un `git diff` vide tant que les paramètres ne changent pas.

```bash
python3 scripts/generate_electropark.py   # produit les 10 CSV dans data/
python3 scripts/validate_electropark.py   # recette : 46 contrôles
```

La recette vérifie la volumétrie, l'unicité des clés, l'intégrité référentielle, les formats,
l'équilibre du bilan énergétique heure par heure, la cohérence croisée entre tables et le
respect des contraintes du cahier des charges.

Le cadrage se modifie en tête de `scripts/electropark_config.py` (période, capacités, zones,
tarifs, climat) et de `scripts/electropark_simulation.py` (flux, durées de séjour, saturation).

---

## 10. Contenu du dépôt

```
data/                                 les 10 tables au format CSV
powerquery/
  connexion_electropark.m             requêtes Power Query à copier
scripts/
  electropark_config.py               référentiels, climat, tarifs, dimensions
  electropark_simulation.py           flux de véhicules et occupation
  generate_electropark.py             point d'entrée : produit les CSV
  validate_electropark.py             recette du jeu de données
README.md
```

---

## 11. Conventions de format

Imposées à la génération pour éviter toute mauvaise interprétation dans Power Query, notamment
entre paramètres régionaux français et anglais :

- dates en **ISO 8601** (`AAAA-MM-JJ`)
- séparateur de colonnes : **virgule** · séparateur décimal : **point**
- encodage **UTF-8 sans BOM**, noms de colonnes sans accent ni espace
- nommage porteur de type : suffixe `Date` pour une date, préfixe `Is`/`Has` pour un binaire,
  suffixes `Code`, `Name`, `Type`, `ID` pour un libellé — c'est ce qui permet à `fnCsv` de
  typer automatiquement toute nouvelle table

Dans Excel en configuration française, ouvrir les CSV via *Données → À partir d'un fichier
texte/CSV*, pas par double-clic, sinon tout arrive dans une seule colonne.

---

*Note de transparence IA — le cahier des charges impose un usage éthique de l'IA : le jeu de
données, les scripts de génération et de recette de ce dépôt ont été produits avec l'assistance
d'une IA générative. Les données sont synthétiques et explicitement fictives.*
