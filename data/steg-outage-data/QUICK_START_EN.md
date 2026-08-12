# ⚡ Guide de Démarrage Rapide

Obtenez les données de coupures STEG en **3 étapes simples** ! (5 minutes)

---

## 📋 Ce Dont Vous Avez Besoin

- **Python 3.8 ou supérieur** installé sur votre ordinateur
- **Connexion Internet** (pour télécharger les données du site STEG)

**Vérifier si Python est installé :**
```bash
python --version
```

Si vous voyez `Python 3.8` ou supérieur → C'est bon ! ✅  
Sinon → [Télécharger Python ici](https://www.python.org/downloads/)

---

## 🚀 3 Étapes Pour Obtenir Les Données

## 🚀 3 Étapes Pour Obtenir Les Données

### Étape 1 : Installer les Bibliothèques Nécessaires

Ouvrez votre terminal et exécutez :

```bash
cd /chemin/vers/steg-outage-data
pip install -r requirements.txt
```

**Ce que ça fait :** Installe les outils dont le scraper a besoin :
- `beautifulsoup4` - Lit les pages web
- `requests` - Télécharge les pages web
- `pandas` - Organise les données
- `openpyxl` - Crée des fichiers Excel

**Durée :** ~1-2 minutes  
**Vous ne devez faire ça qu'une seule fois !** ✅

---

### Étape 2 : Lancer le Scraper

**Option A : Télécharger les Données Fraîches du Site STEG**

```bash
python -m scraper.steg_crawler
```

**Ce qui se passe :**
- Ouvre le site STEG
- Trouve toutes les annonces de coupures
- Les télécharge (attend poliment entre les requêtes)
- Extrait les données du texte arabe
- Sauvegarde en CSV, Excel, JSON

**Durée :** ~5-10 minutes (car il attend 1,5-3s entre chaque téléchargement)  
**Résultat :** Les fichiers apparaissent dans `data/processed/`

---

**Option B : Re-traiter les Fichiers HTML Sauvegardés** (Plus Rapide !)

Si vous avez déjà les fichiers HTML dans `data/raw/html/` :

```bash
python reprocess_html.py
```

**Durée :** ~10 secondes  
**Parfait pour :** Tester des changements sans re-télécharger

---

### Étape 3 : Récupérez Vos Données ! 🎉

Ouvrez le dossier des résultats :

```bash
cd data/processed/
```

**Vous trouverez 3 fichiers :**

```
📄 steg_outages.csv     ← Ouvrir avec Excel, Google Sheets, ou un éditeur de texte
📊 steg_outages.xlsx    ← Ouvrir avec Microsoft Excel
📋 steg_outages.json    ← Utiliser en programmation (Python, JavaScript, etc.)
```

**Double-cliquez sur le fichier Excel pour voir vos données !**

---

## 📊 Que Contiennent Les Données ?

### Colonnes Excel/CSV :

| Colonne | Signification | Exemple |
|---------|---------------|---------|
| `outage_date` | Date de la coupure | 2026-07-28 |
| `planned_start` | Heure de début (format 24h) | 06:00 |
| `planned_end` | Heure de fin ou "0" si inconnu | 12:00 |
| `region` | Quelle région | جهة الشمال |
| `affected_areas` | Quelles villes/zones | سوسة; المنستير; صفاقس |
| `source_url` | Annonce STEG originale | https://www.steg.com.tn/... |
| `published_at` | Quand STEG l'a publié | 2026-07-27 14:39 |

### Aperçu dans Excel :

```
| Date       | Début | Fin   | Région      | Zones              |
|------------|-------|-------|-------------|--------------------|
| 2026-07-21 | 06:00 | 12:00 | جهة الشمال  | سوسة; المنستير     |
| 2026-07-22 | 10:00 | 17:00 | جهة الجنوب  | قابس; مدنين        |
| 2026-07-23 | 18:00 | 22:00 | جهة صفاقس   | صفاقس المدينة      |
```

**Total :** 113 annonces de coupures électriques ✅

---

## 🎯 Cas d'Utilisation Courants

### 1. Ouvrir dans Excel/Google Sheets
```bash
# Juste double-cliquez :
data/processed/steg_outages.xlsx
```

### 2. Utiliser en Python
```python
import pandas as pd

# Charger les données
df = pd.read_csv('data/processed/steg_outages.csv')

# Afficher les 5 premiers enregistrements
print(df.head())

# Filtrer par région
north_outages = df[df['region'] == 'جهة الشمال']

# Compter par région
print(df['region'].value_counts())
```

### 3. Utiliser en JavaScript
```javascript
// Lire le fichier JSON
const data = require('./data/processed/steg_outages.json');

// Afficher le premier enregistrement
console.log(data[0]);

// Filtrer par date
const julyOutages = data.filter(record => 
    record.outage_date.startsWith('2026-07')
);
```

---

## 🔧 Dépannage

### ❌ Erreur : "No module named 'beautifulsoup4'"

**Solution :**
```bash
pip install -r requirements.txt
```

---

### ❌ Erreur : "Permission denied"

**Solution (Linux/Mac) :**
```bash
sudo pip install -r requirements.txt
```

**Solution (Windows) :** Exécutez l'invite de commande en tant qu'Administrateur

---

### ❌ Le Scraper est bloqué ou très lent

**Normal !** Le scraper attend 1,5-3 secondes entre les téléchargements pour être poli avec le serveur.

**Progression :**
- Total d'articles : ~113
- Temps par article : ~2 secondes
- Temps total : ~5-10 minutes

**Voir la progression :** Regardez le terminal - il affiche chaque article pendant le téléchargement !

---

### ❌ "Connection timeout" ou "Failed to fetch"

**Causes :**
- Pas de connexion Internet
- Le site STEG est en panne
- Pare-feu qui bloque

**Solution :**
1. Vérifiez la connexion Internet
2. Réessayez dans quelques minutes
3. Utilisez les fichiers HTML sauvegardés à la place :
   ```bash
   python reprocess_html.py
   ```

---

### ⚠️ Vous voulez des données fraîches sans re-télécharger ?

**Si vous avez déjà lancé le scraper une fois :**

Les fichiers HTML sont sauvegardés dans `data/raw/html/`

Pour les re-traiter (utile si vous avez corrigé des bugs dans le parser) :
```bash
python reprocess_html.py
```

C'est **beaucoup plus rapide** (~10 secondes) car il ne re-télécharge pas !

---

## 📚 Prochaines Étapes

### Vous Voulez Comprendre Comment Ça Marche ?

Lisez **[README.md](README.md)** - Explication complète avec des diagrammes !

Sujets couverts :
- 🔄 Comment fonctionne le web scraping
- 🧠 Comment fonctionne l'analyse de texte arabe
- 📊 Flux de données du site web vers Excel
- 💻 Explication du code pour débutants
- 🎓 Ressources d'apprentissage

---

### Vous Voulez Modifier Le Code ?

**Structure du projet :**
```
scraper/
├── steg_crawler.py     ← Télécharge les pages (COMMENCEZ ICI)
├── steg_parser.py      ← Extrait les données du texte arabe
├── steg_validator.py   ← Vérifie la qualité des données
└── deduplicator.py     ← Supprime les doublons
```

**Chaque fichier contient des commentaires détaillés expliquant ce qu'il fait !**

---

### Vous Voulez Lancer Les Tests ?

```bash
cd tests
python -m pytest
```

Les tests vérifient :
- ✅ L'analyse des dates fonctionne correctement
- ✅ L'analyse des heures gère tous les formats
- ✅ L'extraction des régions fonctionne
- ✅ La déduplication fonctionne

---

## 💡 Astuces Pro

### Astuce 1 : Programmer des Mises à Jour Automatiques

**Linux/Mac (avec cron) :**
```bash
# Lancer tous les jours à 2h du matin
0 2 * * * cd /chemin/vers/steg-outage-data && python -m scraper.steg_crawler
```

**Windows (avec Planificateur de Tâches) :**
1. Ouvrir Planificateur de Tâches
2. Créer une nouvelle tâche
3. Définir le déclencheur : Quotidien à 2h du matin
4. Définir l'action : Exécuter `python -m scraper.steg_crawler`

---

### Astuce 2 : Vérifier la Qualité des Données

```python
import pandas as pd

df = pd.read_csv('data/processed/steg_outages.csv')

# Vérifier les données manquantes
print(df.isnull().sum())

# Compter les enregistrements par région
print(df['region'].value_counts())

# Trouver les enregistrements sans heure de fin
missing_end = df[df['planned_end'] == '0']
print(f"Enregistrements sans heure de fin : {len(missing_end)}")
```

---

### Astuce 3 : Exporter un Format Personnalisé

```python
import pandas as pd

df = pd.read_csv('data/processed/steg_outages.csv')

# Exporter uniquement des régions spécifiques
north_data = df[df['region'] == 'جهة الشمال']
north_data.to_excel('coupures_nord_seulement.xlsx', index=False)

# Exporter uniquement Juillet 2026
july_data = df[df['outage_date'].str.startswith('2026-07')]
july_data.to_csv('coupures_juillet_2026.csv', index=False)
```

---

## ✅ Liste de Vérification

Avant de lancer le scraper :
- [ ] Python 3.8+ installé
- [ ] Bibliothèques installées (`pip install -r requirements.txt`)
- [ ] Connexion Internet fonctionnelle
- [ ] Dans le bon répertoire (`cd steg-outage-data`)

Après l'exécution :
- [ ] Vérifier le dossier `data/processed/`
- [ ] Ouvrir `steg_outages.xlsx` dans Excel
- [ ] Vérifier que les données sont correctes (113 enregistrements, tout le texte arabe visible)

---

## 🎉 Succès !

Si vous voyez des fichiers dans `data/processed/` et pouvez ouvrir le fichier Excel → **Vous avez réussi !** 🎊

**Vous avez maintenant :**
- ✅ 113 enregistrements de coupures structurés
- ✅ Des fichiers CSV/Excel/JSON propres
- ✅ Le texte arabe correctement affiché
- ✅ Toutes les dates, heures, régions extraites
- ✅ Prêt à analyser ou visualiser !

---

## 📞 Besoin d'Aide ?

1. **Lisez attentivement les messages d'erreur** - ils vous disent souvent exactement ce qui ne va pas
2. **Consultez README.md** - Explication détaillée de tout
3. **Regardez les commentaires du code** - Chaque fonction est expliquée
4. **Lancez les tests** - `cd tests && python -m pytest` pour vérifier que tout fonctionne

---

**Bon scraping ! 🚀**

*Temps total de zéro à données : ~10 minutes*
