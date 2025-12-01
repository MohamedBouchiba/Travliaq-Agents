# Plan Pipeline CrewAI + Scripts Python pour générer les trips Travliaq

Objectif : livrer un **plan complet Agents/Tasks/Tools/Scripts** pour transformer un questionnaire Travliaq en **JSON final conforme au schéma “Travliaq Trip”** (Draft-07), avec suffisamment d’agents, un vrai mix CrewAI + scripts Python, et des garde-fous anti-hallucination.

---

## 1) Entrées, sorties, principes anti-hallucination
- **Entrée brute** : réponse du questionnaire (JSON Supabase).
- **Normalisation déterministe (scripts)** :
  - Validation Zod/JSON Schema côté Python, formats ISO (dates), montants numériques, arrays triés/dédupliqués.
  - Calculs sûrs : nuits exactes, budget total estimé, détecteur d’incohérences (budget vs durée, bagages vs vols, enfants vs mobilité).
- **Contextes injectés** :
  - `persona_context` produit par **`app/services/persona_inference_service.py`** (Persona Inference Service).
  - Référentiels MCP : macro-personas, guides destination/saison/budget, valeurs internes (codes FR/EN), exigences sécurité.
- **Sorties** :
  - Phase 1 : `normalized_trip_request.yaml`.
  - Phase 2 : `system_contract.yaml` (pacte anti-hallucination).
  - Phase 3 : `travliaq_trip.yaml` (section `trip`) → converti en JSON pour l’insertion base (via `supabase_service`).

---

## 2) Agents CrewAI élargis (12 agents) et outils MCP/locaux
| Agent | Rôle | Outils MCP/locaux recommandés | Délivrable |
| --- | --- | --- | --- |
| **Input Sanity & Schema Guardian** | Vérifie/normalise les champs questionnaire, remonte les warnings bloquants. | `read_questionnaire_values`, `read_trip_schema` | `input_payload.yaml` propre + log d’erreurs bloquantes |
| **Persona Inference Orchestrator** | Pilote l’appel au script Python Persona Inference Service, enrichit le contexte. | `python:app/services/persona_inference_service.py` | `persona_context.yaml` (top personas, confiance, incertitudes) |
| **Traveller Insights Analyst** | Synthèse narrative du profil, motivations, contraintes cachées. | `read_les_macro_personas`, `read_questionnaire_values` | `traveller_profile_brief.yaml` |
| **Persona Quality Challenger** | Challenge la cohérence (budget/saison/rythme) et les biais, marque les trous d’info. | `read_guide_tourisme`, `read_le_secteur_touristique`, `read_budget_guidelines` | `persona_challenge_review.yaml` |
| **Trip Specifications Architect** | Formalise la demande structurée (`normalized_trip_request.yaml`) avec valeurs null quand inconnues. | `read_trip_schema`, `read_questionnaire_values` | `normalized_trip_request.yaml` |
| **System Contract Validator** | Renforce le contrat anti-hallucination (règles budget, sécurité, min images). | `read_trip_schema`, `read_safety_requirements`, `read_budget_guidelines` | `system_contract.yaml` (sections verrouillées, check-list) |
| **Destination Scout** | Génère 4–5 destinations scorées (saison, budget, sécurité, affinités). | `search_destinations`, `read_climate_database`, `read_travel_advisories` | `destination_slate.yaml` (options, scores, risques) |
| **Flight Pricing Analyst** | Estime vols/bagages/temps de trajet pour chaque option. | `search_flights`, `read_luggage_policies` | `flight_quotes.yaml` |
| **Lodging Pricing Analyst** | Estime hébergements (type, confort, quartier/équipements), note faisabilité budget. | `search_hotels`, `read_quarter_tags` | `lodging_quotes.yaml` |
| **Activities & Geo Designer** | Conçoit les steps (1–3/jour) avec lat/lon, images, why/tips/transfer. | `search_pois`, `search_images`, `read_local_transport` | `activities_plan.yaml` |
| **Budget & Consistency Controller** | Vérifie alignement budget total vs vols/hôtels/activités, propose arbitrages. | `read_budget_guidelines`, outputs vols/hôtels/activités | `budget_alignment_report.yaml` |
| **Destination Decision Maker** | Choisit l’option finale, fixe `total_budget`/`total_price`, pré-sélectionne `summary_stats`. | `read_trip_schema`, outputs précédents | `final_destination_choice.yaml` |
| **Feasibility & Safety Expert** | Gate final (visa, météo, sécurité). Bloque si critique. | `read_safety_requirements`, `read_travel_advisories`, `read_climate_database` | `feasibility_gate.yaml` |

