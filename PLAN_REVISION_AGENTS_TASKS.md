# 📋 PLAN DE RÉVISION - Agents & Tasks

**Date** : 2025-12-05
**Objectif** : Assurer cohérence entre agents/tasks et la pipeline actuelle avec post-processing enrichment

---

## 🎯 CHANGEMENTS RÉCENTS À INTÉGRER

1. ✅ **Post-Processing Enrichment** (nouveau script)
   - Régénère images avec prompts enrichis (basés sur title + why)
   - Traduit automatiquement FR → EN via `translate_en`
   - S'exécute APRÈS Agent 6

2. ✅ **StepTemplateGenerator amélioré**
   - Pré-génère GPS via `geo.place`
   - Pré-génère images via `images.background` (génériques)
   - Valide/corrige URLs Supabase (folder matching)

3. ✅ **Duplicate Summary Steps Fix**
   - Une seule summary step (step 99)
   - IncrementalTripBuilder la crée
   - Agent 6 la remplit

---

## 📊 ANALYSE DE COHÉRENCE

### ✅ AGENTS DÉJÀ COHÉRENTS

#### Agent 1: trip_context_builder
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

#### Agent 2: destination_strategist
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

#### Agent 3: flights_specialist
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

#### Agent 4: accommodation_specialist
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

#### Agent 5: trip_structure_planner
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

#### Agent 6: itinerary_designer
- **État** : ✅ **DÉJÀ MIS À JOUR** (agents.yaml lignes 113-139)
- **Backstory actuel** :
  ```yaml
  Tu reçois des templates de steps déjà remplies avec GPS et images Supabase.
  Tu NE DOIS PAS modifier les GPS, images, ou step_type déjà remplis.
  Tu NE DOIS PAS traduire en anglais (géré par script automatique).
  Tu NE DOIS PAS appeler geo.place ou images.* (déjà fait par script).
  Focus 100% sur la qualité du contenu français.
  ```
- **Action** : **AUCUNE** (parfaitement aligné)

#### Agent 7: budget_calculator
- **État** : ✅ Cohérent
- **Raison** : Aucun changement pipeline ne l'affecte
- **Action** : **AUCUNE**

---

### ⚠️ AGENTS À MODIFIER

#### Agent 8: final_assembler

**État actuel** (agents.yaml lignes 163-182):
```yaml
role: "Trip JSON Assembler & Validator"
goal: >-
  Consolider tous les outputs des agents pour produire le JSON final conforme
  au schéma Trip. Générer le code unique, vérifier que toutes les steps ont
  GPS + images Supabase, calculer summary_stats, et valider la structure complète.
backstory: >-
  Architecte JSON expert, tu es le dernier rempart qualité. Tu consolides les
  outputs de tous les agents et tu construis le JSON final exact attendu par
  la base de données. Tu génères le code voyage unique (format: DESTINATION-ANNEE),
  tu vérifies que CHAQUE step a latitude/longitude ET main_image (URL Supabase),
  tu calcules 4-8 summary_stats pour le récapitulatif, et tu t'assures que le
  JSON respecte strictement le schéma...
```

**Problème** :
- ❌ Mentionne "vérifier que toutes les steps ont GPS + images Supabase"
- ❌ Ne mentionne PAS que les traductions EN sont automatiques
- ❌ Ne mentionne PAS le post-processing

**Modification proposée** :

**AVANT** (backstory ligne 169-177) :
```yaml
backstory: >-
  Architecte JSON expert, tu es le dernier rempart qualité. Tu consolides les
  outputs de tous les agents et tu construis le JSON final exact attendu par
  la base de données. Tu génères le code voyage unique (format: DESTINATION-ANNEE),
  tu vérifies que CHAQUE step a latitude/longitude ET main_image (URL Supabase),
  tu calcules 4-8 summary_stats pour le récapitulatif, et tu t'assures que le
  JSON respecte strictement le schéma (code, destination, total_days, steps avec
  step_number/day_number/title/main_image obligatoires). Tu ne dois JAMAIS
  laisser passer des données manquantes ou incohérentes.
```

