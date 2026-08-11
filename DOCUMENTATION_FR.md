# hack-olive — Système de Prédiction des Coupures Électriques en Tunisie

**Documentation technique synthétique**  
Hackathon Olive · Août 2026

---

## 1. Présentation de la solution

hack-olive est un système automatisé de surveillance et de prédiction des coupures d'électricité en Tunisie. Il croise trois sources de données en temps réel pour produire chaque matin une évaluation du risque par gouvernorat et une prévision sur 7 jours, et surveille en continu les avis officiels de la STEG.

### Sources de données

| Source | Contenu | Mode d'accès |
|--------|---------|--------------|
| **STEG** (steg.com.tn/fr/news) | Avis officiels d'interruption par région | Scraping HTML toutes les 3h |
| **incident.tn** | Rapports citoyens de pannes par gouvernorat | API REST, sans clé |
| **Open-Meteo** | Météo archive ERA5 et prévisions 7 jours | API REST, sans clé |

---

## 2. Architecture technique

```
┌──────────────────────────────────────────────────────────────┐
│  n8n (orchestration)                      :5678              │
│                                                              │
│  Workflow 1 — Quotidien 06h00 UTC                            │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Score risque 24 gouvernorats  →  Email alerte        │    │
│  │ Résumé quotidien              →  Email résumé        │    │
│  │ Prévision météo Sfax 7j       →  Email prévision     │    │
│  │ Prévision coupures ML 7j      →  Email ML            │    │
│  └──────────────────────────────────────────────────────┘    │
│                                                              │
│  Workflow 2 — Surveillance STEG toutes les 3h                │
│  ┌──────────────────────────────────────────────────────┐    │
│  │ Scraping steg.com.tn/fr/news                         │    │
│  │ Détection nouvel article (déduplication par URL)     │    │
│  │ Email alerte + sauvegarde base de données            │    │
│  │ Vérification seuil MLOps → Réentraînement auto       │    │
│  └──────────────────────────────────────────────────────┘    │
└─────────────────────────┬────────────────────────────────────┘
                          │ HTTP
┌─────────────────────────▼────────────────────────────────────┐
│  FastAPI  (api.py)                        :8000              │
│                                                              │
│  /daily/score            Score temps réel 24 gouvernorats    │
│  /forecast/outage        Prévision ML 7j toutes régions      │
│  /forecast/governorate   Prévision météo 1 gouvernorat       │
│  /steg/save-article      Persistance articles STEG           │
│  /model/retrain          Déclenchement réentraînement        │
│  /health  /model/info    Monitoring                          │
└─────────────────────────┬────────────────────────────────────┘
                          │
┌─────────────────────────▼────────────────────────────────────┐
│  core.py — Moteur de scoring                                 │
│                                                              │
│  Phase 1 (actif) : Règles calibrées                          │
│    Température 30% + Indice chaleur 25%                      │
│    + Rapports citoyens 30% + Tendance 15%                    │
│    → score 0–1 → Low / Moderate / High / Extreme            │
│                                                              │
│  Phase 2 (auto ≥90 jours réels) : XGBoost                   │
│    Activation sans redémarrage, même API                     │
└──────────────────────────────────────────────────────────────┘
```

**Déploiement :** deux conteneurs Docker (`risk-api` + `n8n`) orchestrés par `docker compose up --build`.

---

## 3. Modèle de prédiction des coupures (XGBoost)

### Données d'entraînement fusionnées

| Source | Lignes | Période |
|--------|--------|---------|
| STEG scrape | 113 événements | 18 juil. – 6 août 2026 |
| incident.tn | 432 lignes (24 gouvernorats) | 23 juil. – 9 août 2026 |
| Open-Meteo ERA5 | 432 lignes | 23 juil. – 9 août 2026 |

### Variables explicatives (13 features)

```
Calendrier  :  jour_semaine · mois · est_weekend
Météo       :  temp_max · temp_min · temp_moy · humidité_max · vent_max · précipitations
Incidents   :  rapports_national · rapports_région · coupure_hier · nb_coupures_3j
```

### Deux modèles complémentaires

| Modèle | Fichier | Sortie |
|--------|---------|--------|
| Classificateur | `outage_clf.json` | Probabilité de coupure (0–1) |
| Régresseur | `outage_reg.json` | Heure de début prévue (0–23h) |

Format natif XGBoost JSON — portable, lisible, sans risque pickle.

### Cycle de vie MLOps

```
Nouvel article STEG détecté
        │
        ▼
  Save to DB (steg_live.csv)
        │
  total % 30 == 0 ?
        │
   oui  │  non
        ▼
  POST /model/retrain
  ┌─────────────────────┐
  │ pipeline.py         │  ← actualise incident.tn + météo
  │ train_outage_model  │  ← réentraîne sur toutes les données
  │ Reload scorer       │  ← nouveau modèle actif immédiatement
  └─────────────────────┘
```

Déclenchement automatique tous les **30 nouveaux articles STEG** sans intervention humaine.

---

## 4. Emails automatiques (5 types, tous en français)

| # | Déclencheur | Sujet | Contenu |
|---|------------|-------|---------|
| 1 | Quotidien 06h — si risque Élevé/Extrême | `⚡ ALERTE — Risque élevé de coupure — [date]` | Tableau HTML 24 gouvernorats, couleurs de risque |
| 2 | Quotidien 06h — systématique | `📊 Rapport du [date] — N région(s) à risque` | Top 5 gouvernorats, stats nationales |
| 3 | Quotidien 06h — systématique | `🔮 Prévision Sfax 7 jours — pic : [niveau] le [date]` | Tableau jour par jour, score, température, indice chaleur |
| 4 | Quotidien 06h — systématique | `🔮 Prévision coupures ML 7 jours — [date]` | Probabilités par région STEG, fenêtres horaires |
| 5 | Toutes les 3h — si nouvel article | `⚡ STEG — N avis de coupure (dont N Sfax) — [date]` | Titre + lien de chaque nouvel avis officiel |

---

## 5. Lancement rapide

```bash
# Installation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Données + calibration
python pipeline.py

# Entraînement du modèle
python train_outage_model.py

# Démarrage API seule
uvicorn api:app --host 0.0.0.0 --port 8000

# Déploiement complet (API + n8n)
cd docker && docker compose up --build -d
# API  → http://localhost:8000/docs
# n8n  → http://localhost:5678  (admin / changeme)
```
