#!/usr/bin/env python3

import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class PersonaInference:
    persona_principal: str
    confiance: int
    niveau: str
    profils_emergents: List[Tuple[str, int]]
    caracteristiques_sures: List[str]
    incertitudes: List[str]


@dataclass
class InferenceResult:
    questionnaire_data: Dict[str, Any]
    persona_inference: PersonaInference
    recommandations: List[Dict[str, Any]]


class PersonaInferenceEngine:
    CONFIDENCE_HIGH = 85
    CONFIDENCE_MEDIUM = 70
    CONFIDENCE_LOW = 55

    def infer_persona(self, questionnaire_data: Dict[str, Any]) -> InferenceResult:
        try:
            normalized_data = self._normalize_data(questionnaire_data)
            base_persona, base_confidence = self._identify_base_persona(normalized_data)
            minor_personas = self._detect_minor_personas(normalized_data)
            global_confidence = self._calculate_global_confidence(
                normalized_data,
                base_confidence,
                minor_personas,
            )
            niveau = self._confidence_level(global_confidence)
            persona_label = self._finalize_persona_label(
                base_persona, global_confidence, minor_personas
            )
            sure_characteristics = self._extract_sure_characteristics(normalized_data)
            uncertainties = self._identify_uncertainties(normalized_data)
            recommandations = self._generate_recommandations(
                normalized_data, persona_label, minor_personas, global_confidence
            )
            persona_inference = PersonaInference(
                persona_principal=persona_label,
                confiance=global_confidence,
                niveau=niveau,
                profils_emergents=minor_personas,
                caracteristiques_sures=sure_characteristics,
                incertitudes=uncertainties,
            )
            return InferenceResult(
                questionnaire_data=normalized_data,
                persona_inference=persona_inference,
                recommandations=recommandations,
            )
        except Exception as exc:
            logger.error(f"Erreur lors de l'inférence: {exc}")
            raise

    def _normalize_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(data) if data is not None else {}

        groupe = normalized.get("groupe_voyage")
        if groupe is not None:
            normalized["travel_group"] = self._normalize_travel_group(groupe)

        if "a_destination" in normalized:
            normalized["has_destination"] = self._normalize_yes_no(
                normalized.get("a_destination")
            )

        if "a_date_depart_approximative" in normalized:
            normalized["has_approx_depart_date"] = self._normalize_yes_no(
                normalized.get("a_date_depart_approximative")
            )

        if "type_dates" in normalized:
            normalized["dates_type"] = self._normalize_dates_type(
                normalized.get("type_dates")
            )

        json_like_fields = [
            "preference_climat",
            "affinites_voyage",
            "styles",
            "mobilite",
            "mobility",
            "type_hebergement",
            "accommodation_type",
            "equipements",
            "amenities",
            "contraintes",
            "constraints",
            "securite",
            "security",
            "preferences_hotel",
            "hotel_preferences",
            "preferences_horaires",
            "schedule_prefs",
            "aide_avec",
            "help_with",
        ]
        for field in json_like_fields:
            value = normalized.get(field)
            if isinstance(value, str):
                value_stripped = value.strip()
                if value_stripped:
                    try:
                        loaded = json.loads(value_stripped)
                        normalized[field] = loaded
                    except Exception:
                        if "," in value_stripped:
                            parts = [
                                p.strip()
                                for p in value_stripped.split(",")
                                if p.strip()
                            ]
                            normalized[field] = parts

        bagages = normalized.get("bagages")
        if isinstance(bagages, dict):
            try:
                ordered = []
                for key in sorted(bagages.keys(), key=lambda x: int(x)):
                    ordered.append(bagages[key])
                normalized["bagages_list"] = ordered
            except Exception:
                normalized["bagages_list"] = list(bagages.values())
        elif isinstance(bagages, list):
            normalized["bagages_list"] = bagages
        else:
            normalized["bagages_list"] = None

        if "help_with" not in normalized and "aide_avec" in normalized:
            normalized["help_with"] = normalized.get("aide_avec")
        if "aide_avec" not in normalized and "help_with" in normalized:
            normalized["aide_avec"] = normalized.get("help_with")

        if "mobility" not in normalized and "mobilite" in normalized:
            normalized["mobility"] = normalized.get("mobilite")
        if "mobilite" not in normalized and "mobility" in normalized:
            normalized["mobilite"] = normalized.get("mobility")

        if "accommodation_type" not in normalized and "type_hebergement" in normalized:
            normalized["accommodation_type"] = normalized.get("type_hebergement")
        if "type_hebergement" not in normalized and "accommodation_type" in normalized:
            normalized["type_hebergement"] = normalized.get("accommodation_type")

        if "amenities" not in normalized and "equipements" in normalized:
            normalized["amenities"] = normalized.get("equipements")
        if "equipements" not in normalized and "amenities" in normalized:
            normalized["equipements"] = normalized.get("amenities")

        if "constraints" not in normalized and "contraintes" in normalized:
            normalized["constraints"] = normalized.get("contraintes")
        if "contraintes" not in normalized and "constraints" in normalized:
            normalized["contraintes"] = normalized.get("constraints")

        if "security" not in normalized and "securite" in normalized:
            normalized["security"] = normalized.get("securite")
        if "securite" not in normalized and "security" in normalized:
            normalized["securite"] = normalized.get("security")

        if "schedule_prefs" not in normalized and "preferences_horaires" in normalized:
            normalized["schedule_prefs"] = normalized.get("preferences_horaires")
        if "preferences_horaires" not in normalized and "schedule_prefs" in normalized:
            normalized["preferences_horaires"] = normalized.get("schedule_prefs")

        return normalized

    def _normalize_travel_group(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).lower()
        if text in {"solo", "duo", "group35", "family"}:
            return text
        if "solo" in text or "seul" in text:
            return "solo"
        if "duo" in text or "couple" in text:
            return "duo"
        if "famille" in text or "family" in text:
            return "family"
        if "ami" in text or "friends" in text or "groupe" in text or "group 3-5" in text:
            return "group35"
        if "business" in text or "affaires" in text or "travail" in text:
            return "business"
        return text

    def _normalize_yes_no(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).lower().strip()
        if text in {"yes", "oui", "y"}:
            return "yes"
        if text in {"no", "non", "n"}:
            return "no"
        return text

    def _normalize_dates_type(self, value: Any) -> Optional[str]:
        if value is None:
            return None
        text = str(value).lower().strip()
        if "fix" in text:
            return "fixed"
        if "flex" in text:
            return "flexible"
        return text

    def _ensure_list(self, value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, str):
            value_stripped = value.strip()
            if not value_stripped:
                return []
            try:
                loaded = json.loads(value_stripped)
                if isinstance(loaded, list):
                    return loaded
                return [loaded]
            except Exception:
                return [value]
        return [value]

    def _lower_list(self, value: Any) -> List[str]:
        base_list = self._ensure_list(value)
        return [str(v).lower() for v in base_list]

    def _concat_lower(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, list):
            return " ".join(str(v).lower() for v in value)
        return str(value).lower()

    def _has_keyword_in_list(self, value: Any, keywords: List[str]) -> bool:
        if not keywords:
            return False
        items = self._lower_list(value)
        for item in items:
            for k in keywords:
                if k in item:
                    return True
        return False

    def _has_keyword_in_text(self, value: Any, keywords: List[str]) -> bool:
        if not keywords:
            return False
        text = self._concat_lower(value)
        return any(k in text for k in keywords)

    def _identify_base_persona(self, data: Dict[str, Any]) -> Tuple[str, int]:
        travel_group = data.get("travel_group")
        children = data.get("enfants") or data.get("children")
        budget_value = (
            data.get("budget_par_personne")
            or data.get("montant_budget")
            or data.get("budget_amount")
        )
        budget_segment = self._detect_budget_segment(budget_value)

        label = "Voyageur loisirs"
        confidence = 60

        has_children = False
        if isinstance(children, list) and len(children) > 0:
            has_children = True
        elif isinstance(children, int) and children > 0:
            has_children = True

        if travel_group == "family" and has_children:
            label = "Famille avec enfants"
            confidence = 95
        elif travel_group == "family":
            label = "Famille"
            confidence = 90
        elif travel_group == "solo":
            label = "Voyageur solo"
            confidence = 90
        elif travel_group == "duo":
            if has_children:
                label = "Couple avec enfants"
                confidence = 90
            else:
                label = "Couple"
                confidence = 92
        elif travel_group in {"group35", "friends", "group"}:
            label = "Groupe d'amis"
            confidence = 90
        elif travel_group == "business":
            label = "Voyageur d'affaires"
            confidence = 90

        ambiance = data.get("ambiance_voyage") or ""
        ambiance_lower = str(ambiance).lower()
        if (
            ("romant" in ambiance_lower or "intim" in ambiance_lower)
            and travel_group == "duo"
            and not has_children
        ):
            label = "Couple romantique"
            confidence = max(confidence, 93)

        if budget_segment == "luxe":
            label = f"{label} - Segment luxe"
            confidence = max(confidence, 88)
        elif budget_segment == "budget":
            label = f"{label} - Budget-conscient"
            confidence = max(confidence, 85)

        help_with = data.get("aide_avec") or data.get("help_with") or []
        help_with_list = self._ensure_list(help_with)
        help_set = {str(h) for h in help_with_list}

        if help_set == {"activities"} and travel_group in {"solo", "duo"}:
            label = f"{label} orienté expériences"
        elif help_set == {"flights"}:
            label = f"{label} autonome sur place"
        elif help_set == {"accommodation"}:
            label = f"{label} centré hébergement"
        elif {"flights", "accommodation", "activities"}.issubset(help_set):
            label = f"{label} accompagné de bout en bout"

        return label, confidence

    def _detect_budget_segment(self, budget_value: Any) -> Optional[str]:
        if not budget_value:
            return None
        text = str(budget_value).lower()

        if ">" in text or "plus de" in text or "supérieur à" in text:
            return "luxe"

        digits: List[int] = []
        current = ""
        for ch in text:
            if ch.isdigit():
                current += ch
            else:
                if current:
                    digits.append(int(current))
                    current = ""
        if current:
            digits.append(int(current))

        if not digits:
            return None

        if len(digits) == 1:
            amount = digits[0]
        else:
            amount = sum(digits) / len(digits)

        if amount <= 400:
            return "budget"
        if amount >= 1200:
            return "luxe"
        return "mid"

    def _extract_duration_nights(self, data: Dict[str, Any]) -> Optional[int]:
        exact = data.get("nuits_exactes") or data.get("exact_nights")
        if isinstance(exact, int):
            return exact

        duree = data.get("duree") or data.get("duration")
        if not duree:
            return None
        text = str(duree).lower()

        digits: List[int] = []
        current = ""
        for ch in text:
            if ch.isdigit():
                current += ch
            else:
                if current:
                    digits.append(int(current))
                    current = ""
        if current:
            digits.append(int(current))
        if digits:
            return digits[0]
        return None

    def _extract_children_count(self, data: Dict[str, Any]) -> int:
        enfants = data.get("enfants") or data.get("children")
        if isinstance(enfants, list):
            return len(enfants)
        if isinstance(enfants, int):
            return enfants
        return 0

    def _extract_flex_days(self, data: Dict[str, Any]) -> Optional[int]:
        flex = data.get("flexibilite") or data.get("flexibility")
        if not flex:
            return None
        text = str(flex)
        digits: List[int] = []
        current = ""
        for ch in text:
            if ch.isdigit():
                current += ch
            else:
                if current:
                    digits.append(int(current))
                    current = ""
        if current:
            digits.append(int(current))
        if not digits:
            return None
        return max(digits)

    def _check_digital_nomad(self, data: Dict[str, Any]) -> int:
        score = 0
        additional = self._concat_lower(data.get("infos_supplementaires"))
        keywords = [
            "digital nomad",
            "nomade digital",
            "remote work",
            "full remote",
            "travailler en voyage",
            "work from abroad",
            "workation",
        ]
        if any(k in additional for k in keywords):
            score += 60
        nights = self._extract_duration_nights(data)
        if nights and nights >= 30:
            score += 25
        if nights and nights >= 60:
            score += 10
        return min(score, 100)

    def _check_slow_travel(self, data: Dict[str, Any]) -> int:
        score = 0
        nights = self._extract_duration_nights(data)
        if nights and nights >= 10:
            score += 35
        if nights and nights >= 14:
            score += 15
        rythme = data.get("rythme") or data.get("rhythm") or ""
        rythme_lower = str(rythme).lower()
        if (
            "lent" in rythme_lower
            or "relax" in rythme_lower
            or "tranquille" in rythme_lower
            or "slow" in rythme_lower
            or "relaxed" in rythme_lower
        ):
            score += 35
        ambiance = data.get("ambiance_voyage") or ""
        ambiance_lower = str(ambiance).lower()
        if (
            "détente" in ambiance_lower
            or "detente" in ambiance_lower
            or "relax" in ambiance_lower
            or "calme" in ambiance_lower
        ):
            score += 15
        return min(score, 100)

    def _check_wellness(self, data: Dict[str, Any]) -> int:
        score = 0
        affinities = data.get("affinites_voyage") or data.get("travel_affinities") or []
        joined = self._concat_lower(affinities)
        wellness_keywords = [
            "bien_etre",
            "bien-être",
            "bien etre",
            "spa",
            "thermes",
            "thermal",
            "yoga",
            "meditation",
            "méditation",
            "retraite",
            "retreat",
            "detox",
            "détox",
        ]
        if any(k in joined for k in wellness_keywords):
            score += 60
        ambiance = data.get("ambiance_voyage") or ""
        ambiance_lower = str(ambiance).lower()
        if (
            "relax" in ambiance_lower
            or "détente" in ambiance_lower
            or "detente" in ambiance_lower
        ):
            score += 20
        return min(score, 100)

    def _check_bleisure(self, data: Dict[str, Any]) -> int:
        score = 0
        additional = self._concat_lower(data.get("infos_supplementaires"))
        keywords = [
            "business trip",
            "voyage d'affaires",
            "voyage pro",
            "conférence",
            "conference",
            "séminaire",
            "seminaire",
            "salon",
        ]
        if any(k in additional for k in keywords):
            score += 60
        dates_type = data.get("dates_type")
        if dates_type == "fixed":
            score += 10
        aide = data.get("aide_avec") or data.get("help_with")
        if isinstance(aide, list) and "flights" in aide and "accommodation" in aide:
            score += 15
        return min(score, 100)

    def _check_eco_conscious(self, data: Dict[str, Any]) -> int:
        score = 0
        contraintes = data.get("contraintes") or data.get("constraints") or []
        additional = data.get("infos_supplementaires") or ""
        texts: List[str] = []
        if isinstance(contraintes, list):
            texts.extend(str(x).lower() for x in contraintes)
        elif contraintes:
            texts.append(str(contraintes).lower())
        texts.append(str(additional).lower())
        eco_keywords = [
            "écologique",
            "ecologique",
            "environnement",
            "co2",
            "empreinte",
            "train plutôt que l'avion",
            "train plutot que l'avion",
            "pas d'avion",
            "no plane",
            "low impact",
        ]
        if any(k in t for t in texts for k in eco_keywords):
            score += 65
        preference_vol = str(
            data.get("preference_vol") or data.get("flight_preference") or ""
        ).lower()
        if (
            "train" in preference_vol
            or "pas d'avion" in preference_vol
            or "no plane" in preference_vol
        ):
            score += 20
        return min(score, 100)

    def _check_roadtrip(self, data: Dict[str, Any]) -> int:
        score = 0
        nights = self._extract_duration_nights(data) or 0
        mobility = data.get("mobilite") or data.get("mobility")
        affinities = data.get("affinites_voyage") or data.get("travel_affinities") or []
        if nights >= 7:
            score += 30
        if self._has_keyword_in_list(
            mobility, ["location voiture", "rental car", "moto", "scooter", "roadtrip"]
        ):
            score += 40
        if self._has_keyword_in_list(
            affinities, ["nature", "randonnée", "hiking", "roadtrip", "paysages"]
        ):
            score += 20
        return min(score, 100)

    def _check_city_break(self, data: Dict[str, Any]) -> int:
        score = 0
        nights = self._extract_duration_nights(data) or 0
        travel_group = data.get("travel_group")
        affinities = data.get("affinites_voyage") or data.get("travel_affinities") or []
        mobility = data.get("mobilite") or data.get("mobility")
        if nights and nights <= 4:
            score += 40
        if travel_group in {"solo", "duo"}:
            score += 20
        if self._has_keyword_in_list(
            affinities,
            ["shopping", "mode", "shopping & fashion", "culture", "musée", "museum"],
        ):
            score += 20
        if self._has_keyword_in_list(
            mobility, ["métro", "metro", "train", "transports en commun", "subway"]
        ):
            score += 10
        return min(score, 100)

    def _detect_minor_personas(self, data: Dict[str, Any]) -> List[Tuple[str, int]]:
        personas: List[Tuple[str, int]] = []

        score_digital = self._check_digital_nomad(data)
        if score_digital >= 80:
            personas.append(("Digital nomad", score_digital))

        score_slow = self._check_slow_travel(data)
        if score_slow >= 80:
            personas.append(("Slow traveler", score_slow))

        score_wellness = self._check_wellness(data)
        if score_wellness >= 80:
            personas.append(("Voyage bien-être", score_wellness))

        score_bleisure = self._check_bleisure(data)
        if score_bleisure >= 80:
            personas.append(("Bleisure traveler", score_bleisure))

        score_eco = self._check_eco_conscious(data)
        if score_eco >= 80:
            personas.append(("Voyageur éco-conscient", score_eco))

        score_roadtrip = self._check_roadtrip(data)
        if score_roadtrip >= 80:
            personas.append(("Amateur de roadtrip", score_roadtrip))

        score_city_break = self._check_city_break(data)
        if score_city_break >= 80:
            personas.append(("Amateur de city-break urbain", score_city_break))

        affinities = data.get("affinites_voyage") or data.get("travel_affinities") or []
        styles = data.get("styles") or []
        affinities_lower = self._lower_list(affinities)
        styles_lower = self._lower_list(styles)

        def list_has_any(values: List[str], keywords: List[str]) -> bool:
            for v in values:
                for k in keywords:
                    if k in v:
                        return True
            return False

        if list_has_any(
            affinities_lower + styles_lower,
            ["plage", "beach", "détente", "detente", "sun", "paradise beaches"],
        ):
            personas.append(("Amateur de plage & détente", 85))

        if list_has_any(
            affinities_lower + styles_lower,
            ["nature", "randonnée", "hiking", "montagne", "mountain", "paysages"],
        ):
            personas.append(("Amoureux de nature & paysages", 85))

        if list_has_any(
            affinities_lower + styles_lower,
            ["culture", "histoire", "museum", "musée", "city tour"],
        ):
            personas.append(("Passionné de culture & histoire", 82))

        if list_has_any(
            affinities_lower + styles_lower,
            ["gastronomie", "food", "cuisine", "street food"],
        ):
            personas.append(("Gourmet & gastronomie", 82))

        if list_has_any(
            affinities_lower + styles_lower,
            ["parc d'attractions", "amusement park", "roller coaster"],
        ):
            personas.append(("Fan de parcs & attractions", 82))

        if list_has_any(
            affinities_lower + styles_lower,
            ["festival", "festivals", "nightlife", "fête", "soirée", "party"],
        ):
            personas.append(("Amateur de vie nocturne & festivals", 82))

        unique: Dict[str, int] = {}
        for name, score in personas:
            if name not in unique or score > unique[name]:
                unique[name] = score

        sorted_personas = sorted(unique.items(), key=lambda x: x[1], reverse=True)
        return sorted_personas[:1]

    def _calculate_global_confidence(
        self,
        data: Dict[str, Any],
        base_confidence: int,
        minor_personas: List[Tuple[str, int]],
    ) -> int:
        score = base_confidence

        core_fields = [
            "travel_group",
            "has_destination",
            "dates_type",
            "budget_par_personne",
            "montant_budget",
            "lieu_depart",
            "destination",
        ]
        filled_core = sum(
            1 for f in core_fields if data.get(f) not in (None, "", [])
        )
        score += min(filled_core * 2, 8)

        if data.get("affinites_voyage") or data.get("travel_affinities"):
            score += 1
        if data.get("preference_climat") or data.get("climate_preference"):
            score += 1
        if data.get("rythme") or data.get("rhythm"):
            score += 1
        if data.get("mobilite") or data.get("mobility"):
            score += 1

        filled = self._count_filled_fields(data)
        total = len(data) if data else 1
        ratio = filled / total
        if ratio >= 0.7:
            score += 3
        elif ratio <= 0.3:
            score -= 5

        if minor_personas:
            score += 2

        destination_flag = data.get("has_destination")
        if destination_flag == "no":
            score -= 2

        dates_type = data.get("dates_type")
        if dates_type == "flexible":
            score -= 1

        score = max(0, min(100, score))
        return score

    def _confidence_level(self, score: int) -> str:
        if score >= self.CONFIDENCE_HIGH:
            return "HAUT"
        if score >= self.CONFIDENCE_MEDIUM:
            return "MOYEN"
        return "FAIBLE"

    def _finalize_persona_label(
        self,
        base_persona: str,
        confidence: int,
        minor_personas: List[Tuple[str, int]],
    ) -> str:
        label = base_persona
        if minor_personas:
            top_minor = minor_personas[0][0]
            label = f"{label} + {top_minor}"
        if confidence < self.CONFIDENCE_MEDIUM:
            label = f"{label} (persona à confirmer)"
        elif self.CONFIDENCE_MEDIUM <= confidence < self.CONFIDENCE_HIGH:
            label = f"{label} (persona probable)"
        return label

    def _extract_sure_characteristics(self, data: Dict[str, Any]) -> List[str]:
        items: List[str] = []

        travel_group = data.get("travel_group")
        if travel_group == "solo":
            items.append("Voyage en solo")
        elif travel_group == "duo":
            items.append("Voyage en duo")
        elif travel_group == "family":
            items.append("Voyage en famille")
        elif travel_group in {"friends", "group", "group35"}:
            items.append("Voyage en groupe d'amis")

        nombre = data.get("nombre_voyageurs") or data.get("number_of_travelers")
        if isinstance(nombre, int) and nombre > 0:
            items.append(f"Nombre de voyageurs: {nombre}")

        children_count = self._extract_children_count(data)
        if children_count > 0:
            items.append(f"Présence d'enfants dans le groupe: {children_count}")

        budget = (
            data.get("budget_par_personne")
            or data.get("montant_budget")
            or data.get("budget_amount")
        )
        if budget:
            items.append(f"Budget indicatif renseigné: {budget}")

        nights = self._extract_duration_nights(data)
        duree = data.get("duree") or data.get("duration")
        if nights is not None:
            items.append(f"Durée prévue approximative: {nights} nuits")
        elif duree:
            items.append(f"Durée prévue: {duree}")

        dates_type = data.get("dates_type")
        flex = data.get("flexibilite") or data.get("flexibility")
        if dates_type == "fixed":
            items.append("Dates de voyage plutôt fixes")
        elif dates_type == "flexible":
            if flex:
                items.append(f"Dates de voyage flexibles ({flex})")
            else:
                items.append("Dates de voyage flexibles")

        climat = data.get("preference_climat") or data.get("climate_preference")
        if isinstance(climat, list) and climat:
            labels: List[str] = []
            for c in climat:
                labels.append(str(c))
            items.append("Préférence de climat: " + ", ".join(labels))

        ambiance = data.get("ambiance_voyage")
        if ambiance:
            items.append(f"Ambiance recherchée: {ambiance}")

        bagages_list = data.get("bagages_list")
        if isinstance(bagages_list, list) and len(bagages_list) > 0:
            only_personal = all(
                str(b).lower().startswith("personal")
                or "objet personnel" in str(b).lower()
                for b in bagages_list
            )
            if only_personal:
                items.append(
                    "Voyage prévu avec uniquement des petits bagages personnels"
                )

        aide = data.get("aide_avec") or data.get("help_with")
        if isinstance(aide, list) and aide:
            items.append(
                "Aide demandée en priorité sur: "
                + ", ".join(str(a) for a in aide)
            )

        langue = data.get("langue") or data.get("language")
        if langue:
            items.append(f"Langue principale du questionnaire: {langue}")

        depart = data.get("lieu_depart") or data.get("departure_location")
        if depart:
            items.append(f"Lieu de départ: {depart}")

        return items

    def _identify_uncertainties(self, data: Dict[str, Any]) -> List[str]:
        items: List[str] = []

        destination_flag = data.get("has_destination")
        destination_value = data.get("destination")
        if destination_flag != "yes" or not destination_value:
            items.append("Destination finale non précisée")

        if not data.get("date_depart") and not data.get("departure_date"):
            items.append("Date précise de départ non renseignée")

        if not data.get("date_retour") and not data.get("return_date"):
            items.append("Date précise de retour non renseignée")

        if not data.get("type_hebergement") and not data.get("accommodation_type"):
            items.append("Type d'hébergement souhaité non précisé")

        if not data.get("rythme") and not data.get("rhythm"):
            items.append("Rythme de voyage préféré non précisé")

        if not data.get("mobilite") and not data.get("mobility"):
            items.append("Contraintes ou préférences de mobilité non renseignées")

        if not data.get("securite") and not data.get("security"):
            items.append("Niveau de sensibilité à la sécurité non précisé")

        if not data.get("preferences_hotel") and not data.get("hotel_preferences"):
            items.append("Préférences détaillées pour l'hébergement non renseignées")

        return items

    def _generate_recommandations(
        self,
        data: Dict[str, Any],
        persona_label: str,
        minor_personas: List[Tuple[str, int]],
        global_confidence: int,
    ) -> List[Dict[str, Any]]:
        recs: Dict[str, int] = {}

        def add_rec(texte: str, base_score: int) -> None:
            if not texte:
                return
            adjusted = base_score + (global_confidence - 70) // 4
            score = max(60, min(98, adjusted))
            prev = recs.get(texte)
            if prev is None or score > prev:
                recs[texte] = score

        travel_group = data.get("travel_group")
        children_count = self._extract_children_count(data)
        nights = self._extract_duration_nights(data)
        budget_value = (
            data.get("budget_par_personne")
            or data.get("montant_budget")
            or data.get("budget_amount")
        )
        budget_segment = self._detect_budget_segment(budget_value) if budget_value else None
        help_with = data.get("aide_avec") or data.get("help_with") or []
        dates_type = data.get("dates_type")
        flex_days = self._extract_flex_days(data)
        climat = data.get("preference_climat") or data.get("climate_preference")
        constraints = data.get("contraintes") or data.get("constraints") or []
        security = data.get("securite") or data.get("security") or []
        ambiance = data.get("ambiance_voyage") or ""
        ambiance_lower = str(ambiance).lower()
        langue = data.get("langue") or data.get("language")
        depart = data.get("lieu_depart") or data.get("departure_location")
        affinities = data.get("affinites_voyage") or data.get("travel_affinities") or []
        styles = data.get("styles") or []
        mobility = data.get("mobilite") or data.get("mobility") or []
        accommodation_type = data.get("type_hebergement") or data.get("accommodation_type") or []
        amenities = data.get("equipements") or data.get("amenities") or []
        schedule_prefs = data.get("preferences_horaires") or data.get("schedule_prefs") or []

        if travel_group == "solo":
            add_rec(
                "Privilégier des quartiers faciles à naviguer et perçus comme sûrs pour un voyageur solo, avec une logistique simple.",
                90,
            )
        elif travel_group == "duo":
            if "romant" in ambiance_lower or "intim" in ambiance_lower:
                add_rec(
                    "Concevoir un itinéraire pensé pour un couple, avec des temps de qualité à deux et quelques moments forts mémorables.",
                    90,
                )
            elif "fête" in ambiance_lower or "nightlife" in ambiance_lower or "party" in ambiance_lower:
                add_rec(
                    "Prévoir un mix d'activités à partager à deux et de soirées animées, tout en gardant des temps de repos.",
                    90,
                )
            else:
                add_rec(
                    "Structurer le voyage pour un couple, avec un bon équilibre entre découvertes, moments à deux et temps libre.",
                    88,
                )
        elif travel_group == "family":
            if children_count > 0:
                add_rec(
                    "Adapter le rythme et les activités pour une famille avec enfants, en alternant temps de jeu, découvertes et pauses.",
                    90,
                )
            else:
                add_rec(
                    "Penser le voyage pour une famille sans enfants à charge, avec un rythme confortable pour tous les membres du groupe.",
                    88,
                )
        elif travel_group in {"friends", "group", "group35"}:
            add_rec(
                "Proposer des activités faciles à partager en groupe et des hébergements qui facilitent les moments conviviaux.",
                90,
            )
        elif travel_group == "business":
            add_rec(
                "Distinguer clairement les contraintes professionnelles des temps libres pour optimiser un voyage mêlant travail et loisirs.",
                88,
            )

        if nights is not None:
            if nights <= 3:
                add_rec(
                    "Limiter l'itinéraire à une seule destination principale pour éviter la fatigue sur un séjour très court.",
                    86,
                )
            elif 4 <= nights <= 8:
                add_rec(
                    "Construire un itinéraire concentré autour d'une ou deux zones bien reliées, sans multiplier les changements d'hébergement.",
                    86,
                )
            else:
                add_rec(
                    "Profiter de la durée du séjour pour proposer une immersion progressive avec quelques étapes cohérentes plutôt qu'un programme surchargé.",
                    86,
                )

        if budget_segment == "budget":
            add_rec(
                "Optimiser le rapport qualité/prix en sélectionnant des transports et hébergements simples mais bien notés, en évitant les frais cachés.",
                86,
            )
        elif budget_segment == "mid":
            add_rec(
                "Rechercher un équilibre entre budget et confort, avec quelques expériences à forte valeur ajoutée plutôt que des journées surchargées.",
                84,
            )
        elif budget_segment == "luxe":
            add_rec(
                "Inclure des hébergements et expériences de standing cohérents avec un budget plus confortable, tout en gardant une logistique fluide.",
                86,
            )

        if dates_type == "fixed":
            add_rec(
                "Donner la priorité à la fiabilité des trajets et des horaires, même si certains prix sont légèrement plus élevés.",
                82,
            )
        elif dates_type == "flexible":
            if flex_days is not None and flex_days >= 2:
                add_rec(
                    f"Exploiter la flexibilité des dates (±{flex_days} jours) pour cibler les meilleures fenêtres de prix sur les vols et hébergements.",
                    84,
                )
            elif flex_days is not None and flex_days <= 1:
                add_rec(
                    "Considérer les dates comme quasi fixes et privilégier des trajets simples et fiables sur la période demandée.",
                    82,
                )

        if isinstance(climat, list):
            clean_climat = [c for c in climat if str(c).lower() not in {"dont_mind", "peu importe"}]
            if clean_climat:
                add_rec(
                    "Tenir compte en priorité des préférences de climat déclarées pour filtrer les régions et la saison les plus pertinentes.",
                    82,
                )

        if isinstance(help_with, list):
            if "flights" in help_with:
                if depart:
                    add_rec(
                        "Optimiser les vols à partir du lieu de départ indiqué, en comparant quelques combinaisons réalistes de durée totale et de prix.",
                        84,
                    )
                else:
                    add_rec(
                        "Optimiser les vols en recherchant un bon compromis entre durée totale de trajet, nombre d'escales et budget.",
                        82,
                    )
            if "accommodation" in help_with:
                add_rec(
                    "Mettre l'accent sur la sélection d'hébergements alignés avec le niveau de confort souhaité et le type de quartier recherché.",
                    84,
                )
            if "activities" in help_with:
                add_rec(
                    "Structurer les journées autour de quelques activités fortes en lien avec les affinités principales, tout en gardant du temps libre planifié.",
                    84,
                )

        constraints_text = " ".join(str(c).lower() for c in self._ensure_list(constraints))
        if constraints_text:
            if any(k in constraints_text for k in ["halal", "sans porc", "no pork", "no alcohol", "sans alcool"]):
                add_rec(
                    "Intégrer explicitement les contraintes alimentaires (halal/sans porc/sans alcool) dans le choix des destinations, quartiers et restaurants proposés.",
                    90,
                )
            else:
                add_rec(
                    "Tenir systématiquement compte des contraintes déclarées (santé, alimentation, pratiques) dans les propositions de transports, activités et hébergements.",
                    86,
                )

        security_text = " ".join(str(s).lower() for s in self._ensure_list(security))
        if security_text:
            if "éviter zones peu sûres" in security_text or "avoid unsafe" in security_text:
                add_rec(
                    "Limiter les suggestions à des quartiers perçus comme sûrs, bien desservis et adaptés aux attentes exprimées en matière de sécurité.",
                    88,
                )

        affinities_lower = self._lower_list(affinities)
        styles_lower = self._lower_list(styles)
        if affinities_lower or styles_lower:
            if any("parc" in v or "amusement" in v for v in affinities_lower + styles_lower):
                add_rec(
                    "Réserver à l'avance les activités à forte demande comme les parcs d'attractions ou excursions populaires pour sécuriser les créneaux.",
                    84,
                )
            if any("plongée" in v or "diving" in v or "snorkeling" in v for v in affinities_lower + styles_lower):
                add_rec(
                    "Prévoir les activités à contraintes météo comme la plongée ou le snorkeling en gardant des jours tampons pour s'adapter aux conditions.",
                    84,
                )
            if any("yoga" in v or "bien-être" in v or "wellness" in v for v in affinities_lower + styles_lower):
                add_rec(
                    "Positionner les expériences bien-être (spa, yoga, retraites) à des moments clés du séjour pour favoriser la récupération.",
                    84,
                )

        mobility_lower = self._lower_list(mobility)
        if mobility_lower:
            if any("location voiture" in v or "rental car" in v or "moto" in v or "scooter" in v for v in mobility_lower):
                add_rec(
                    "Organiser les étapes de manière à optimiser les trajets en voiture ou scooter, en limitant les longs allers-retours inutiles.",
                    84,
                )
            if any("métro" in v or "metro" in v or "train" in v or "transports en commun" in v for v in mobility_lower):
                add_rec(
                    "Choisir des hébergements bien connectés aux transports en commun pour simplifier les déplacements quotidiens.",
                    84,
                )

        accommodation_lower = self._lower_list(accommodation_type)
        if accommodation_lower:
            if any("resort" in v for v in accommodation_lower):
                add_rec(
                    "Prévoir du temps sur place pour profiter pleinement des services du resort plutôt que de multiplier les sorties extérieures.",
                    84,
                )
            if any("camping" in v or "glamping" in v for v in accommodation_lower):
                add_rec(
                    "Adapter l'itinéraire aux contraintes d'un séjour en camping ou glamping, en tenant compte des trajets et de la météo.",
                    82,
                )

        amenities_lower = self._lower_list(amenities)
        if amenities_lower:
            if any("wifi" in v or "wi-fi" in v for v in amenities_lower):
                add_rec(
                    "Vérifier la qualité de la connexion internet dans les hébergements clés si le voyage nécessite de rester joignable ou de travailler.",
                    80,
                )
            if any("cuisine" in v or "kitchen" in v for v in amenities_lower):
                add_rec(
                    "Tirer parti d'une cuisine équipée pour réduire certains coûts de repas tout en gardant quelques expériences culinaires locales.",
                    80,
                )

        schedule_lower = self._lower_list(schedule_prefs)
        if schedule_lower:
            if any("night_owl" in v or "couche-tard" in v for v in schedule_lower):
                add_rec(
                    "Éviter de placer des vols ou activités très matinaux si le voyageur a un rythme de couche-tard déclaré.",
                    82,
                )
            if any("early_bird" in v or "lève-tôt" in v for v in schedule_lower):
                add_rec(
                    "Placer les expériences majeures en début de journée pour profiter de la préférence pour les matinées.",
                    82,
                )

        if langue in {"fr", "en"}:
            add_rec(
                "Privilégier des destinations et des prestataires où la langue du voyageur (ou l'anglais) est couramment utilisée pour réduire la friction sur place.",
                80,
            )

        if depart:
            add_rec(
                "Construire l'itinéraire à partir du lieu de départ déclaré afin de limiter les ruptures de charge et les temps de trajet inutiles.",
                82,
            )

        for name, score in minor_personas:
            if name == "Digital nomad":
                add_rec(
                    "Favoriser des hébergements avec bonne connexion internet et espaces de travail adaptés si le voyage mélange travail et découverte.",
                    86,
                )
            elif name == "Slow traveler":
                add_rec(
                    "Limiter volontairement le nombre d'étapes pour privilégier l'immersion locale plutôt qu'une liste de lieux à cocher.",
                    86,
                )
            elif name == "Voyage bien-être":
                add_rec(
                    "Inclure des expériences orientées bien-être (spa, thermes, espaces calmes, activités corps-esprit) en cohérence avec les attentes.",
                    86,
                )
            elif name == "Bleisure traveler":
                add_rec(
                    "Organiser les temps libres autour des contraintes professionnelles, en limitant les déplacements complexes les jours de travail.",
                    84,
                )
            elif name == "Voyageur éco-conscient":
                add_rec(
                    "Mettre en avant des options plus durables (train, bus, hébergements engagés) lorsqu'elles sont réalistes par rapport à l'itinéraire.",
                    84,
                )
            elif name == "Amateur de roadtrip":
                add_rec(
                    "Structurer le voyage comme un roadtrip fluide avec des étapes d'une à trois nuits, en évitant les retours en arrière inutiles.",
                    86,
                )
            elif name == "Amateur de city-break urbain":
                add_rec(
                    "Concentrer les efforts sur une ville ou deux au maximum, en optimisant les déplacements à pied et en transports en commun.",
                    86,
                )

        sorted_recs = sorted(recs.items(), key=lambda x: x[1], reverse=True)
        top_recs = sorted_recs[:3]

        return [{"texte": texte, "confiance": score} for texte, score in top_recs]

    def _count_filled_fields(self, data: Dict[str, Any]) -> int:
        if not data:
            return 0
        count = 0
        for value in data.values():
            if value is None:
                continue
            if isinstance(value, str) and value.strip() == "":
                continue
            if isinstance(value, (list, dict)) and not value:
                continue
            count += 1
        return count

    def to_dict(self, result: InferenceResult) -> Dict[str, Any]:
        return {
            "persona": {
                "principal": result.persona_inference.persona_principal,
                "confiance": result.persona_inference.confiance,
                "niveau": result.persona_inference.niveau,
                "profils_emergents": [
                    {"nom": p[0], "confiance": p[1]}
                    for p in result.persona_inference.profils_emergents
                ],
            },
            "caracteristiques_sures": result.persona_inference.caracteristiques_sures,
            "incertitudes": result.persona_inference.incertitudes,
            "recommandations": result.recommandations,
        }


persona_engine = PersonaInferenceEngine()
