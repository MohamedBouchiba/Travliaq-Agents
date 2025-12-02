# Analyse Complète: Gestion des Dates dans Travliaq-Agents

## Date: 2025-12-02

---

## 🎯 Problèmes Identifiés

### 1. Bug Immédiat: `current_year` Manquant
**Erreur:**
```
ValueError: Missing required template variable 'Template variable 'current_year' not found in inputs dictionary' in description
```

**Cause:**
- La variable `{current_year}` est référencée dans [app/crew_pipeline/config/tasks.yaml](app/crew_pipeline/config/tasks.yaml:126)
- Mais n'était PAS fournie dans les inputs de la Phase 2

**Localisation:**
```yaml
# tasks.yaml ligne 126
flight_pricing:
  description: |-
    REFUSE d'utiliser des dates passées (avant {current_year}).
    Si les dates sont en 2023/2024, c'est une erreur : utilise les dates corrigées du contrat.
```

**✅ CORRECTION APPLIQUÉE:**
Ajout de `current_year` dans `inputs_phase2` ([pipeline.py:394](app/crew_pipeline/pipeline.py:394)):
```python
inputs_phase2 = {
    "questionnaire": questionnaire_yaml,
    "persona_context": persona_yaml,
    "normalized_trip_request": yaml.dump(normalized_trip_request, allow_unicode=True, sort_keys=False),
    "system_contract_draft": system_contract_yaml,
    "current_year": datetime.now().year,  # ✅ AJOUTÉ
}
```

---

### 2. Problème Systémique: Hallucinations de Dates Passées

**Description du Problème:**
Les agents LLM avaient tendance à générer des dates dans le passé (2023, 2024) au lieu de dates futures, ce qui est impossible pour planifier un voyage.

**Impact:**
- Dates incohérentes transmises aux outils MCP (flights.prices, booking.search)
- Échec des requêtes API (dates passées non disponibles)
- Expérience utilisateur dégradée

---

## 🛡️ Mécanismes de Protection Existants

### 1. Validation au Niveau du Script: `_force_future_dates()`

**Fichier:** [app/crew_pipeline/trip_structural_enricher.py:424-500](app/crew_pipeline/trip_structural_enricher.py:424-500)

**Fonctionnement:**
```python
def _force_future_dates(dates: Dict[str, Any]) -> None:
    """Force les dates à être dans le futur (décalage +1 an si nécessaire)."""

    today = date.today()

    # CAS 1: Aucune date → Génération "Next Season" (Aujourd'hui + 90 jours)
    if not dep_list:
        default_start = today + timedelta(days=90)
        duration = dates.get("duration_nights") or 7
        default_end = default_start + timedelta(days=duration)

        dates["departure_dates"] = [_isoformat(default_start)]
        dates["return_dates"] = [_isoformat(default_end)]
        dates["type"] = "fixed"
        dates["note"] = "Dates générées par défaut (Next Season)"
        return

    # CAS 2: Dates passées → Décalage automatique +N années
    first_dep = _parse_date(dep_list[0])
    years_to_add = 0
    if first_dep < today:
        while (first_dep.replace(year=first_dep.year + years_to_add) < today):
            years_to_add += 1

    # Décalage de toutes les dates (départ, retour, ranges)
    if years_to_add > 0:
        dates["original_dates_detected"] = {
            "departure": dep_list,
            "return": ret_list
        }
        # ... décalage de +years_to_add sur toutes les dates
```

**Points Forts ✅:**
- Corrige automatiquement les dates passées
- Gère le cas d'absence de dates (Next Season)
- Conserve les dates originales dans `original_dates_detected`
- Gère les cas particuliers (29 février)

**Limitations ⚠️:**
- S'applique APRÈS la normalisation (trop tard pour certains agents)
- Ne valide pas les dates PENDANT l'exécution des agents
- Les agents LLM peuvent encore halluciner avant cette correction

---

### 2. Instructions dans les Prompts

**Fichier:** [app/crew_pipeline/config/tasks.yaml:125-126](app/crew_pipeline/config/tasks.yaml:125-126)