**Principe** : si un outil est indisponible, l’agent **documente l’absence** et positionne les champs dépendants à `null` pour éviter toute hallucination.

---

## 3) Scripts Python indispensables dans la pipeline
- **`app/services/persona_inference_service.py`** : inférence persona et signaux (déjà existant, piloté par l’agent Persona Inference Orchestrator).
- **`app/services/supabase_service.py`** : insertion finale du JSON dans la base (à appeler après validation schéma).
- **Nouveaux scripts à prévoir** :
  - `app/crew_pipeline/scripts/normalize_questionnaire.py` (T0) : validation/normalisation, calculs déterministes (nuits exactes, budget estimé, flags incohérences).
  - `app/crew_pipeline/scripts/system_contract_builder.py` (T4) : génère le contrat système à partir de la spécification + règles anti-hallucination.
  - `app/crew_pipeline/scripts/trip_yaml_assembler.py` (T11) : assemble et valide le YAML final (`trip`), ajoute step summary et convertit en JSON prêt pour Supabase.
  - `app/crew_pipeline/scripts/schema_validator.py` (T11 bis) : validation JSON Schema Draft-07 du YAML produit.

---

## 4) Tasks hiérarchiques (séquence complète, 12 étapes + gates)
1. **T0 – Sanity & Normalization (script)**
   - Inputs : questionnaire brut.
   - Actions : validation schéma, ISO dates, calcul nuits/budget, flags incohérences.
   - Output : `input_payload.yaml` + `sanity_report` (bloquant si erreurs critiques).
2. **T1 – Persona Inference (script + agent)**
   - Script : `persona_inference_service.py` → `persona_context.yaml`.
   - Agent (Persona Inference Orchestrator) : relit/simplifie les signaux clefs.
3. **T2 – Traveller Profile Brief (agent)**
   - Output : `traveller_profile_brief.yaml` (motivations, contraintes, langage).
4. **T3 – Persona Challenge Review (agent)**
   - Output : `persona_challenge_review.yaml` (risques budget/saison, trous d’info).
5. **T4 – Trip Specifications Design (agent)**
   - Output : `normalized_trip_request.yaml` (toutes valeurs null si inconnues, pas d’invention).
6. **T5 – System Contract Build (script) + Validation (agent)**
   - Script génère le contrat de règles ; agent System Contract Validator ajoute check-list et garde-fous.
7. **T6 – Destination Scouting (agent)**
   - Output : `destination_slate.yaml` (4–5 options, scores, météo, risques, budget).
8. **T7 – Pricing & Activities Layer (agents parallèles)**
   - **T7a Flight Pricing Analyst** → `flight_quotes.yaml`.
   - **T7b Lodging Pricing Analyst** → `lodging_quotes.yaml`.
   - **T7c Activities & Geo Designer** → `activities_plan.yaml` (avec images/lat-lon obligatoires par step).
9. **T8 – Budget & Consistency Control (agent)**
   - Vérifie cohérence vols+hôtels+activités vs budget ; propose arbitrages (réduction nuits, downgrade confort, changer hub aéroport).
   - Output : `budget_alignment_report.yaml` (bloquant si hors tolérance >15%).
