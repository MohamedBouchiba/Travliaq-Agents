# 🚀 NOUVELLE ARCHITECTURE PIPELINE TRAVLIAQ

**Date**: 2025-12-02
**Version**: 2.0
**Auteur**: Refonte complète basée sur analyse du JSON final et du questionnaire

---

## 📋 TABLE DES MATIÈRES

1. [Vue d'ensemble](#vue-densemble)
2. [Agents (7 au lieu de 13)](#agents-7-au-lieu-de-13)
3. [Tâches et chemins de réponse](#tâches-et-chemins-de-réponse)
4. [Modifications pipeline.py](#modifications-pipelinepy)
5. [Flux d'exécution](#flux-dexécution)
6. [Points clés](#points-clés)
7. [Exemple de run](#exemple-de-run)

---

## 🎯 VUE D'ENSEMBLE

### Problèmes résolus

1. ✅ **Trop d'agents** → Réduction de 13 à 7 agents focalisés
2. ✅ **Pas de focus sur JSON final** → Agent Final Assembler dédié
3. ✅ **Manque de GPS** → Obligation d'utiliser MCP geo tools
4. ✅ **Images externes** → Validation stricte des URLs Supabase
5. ✅ **Pas de code voyage** → Génération automatique (DESTINATION-ANNEE)
6. ✅ **Chemins de réponse non optimisés** → 16 chemins identifiés et gérés

### Objectifs

- Générer **exactement** le JSON attendu par la DB
- **1-3 steps/jour minimum** avec GPS + images Supabase
- **Code voyage unique** généré automatiquement
- **Support complet** de tous les chemins du questionnaire (destination yes/no, services variés)

---

## 🤖 AGENTS (7 au lieu de 13)

### 1. Trip Context Builder
**Remplace**: input_sanity_guardian + persona_inference_orchestrator
**Rôle**: Extraire et structurer toutes les infos du questionnaire + persona
**Output**: `trip_context` (structure complète avec tous les champs)

### 2. Destination Strategist
**Remplace**: destination_scout + destination_decision_maker
**Rôle**:
- Si `has_destination=yes` : Valider et enrichir (GPS, météo)
- Si `has_destination=no` : Proposer 3-5 options et choisir la meilleure
**Output**: `destination_choice` (code, nom, GPS, météo, style)

### 3. Flights Specialist
**Garde**: flight_pricing_analyst (amélioré)
**Rôle**: Rechercher vols via MCP (airports.nearest, flights.prices)
**Output**: `flight_quotes` (origine, destination, prix, durée)

### 4. Accommodation Specialist
**Garde**: lodging_pricing_analyst (amélioré)
**Rôle**: Rechercher hébergements via MCP (booking.search, places.overview)
**Output**: `lodging_quotes` (nom, note, prix, quartier)

### 5. Itinerary Designer ⭐ **CŒUR DE LA PIPELINE**
**Améliore**: activities_geo_designer
**Rôle**:
- Concevoir **1-3 steps/jour minimum**
- Appeler `geo.text_to_place` pour **CHAQUE step** (GPS obligatoire)
- Appeler `images.hero` UNE fois + `images.background` pour CHAQUE step
- Copier URLs Supabase (validation stricte, rejet URLs externes)
**Output**: `itinerary_plan` (hero_image + steps complètes)

### 6. Budget Calculator
**Simplifie**: budget_consistency_controller + system_contract_validator
**Rôle**: Calculer budget total et vérifier cohérence
**Output**: `budget_summary` (vols + hôtel + activités + transport)

### 7. Final Assembler 🆕 **AGENT INTELLIGENT**
**Remplace**: trip_yaml_assembler.py (script)
**Rôle**:
- **Consolider** tous les outputs
- **Générer** le JSON final conforme au schéma Trip
- **Valider** chaque step (GPS + images Supabase)
- **Générer** le code voyage unique
- **Calculer** summary_stats (4-8 items)
**Output**: `trip` (JSON final prêt pour DB)

---

## 🗺️ TÂCHES ET CHEMINS DE RÉPONSE

### Task 1: Trip Context Building
**Input**: questionnaire + persona_inference
**Output**: `trip_context`

**Extraction de**:
- Destination (has_destination yes/no)
- Dates (fixed/flexible/no_dates)
- Voyageurs (solo/duo/group35/family)
- Budget (amount, currency, type)
- Services (help_with: flights/accommodation/activities)
- Préférences (rhythm, styles, mobility)
- Contraintes (allergies, handicap, etc.)
- Préférences vols (departure_location, flight_preference, luggage)
- Préférences hébergement (type, confort, quartier, équipements)

### Task 2: Destination Strategy
**Input**: trip_context
**Output**: `destination_choice`

**CAS A** (has_destination=yes):
- Valider avec `geo.text_to_place(query="Tokyo")`
- Enrichir avec `places.overview(query="Tokyo")`
- Générer code voyage (ex: "TOKYO-2025")

**CAS B** (has_destination=no):
- Proposer 3-5 destinations avec scores
- Choisir la meilleure (score le plus élevé)
- Générer code voyage pour destination choisie

### Task 3: Flights Research (conditionnelle)
**Condition**: `help_with` inclut "flights"
**Input**: trip_context + destination_choice
**Output**: `flight_quotes`

- Identifier aéroports avec `airports.nearest`
- Rechercher vols avec `flights.prices`
- Respecter flight_preference (direct/1_escale/flexible)

### Task 4: Accommodation Research (conditionnelle)
**Condition**: `help_with` inclut "accommodation"
**Input**: trip_context + destination_choice
**Output**: `lodging_quotes`

- Valider destination avec `places.overview`
- Rechercher hébergements avec `booking.search`
- Filtrer par type, confort, quartier, équipements

### Task 5: Itinerary Design (conditionnelle)
**Condition**: `help_with` inclut "activities"
**Input**: trip_context + destination_choice
**Output**: `itinerary_plan`

**PROCESSUS OBLIGATOIRE**:
1. Appeler `images.hero` UNE fois → copier URL dans `hero_image`
2. Pour CHAQUE step:
   - Appeler `geo.text_to_place` → copier latitude/longitude
   - Appeler `images.background` → copier URL dans `main_image`
3. Ajouter step récapitulative avec `is_summary: true` + `summary_stats`

**RÈGLES CRITIQUES**:
- ✅ 1-3 steps/jour (adapter selon rhythm)
- ✅ GPS obligatoire (sauf transport/récap)
- ✅ URLs Supabase obligatoires (commencent par `https://xznsdvvfqoztlqtqhkhv.supabase.co/storage/v1/object/public/TRIPS/`)
- ❌ JAMAIS d'URLs Wikipedia, Unsplash ou externes

### Task 6: Budget Calculation
**Input**: trip_context + flight_quotes + lodging_quotes + itinerary_plan
**Output**: `budget_summary`

- Calculer total (vols + hôtel + activités + transport local)
- Comparer avec budget utilisateur
- Proposer ajustements si dépassement > 15%

### Task 7: Final Assembly
**Input**: TOUS les outputs précédents
**Output**: `trip` (JSON final)

**VALIDATIONS CRITIQUES**:
- ✅ Code voyage valide (pattern: ^[A-Z][A-Z0-9-]{2,19}$)
- ✅ Champs obligatoires présents (code, destination, total_days, steps)
- ✅ TOUTES les steps ont step_number, day_number, title, main_image
- ✅ TOUTES les main_image commencent par l'URL Supabase
- ✅ TOUTES les steps ont GPS (sauf transport/récap)
- ✅ AU MOINS une step avec is_summary: true
- ✅ summary_stats contient 4-8 items

---

## 🔧 MODIFICATIONS PIPELINE.PY

### Changements principaux

#### 1. Méthode `_derive_trip_intent` (lignes 158-202)
**Garder tel quel** → Cette méthode analyse déjà `help_with` et `has_destination`

#### 2. Méthode `run` - Section agents (lignes 293-304)
**REMPLACER** par :

```python
# Agents nécessaires
context_builder = self._create_agent("trip_context_builder", agents_config["trip_context_builder"], tools=[])
strategist = self._create_agent("destination_strategist", agents_config["destination_strategist"], tools=mcp_tools)
flight_specialist = self._create_agent("flights_specialist", agents_config["flights_specialist"], tools=mcp_tools)
accommodation_specialist = self._create_agent("accommodation_specialist", agents_config["accommodation_specialist"], tools=mcp_tools)
itinerary_designer = self._create_agent("itinerary_designer", agents_config["itinerary_designer"], tools=mcp_tools)
budget_calculator = self._create_agent("budget_calculator", agents_config["budget_calculator"], tools=[])
final_assembler = self._create_agent("final_assembler", agents_config["final_assembler"], tools=[])
```

#### 3. Méthode `run` - Phase 1 (lignes 306-330)
**REMPLACER** par :

```python
# 4. Phase 1 - Context + Strategy
task1 = Task(name="trip_context_building", agent=context_builder, **tasks_config["trip_context_building"])
task2 = Task(name="destination_strategy", agent=strategist, context=[task1], **tasks_config["destination_strategy"])

crew_phase1 = self._crew_builder(
    agents=[context_builder, strategist],
    tasks=[task1, task2],
    verbose=self._verbose,
    process=Process.sequential,
)

inputs_phase1 = {
    "questionnaire": questionnaire_yaml,
    "persona_context": persona_yaml,
    "current_year": datetime.now().year,
}

output_phase1 = crew_phase1.kickoff(inputs=inputs_phase1)
tasks_phase1, parsed_phase1 = self._collect_tasks_output(output_phase1, should_save, run_dir, phase_label="PHASE1_CONTEXT")

trip_context = parsed_phase1.get("trip_context_building", {}).get("trip_context", {})
destination_choice = parsed_phase1.get("destination_strategy", {}).get("destination_choice", {})
trip_intent = self._derive_trip_intent(normalized_questionnaire, trip_context)
```

#### 4. Méthode `run` - Phase 2 (lignes 346-418)
**REMPLACER** par :

```python
# 5. Phase 2 - Research (conditionnelle selon help_with)
phase2_tasks: List[Task] = []
phase2_agents: List[Agent] = []

# Convertir trip_context en YAML pour prompts
trip_context_yaml = yaml.dump(trip_context, allow_unicode=True, sort_keys=False)
destination_choice_yaml = yaml.dump(destination_choice, allow_unicode=True, sort_keys=False)

# Extraire dates validées
departure_dates = trip_context.get("dates", {}).get("departure_date") or trip_context.get("dates", {}).get("departure_window", {}).get("start") or "Non spécifiée"
return_dates = trip_context.get("dates", {}).get("return_date") or trip_context.get("dates", {}).get("return_window", {}).get("end") or "Non spécifiée"

inputs_phase2 = {
    "trip_context": trip_context_yaml,
    "destination_choice": destination_choice_yaml,
    "current_year": datetime.now().year,
    "validated_departure_dates": departure_dates,
    "validated_return_dates": return_dates,
}

flight_task: Optional[Task] = None
lodging_task: Optional[Task] = None
itinerary_task: Optional[Task] = None

if trip_intent.assist_flights:
    flight_task = Task(name="flights_research", agent=flight_specialist, **tasks_config["flights_research"])
    phase2_tasks.append(flight_task)
    phase2_agents.append(flight_specialist)

if trip_intent.assist_accommodation:
    lodging_task = Task(name="accommodation_research", agent=accommodation_specialist, **tasks_config["accommodation_research"])
    phase2_tasks.append(lodging_task)
    phase2_agents.append(accommodation_specialist)

if trip_intent.assist_activities:
    itinerary_task = Task(name="itinerary_design", agent=itinerary_designer, **tasks_config["itinerary_design"])
    phase2_tasks.append(itinerary_task)
    phase2_agents.append(itinerary_designer)

# Lancer Phase 2 seulement si au moins un service demandé
parsed_phase2 = {}
if phase2_tasks:
    crew_phase2 = self._crew_builder(
        agents=phase2_agents,
        tasks=phase2_tasks,
        verbose=self._verbose,
        process=Process.sequential,
    )
    output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
    tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_RESEARCH")
else:
    tasks_phase2 = []
```

#### 5. Méthode `run` - Phase 3 (lignes 419-451)
**REMPLACER** par :

```python
# 6. Phase 3 - Budget + Assembly
budget_task = Task(name="budget_calculation", agent=budget_calculator, **tasks_config["budget_calculation"])
final_task = Task(name="final_assembly", agent=final_assembler, context=[budget_task], **tasks_config["final_assembly"])

crew_phase3 = self._crew_builder(
    agents=[budget_calculator, final_assembler],
    tasks=[budget_task, final_task],
    verbose=self._verbose,
    process=Process.sequential,
)

# Convertir outputs en YAML pour prompts
flight_quotes_yaml = yaml.dump(parsed_phase2.get("flights_research", {}).get("flight_quotes", {}), allow_unicode=True, sort_keys=False)
lodging_quotes_yaml = yaml.dump(parsed_phase2.get("accommodation_research", {}).get("lodging_quotes", {}), allow_unicode=True, sort_keys=False)
itinerary_plan_yaml = yaml.dump(parsed_phase2.get("itinerary_design", {}).get("itinerary_plan", {}), allow_unicode=True, sort_keys=False)

inputs_phase3 = {
    "trip_context": trip_context_yaml,
    "destination_choice": destination_choice_yaml,
    "flight_quotes": flight_quotes_yaml,
    "lodging_quotes": lodging_quotes_yaml,
    "itinerary_plan": itinerary_plan_yaml,
}

output_phase3 = crew_phase3.kickoff(inputs=inputs_phase3)
tasks_phase3, parsed_phase3 = self._collect_tasks_output(output_phase3, should_save, run_dir, phase_label="PHASE3_ASSEMBLY")

# Extraire le JSON final
trip_payload = parsed_phase3.get("final_assembly", {})
```

#### 6. Méthode `run` - Validation et Persistence (lignes 452-525)
**REMPLACER** la section d'assemblage par :

```python
# 7. Validation Schema
is_valid, schema_error = False, "No trip payload generated"
if "trip" in trip_payload and isinstance(trip_payload.get("trip"), dict):
    is_valid, schema_error = validate_trip_schema(trip_payload.get("trip", {}))
elif "error" in trip_payload:
    schema_error = trip_payload.get("error_message", "Agent returned error")

# Suite identique (persistence, etc.)
```

#### 7. Supprimer les méthodes obsolètes
**Supprimer**:
- Section "System Contract Draft" (lignes 332-343)
- Importations inutiles (`build_system_contract`, `normalize_questionnaire` si plus utilisé dans run())

---

## 🔄 FLUX D'EXÉCUTION

### Schéma complet

```
Input (questionnaire + persona)
    ↓
┌─────────────────────────────────────────┐
│ PHASE 1: CONTEXT & STRATEGY             │
├─────────────────────────────────────────┤
│ 1. Trip Context Builder                 │
│    → Extrait tout du questionnaire      │
│ 2. Destination Strategist               │
│    → CAS A: Valide destination fournie  │
│    → CAS B: Propose et choisit          │
└─────────────────────────────────────────┘
    ↓
    trip_context + destination_choice
    ↓
┌─────────────────────────────────────────┐
│ PHASE 2: RESEARCH (conditionnelle)      │
├─────────────────────────────────────────┤
│ 3. Flights Specialist (si demandé)      │
│ 4. Accommodation Specialist (si demandé)│
│ 5. Itinerary Designer (si demandé) ⭐    │
│    → 1-3 steps/jour avec GPS + images   │
└─────────────────────────────────────────┘
    ↓
    flight_quotes + lodging_quotes + itinerary_plan
    ↓
┌─────────────────────────────────────────┐
│ PHASE 3: BUDGET & ASSEMBLY              │
├─────────────────────────────────────────┤
│ 6. Budget Calculator                    │
│    → Calcule et vérifie cohérence       │
│ 7. Final Assembler ⭐                    │
│    → Génère JSON final                  │
│    → Valide GPS + images Supabase       │
│    → Génère code voyage                 │
└─────────────────────────────────────────┘
    ↓
    trip (JSON final)
    ↓
Validation Schema + Insertion DB
```

### Durée estimée

- Phase 1 (Context + Strategy): ~2-3 min
- Phase 2 (Research): ~5-8 min (selon services)
- Phase 3 (Budget + Assembly): ~2-3 min
- **Total**: ~10-15 min (selon complexité)

---

## ✨ POINTS CLÉS

### 1. Réduction drastique de complexité
- **Avant**: 13 agents, 3 phases, beaucoup de redondance
- **Après**: 7 agents, 3 phases, chaque agent a un rôle clair

### 2. Focus sur le JSON final
- Agent Final Assembler dédié (remplace script assembler)
- Validations strictes à chaque étape
- Rejet des steps invalides (URLs externes, GPS manquante)

### 3. Support complet des chemins
- 16 chemins identifiés (destination yes/no × services variés)
- Agents activés conditionnellement selon `help_with`
- Gestion gracieuse si services non demandés

### 4. Qualité des données
- GPS obligatoire pour toutes les steps (sauf transport/récap)
- Images Supabase obligatoires (validation stricte)
- Code voyage généré automatiquement (DESTINATION-ANNEE)
- Summary stats calculées automatiquement (4-8 items)

### 5. Performance
- Moins d'agents = moins de temps d'exécution
- Agents conditionnels = pas de travail inutile
- MCP tools utilisés intelligemment (geo, images, booking, flights)

---

## 📝 EXEMPLE DE RUN

### Input
```yaml
questionnaire:
  has_destination: "yes"
  destination: "Tokyo, Japon 🇯🇵"
  help_with: ["flights", "activities"]  # PAS accommodation
  dates_type: "fixed"
  departure_date: "2025-12-15"
  return_date: "2025-12-22"
  travel_group: "duo"
  travelers_count: 2
  budget_amount: 3000
  budget_currency: "EUR"
  rhythm: "balanced"
  styles: ["Culture", "Gastronomie"]
```

### Output (simplifié)
```yaml
trip:
  code: "TOKYO-2025"
  destination: "Tokyo, Japon 🇯🇵"
  total_days: 7
  main_image: "https://xznsdvvfqoztlqtqhkhv.supabase.co/storage/v1/object/public/TRIPS/tokyo-2025-abc123/hero_1733155800.jpg"

  flight_from: "Bruxelles"
  flight_to: "Tokyo"
  flight_duration: "12h30"
  flight_type: "Vol direct"

  # Pas de hotel_name/hotel_rating car accommodation non demandé

  total_price: "3 200€"
  total_budget: "3 000€"

  steps:
    - step_number: 1
      day_number: 1
      title: "Shibuya Crossing"
      main_image: "https://xznsdvvfqoztlqtqhkhv.supabase.co/storage/v1/object/public/TRIPS/tokyo-2025-abc123/background_1733155900.jpg"
      latitude: 35.6595
      longitude: 139.7004
      price: 0
      why: "..."
      tips: "..."

    # [...] 2 steps par jour × 7 jours = 14 steps

    - step_number: 15
      day_number: 7
      title: "Résumé du voyage"
      is_summary: true
      main_image: "https://xznsdvvfqoztlqtqhkhv.supabase.co/storage/v1/object/public/TRIPS/tokyo-2025-abc123/hero_1733155800.jpg"
      summary_stats:
        - type: days
          value: 7
        - type: budget
          value: "3 200€"
        # [...]
```

---

## 🚦 STATUT DE L'IMPLÉMENTATION

- ✅ **agents.yaml** : Créé (7 agents)
- ✅ **tasks.yaml** : Créé (7 tâches complètes)
- ⚠️ **pipeline.py** : Modifications à appliquer (voir section ci-dessus)
- ⏳ **Tests** : À réaliser après modifications pipeline.py

---

## 📚 FICHIERS MODIFIÉS

1. `app/crew_pipeline/config/agents.yaml` - RÉÉCRIT COMPLÈTEMENT
2. `app/crew_pipeline/config/tasks.yaml` - RÉÉCRIT COMPLÈTEMENT
3. `app/crew_pipeline/pipeline.py` - MODIFICATIONS À APPLIQUER
4. `app/crew_pipeline/scripts/trip_yaml_assembler.py` - **OBSOLÈTE** (remplacé par agent final_assembler)

---

## 🎯 PROCHAINES ÉTAPES

1. **Modifier pipeline.py** selon instructions ci-dessus
2. **Tester avec questionnaire has_destination=yes + tous services**
3. **Tester avec questionnaire has_destination=no + tous services**
4. **Tester avec questionnaire services partiels** (ex: flights seulement)
5. **Vérifier logs** pour s'assurer que images.hero et images.background retournent bien URLs Supabase
6. **Valider le JSON final** dans Supabase (insertion réussie)

---

**🎉 Cette nouvelle architecture garantit la génération du JSON final attendu avec 1-3 steps/jour, GPS obligatoire, images Supabase, code voyage unique, et support de tous les chemins du questionnaire !**
