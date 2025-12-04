# Patch: Intégration Scripts dans pipeline.py

## Modification 1: Ajout des Imports (Ligne ~18)

**Localisation:** Après `from .scripts.incremental_trip_builder import IncrementalTripBuilder`

**À ajouter:**

```python
from .scripts.incremental_trip_builder import IncrementalTripBuilder
from .scripts.step_template_generator import StepTemplateGenerator  # NOUVEAU
from .scripts.translation_service import TranslationService  # NOUVEAU
from .scripts.step_validator import StepValidator  # NOUVEAU
```

---

## Modification 2: Intégration StepTemplateGenerator (Ligne ~440)

**Localisation:** Après `output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)` et avant `self._enrich_builder_from_phase2`

**Code existant (ligne ~439-444):**

```python
output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_RESEARCH")

# 🆕 ENRICHISSEMENT: Mettre à jour le builder avec les résultats de PHASE2
logger.info("🔧 Enrichissement du trip JSON avec les résultats de PHASE2...")
self._enrich_builder_from_phase2(builder, parsed_phase2)
```

**REMPLACER PAR:**

```python
output_phase2 = crew_phase2.kickoff(inputs=inputs_phase2)
tasks_phase2, parsed_phase2 = self._collect_tasks_output(output_phase2, should_save, run_dir, phase_label="PHASE2_RESEARCH")

# 🆕 SCRIPT 1: Générer templates de steps (GPS + images pré-remplies)
if "plan_trip_structure" in parsed_phase2 and trip_intent.assist_activities:
    logger.info("🏗️ Generating step templates with GPS and images...")

    trip_structure_plan = parsed_phase2["plan_trip_structure"].get("structural_plan", {})

    if trip_structure_plan and trip_structure_plan.get("daily_distribution"):
        try:
            # Initialiser générateur
            step_template_generator = StepTemplateGenerator(mcp_tools=mcp_tools)

            # Générer templates
            step_templates = step_template_generator.generate_templates(
                trip_structure_plan=trip_structure_plan,
                destination=destination,
                destination_country=destination_country or "",
                trip_code=builder.trip_json["code"],
            )

            logger.info(f"✅ {len(step_templates)} step templates generated with GPS and images")

            # Enrichir builder avec templates (optionnel - pour enrichissement immédiat)
            for template in step_templates:
                if not template.get("is_summary"):
                    step_num = template.get("step_number")
                    if step_num:
                        builder.set_step_gps(
                            step_number=step_num,
                            latitude=template.get("latitude", 0),
                            longitude=template.get("longitude", 0),
                        )
                        if template.get("main_image"):
                            builder.set_step_image(
                                step_number=step_num,
                                image_url=template.get("main_image"),
                            )
                        if template.get("step_type"):
                            builder.set_step_type(
                                step_number=step_num,
                                step_type=template.get("step_type"),
                            )

            logger.info("✅ Builder enriched with GPS and images from templates")

        except Exception as e:
            logger.error(f"❌ StepTemplateGenerator failed: {e}")
            logger.warning("⚠️ Continuing without templates, Agent 6 will generate from scratch")
    else:
        logger.warning("⚠️ No trip_structure_plan found, skipping template generation")

# 🆕 ENRICHISSEMENT: Mettre à jour le builder avec les résultats de PHASE2
logger.info("🔧 Enrichissement du trip JSON avec les résultats de PHASE2...")
self._enrich_builder_from_phase2(builder, parsed_phase2)
```

---

## Modification 3: Intégration TranslationService (Ligne ~445)

**Localisation:** Après `self._enrich_builder_from_phase2(builder, parsed_phase2)`

**Code existant (ligne ~444-445):**

```python
self._enrich_builder_from_phase2(builder, parsed_phase2)

# 6. Phase 3 - Budget + Assembly
```

**INSÉRER ENTRE les deux:**

```python
self._enrich_builder_from_phase2(builder, parsed_phase2)

# 🆕 SCRIPT 2: Traduire contenu FR → EN
if trip_intent.assist_activities:
    logger.info("🌍 Translating itinerary content FR → EN...")

    # Récupérer steps depuis builder
    current_trip = builder.trip_json
    steps_to_translate = current_trip.get("steps", [])

    if steps_to_translate:
        try:
            # Initialiser service de traduction
            translation_service = TranslationService(llm=self._llm)

            # Traduire toutes les steps
            translated_steps = translation_service.translate_steps(steps_to_translate)

            # Mettre à jour le builder avec steps traduites
            for step in translated_steps:
                step_num = step.get("step_number")

                if step_num and step_num != 99:  # Skip summary
                    builder.set_step_title(
                        step_number=step_num,
                        title=step.get("title", ""),
                        title_en=step.get("title_en", ""),
                        subtitle=step.get("subtitle", ""),
                        subtitle_en=step.get("subtitle_en", ""),
                    )

                    builder.set_step_content(
                        step_number=step_num,
                        why=step.get("why", ""),
                        why_en=step.get("why_en", ""),
                        tips=step.get("tips", ""),
                        tips_en=step.get("tips_en", ""),
                        transfer=step.get("transfer", ""),
                        transfer_en=step.get("transfer_en", ""),
                        suggestion=step.get("suggestion", ""),
                        suggestion_en=step.get("suggestion_en", ""),
                    )

                    # Météo si disponible
                    if step.get("weather_description_en"):
                        builder.set_step_weather(
                            step_number=step_num,
                            icon=step.get("weather_icon", ""),
                            temp=step.get("weather_temp", ""),
                            description=step.get("weather_description", ""),
                            description_en=step.get("weather_description_en", ""),
                        )

            logger.info(f"✅ {len(translated_steps)} steps translated FR → EN")

        except Exception as e:
            logger.error(f"❌ TranslationService failed: {e}")
            logger.warning("⚠️ Continuing without translations")
    else:
        logger.warning("⚠️ No steps found for translation")

# 6. Phase 3 - Budget + Assembly
```