**APRÈS** (proposition) :
```yaml
backstory: >-
  Architecte JSON expert, tu es le dernier rempart qualité. Tu consolides les
  outputs de tous les agents et tu construis le JSON final exact attendu par
  la base de données. Tu génères le code voyage unique (format: DESTINATION-ANNEE),
  tu calcules 4-8 summary_stats pour le récapitulatif, et tu t'assures que le
  JSON respecte strictement le schéma (code, destination, total_days, steps avec
  step_number/day_number/title obligatoires).

  NOTE: Les GPS, images Supabase, et traductions EN sont gérés automatiquement
  par la pipeline (templates + post-processing). Tu n'as PAS besoin de les valider.
  Focus sur la cohérence structurelle et le contenu FR.
```

**Justification** :
- Agent 8 ne doit plus se soucier des GPS/images (déjà validés par scripts)
- Agent 8 ne doit plus se soucier des traductions EN (post-processing)
- Réduit charge mentale de l'agent
- Évite redondance/confusion

---

## 📝 TASKS À MODIFIER

### ⚠️ Task: itinerary_design

**Sections déjà mises à jour** :
- ✅ Lignes 761-809 : Instructions principales (CORRECTES)
- ✅ Lignes 860-875 : Section templates (CORRECTE)
- ✅ Lignes 901-928 : Section images/traductions (CORRECTE - mise à jour récemment)
- ✅ Lignes 1260-1272 : Checklist (CORRECTE - mise à jour récemment)

**Sections à vérifier** :
- 🔍 Section "EXEMPLE COMPLET D'OUTPUT" (lignes ~1100-1280) : Vérifier cohérence

**Action proposée** : **VÉRIFICATION COMPLÈTE** de la task itinerary_design

---

### ⚠️ Task: final_assembly

**État actuel** : Probablement obsolète sur quelques points

**À vérifier** :
- Instructions sur GPS/images validation
- Instructions sur traductions EN
- Mention du post-processing

**Action proposée** : **LECTURE + PLAN** pour cette task

---

## 🎯 RÉSUMÉ DES ACTIONS

### Agents (agents.yaml)
| Agent | Action | Priorité |
|-------|--------|----------|
| 1-7 | ✅ Aucune | - |
| 8 (final_assembler) | ⚠️ Modifier backstory | HAUTE |

### Tasks (tasks.yaml)
| Task | Action | Priorité |
|------|--------|----------|
| trip_context_building | ✅ Aucune | - |
| destination_strategy | ✅ Aucune | - |
| flights_research | ✅ Aucune | - |
| accommodation_research | ✅ Aucune | - |
| plan_trip_structure | ✅ Aucune | - |
| itinerary_design | 🔍 Vérifier exemples | MOYENNE |
| budget_calculation | ✅ Aucune | - |
| final_assembly | ⚠️ Réviser instructions | HAUTE |

---

## 📋 PROCHAINES ÉTAPES

1. **VALIDATION** : User approuve les modifications proposées
2. **LECTURE** : Lire task final_assembly complète
3. **PLAN** : Créer plan détaillé pour final_assembly
4. **VALIDATION** : User approuve modifications final_assembly
5. **EXÉCUTION** : Appliquer toutes modifications approuvées
6. **TEST** : Tester pipeline end-to-end

---

## ✅ VALIDATION REQUISE

**User, es-tu d'accord avec** :

1. ✅ **Agent 8 (final_assembler)** - Modification backstory pour retirer validation GPS/images/traductions ?
   - [ ] OUI, approuvé
   - [ ] NON, à revoir
   - [ ] À DISCUTER

2. ✅ **Task final_assembly** - Lire et créer plan de modifications ?
   - [ ] OUI, procéder
   - [ ] NON, pas nécessaire
   - [ ] À DISCUTER

3. ✅ **Task itinerary_design** - Vérifier section exemples pour cohérence ?
   - [ ] OUI, vérifier
   - [ ] NON, déjà correct
   - [ ] À DISCUTER