10. **T9 – Destination Decision (agent)**
    - Choix final + calcul `total_budget`, `total_price`, pré-sélection `summary_stats` (4–8 stats).
    - Output : `final_destination_choice.yaml`.
11. **T10 – Feasibility & Safety Gate (agent)**
    - Bloque si visa impossible/météo extrême/alerte sécurité rouge.
    - Output : `feasibility_gate.yaml` (status OK/WARN/CRITICAL).
12. **T11 – Assembly & Validation (scripts)**
    - `trip_yaml_assembler.py` : fusionne tous les artefacts en `travliaq_trip.yaml` (section `trip`).
    - `schema_validator.py` : valide avec le JSON Schema Draft-07 ; si échec ⇒ stop.
    - Conversion JSON + appel `supabase_service.py` pour persister.

---

## 5) Règles de production du YAML/JSON final
- Respect strict du schéma Draft-07 ; tout champ incertain = `null` ou omis s’il est optionnel.
- **Steps** :
  - `main_image` obligatoire ; `images` peut être vide.
  - `is_summary=true` ⇒ `summary_stats` (4–8) obligatoire, alterner turquoise/golden recommandé.
  - Cohérence `step_number`/`day_number` (pas de doublons).
- **Budgets/Prix** : totaux en string avec devise ; `price` (step) en nombre ou `null`.
- **Multilingue** : champs `_en` remplis seulement si source fiable ; sinon `null`.
- **Traçabilité** : chaque agent doit mentionner les outils et sources MCP utilisés dans son fichier (champ `sources:` ou bloc commenté).
- **Fail-safe** : si un bloc est incomplet (ex : vols manquants), l’assembler place `null` + note dans `sanity_report` et **n’invente rien**.

---

## 6) Exemple d’assemblage (squelette minimal, à compléter par la pipeline)
```yaml
trip:
  code: "DEST2026"
  destination: "Doha, Qatar"
  destination_en: "Doha, Qatar"
  total_days: 21
  main_image: null
  flight_from: "Bruxelles (BRU)"
  flight_to: "Doha (DOH)"
  flight_duration: "6h30"
  flight_type: "1 escale"
  hotel_name: null
  hotel_rating: null
  total_price: null
  total_budget: "900-1 200€"
  start_date: "2026-01-08"
  travelers: 1
  steps:
    - step_number: 1
      day_number: 1
      title: "Arrivée et check-in"
      main_image: "https://.../arrival.jpg"
      step_type: "arrivée"
      is_summary: false
    - step_number: 2
      day_number: 21
      title: "Résumé du voyage"
      main_image: "https://.../summary.jpg"
      is_summary: true
      summary_stats:
        - {type: "days", value: 21}
        - {type: "budget", value: "900-1 200€"}
        - {type: "people", value: 1}
        - {type: "style", value: "Culture & Food"}
```

---

## 7) Mise en œuvre pratique (fichiers et séquencement)
1. Définir les agents dans `app/crew_pipeline/config/agents.yaml` avec les couples (rôle/outils) listés ci-dessus.
2. Définir les tasks dans `app/crew_pipeline/config/tasks.yaml` en suivant l’ID T0–T11.
3. Scripts :
   - `normalize_questionnaire.py` → lancé avant toute exécution CrewAI (T0).
   - `persona_inference_service.py` → appelé par l’agent T1.
   - `system_contract_builder.py` → T5 (script), puis validation par agent.
   - `trip_yaml_assembler.py` + `schema_validator.py` → T11 pour construire/valider le YAML/JSON final.
   - `supabase_service.py` → persistance après validation.
4. Exécution : séquentiel strict ; si un gate (T0, T8, T10, T11) échoue, on stoppe et retourne le rapport d’erreurs.

Ce plan fournit la granularité d’agents, de tasks, d’outils MCP et de scripts Python nécessaires pour architecturer la pipeline et sortir un JSON final conforme, insérable en base, sans hallucination.
