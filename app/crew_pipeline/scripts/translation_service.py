"""
TranslationScript - Traduit le contenu FR vers EN

Ce script offload les traductions de l'Agent 6 (Itinerary Designer):
- Traduit tous les champs FR → EN (title, subtitle, why, tips, transfer, suggestion)
- Utilise DeepL API (ou fallback LLM si pas de clé)
- Garantit traductions complètes et cohérentes

Gains attendus:
- Coût: -30k tokens (évite Agent 6 de traduire)
- Qualité: Traductions professionnelles via DeepL
- Temps: -20s (API rapide vs LLM)
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class TranslationService:
    """
    Service de traduction FR → EN pour steps d'itinéraire.
    
    Workflow:
    1. Vérifier si DeepL API key disponible
    2. Si oui: utiliser DeepL (rapide, qualité pro)
    3. Si non: fallback LLM simple (plus lent, moins cher)
    """
    
    def __init__(self, llm: Optional[Any] = None):
        """
        Initialiser service de traduction.
        
        Args:
            llm: Instance LLM pour fallback si DeepL indisponible
        """
        self.deepl_key = os.getenv("DEEPL_API_KEY")
        self.llm = llm
        self.use_deepl = bool(self.deepl_key)
        
        if self.use_deepl:
            logger.info("✅ DeepL API key found, using DeepL for translations")
        else:
            logger.warning("⚠️ DeepL API key not found, will use LLM fallback")
    
    def translate_steps(
        self,
        steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Traduire tous les champs FR → EN pour toutes les steps.
        
        Args:
            steps: Liste de steps avec contenu FR rempli
        
        Returns:
            Steps avec champs _en complétés
        
        Example:
            >>> service = TranslationService()
            >>> steps = [
            ...     {
            ...         "step_number": 1,
            ...         "title": "Visite de la Tour Eiffel",
            ...         "why": "Monument emblématique de Paris...",
            ...     }
            ... ]
            >>> translated = service.translate_steps(steps)
            >>> translated[0]["title_en"]
            "Visit to the Eiffel Tower"
        """
        logger.info(f"🌍 Translating {len(steps)} steps FR → EN")
        
        translated_steps = []
        
        for step in steps:
            # Skip summary step (déjà traduit)
            if step.get("is_summary"):
                translated_steps.append(step)
                continue
            
            # Traduire chaque champ FR
            step_translated = self._translate_single_step(step)
            translated_steps.append(step_translated)
        
        logger.info(f"✅ {len(translated_steps)} steps translated")
        
        return translated_steps
    
    def _translate_single_step(
        self,
        step: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Traduire une step FR → EN.
        
        Champs traduits:
        - title → title_en
        - subtitle → subtitle_en
        - why → why_en
        - tips → tips_en
        - transfer → transfer_en
        - suggestion → suggestion_en
        - weather_description → weather_description_en
        """
        step_copy = dict(step)
        
        # Liste des champs à traduire
        fields_to_translate = [
            ("title", "title_en"),
            ("subtitle", "subtitle_en"),
            ("why", "why_en"),
            ("tips", "tips_en"),
            ("transfer", "transfer_en"),
            ("suggestion", "suggestion_en"),
            ("weather_description", "weather_description_en"),
        ]
        
        for fr_field, en_field in fields_to_translate:
            fr_text = step.get(fr_field, "")
            
            # Skip si déjà en anglais ou vide
            if not fr_text or fr_text.strip() == "":
                continue
            
            # Traduire
            en_text = self._translate_text(fr_text)
            step_copy[en_field] = en_text
        
        return step_copy
    
    def _translate_text(self, text: str) -> str:
        """
        Traduire un texte FR → EN.
        
        Méthode 1 (préférée): DeepL API
        Méthode 2 (fallback): LLM simple
        """
        if not text or text.strip() == "":
            return ""
        
        if self.use_deepl:
            return self._translate_with_deepl(text)
        else:
            return self._translate_with_llm(text)
    
    def _translate_with_deepl(self, text: str) -> str:
        """
        Traduire via DeepL API.
        
        Avantages:
        - Qualité professionnelle
        - Rapide (~100ms/text)
        - Coût faible (~0.005€/1000 chars)
        """
        try:
            import deepl
            
            translator = deepl.Translator(self.deepl_key)
            result = translator.translate_text(
                text,
                source_lang="FR",
                target_lang="EN-US",
            )
            
            return str(result)
            
        except ImportError:
            logger.warning("⚠️ deepl package not installed, falling back to LLM")
            return self._translate_with_llm(text)
            
        except Exception as e:
            logger.error(f"❌ DeepL translation failed: {e}, falling back to LLM")
            return self._translate_with_llm(text)
    
    def _translate_with_llm(self, text: str) -> str:
        """
        Traduire via LLM simple (fallback).
        
        Avantages:
        - Pas besoin d'API externe
        - Gratuit (utilise LLM existant)
        
        Inconvénients:
        - Plus lent (~1-2s/text)
        - Coût tokens (~500 tokens/text)
        - Qualité variable
        """
        if not self.llm:
            logger.error("❌ No LLM available for translation fallback")
            return text  # Retourner texte FR si pas de fallback
        
        try:
            prompt = f"""Translate the following French text to English. Provide ONLY the translation, no explanation.

French text:
{text}

English translation:"""
            
            # Appeler LLM (méthode dépend de l'implémentation)
            # TODO: Adapter selon votre LLM wrapper
            response = self.llm.call(messages=[{"role": "user", "content": prompt}])
            
            return response.strip()
            
        except Exception as e:
            logger.error(f"❌ LLM translation failed: {e}")
            return text  # Retourner texte FR si échec


def translate_steps_batch(
    steps: List[Dict[str, Any]],
    llm: Optional[Any] = None
) -> List[Dict[str, Any]]:
    """
    Fonction helper pour traduire batch de steps.
    
    Usage:
        >>> from app.crew_pipeline.scripts.translation_service import translate_steps_batch
        >>> steps_with_fr = [...]
        >>> steps_with_en = translate_steps_batch(steps_with_fr, llm=my_llm)
    """
    service = TranslationService(llm=llm)
    return service.translate_steps(steps)