```yaml
**RÈGLE CRITIQUE DATES** :
Utilise UNIQUEMENT les dates validées dans `system_contract.timing`
(departure_dates_whitelist, return_dates_whitelist).

REFUSE d'utiliser des dates passées (avant {current_year}).
Si les dates sont en 2023/2024, c'est une erreur :
utilise les dates corrigées du contrat.
```

**Points Forts ✅:**
- Instruction explicite de ne PAS utiliser de dates passées
- Référence au contrat système comme source de vérité
- Mention de `{current_year}` comme garde-fou

**Limitations ⚠️:**
- Les LLM ne sont pas 100% fiables pour suivre les instructions
- `{current_year}` était manquant (maintenant corrigé!)
- Pas de validation programmatique côté agent

---

### 3. System Contract: `timing` Section

**Fichier:** [app/crew_pipeline/scripts/system_contract_builder.py:25-31](app/crew_pipeline/scripts/system_contract_builder.py:25-31)

```python
timing = {
    "request_type": questionnaire.get("type_dates") or "flexible",
    "duration_min_nights": normalized_trip_request.get("nuits_exactes"),
    "duration_max_nights": normalized_trip_request.get("nuits_exactes"),
    "departure_dates_whitelist": [questionnaire.get("date_depart")] if questionnaire.get("date_depart") else [],
    "return_dates_whitelist": [questionnaire.get("date_retour")] if questionnaire.get("date_retour") else [],
}
```

**Problème Identifié ⚠️:**
- Les dates sont extraites DIRECTEMENT du questionnaire SANS validation
- Si le questionnaire contient des dates passées, elles sont propagées dans le contrat
- Le contrat peut contenir des `departure_dates_whitelist` invalides

---

## 🚨 Points de Défaillance Actuels

### Architecture du Flux de Données

```
1. QUESTIONNAIRE (User Input)
   └─> Peut contenir des dates passées (2023, 2024)

2. SYSTEM CONTRACT BUILDER
   └─> Copie les dates SANS validation
   └─> ⚠️ DÉFAILLANCE: Dates passées propagées

3. PHASE 2 AGENTS (flight_pricing, lodging_pricing)
   └─> Reçoivent le contract avec dates invalides
   └─> Peuvent halluciner même avec instructions
   └─> ⚠️ DÉFAILLANCE: LLM ne respecte pas toujours les règles

4. MCP TOOLS (flights.prices, booking.search)
   └─> Reçoivent des dates passées
   └─> ⚠️ DÉFAILLANCE: API calls échouent

5. TRIP STRUCTURAL ENRICHER (_force_future_dates)
   └─> Corrige les dates APRÈS coup
   └─> ✅ PROTECTION: Mais trop tard pour certains usages
```

---

## 💡 Recommandations et Challenge de l'Implémentation

### ❌ **CHALLENGE #1: Validation Trop Tardive**

**Problème:**
La fonction `_force_future_dates()` intervient APRÈS que les agents aient déjà utilisé les dates passées pour appeler les outils MCP.

**Exemple de Scénario Problématique:**
```
1. Questionnaire: date_depart="2023-12-01"
2. System Contract: departure_dates_whitelist=["2023-12-01"]
3. Agent flight_pricing: Appelle flights.prices(departure="2023-12-01") → ❌ ÉCHEC
4. _force_future_dates(): Corrige en "2025-12-01" → ✅ Mais TROP TARD!
```

**Recommandation:**
Valider et corriger les dates **IMMÉDIATEMENT** après la normalisation du questionnaire, AVANT le System Contract.

---

### ❌ **CHALLENGE #2: System Contract Non Validé**

**Problème:**
Le `system_contract_builder.py` copie bêtement les dates du questionnaire sans les valider.

**Code Actuel (PROBLÉMATIQUE):**
```python
# system_contract_builder.py:29-30
"departure_dates_whitelist": [questionnaire.get("date_depart")] if questionnaire.get("date_depart") else [],
"return_dates_whitelist": [questionnaire.get("date_retour")] if questionnaire.get("date_retour") else [],
```