---

## Modification 4: Intégration StepValidator (Ligne ~446)

**Localisation:** Juste après TranslationService, avant Phase 3

**Code existant (ligne ~446):**

```python
# 6. Phase 3 - Budget + Assembly
budget_task = Task(name="budget_calculation", agent=budget_calculator, **tasks_config["budget_calculation"])
```

**INSÉRER AVANT:**

```python
# 🆕 SCRIPT 3: Valider et corriger steps automatiquement
if trip_intent.assist_activities:
    logger.info("🔍 Validating all steps...")

    # Récupérer steps depuis builder
    current_trip = builder.trip_json
    steps_to_validate = current_trip.get("steps", [])

    if steps_to_validate:
        try:
            # Initialiser validateur
            validator = StepValidator(mcp_tools=mcp_tools, llm=self._llm)

            # Valider et auto-fix
            validated_steps, validation_report = validator.validate_all_steps(
                steps=steps_to_validate,
                auto_fix=True,  # Auto-correction activée
                destination=destination,
                destination_country=destination_country or "",
                trip_code=current_trip.get("code", ""),
            )

            # Logger rapport
            logger.info(
                f"✅ Validation: {validation_report['valid_steps']}/{validation_report['total_steps']} valid, "
                f"{validation_report['fixes_applied']} auto-fixed"
            )

            if validation_report["invalid_steps"] > 0:
                logger.warning(f"⚠️ {validation_report['invalid_steps']} steps still invalid after auto-fix")
                for detail in validation_report.get("details", []):
                    logger.warning(f"  Step {detail.get('step_number')}: {detail.get('errors_after', detail.get('errors', []))}")

            # Remplacer steps dans builder par versions validées
            builder.trip_json["steps"] = validated_steps

            logger.info("✅ Steps validation complete, builder updated")

        except Exception as e:
            logger.error(f"❌ StepValidator failed: {e}")
            logger.warning("⚠️ Continuing without validation")
    else:
        logger.warning("⚠️ No steps to validate")

# 6. Phase 3 - Budget + Assembly
budget_task = Task(name="budget_calculation", agent=budget_calculator, **tasks_config["budget_calculation"])
```

---

## Résumé des Modifications

| #   | Ligne | Type   | Description                                                                  |
| --- | ----- | ------ | ---------------------------------------------------------------------------- |
| 1   | ~18   | Import | Ajouter 3 imports (StepTemplateGenerator, TranslationService, StepValidator) |
| 2   | ~440  | Insert | StepTemplateGenerator (40 lignes)                                            |
| 3   | ~445  | Insert | TranslationService (45 lignes)                                               |
| 4   | ~446  | Insert | StepValidator (40 lignes)                                                    |

**Total:** ~125 lignes ajoutées

---

## Application du Patch

### Option A: Copier-Coller Manuel

1. Ouvrir `e:/CrewTravliaq/Travliaq-Agents/app/crew_pipeline/pipeline.py`
2. Trouver ligne 18 → Ajouter imports
3. Trouver ligne 440 (après `kickoff`) → Insérer StepTemplateGenerator
4. Trouver ligne 445 (après `_enrich_builder_from_phase2`) → Insérer TranslationService
5. Trouver ligne 446 (avant Phase 3) → Insérer StepValidator
6. Sauvegarder

### Option B: Utiliser ce Guide

1. Chercher chaque "Code existant" dans le fichier
2. Remplacer/Insérer selon instructions
3. Vérifier indentation (4 espaces)
4. Sauvegarder

---

## Vérification Post-Patch

### Test 1: Imports

```python
python -c "from app.crew_pipeline.scripts.step_template_generator import StepTemplateGenerator; print('OK')"
python -c "from app.crew_pipeline.scripts.translation_service import TranslationService; print('OK')"
python -c "from app.crew_pipeline.scripts.step_validator import StepValidator; print('OK')"
```

### Test 2: Syntaxe

```bash
python -m py_compile app/crew_pipeline/pipeline.py
```

### Test 3: Run Pipeline

```bash
python crew_pipeline_cli.py --questionnaire-id <ID>
```

**Vérifier logs pour:**

- `🏗️ Generating step templates`
- `✅ X step templates generated`
- `🌍 Translating itinerary content`
- `✅ X steps translated`
- `🔍 Validating all steps`
- `✅ Validation: X/Y valid`

---

## Rollback (si besoin)

Si problème, restaurer version originale:

```bash
git checkout app/crew_pipeline/pipeline.py
```

Ou supprimer les 3 sections ajoutées manuellement.
