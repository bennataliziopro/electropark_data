// =====================================================================
// ElectroPark Ontario - connexion Power Query
// Supervision d'exploitation du hub logistique MKR Corp.
// =====================================================================
//
// A creer dans Power BI Desktop, requete par requete :
//   Accueil > Transformer les donnees > Nouvelle source > Requete vide
//   puis Accueil > Editeur avance > remplacer tout par le bloc
//   puis renommer la requete avec le nom exact indique.
//
// Les deux premieres requetes sont la plomberie. Les dix suivantes ne
// font qu'une ligne chacune : le typage des colonnes est deduit de leur
// nom par fnCsv, il n'y a donc rien a declarer table par table.
//
// =====================================================================


// ---------------------------------------------------------------------
// REQUETE 1/12   -   nom exact : BaseUrl
// ---------------------------------------------------------------------
// Seul endroit a modifier pour pointer vers un autre depot ou une autre
// branche. Remplacer VOTRE-COMPTE et VOTRE-REPO.
// Conserver la barre oblique finale.
// ---------------------------------------------------------------------

"https://raw.githubusercontent.com/VOTRE-COMPTE/VOTRE-REPO/main/data/"


// ---------------------------------------------------------------------
// REQUETE 2/12   -   nom exact : fnCsv
// ---------------------------------------------------------------------
// Lit un CSV du depot et type ses colonnes d'apres leur nom.
//
// Deux choix d'implementation qui evitent des heures de depannage :
//
// 1. Web.Contents(BaseUrl, [RelativePath = ...]) plutot qu'une URL
//    concatenee. Une URL construite par concatenation est vue par
//    Power BI comme une "source de donnees dynamique", ce qui casse
//    l'actualisation une fois le rapport publie.
//
// 2. Typage force avec la culture "en-US". Les dates du depot sont en
//    ISO (AAAA-MM-JJ) et les decimaux utilisent le point ; sans culture
//    explicite, un poste configure en francais et un poste configure en
//    anglais ne liraient pas les memes valeurs.
// ---------------------------------------------------------------------

(nomFichier as text) as table =>
let
    Source = Csv.Document(
        Web.Contents(BaseUrl, [RelativePath = nomFichier]),
        [Delimiter = ",", Encoding = 65001, QuoteStyle = QuoteStyle.Csv]
    ),
    Entetes = Table.PromoteHeaders(Source, [PromoteAllScalars = true]),

    // Colonnes textuelles : noms exacts, puis suffixes
    TexteExact = {"Quarter", "YearMonth", "YearWeek", "Season", "TariffSeason",
                  "MonthName", "MonthShort", "DayName"},
    TexteSuffixe = {"Code", "Name", "Type", "ID", "Zone", "Segment", "Plant",
                    "Mode", "Region", "Period", "Result", "Manufacturer",
                    "Connector", "Available"},

    TypeDe = (nom as text) as type =>
        if Text.EndsWith(nom, "Date") then type date
        else if Text.StartsWith(nom, "Is") or Text.StartsWith(nom, "Has")
            then Int64.Type
        else if List.Contains(TexteExact, nom) then type text
        else if List.AnyTrue(List.Transform(TexteSuffixe,
                 (s) => Text.EndsWith(nom, s))) then type text
        else type number,

    Plan = List.Transform(Table.ColumnNames(Entetes), (n) => {n, TypeDe(n)}),
    Types = Table.TransformColumnTypes(Entetes, Plan, "en-US")
in
    Types


// ---------------------------------------------------------------------
// REQUETES 3/12 a 7/12   -   les dimensions
// ---------------------------------------------------------------------
// Un bloc par requete. Le nom de la requete doit reprendre le nom du
// fichier, sans l'extension.
// ---------------------------------------------------------------------

// nom exact : dim_date
fnCsv("dim_date.csv")

// nom exact : dim_zone
fnCsv("dim_zone.csv")

// nom exact : dim_charger
fnCsv("dim_charger.csv")

// nom exact : dim_vehicle_model
fnCsv("dim_vehicle_model.csv")

// nom exact : dim_carrier
fnCsv("dim_carrier.csv")


// ---------------------------------------------------------------------
// REQUETES 8/12 a 12/12   -   les tables de faits
// ---------------------------------------------------------------------

// nom exact : fact_vehicle_flow        un sejour de vehicule par ligne
fnCsv("fact_vehicle_flow.csv")

// nom exact : fact_zone_occupancy_daily    occupation par zone et par jour
fnCsv("fact_zone_occupancy_daily.csv")

// nom exact : fact_charging_daily      activite par borne et par jour
fnCsv("fact_charging_daily.csv")

// nom exact : fact_energy_hourly       bilan energetique heure par heure
fnCsv("fact_energy_hourly.csv")

// nom exact : fact_site_daily          indicateurs journaliers du site
fnCsv("fact_site_daily.csv")


// =====================================================================
// POUR AJOUTER UNE TABLE PLUS TARD
// =====================================================================
// Deposer le CSV dans data/ sur GitHub, creer une requete vide et y
// mettre une seule ligne :
//
//     fnCsv("ma_nouvelle_table.csv")
//
// Le typage suit automatiquement, a condition de respecter les
// conventions de nommage des colonnes :
//   - une date se termine par "Date"          -> type date
//   - un indicateur binaire commence par "Is" ou "Has"  -> entier
//   - un libelle se termine par Code, Name, Type, ID... -> texte
//   - tout le reste                            -> nombre
// =====================================================================