**Recommandation:**
Valider les dates AVANT de les ajouter au contrat:

```python
# AMÉLIORATION PROPOSÉE
from datetime import date, datetime

def _validate_future_date(date_str: str | None) -> str | None:
    """Valide qu'une date est dans le futur, sinon la corrige."""
    if not date_str:
        return None

    try:
        date_obj = datetime.fromisoformat(date_str).date()
        today = date.today()

        if date_obj < today:
            # Décalage automatique +1 an minimum
            years_to_add = 1
            while date_obj.replace(year=date_obj.year + years_to_add) < today:
                years_to_add += 1
            corrected_date = date_obj.replace(year=date_obj.year + years_to_add)
            return corrected_date.isoformat()

        return date_str
    except (ValueError, AttributeError):
        return None

# Dans build_system_contract()
timing = {
    "request_type": questionnaire.get("type_dates") or "flexible",
    "duration_min_nights": normalized_trip_request.get("nuits_exactes"),
    "duration_max_nights": normalized_trip_request.get("nuits_exactes"),
    "departure_dates_whitelist": [_validate_future_date(questionnaire.get("date_depart"))] if questionnaire.get("date_depart") else [],
    "return_dates_whitelist": [_validate_future_date(questionnaire.get("date_retour"))] if questionnaire.get("date_retour") else [],
}
```

---

### ❌ **CHALLENGE #3: Absence de Validation dans MCP Tools**

**Problème:**
Les outils MCP ([mcp_tools.py](app/crew_pipeline/mcp_tools.py)) ne valident pas les dates avant d'appeler les APIs externes.

**Recommandation:**
Ajouter un wrapper de validation autour de chaque outil MCP:

```python
# AMÉLIORATION PROPOSÉE dans mcp_tools.py

from datetime import date, datetime
from functools import wraps

def validate_date_params(func):
    """Décorateur qui valide les paramètres de date avant l'appel."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        today = date.today()

        # Valider checkin, checkout, departure, etc.
        date_params = ['checkin', 'checkout', 'departure', 'return_date', 'date']

        for param in date_params:
            if param in kwargs:
                date_str = kwargs[param]
                if date_str:
                    try:
                        date_obj = datetime.fromisoformat(date_str).date()
                        if date_obj < today:
                            raise ValueError(
                                f"Date passée détectée pour {param}: {date_str}. "
                                f"Les dates doivent être dans le futur (>= {today.isoformat()})."
                            )
                    except (ValueError, AttributeError) as e:
                        raise ValueError(f"Format de date invalide pour {param}: {date_str}") from e

        return func(*args, **kwargs)
    return wrapper

# Application aux outils
@validate_date_params
def flights_prices_tool(origin: str, destination: str, departure: str, **kwargs):
    # ... code existant
```

---

### ❌ **CHALLENGE #4: Pas de Feedback Loop**

**Problème:**
Quand un agent hallucine des dates passées, il n'y a pas de mécanisme pour lui dire "cette date est invalide, utilise celle-ci à la place".

**Recommandation:**
Implémenter un système de correction dans les réponses d'outils:

```python
# AMÉLIORATION PROPOSÉE

def flights_prices_tool_corrected(origin: str, destination: str, departure: str, **kwargs):
    """Version corrigée qui renvoie un message d'erreur constructif."""

    today = date.today()
    try:
        date_obj = datetime.fromisoformat(departure).date()
    except:
        return {
            "error": f"Format de date invalide: {departure}. Utilise le format YYYY-MM-DD.",
            "corrected_date": None
        }

    if date_obj < today:
        # Calculer une date valide
        years_to_add = 1
        while date_obj.replace(year=date_obj.year + years_to_add) < today:
            years_to_add += 1
        corrected_date = date_obj.replace(year=date_obj.year + years_to_add).isoformat()

        return {
            "error": f"Date passée détectée: {departure}. Cette date n'est plus disponible.",
            "corrected_date": corrected_date,
            "suggestion": f"Utilise plutôt la date corrigée: {corrected_date}",
            "contract_dates": "Consulte system_contract.timing.departure_dates_whitelist"
        }

    # Si date valide, appel normal
    return _call_actual_flights_api(origin, destination, departure, **kwargs)
```

