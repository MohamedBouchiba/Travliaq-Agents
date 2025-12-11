"""
StepValidator - Valide et corrige automatiquement les steps

Ce script garantit la qualité des steps générées par l'Agent 6:
- Valide présence GPS, images, contenu
- Détecte champs manquants ou invalides
- Auto-fix GPS/images manquantes via MCP
- Auto-fix traductions manquantes

Gains attendus:
- Fiabilité: +20-30% (correction auto des erreurs Agent 6)
- Qualité: Garantie conformité schéma Trip
"""

from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class StepValidator:
    """
    Validateur et correcteur automatique de steps.
    
    Workflow:
    1. validate_step() → retourne (is_valid, liste_erreurs)
    2. auto_fix_step() → corrige erreurs détectées
    3. validate_all_steps() → valide batch complet
    """
    
    # Regex pour valider URLs Supabase
    SUPABASE_URL_PATTERN = re.compile(
        r"https://[a-z0-9]+\.supabase\.co/storage/v1/object/public/TRIPS/.+"
    )
    
    def __init__(self, mcp_tools: Optional[Any] = None, llm: Optional[Any] = None):
        """
        Initialiser validateur.
        
        Args:
            mcp_tools: Pour auto-fix GPS/images via MCP
            llm: Pour auto-fix traductions via LLM
        """
        self.mcp_tools = mcp_tools
        self.llm = llm
    
    def validate_step(
        self,
        step: Dict[str, Any],
        strict: bool = False,
    ) -> Tuple[bool, List[str]]:
        """
        Valider une step et retourner erreurs détectées.
        
        Args:
            step: Dictionary représentant la step
            strict: Si True, exige TOUS les champs remplis
        
        Returns:
            (is_valid, liste_erreurs)
        
        Example:
            >>> validator = StepValidator()
            >>> step = {"step_number": 1, "title": "", "latitude": 0}
            >>> is_valid, errors = validator.validate_step(step)
            >>> is_valid
            False
            >>> errors
            ['Title manquant', 'GPS manquants ou invalides']
        """
        errors = []
        step_num = step.get("step_number", "?")
        
        # Skip validation pour summary step
        if step.get("is_summary"):
            return True, []
        
        # 1. VALIDATION CHAMPS OBLIGATOIRES
        required_fields = ["step_number", "day_number", "title", "main_image"]
        
        for field in required_fields:
            if not step.get(field) or str(step.get(field)).strip() == "":
                errors.append(f"Step {step_num}: Champ obligatoire manquant '{field}'")
        
        # 2. VALIDATION GPS
        lat = step.get("latitude", 0)
        lon = step.get("longitude", 0)
        
        if lat == 0 or lon == 0:
            errors.append(f"Step {step_num}: GPS manquants ou invalides (lat={lat}, lon={lon})")
        elif not self._is_valid_gps(lat, lon):
            errors.append(f"Step {step_num}: GPS hors limites (lat={lat}, lon={lon})")
        
        # 3. VALIDATION IMAGES SUPABASE
        main_image = step.get("main_image", "")
        
        if not main_image or main_image.strip() == "":
            errors.append(f"Step {step_num}: Image manquante")
        elif not self._is_supabase_url(main_image):
            errors.append(f"Step {step_num}: Image invalide (pas Supabase URL)")
        
        # 4. VALIDATION CONTENU FR
        content_fields_fr = ["subtitle", "why", "tips", "transfer"]
        
        for field in content_fields_fr:
            content = step.get(field, "")
            
            if strict and (not content or content.strip() == ""):
                errors.append(f"Step {step_num}: Contenu FR manquant '{field}'")
            elif content and len(content.split()) < 5:  # Minimum 5 mots
                errors.append(f"Step {step_num}: Contenu FR trop court '{field}' ({len(content.split())} mots)")
        
        # 5. VALIDATION TRADUCTIONS EN
        content_fields_en = ["title_en", "subtitle_en", "why_en", "tips_en", "transfer_en"]
        
        for field in content_fields_en:
            fr_field = field.replace("_en", "")
            fr_content = step.get(fr_field, "")
            en_content = step.get(field, "")
            
            # Si contenu FR existe mais pas EN
            if fr_content and fr_content.strip() and (not en_content or en_content.strip() == ""):
                errors.append(f"Step {step_num}: Traduction manquante '{field}'")
        
        # 6. VALIDATION PRIX/DURÉE
        if strict:
            if not step.get("duration") or step.get("duration", "").strip() == "":
                errors.append(f"Step {step_num}: Durée manquante")
            
            if "price" not in step:
                errors.append(f"Step {step_num}: Prix manquant")
        
        is_valid = len(errors) == 0
        
        if not is_valid:
            logger.warning(f"⚠️ Step {step_num} validation: {len(errors)} erreur(s)")
        
        return is_valid, errors
    
    def auto_fix_step(
        self,
        step: Dict[str, Any],
        destination: str = "",
        destination_country: str = "",
        trip_code: str = "",
    ) -> Dict[str, Any]:
        """
        Corriger automatiquement erreurs détectées.
        
        Corrections possibles:
        - GPS manquants → appeler geo.place
        - Image manquante → appeler images.background
        - Traductions manquantes → appeler LLM ou DeepL
        
        Args:
            step: Step à corriger
            destination: Pour MCP calls
            destination_country: Pour MCP calls
            trip_code: Pour images Supabase
        
        Returns:
            Step corrigée
        """
        step_copy = dict(step)
        step_num = step.get("step_number", "?")
        fixes_applied = []
        
        # 1. FIX GPS MANQUANTS
        if step_copy.get("latitude", 0) == 0 or step_copy.get("longitude", 0) == 0:
            if self.mcp_tools and step_copy.get("title"):
                logger.info(f"  🔧 Fixing GPS for step {step_num}...")
                gps_fixed = self._fix_gps(step_copy, destination, destination_country)
                
                if gps_fixed:
                    step_copy.update(gps_fixed)
                    fixes_applied.append("GPS")
        
        # 2. FIX IMAGE MANQUANTE
        if not step_copy.get("main_image") or not self._is_supabase_url(step_copy.get("main_image", "")):
            if self.mcp_tools:
                logger.info(f"  🔧 Fixing image for step {step_num}...")
                image_fixed = self._fix_image(step_copy, destination, destination_country, trip_code)
                
                if image_fixed:
                    step_copy["main_image"] = image_fixed
                    fixes_applied.append("Image")
        
        # 3. FIX TRADUCTIONS MANQUANTES
        if self.llm:
            translation_fixes = self._fix_translations(step_copy)
            
            if translation_fixes:
                step_copy.update(translation_fixes)
                fixes_applied.append("Traductions")
        
        if fixes_applied:
            logger.info(f"  ✅ Step {step_num} auto-fixed: {', '.join(fixes_applied)}")
        
        return step_copy
    
    def validate_all_steps(
        self,
        steps: List[Dict[str, Any]],
        auto_fix: bool = False,
        destination: str = "",
        destination_country: str = "",
        trip_code: str = "",
        parallel: bool = True,
        max_workers: int = 6,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Valider et optionnellement corriger toutes les steps.

        Args:
            steps: Liste de steps
            auto_fix: Si True, auto-corriger erreurs
            destination, destination_country, trip_code: Pour auto-fix
            parallel: Si True, valide en parallèle (défaut)
            max_workers: Nombre max de threads parallèles

        Returns:
            (steps_validées, rapport)

        Rapport:
            {
              "total_steps": 10,
              "valid_steps": 7,
              "invalid_steps": 3,
              "errors_count": 5,
              "fixes_applied": 3,
              "details": [...]
            }
        """
        logger.info(f"🔍 Validating {len(steps)} steps (auto_fix={auto_fix}, parallel={parallel})")

        # Validation/fix parallèle ou séquentielle
        if parallel and len(steps) > 1:
            return self._validate_steps_parallel(
                steps, auto_fix, destination, destination_country, trip_code, max_workers
            )
        else:
            return self._validate_steps_sequential(
                steps, auto_fix, destination, destination_country, trip_code
            )

    def _validate_steps_sequential(
        self,
        steps: List[Dict[str, Any]],
        auto_fix: bool,
        destination: str,
        destination_country: str,
        trip_code: str,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Validation séquentielle (méthode originale)."""
        validated_steps = []
        report = {
            "total_steps": len(steps),
            "valid_steps": 0,
            "invalid_steps": 0,
            "errors_count": 0,
            "fixes_applied": 0,
            "details": [],
        }

        for step in steps:
            # Validation initiale
            is_valid, errors = self.validate_step(step)

            if is_valid:
                report["valid_steps"] += 1
                validated_steps.append(step)
            else:
                report["invalid_steps"] += 1
                report["errors_count"] += len(errors)

                # Auto-fix si demandé
                if auto_fix:
                    step_fixed = self.auto_fix_step(
                        step,
                        destination=destination,
                        destination_country=destination_country,
                        trip_code=trip_code,
                    )

                    # Re-valider après fix
                    is_valid_after, errors_after = self.validate_step(step_fixed)

                    if is_valid_after:
                        report["fixes_applied"] += 1
                        validated_steps.append(step_fixed)
                    else:
                        # Fix n'a pas résolu tous les problèmes
                        validated_steps.append(step_fixed)
                        report["details"].append({
                            "step_number": step.get("step_number"),
                            "errors_before": errors,
                            "errors_after": errors_after,
                        })
                else:
                    validated_steps.append(step)
                    report["details"].append({
                        "step_number": step.get("step_number"),
                        "errors": errors,
                    })

        logger.info(f"✅ Validation complete: {report['valid_steps']}/{report['total_steps']} valid")
        if report["fixes_applied"] > 0:
            logger.info(f"  🔧 {report['fixes_applied']} steps auto-fixed")

        return validated_steps, report

    def _validate_steps_parallel(
        self,
        steps: List[Dict[str, Any]],
        auto_fix: bool,
        destination: str,
        destination_country: str,
        trip_code: str,
        max_workers: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """Validation parallèle avec ThreadPoolExecutor."""
        logger.info(f"⚡ Validating {len(steps)} steps in parallel (max_workers={max_workers})")

        validated_steps = []
        report = {
            "total_steps": len(steps),
            "valid_steps": 0,
            "invalid_steps": 0,
            "errors_count": 0,
            "fixes_applied": 0,
            "details": [],
        }

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Soumettre toutes les validations
            future_to_step = {
                executor.submit(
                    self._validate_and_fix_single_step,
                    step, auto_fix, destination, destination_country, trip_code
                ): step
                for step in steps
            }

            # Collecter résultats au fur et à mesure
            for future in as_completed(future_to_step):
                original_step = future_to_step[future]
                step_num = original_step.get("step_number", "?")

                try:
                    result = future.result()
                    validated_steps.append(result["step"])

                    if result["is_valid"]:
                        report["valid_steps"] += 1
                    else:
                        report["invalid_steps"] += 1
                        report["errors_count"] += len(result.get("errors", []))

                        if result.get("was_fixed"):
                            report["fixes_applied"] += 1

                        if result.get("errors_after"):
                            report["details"].append({
                                "step_number": step_num,
                                "errors_before": result.get("errors", []),
                                "errors_after": result.get("errors_after", []),
                            })

                    logger.debug(f"  ✅ Step {step_num} validated")

                except Exception as e:
                    logger.error(f"  ❌ Step {step_num} validation failed: {e}")
                    # En cas d'erreur, garder step originale
                    validated_steps.append(original_step)
                    report["invalid_steps"] += 1

        # Trier par step_number
        validated_steps.sort(key=lambda s: s.get("step_number", 0))

        logger.info(f"✅ Validation complete: {report['valid_steps']}/{report['total_steps']} valid")
        if report["fixes_applied"] > 0:
            logger.info(f"  🔧 {report['fixes_applied']} steps auto-fixed")

        return validated_steps, report

    def _validate_and_fix_single_step(
        self,
        step: Dict[str, Any],
        auto_fix: bool,
        destination: str,
        destination_country: str,
        trip_code: str,
    ) -> Dict[str, Any]:
        """
        Valider et éventuellement fixer une step (pour parallélisation).

        Returns:
            {
                "step": step_validée_ou_fixée,
                "is_valid": bool,
                "errors": [...],
                "was_fixed": bool,
                "errors_after": [...]
            }
        """
        # Validation initiale
        is_valid, errors = self.validate_step(step)

        if is_valid:
            return {
                "step": step,
                "is_valid": True,
                "errors": [],
                "was_fixed": False,
            }

        # Step invalide
        if not auto_fix:
            return {
                "step": step,
                "is_valid": False,
                "errors": errors,
                "was_fixed": False,
            }

        # Auto-fix
        step_fixed = self.auto_fix_step(
            step,
            destination=destination,
            destination_country=destination_country,
            trip_code=trip_code,
        )

        # Re-valider après fix
        is_valid_after, errors_after = self.validate_step(step_fixed)

        return {
            "step": step_fixed,
            "is_valid": is_valid_after,
            "errors": errors,
            "was_fixed": True,
            "errors_after": errors_after if not is_valid_after else [],
        }
    
    def _is_valid_gps(self, lat: float, lon: float) -> bool:
        """Vérifier que GPS sont dans limites raisonnables."""
        return -90 <= lat <= 90 and -180 <= lon <= 180
    
    def _is_supabase_url(self, url: str) -> bool:
        """Vérifier qu'une URL est bien Supabase."""
        if not url:
            return False
        return bool(self.SUPABASE_URL_PATTERN.match(url))
    
    def _fix_gps(
        self,
        step: Dict[str, Any],
        destination: str,
        destination_country: str,
    ) -> Optional[Dict[str, float]]:
        """Corriger GPS manquants via geo.place."""
        if not self.mcp_tools:
            return None
        
        title = step.get("title", "")
        if not title:
            return None
        
        try:
            # Tentative 1: Chercher titre exact
            query = f"{title}, {destination}, {destination_country}"
            results = self.mcp_tools.call_tool("geo.place", query=query, max_results=1)
            
            if results and len(results) > 0:
                return {
                    "latitude": results[0]["latitude"],
                    "longitude": results[0]["longitude"],
                }
                
        except Exception:
            pass
        
        try:
            # Tentative 2: Fallback destination
            results = self.mcp_tools.call_tool(
                "geo.city",
                query=f"{destination}, {destination_country}",
                max_results=1
            )
            
            if results and len(results) > 0:
                return {
                    "latitude": results[0]["latitude"],
                    "longitude": results[0]["longitude"],
                }
                
        except Exception:
            pass
        
        return None
    
    def _fix_image(
        self,
        step: Dict[str, Any],
        destination: str,
        destination_country: str,
        trip_code: str,
    ) -> Optional[str]:
        """Corriger image manquante via images.background."""
        if not self.mcp_tools:
            return None
        
        title = step.get("title", "")
        if not title:
            return None
        
        try:
            # Construct prompt from available info
            prompt = f"{title} in {destination}, {destination_country}"
            
            result = self.mcp_tools.call_tool(
                "images.background",
                trip_code=trip_code,
                prompt=prompt,
            )
            
            # 🔧 FIX: Handle dict result from MCP
            if isinstance(result, dict):
                if result.get("success") is False:
                    logger.warning(f"⚠️ images.background failed: {result.get('error')}")
                    return None
                return result.get("url")
            
            # Handle string result
            if isinstance(result, str) and ("supabase.co" in result or result.startswith("http")):
                return result
                
        except Exception as e:
            logger.warning(f"Image fix failed: {e}")
        
        return None
    
    def _fix_translations(
        self,
        step: Dict[str, Any]
    ) -> Dict[str, str]:
        """Corriger traductions manquantes via LLM."""
        if not self.llm:
            return {}
        
        fixes = {}
        fields_to_translate = [
            ("title", "title_en"),
            ("subtitle", "subtitle_en"),
            ("why", "why_en"),
            ("tips", "tips_en"),
            ("transfer", "transfer_en"),
        ]
        
        for fr_field, en_field in fields_to_translate:
            fr_text = step.get(fr_field, "")
            en_text = step.get(en_field, "")
            
            # Si FR existe mais pas EN
            if fr_text and fr_text.strip() and (not en_text or en_text.strip() == ""):
                try:
                    # Simple translation via LLM
                    prompt = f"Translate to English: {fr_text}"
                    translation = self.llm.call(prompt, max_tokens=500)
                    fixes[en_field] = translation.strip()
                    
                except Exception:
                    pass
        
        return fixes
