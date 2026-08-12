# 🔌 Scraper de Données de Coupures Électriques STEG

Un scraper web complet qui collecte automatiquement les annonces de coupures électriques du site STEG et les convertit en données structurées et propres (CSV, Excel, JSON).

**Parfait pour les débutants !** Ce guide explique tout étape par étape avec des diagrammes faciles à comprendre.

---

## 📚 Table des Matières

1. [Que Fait Ce Programme ?](#que-fait-ce-programme-)
2. [Comment Ça Marche - Méthodologie Complète](#comment-ça-marche---méthodologie-complète)
3. [Structure du Projet](#structure-du-projet)
4. [Données en Sortie](#données-en-sortie)
5. [Installation & Utilisation](#installation--utilisation)
6. [Comprendre le Code](#comprendre-le-code)
7. [Dépannage](#dépannage)

---

## 🎯 Que Fait Ce Programme ?

Ce scraper automatiquement :
1. **Visite** le site STEG (compagnie d'électricité tunisienne)
2. **Trouve** toutes les annonces de coupures électriques (en arabe)
3. **Extrait** les informations importantes comme :
   - Quand est la coupure ? (date)
   - À quelle heure commence-t-elle ? 
   - À quelle heure se termine-t-elle ?
   - Quelle région ? (جهة الشمال, جهة الجنوب, etc.)
   - Quelles zones sont affectées ?
4. **Sauvegarde** tout dans des formats faciles à utiliser (Excel, CSV, JSON)

**Résultat** : Au lieu de lire 113 annonces arabes manuellement, vous obtenez un tableur propre ! 📊

---

## 🔄 Comment Ça Marche - Méthodologie Complète

### Vue d'Ensemble

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐      ┌──────────────┐
│   Site      │      │ Télécharge   │      │  Extrait    │      │ Sauvegarde   │
│   STEG      │ ───> │   Pages      │ ───> │  Données    │ ───> │   Fichiers   │
│  (Arabe)    │      │   HTML       │      │  (Analyse)  │      │ (CSV/Excel)  │
└─────────────┘      └──────────────┘      └─────────────┘      └──────────────┘
```

### Processus Étape par Étape

#### 📥 **ÉTAPE 1 : Découverte** (Trouver les Articles)

Le scraper visite le site STEG et filtre uniquement les annonces de coupures.

**Ce qui se passe :**
- Ouvre la page d'actualités STEG (page 1, 2, 3, etc.)
- Regarde chaque titre d'article
- **Filtre** : Garde seulement les articles avec "إشعار بانقطاع الكهرباء" (annonce de coupure)
- **Ignore** : Offres d'emploi, études, autres actualités
- Collecte toutes les URLs d'articles (113 au total)

---

#### 📥 **ÉTAPE 2 : Téléchargement** (Récupération du Contenu Complet)

Pour chaque article trouvé, le scraper :
- Télécharge la page d'annonce complète
- Attend 1,5-3 secondes entre les téléchargements (pour être gentil avec le serveur)
- Sauvegarde le HTML dans le dossier `data/raw/html/`

**Pourquoi sauvegarder le HTML ?** Pour pouvoir re-traiter plus tard sans re-télécharger !

---

#### 🔍 **ÉTAPE 3 : Extraction de Données** (Analyse du Texte Arabe)

C'est la partie la plus complexe ! Le texte arabe ressemble à ça :

```
في إطار الحفاظ على سلامة و ديمومة المنظومة الكهربائية،
تعلم الشركة التونسية للكهرباء و الغاز أنّه قد يتمّ اللجوء إلى
القطع الدوري للكهرباء اليوم الثلاثاء 21 جويلية 2026،
خلال الفترة المتراوحة بين الساعة السادسة صباحا والساعة منتصف النهار،
```

**L'analyseur extrait :**

```
┌──────────────────────────────────────┐
│  Texte Arabe (Annonce)               │
└──────────────────────────────────────┘
           ↓
    ┌──────┴──────┐
    │  ANALYSEUR  │
    └──────┬──────┘
           ↓
┌──────────────────────────────────────┐
│  Données Structurées :               │
│  • Date : 2026-07-21                 │
│  • Début : 06:00                     │
│  • Fin : 12:00                       │
│  • Région : جهة الوسط                │
│  • Zones : سوسة; المنستير; صفاقس    │
└──────────────────────────────────────┘
```

##### 🗓️ **Analyse des Dates**

L'analyseur comprend les dates en arabe et les convertit en format standard :
- "21 جويلية 2026" → "2026-07-21"
- "21/07/2026" → "2026-07-21"

##### 🕐 **Analyse des Heures**

L'analyseur gère les expressions de temps arabes :

| Expression Arabe | Résultat |
|-----------------|----------|
| الساعة السادسة صباحا | 06:00 (6h du matin) |
| منتصف النهار | 12:00 (midi) |
| الساعة الرابعة مساء | 16:00 (4h après-midi) |
| العاشرة ليلا | 22:00 (10h du soir) |
| منتصف الليل | 00:00 (minuit) |

**Bonus :** Gère même les fautes de frappe comme "منتصف النهر" (→ 12:00)

##### 📍 **Extraction de Région**

L'analyseur cherche la région dans le titre :
- جهة الشمال (Nord)
- جهة الجنوب (Sud)
- جهة الوسط (Centre)
- جهة صفاقس (Sfax)
- جهة تونس الكبرى (Grand Tunis)

##### 🏘️ **Extraction des Zones**

L'analyseur trouve la liste des villes/zones après "المناطق التالية" et les formate en liste séparée par des points-virgules.

---

#### ✅ **ÉTAPE 4 : Validation** (Contrôle Qualité)

Chaque enregistrement passe par 8 règles de validation :
1. ✅ A une date valide ?
2. ✅ A une heure de début ?
3. ✅ A une région ?
4. ✅ La région est dans la liste connue ?
5. ✅ A des zones affectées ?
6. ✅ La date n'est pas dans le passé ?
7. ✅ Les heures sont logiques ? (début avant fin)
8. ✅ Pas de doublon ?

---

#### 🔄 **ÉTAPE 5 : Déduplication** (Supprimer les Doublons)

Deux méthodes pour détecter les doublons :
1. **Vérification URL** : Même URL = Doublon
2. **Hash de Contenu** : Hash(date + région + heure + zones) — si identique = Doublon

---

#### 💾 **ÉTAPE 6 : Export** (Sauvegarder dans des Fichiers)

Les 113 enregistrements propres sont exportés en 3 formats :
- 📄 **CSV** → steg_outages.csv (pour Excel, Google Sheets)
- 📊 **Excel** → steg_outages.xlsx (pour Microsoft Excel)
- 📋 **JSON** → steg_outages.json (pour programmation)

---

## 📁 Structure du Projet

```
steg-outage-data/
│
├── 📊 data/
│   ├── processed/              ← VOS RÉSULTATS SONT ICI !
│   │   ├── steg_outages.csv    ← Ouvrir avec Excel/Google Sheets
│   │   ├── steg_outages.xlsx   ← Ouvrir avec Excel
│   │   └── steg_outages.json   ← Utiliser en programmation
│   │
│   └── raw/
│       ├── html/               ← 120 pages web sauvegardées
│       └── steg_outages_raw.json
│
├── 🔧 scraper/                  ← Le code qui fait le travail
│   ├── steg_crawler.py         ← Principal : Télécharge les pages
│   ├── steg_parser.py          ← Extrait les données du texte arabe
│   ├── steg_validator.py       ← Vérifie la qualité des données
│   └── deduplicator.py         ← Supprime les doublons
│
├── ✅ tests/                    ← Tests du code (optionnel)
│
├── 📝 README.md                 ← Version anglaise
├── 📝 README_FR.md              ← Vous êtes ici !
├── 📝 QUICK_START.md            ← Comment lancer (3 étapes)
│
└── ⚙️ Autres fichiers :
    ├── reprocess_html.py       ← Re-traiter les fichiers HTML sauvegardés
    └── requirements.txt        ← Liste des bibliothèques nécessaires
```

---

## 📊 Données en Sortie

### Colonnes CSV/Excel

| Colonne | Type | Description | Exemple |
|---------|------|-------------|---------|
| `source_url` | URL | Page d'annonce originale | https://www.steg.com.tn/... |
| `source_title` | Texte | Titre de l'annonce | "إشعار بانقطاع الكهرباء..." |
| `published_at` | DateTime | Quand STEG l'a publié | "2026-07-27 14:39" |
| `outage_date` | Date | Date de la coupure | "2026-07-28" |
| `planned_start` | Time | Heure de début (24h) | "06:00" |
| `planned_end` | Time | Heure de fin ou "0" si inconnue | "12:00" ou "0" |
| `region` | Texte | Quelle région | "جهة الشمال" |
| `affected_areas` | Texte | Villes/zones (séparées par ;) | "سوسة; المنستير; صفاقس" |
| `scraped_at` | DateTime | Quand nous l'avons extrait | "2026-08-11 15:00:30" |

### Exemple de Données

```csv
outage_date,planned_start,planned_end,region,affected_areas
2026-07-21,06:00,12:00,جهة الشمال,"سوسة; المنستير"
2026-07-22,10:00,17:00,جهة الجنوب,"قابس; مدنين"
2026-07-23,18:00,22:00,جهة صفاقس,"صفاقس المدينة; ساقية الزيت"
```

---

## 🚀 Installation & Utilisation

**Voir [QUICK_START.md](QUICK_START.md) pour les instructions complètes !**

Aperçu rapide :
```bash
# 1. Installer les bibliothèques Python
pip install -r requirements.txt

# 2. Lancer le scraper
python -m scraper.steg_crawler
```

**Ou re-traiter les fichiers HTML sauvegardés :**
```bash
python reprocess_html.py
```

**Durée totale :** ~5-10 minutes pour télécharger toutes les données

---

## 💡 Comprendre le Code

### Fichiers Principaux (pour débutants)

#### 1. `steg_crawler.py` - Le Téléchargeur

**Ce qu'il fait :** Va sur le site STEG et télécharge les pages

**Fonctions clés :**
- `discover_articles()` - Trouve tous les liens d'articles
- `download_and_parse(url)` - Télécharge un article et extrait les données

#### 2. `steg_parser.py` - L'Expert en Texte Arabe

**Ce qu'il fait :** Lit le texte arabe et extrait des données structurées

**Fonctions clés :**
- `parse_date(text)` - Convertit "21 جويلية 2026" → "2026-07-21"
- `parse_time(text)` - Convertit "منتصف النهار" → "12:00"
- `parse_region(title)` - Trouve la région dans le titre
- `parse_affected_areas(text)` - Extrait la liste des villes

#### 3. `steg_validator.py` - Le Vérificateur de Qualité

**Ce qu'il fait :** S'assure que les données sont valides avec 8 règles

#### 4. `deduplicator.py` - Le Détecteur de Doublons

**Ce qu'il fait :** Supprime les annonces en double

---

## 🐛 Dépannage

### Problèmes Courants

**❌ Erreur : "No module named 'beautifulsoup4'"**
```bash
Solution : pip install -r requirements.txt
```

**❌ Le scraper est très lent**
- C'est normal ! Il attend 1,5-3 secondes entre chaque téléchargement
- Durée totale : ~5-10 minutes pour 113 articles

**❌ "Connection timeout"**
- Vérifiez votre connexion Internet
- Le site STEG pourrait être en panne
- Utilisez `python reprocess_html.py` pour re-traiter les fichiers sauvegardés

**⚠️ Vous voulez des données fraîches sans re-télécharger ?**
```bash
python reprocess_html.py
```
C'est beaucoup plus rapide (~10 secondes) !

---

## ✨ Fonctionnalités Clés

✅ **Accessible aux Débutants** - Code clair avec commentaires  
✅ **Robuste** - Gère les fautes, variations, données manquantes  
✅ **Intelligent** - Filtre automatiquement le contenu non-coupure  
✅ **Poli** - Attend entre les requêtes pour ne pas surcharger le serveur  
✅ **Reproductible** - Sauvegarde le HTML pour re-traitement  
✅ **Multi-Format** - CSV, Excel, JSON  
✅ **Support Arabe** - Encodage UTF-8 approprié  
✅ **Testé** - Tests unitaires pour les fonctions critiques  

---

## 📈 Statistiques

- **113** annonces de coupures collectées
- **5** régions couvertes
- **120** pages HTML sauvegardées
- **1 105** lignes de code Python
- **8** règles de validation
- **100%** de support UTF-8 arabe

---

## 🤝 Crédits

**Développé pour :** Hackathon Olive 2026  
**Source des Données :** [Site Officiel STEG](https://www.steg.com.tn)  
**Langage :** Python 3.12+  
**Localisation :** Tunisie 🇹🇳

---

## 📝 Licence

Ce projet est à des fins éducatives.

---

**Des questions ?** Lisez les commentaires du code - ils expliquent tout étape par étape ! 💡

**Bon scraping ! 🚀**