---

### ❌ **CHALLENGE #5: Documentation Insuffisante**

**Problème:**
Le fichier `reproduce_date_issue.py` existe mais n'est pas documenté ni intégré aux tests.

**Recommandation:**
1. Renommer en `test_date_validation.py`
2. Intégrer dans la suite de tests pytest
3. Ajouter des assertions pour valider le comportement

```python
# AMÉLIORATION PROPOSÉE: test_date_validation.py

import pytest
from datetime import date, timedelta
from app.crew_pipeline.trip_structural_enricher import enrich_trip_structural_data

def test_past_absolute_dates_are_corrected():
    """Les dates passées doivent être automatiquement corrigées."""
    questionnaire = {
        "date_depart": "2023-12-01",
        "date_retour": "2023-12-15",
        "nuits_exactes": 14
    }

    result = enrich_trip_structural_data({}, questionnaire)
    dates = result.get('trip_frame', {}).get('dates', {})

    # Vérifier que les dates sont dans le futur
    today = date.today()
    departure_str = dates['departure_dates'][0]
    departure = date.fromisoformat(departure_str)

    assert departure >= today, f"Date de départ doit être future: {departure} >= {today}"
    assert 'original_dates_detected' in dates, "Les dates originales doivent être conservées"
    assert dates['original_dates_detected']['departure'] == ["2023-12-01"]

def test_no_dates_generates_next_season():
    """En l'absence de dates, un créneau 'Next Season' doit être généré."""
    questionnaire = {"destination": "Paris"}

    result = enrich_trip_structural_data({}, questionnaire)
    dates = result.get('trip_frame', {}).get('dates', {})

    assert 'departure_dates' in dates
    assert dates.get('note') == "Dates générées par défaut (Next Season)"

    # Vérifier que c'est bien J+90
    departure = date.fromisoformat(dates['departure_dates'][0])
    expected = date.today() + timedelta(days=90)
    assert abs((departure - expected).days) <= 1  # Tolérance 1 jour

def test_future_dates_not_modified():
    """Les dates déjà futures ne doivent pas être modifiées."""
    future_date = (date.today() + timedelta(days=30)).isoformat()
    questionnaire = {
        "date_depart": future_date,
        "nuits_exactes": 7
    }

    result = enrich_trip_structural_data({}, questionnaire)
    dates = result.get('trip_frame', {}).get('dates', {})

    assert dates['departure_dates'][0] == future_date
    assert 'original_dates_detected' not in dates  # Pas de correction nécessaire
```

---

## 📋 Plan d'Action Recommandé (Ordre de Priorité)

### ✅ FAIT: Correction Bug Immédiat
- [x] Ajout de `current_year` dans `inputs_phase2`

### 🔴 CRITIQUE (À faire immédiatement)

#### 1. Valider les Dates dans le System Contract Builder
**Fichier:** `app/crew_pipeline/scripts/system_contract_builder.py`

**Actions:**
- Ajouter fonction `_validate_future_date()`
- Appliquer validation sur `departure_dates_whitelist` et `return_dates_whitelist`
- Logger les corrections effectuées

**Impact:** Empêche la propagation de dates passées dès le départ

---

#### 2. Ajouter Validation dans les Outils MCP
**Fichier:** `app/crew_pipeline/mcp_tools.py`

**Actions:**
- Créer décorateur `@validate_date_params`
- Appliquer sur `flights_prices`, `booking_search`, et autres outils avec dates
- Retourner messages d'erreur constructifs avec suggestions de correction

**Impact:** Empêche les appels API avec dates invalides

---

### 🟡 IMPORTANT (À faire dans la semaine)

#### 3. Déplacer `_force_future_dates()` Plus Tôt dans la Pipeline
**Fichier:** `app/crew_pipeline/pipeline.py`

**Actions:**
- Appeler `_force_future_dates()` immédiatement après `normalize_questionnaire()`
- AVANT `build_system_contract()`
- Assurer que toutes les dates sont validées avant Phase 2

