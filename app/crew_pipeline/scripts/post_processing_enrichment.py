"""
Post-Processing Enrichment Script

Exécuté APRÈS l'Agent 6 (Itinerary Designer) pour :
1. Régénérer les images avec des prompts enrichis (basés sur title + why)
2. Traduire automatiquement tous les champs FR → EN via translate_en

Avantages :
- Images de meilleure qualité (prompts riches vs génériques)
- Traduction automatique (agent se concentre sur contenu FR)
- Performance : batch processing des MCP calls
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from app.crew_pipeline.scripts.image_generator import ImageGenerator

logger = logging.getLogger(__name__)


class PostProcessingEnricher:
    """
    Enrichit les steps après génération du contenu par l'Agent 6.

    Workflow:
    1. Agent 6 crée le contenu FR (title, why, tips)
    2. Ce script régénère les images avec prompts enrichis
    3. Ce script traduit automatiquement FR → EN
    4. Résultat : steps complètes avec images de qualité et traduction parfaite
    """

    def __init__(self, mcp_tools: Any):
        """
        Initialiser avec accès aux outils MCP.

        Args:
            mcp_tools: Instance MCPToolManager avec accès à images.*, translate_en, etc.
        """
        self.mcp_tools = mcp_tools
        self.image_generator = ImageGenerator(mcp_tools)

    def enrich_trip(
        self,
        trip_json: Dict[str, Any],
        regenerate_images: bool = True,
        translate_fields: bool = True,
        parallel: bool = True,
        max_workers: int = 6,
    ) -> Dict[str, Any]:
        """
        Enrichir un trip complet avec images améliorées et traductions.

        Args:
            trip_json: Trip JSON avec steps remplies par Agent 6
            regenerate_images: Si True, régénère les images avec prompts enrichis
            translate_fields: Si True, traduit automatiquement FR → EN
            parallel: Si True, enrichit en parallèle (défaut)
            max_workers: Nombre max de threads parallèles

        Returns:
            Trip JSON enrichi
        """
        logger.info(f"🎨 Starting post-processing enrichment (parallel={parallel})...")

        if not isinstance(trip_json, dict) or "steps" not in trip_json:
            logger.error("❌ Invalid trip_json structure")
            return trip_json

        steps = trip_json["steps"]
        trip_code = trip_json.get("code", "")
        destination = trip_json.get("destination", "")

        # Séparer summary steps et steps normales
        summary_steps = [s for s in steps if s.get("is_summary")]
        normal_steps = [s for s in steps if not s.get("is_summary")]

        if not normal_steps:
            logger.info("✅ No steps to enrich (only summary)")
            return trip_json

        # Enrichissement parallèle ou séquentiel
        if parallel and len(normal_steps) > 1:
            enriched_normal = self._enrich_steps_parallel(
                normal_steps, trip_code, destination, regenerate_images, translate_fields, max_workers
            )
        else:
            enriched_normal = self._enrich_steps_sequential(
                normal_steps, trip_code, destination, regenerate_images, translate_fields
            )

        # Remplacer steps dans trip_json
        trip_json["steps"] = summary_steps + enriched_normal
        trip_json["steps"].sort(key=lambda s: s.get("step_number", 0))

        enriched_count = len([s for s in enriched_normal if s.get("_enriched")])
        logger.info(f"✅ Post-processing complete: {enriched_count}/{len(normal_steps)} steps enriched")

        return trip_json

    def _enrich_steps_sequential(
        self,
        steps: List[Dict[str, Any]],
        trip_code: str,
        destination: str,
        regenerate_images: bool,
        translate_fields: bool,
    ) -> List[Dict[str, Any]]:
        """Enrichissement séquentiel (méthode originale)."""
        enriched_steps = []

        for step in steps:
            step_number = step.get("step_number")

            try:
                # 1. Régénérer image avec prompt enrichi
                if regenerate_images:
                    new_image_url = self._regenerate_step_image(
                        step=step,
                        trip_code=trip_code,
                        destination=destination,
                    )
                    if new_image_url:
                        step["main_image"] = new_image_url
                        logger.debug(f"  ✅ Step {step_number}: Image regenerated")

                # 2. Traduire champs FR → EN
                if translate_fields:
                    self._translate_step_fields(step)
                    logger.debug(f"  ✅ Step {step_number}: Fields translated")

                step["_enriched"] = True
                enriched_steps.append(step)

            except Exception as e:
                logger.warning(f"  ⚠️ Step {step_number} enrichment failed: {e}")
                enriched_steps.append(step)

        return enriched_steps

    def _enrich_steps_parallel(
        self,
        steps: List[Dict[str, Any]],
        trip_code: str,
        destination: str,
        regenerate_images: bool,
        translate_fields: bool,
        max_workers: int,
    ) -> List[Dict[str, Any]]:
        """Enrichissement parallèle avec ThreadPoolExecutor."""
        logger.info(f"⚡ Enriching {len(steps)} steps in parallel (max_workers={max_workers})")

        enriched_steps = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Soumettre tous les enrichissements
            future_to_step = {
                executor.submit(
                    self._enrich_single_step,
                    step, trip_code, destination, regenerate_images, translate_fields
                ): step
                for step in steps
            }

            # Collecter résultats au fur et à mesure
            for future in as_completed(future_to_step):
                original_step = future_to_step[future]
                step_num = original_step.get("step_number", "?")

                try:
                    enriched_step = future.result()
                    enriched_steps.append(enriched_step)
                    logger.debug(f"  ✅ Step {step_num} enriched")
                except Exception as e:
                    logger.error(f"  ❌ Step {step_num} enrichment failed: {e}")
                    # En cas d'erreur, garder step originale
                    enriched_steps.append(original_step)

        # Trier par step_number
        enriched_steps.sort(key=lambda s: s.get("step_number", 0))

        return enriched_steps

    def _enrich_single_step(
        self,
        step: Dict[str, Any],
        trip_code: str,
        destination: str,
        regenerate_images: bool,
        translate_fields: bool,
    ) -> Dict[str, Any]:
        """
        Enrichir une step (pour parallélisation).

        Returns:
            Step enrichie
        """
        step_copy = dict(step)

        # 1. Régénérer image avec prompt enrichi
        if regenerate_images:
            new_image_url = self._regenerate_step_image(
                step=step_copy,
                trip_code=trip_code,
                destination=destination,
            )
            if new_image_url:
                step_copy["main_image"] = new_image_url

        # 2. Traduire champs FR → EN
        if translate_fields:
            self._translate_step_fields(step_copy)

        step_copy["_enriched"] = True
        return step_copy

    def _regenerate_step_image(
        self,
        step: Dict[str, Any],
        trip_code: str,
        destination: str,
    ) -> Optional[str]:
        """
        Régénérer l'image d'une step avec un prompt enrichi.

        Stratégie:
        - Utilise title + why pour créer un prompt descriptif riche
        - Meilleure qualité d'image que les prompts génériques

        Args:
            step: Step data avec title, why, etc.
            trip_code: Code du trip (pour folder Supabase)
            destination: Destination du voyage

        Returns:
            URL de la nouvelle image ou None si échec
        """
        # Construire prompt enrichi depuis le contenu
        title = step.get("title", "")
        why = step.get("why", "")
        subtitle = step.get("subtitle", "")

        # Créer prompt riche (max 150 chars pour éviter surcharge)
        if why:
            # Utiliser why (description détaillée) + destination
            prompt_parts = [
                title,
                why[:100],  # Première partie de why
                destination
            ]
            prompt = " ".join(filter(None, prompt_parts))[:150]
        elif subtitle:
            # Fallback sur subtitle + title
            prompt = f"{title} {subtitle} in {destination}"[:150]
        else:
            # Fallback minimal
            prompt = f"{title} in {destination}"[:150]

        logger.debug(f"    🖼️ Regenerating image with enriched prompt: '{prompt[:80]}...'")

        return self.image_generator.generate_image(
            prompt=prompt,
            trip_code=trip_code,
            image_type="background"
        )



    def _translate_step_fields(self, step: Dict[str, Any]) -> None:
        """
        Traduire automatiquement les champs FR → EN d'une step.

        Champs traduits:
        - title → title_en
        - subtitle → subtitle_en
        - why → why_en
        - tips → tips_en
        - transfer → transfer_en
        - suggestion → suggestion_en

        Args:
            step: Step data à enrichir (modifié in-place)
        """
        fields_to_translate = [
            ("title", "title_en"),
            ("subtitle", "subtitle_en"),
            ("why", "why_en"),
            ("tips", "tips_en"),
            ("transfer", "transfer_en"),
            ("suggestion", "suggestion_en"),
        ]

        for fr_field, en_field in fields_to_translate:
            fr_text = step.get(fr_field, "")
            en_text = step.get(en_field, "")

            # Traduire si :
            # - Le champ FR est non vide
            # - ET (le champ EN est vide OU identique au FR)
            if fr_text and (not en_text or en_text == fr_text):
                try:
                    translation = self._call_translate_en(fr_text)
                    if translation:
                        step[en_field] = translation
                        logger.debug(f"      Translated {fr_field}: '{fr_text[:30]}...' → '{translation[:30]}...'")
                except Exception as e:
                    logger.warning(f"      ⚠️ Translation failed for {fr_field}: {e}")
                    # En cas d'échec, copier FR → EN (fallback)
                    step[en_field] = fr_text

    def _call_translate_en(self, text: str) -> Optional[str]:
        """
        Appeler le tool MCP translate_en pour traduire FR → EN.

        Args:
            text: Texte en français à traduire

        Returns:
            Texte traduit en anglais ou None si échec
        """
        if not text or len(text.strip()) == 0:
            return None

        try:
            result = self.mcp_tools.call_tool(
                "translate_en",
                text=text,
            )

            # Handle different response formats
            if isinstance(result, str):
                return result.strip()
            elif isinstance(result, dict) and "translation" in result:
                return result["translation"].strip()
            elif isinstance(result, dict) and "text" in result:
                return result["text"].strip()
            else:
                logger.warning(f"      ⚠️ translate_en returned unexpected format: {type(result)}")
                return None

        except Exception as e:
            logger.warning(f"      ⚠️ translate_en call failed: {e}")
            return None