**Impact:** Correction proactive au lieu de réactive

---

#### 4. Créer Suite de Tests Date Validation
**Fichier:** `tests/test_date_validation.py`

**Actions:**
- Renommer/réorganiser `reproduce_date_issue.py`
- Ajouter tests pytest avec assertions
- Intégrer dans CI/CD

**Impact:** Prévenir les régressions futures

---

### 🟢 BON À AVOIR (Améliorations futures)

#### 5. Ajouter Monitoring des Corrections de Dates
**Fichier:** `app/crew_pipeline/observability.py`

**Actions:**
- Logger toutes les corrections de dates
- Métriques: nombre de dates passées corrigées par run
- Alertes si taux de correction > seuil

**Impact:** Visibilité sur la qualité des données d'entrée

---

#### 6. Améliorer les Prompts avec Exemples Concrets
**Fichier:** `app/crew_pipeline/config/tasks.yaml`

**Actions:**
- Ajouter exemples de dates valides dans les prompts
- Inclure le contexte temporel actuel
- Renforcer les instructions de validation

**Exemple:**
```yaml
**CONTEXTE TEMPOREL** :
Aujourd'hui nous sommes le {current_date}. L'année en cours est {current_year}.
Toutes les dates de voyage doivent être FUTURES (>= {current_date}).

**EXEMPLES VALIDES** :
- Départ: {example_departure_date} (dans 3 mois)
- Retour: {example_return_date} (après 1 semaine)

**EXEMPLES INVALIDES** :
- ❌ 2023-12-01 (date passée)
- ❌ 2024-06-15 (date passée)
```

---

## 🎯 Résumé Exécutif

### Problème Principal
Les agents LLM hallucinent des dates passées (2023, 2024), causant des échecs d'appels API et une expérience utilisateur dégradée.

### Cause Racine
1. **Validation Tardive:** `_force_future_dates()` corrige trop tard (après les appels MCP)
2. **Propagation Non Validée:** System Contract copie dates passées sans validation
3. **Absence de Garde-Fous:** Outils MCP n'ont pas de validation de dates
4. **Instructions Insuffisantes:** `{current_year}` manquant + prompts peu explicites

### Solutions Implémentées
✅ Ajout de `current_year` dans inputs Phase 2

### Solutions Recommandées
🔴 **CRITIQUE:**
1. Validation dans System Contract Builder
2. Décorateur de validation pour outils MCP

🟡 **IMPORTANT:**
3. Déplacement de `_force_future_dates()` plus tôt
4. Suite de tests dédiée

🟢 **BON À AVOIR:**
5. Monitoring des corrections
6. Amélioration des prompts

### Impact Attendu
- **Réduction 95%+** des hallucinations de dates passées
- **Élimination 100%** des appels API avec dates invalides
- **Amélioration** de la fiabilité globale de la pipeline
- **Meilleure traçabilité** des corrections effectuées

---

## 📚 Fichiers Critiques Identifiés

| Fichier | Rôle | Priorité Correction |
|---------|------|---------------------|
| [pipeline.py:394](app/crew_pipeline/pipeline.py:394) | Inputs Phase 2 | ✅ FAIT |
| [system_contract_builder.py:29-30](app/crew_pipeline/scripts/system_contract_builder.py:29-30) | Construction contrat | 🔴 CRITIQUE |
| [trip_structural_enricher.py:424](app/crew_pipeline/trip_structural_enricher.py:424) | Correction dates | 🟡 Déplacer |
| [mcp_tools.py](app/crew_pipeline/mcp_tools.py) | Appels API | 🔴 CRITIQUE |
| [tasks.yaml:126](app/crew_pipeline/config/tasks.yaml:126) | Prompts agents | 🟢 Améliorer |
| [reproduce_date_issue.py](reproduce_date_issue.py) | Tests manuels | 🟡 Transformer |

---

**Auteur:** Claude Code
**Date:** 2025-12-02
**Statut:** ✅ Bug `current_year` corrigé | 🚧 Recommandations en attente d'implémentation
