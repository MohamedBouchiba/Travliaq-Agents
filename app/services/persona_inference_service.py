#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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
    profil_emergent: Optional[Tuple[str, int]]
    caracteristiques_sures: List[str]
    incertitudes: List[str]


@dataclass
class InferenceResult:
    questionnaire_data: Dict[str, Any]
    persona_inference: PersonaInference
    recommandations: List[Dict[str, Any]]


class PersonaInferenceEngine:
    CONFIDENCE_HIGH = 85
    CONFIDENCE_MEDIUM = 65

    def infer_persona(self, questionnaire_data: Dict[str, Any]) -> InferenceResult:
        try:
            data = self._normalize_data(questionnaire_data)
            macro_label, base_conf = self._identify_macro_persona(data)
            emerging_profiles = self._detect_emerging_profiles(data)
            best_emergent = self._select_best_emergent(emerging_profiles)
            global_conf = self._calculate_global_confidence(
                data, macro_label, base_conf, best_emergent
            )
            niveau = self._confidence_level(global_conf)
            caracteristiques_sures = self._extract_sure_characteristics(
                data, macro_label, best_emergent
            )
            incertitudes = self._identify_uncertainties(data)
            recommandations = self._generate_recommendations(
                data, macro_label, best_emergent
            )

            persona = PersonaInference(
                persona_principal=macro_label,
                confiance=global_conf,
                niveau=niveau,
                profil_emergent=best_emergent,
                caracteristiques_sures=caracteristiques_sures,
                incertitudes=incertitudes,
            )
            return InferenceResult(
                questionnaire_data=data,
                persona_inference=persona,
                recommandations=recommandations,
            )
        except Exception as exc:
            logger.error(f"Erreur lors de l'inférence de persona: {exc}")
            raise

    # ----------------------------
    # NORMALISATION
    # ----------------------------
    def _normalize_data(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        data: Dict[str, Any] = dict(raw) if raw else {}

        # Groupe de voyage → travel_group canonique
        g = data.get("groupe_voyage") or data.get("travel_group")
        if g:
            g2 = str(g).lower().strip()
            if "duo" in g2:
                data["travel_group"] = "duo"
            elif "solo" in g2:
                data["travel_group"] = "solo"
            elif "family" in g2 or "famille" in g2:
                data["travel_group"] = "family"
            elif "group" in g2 or "ami" in g2:
                data["travel_group"] = "friends"
            else:
                data["travel_group"] = g2
        else:
            data["travel_group"] = None

        def norm_yes_no(v: Any) -> Optional[str]:
            if not v:
                return None
            x = str(v).lower().strip()
            if x in ("yes", "oui", "y"):
                return "yes"
            if x in ("no", "non", "n"):
                return "no"
            return x

        data["has_destination"] = norm_yes_no(
            data.get("a_destination") or data.get("has_destination")
        )

        data["has_approx_date"] = norm_yes_no(
            data.get("a_date_depart_approximative")
            or data.get("has_approximate_departure_date")
        )

        dt = data.get("type_dates") or data.get("dates_type")
        if dt:
            t = str(dt).lower()
            if "fix" in t:
                data["dates_type"] = "fixed"
            elif "flex" in t:
                data["dates_type"] = "flexible"
            else:
                data["dates_type"] = t
        else:
            data["dates_type"] = None

        # Champs potentiellement sérialisés en JSON
        json_fields = [
            "preference_climat",
            "affinites_voyage",
            "styles",
            "mobilite",
            "type_hebergement",
            "equipements",
            "contraintes",
            "securite",
            "preferences_hotel",
            "preferences_horaires",
            "aide_avec",
        ]
        for field in json_fields:
            v = data.get(field)
            if isinstance(v, str):
                vs = v.strip()
                if vs:
                    if vs.startswith("[") or vs.startswith("{"):
                        try:
                            data[field] = json.loads(vs)
                        except Exception:
                            # On laisse tel quel si ce n'est pas du JSON valide
                            pass

        # Bagages → liste ordonnée
        bag = data.get("bagages")
        if isinstance(bag, dict):
            try:
                ordered = [bag[k] for k in sorted(bag.keys(), key=lambda x: int(x))]
                data["bagages_list"] = ordered
            except Exception:
                data["bagages_list"] = list(bag.values())
        elif isinstance(bag, list):
            data["bagages_list"] = bag
        else:
            data["bagages_list"] = None

        # Durée & budget
        data["duration_nights"] = self._extract_nights(data)
        data["budget_segment"] = self._parse_budget(data)
        return data

    def _extract_nights(self, data: Dict[str, Any]) -> Optional[int]:
        if isinstance(data.get("nuits_exactes"), int):
            return data["nuits_exactes"]
        duree = data.get("duree")
        if not duree:
            return None
        text = str(duree)
        digits = ""
        for ch in text:
            if ch.isdigit():
                digits += ch
        if digits:
            try:
                return int(digits)
            except Exception:
                return None
        return None

    def _parse_budget(self, data: Dict[str, Any]) -> Optional[str]:
        b = data.get("budget_par_personne") or data.get("montant_budget")
        if not b:
            return None
        t = str(b).lower()
        nums: List[int] = []
        buf = ""
        for c in t:
            if c.isdigit():
                buf += c
            else:
                if buf:
                    nums.append(int(buf))
                    buf = ""
        if buf:
            nums.append(int(buf))
        if not nums:
            if "je ne sais" in t:
                return "unknown"
            return None
        avg = sum(nums) / len(nums)
        if avg <= 400:
            return "budget"
        if avg >= 1200:
            return "high"
        return "mid"

    # ----------------------------
    # MACRO PERSONA
    # ----------------------------
    def _identify_macro_persona(self, data: Dict[str, Any]) -> Tuple[str, int]:
        group = data.get("travel_group")
        enfants = data.get("enfants")
        nb_voyageurs = data.get("nombre_voyageurs")
        ambiance = self._safe_lower(data.get("ambiance_voyage"))
        help_with = data.get("aide_avec") or data.get("help_with") or []
        if not isinstance(help_with, list):
            help_with = [help_with]

        has_children = False
        if isinstance(enfants, list) and len(enfants) > 0:
            has_children = True
        elif isinstance(enfants, int) and enfants > 0:
            has_children = True

        label = "Voyageur Loisirs"
        base_conf = 55

        if group == "solo":
            label = "Voyageur Solo"
            base_conf = 80
        elif group == "family":
            if has_children or (isinstance(nb_voyageurs, int) and nb_voyageurs >= 3):
                label = "Famille"
                base_conf = 85
            else:
                label = "Famille / Petit groupe"
                base_conf = 80
        elif group in ("friends", "group35", "group"):
            label = "Groupe d'amis"
            base_conf = 82
        elif group == "duo":
            # Cas ambigu : duo peut être couple ou amis → on reste neutre
            if "romant" in ambiance or "honeymoon" in ambiance:
                label = "Couple"
                base_conf = 85
            else:
                label = "Duo Loisirs"
                base_conf = 78

        # Cas business / bleisure
        if "business" in str(group or "") or "affaires" in ambiance:
            if "flights" in help_with and "accommodation" in help_with:
                label = "Voyageur d'affaires / Bleisure"
                base_conf = max(base_conf, 80)

        # Raffinage par budget
        seg = data.get("budget_segment")
        if seg == "budget":
            label = f"{label} - Budget-Conscient"
            base_conf = max(base_conf, 78)
        elif seg == "mid":
            label = f"{label} - Confort modéré"
            base_conf = max(base_conf, 80)
        elif seg == "high":
            label = f"{label} - Haut de gamme"
            base_conf = max(base_conf, 82)

        # Duo non explicitement romantique → on ne monte pas trop la confiance
        if group == "duo" and not ("romant" in ambiance or "honeymoon" in ambiance):
            base_conf = min(base_conf, 83)

        return label, base_conf

    # ----------------------------
    # PROFILS ÉMERGENTS
    # ----------------------------
    def _detect_emerging_profiles(self, data: Dict[str, Any]) -> List[Tuple[str, int]]:
        profiles: List[Tuple[str, int]] = []

        digital = self._score_digital_nomad(data)
        if digital >= 70:
            profiles.append(("Digital Nomad", digital))

        slow = self._score_slow_travel(data)
        if slow >= 70:
            profiles.append(("Slow Traveler", slow))

        wellness = self._score_wellness(data)
        if wellness >= 70:
            profiles.append(("Wellness Traveler", wellness))

        bleisure = self._score_bleisure(data)
        if bleisure >= 70:
            profiles.append(("Bleisure Traveler", bleisure))

        eco = self._score_eco_conscious(data)
        if eco >= 70:
            profiles.append(("Voyageur éco-conscient", eco))

        beach = self._score_beach_lover(data)
        if beach >= 70:
            profiles.append(("Amateur de Plage & Détente", beach))

        nature = self._score_nature_lover(data)
        if nature >= 70:
            profiles.append(("Amoureux de Nature & Paysages", nature))

        city = self._score_city_breaker(data)
        if city >= 70:
            profiles.append(("City Breaker", city))

        parks = self._score_theme_parks(data)
        if parks >= 70:
            profiles.append(("Fan de Parcs & Attractions", parks))

        return profiles

    def _select_best_emergent(
        self, profiles: List[Tuple[str, int]]
    ) -> Optional[Tuple[str, int]]:
        if not profiles:
            return None
        profiles_sorted = sorted(profiles, key=lambda p: p[1], reverse=True)
        best = profiles_sorted[0]
        if best[1] < 70:
            return None
        return best

    def _score_digital_nomad(self, data: Dict[str, Any]) -> int:
        score = 0
        infos = self._safe_lower(data.get("infos_supplementaires"))
        nights = data.get("duration_nights")
        if any(
            k in infos
            for k in [
                "digital nomad",
                "nomade digital",
                "remote work",
                "workation",
                "travailler en voyage",
            ]
        ):
            score += 60
        if isinstance(nights, int) and nights >= 21:
            score += 20
        help_with = data.get("aide_avec") or []
        if isinstance(help_with, list) and "accommodation" in help_with:
            score += 10
        return min(score, 100)

    def _score_slow_travel(self, data: Dict[str, Any]) -> int:
        score = 0
        nights = data.get("duration_nights")
        if isinstance(nights, int) and nights >= 10:
            score += 35
        if isinstance(nights, int) and nights >= 14:
            score += 10
        rythme = self._safe_lower(data.get("rythme"))
        if any(k in rythme for k in ["lent", "relax", "tranquille", "relaxed", "slow"]):
            score += 35
        ambiance = self._safe_lower(data.get("ambiance_voyage"))
        if any(k in ambiance for k in ["détente", "detente", "relaxation"]):
            score += 10
        return min(score, 100)

    def _score_wellness(self, data: Dict[str, Any]) -> int:
        score = 0
        affinities = self._as_list(data.get("affinites_voyage"))
        affinities_text = " ".join(self._safe_lower(a) for a in affinities)
        if any(
            k in affinities_text
            for k in ["yoga", "bien-être", "bien_etre", "spa", "wellness", "thermes"]
        ):
            score += 60
        ambiance = self._safe_lower(data.get("ambiance_voyage"))
        if any(k in ambiance for k in ["relax", "détente", "detente", "calme"]):
            score += 20
        return min(score, 100)

    def _score_bleisure(self, data: Dict[str, Any]) -> int:
        score = 0
        infos = self._safe_lower(data.get("infos_supplementaires"))
        if any(
            k in infos
            for k in [
                "voyage pro",
                "voyage professionnel",
                "conférence",
                "conference",
                "séminaire",
                "seminaire",
                "salon",
                "business trip",
            ]
        ):
            score += 60
        dates_type = data.get("dates_type")
        if dates_type == "fixed":
            score += 10
        return min(score, 100)

    def _score_eco_conscious(self, data: Dict[str, Any]) -> int:
        score = 0
        contraintes = self._as_list(data.get("contraintes"))
        additional = self._safe_lower(data.get("infos_supplementaires"))
        text = " ".join(self._safe_lower(c) for c in contraintes) + " " + additional
        eco_keywords = [
            "écologique",
            "ecologique",
            "environnement",
            "co2",
            "empreinte",
            "pas d'avion",
            "no plane",
            "train plutôt que l'avion",
            "train plutot que l'avion",
        ]
        if any(k in text for k in eco_keywords):
            score += 65
        pref_vol = self._safe_lower(data.get("preference_vol"))
        if any(k in pref_vol for k in ["train", "no plane", "pas d'avion"]):
            score += 15
        return min(score, 100)

    def _score_beach_lover(self, data: Dict[str, Any]) -> int:
        score = 0
        climat = self._as_list(data.get("preference_climat"))
        climat_txt = " ".join(self._safe_lower(c) for c in climat)
        if any(
            k in climat_txt
            for k in [
                "hot",
                "chaud",
                "ensoleillé",
                "sunny",
                "tropical",
                "plage",
                "beach",
            ]
        ):
            score += 40
        affinities = self._as_list(data.get("affinites_voyage"))
        affin_txt = " ".join(self._safe_lower(a) for a in affinities)
        if any(
            k in affin_txt
            for k in [
                "plage",
                "beach",
                "détente",
                "detente",
                "paradise beaches",
                "snorkeling",
                "diving",
            ]
        ):
            score += 35
        return min(score, 100)

    def _score_nature_lover(self, data: Dict[str, Any]) -> int:
        score = 0
        climat = self._as_list(data.get("preference_climat"))
        climat_txt = " ".join(self._safe_lower(c) for c in climat)
        if any(k in climat_txt for k in ["mountain", "montagne", "altitude"]):
            score += 40
        affinities = self._as_list(data.get("affinites_voyage"))
        affin_txt = " ".join(self._safe_lower(a) for a in affinities)
        if any(
            k in affin_txt
            for k in [
                "nature",
                "randonnée",
                "hiking",
                "paysages",
                "ski",
                "winter",
                "montagne",
            ]
        ):
            score += 35
        return min(score, 100)

    def _score_city_breaker(self, data: Dict[str, Any]) -> int:
        score = 0
        affinities = self._as_list(data.get("affinites_voyage"))
        affin_txt = " ".join(self._safe_lower(a) for a in affinities)
        if any(
            k in affin_txt
            for k in [
                "city",
                "ville",
                "city-trip",
                "city break",
                "historic_cities",
                "culture",
                "musées",
            ]
        ):
            score += 40
        nights = data.get("duration_nights")
        if isinstance(nights, int) and nights <= 5:
            score += 25
        return min(score, 100)

    def _score_theme_parks(self, data: Dict[str, Any]) -> int:
        score = 0
        affinities = self._as_list(data.get("affinites_voyage"))
        affin_txt = " ".join(self._safe_lower(a) for a in affinities)
        if any(
            k in affin_txt
            for k in [
                "parcs d'attractions",
                "amusement parks",
                "theme park",
                "parcs d'attraction",
            ]
        ):
            score += 70
        return min(score, 100)

    # ----------------------------
    # CONFIANCE GLOBALE
    # ----------------------------
    def _calculate_global_confidence(
        self,
        data: Dict[str, Any],
        macro_label: str,
        base_conf: int,
        best_emergent: Optional[Tuple[str, int]],
    ) -> int:
        score = base_conf

        filled = self._count_filled_fields(data)
        total = max(len(data), 1)
        ratio = filled / total
        if ratio >= 0.7:
            score += 5
        elif ratio <= 0.3:
            score -= 5

        if best_emergent:
            score += 3

        if data.get("has_destination") == "no":
            score -= 2

        if data.get("dates_type") == "flexible":
            score -= 1

        seg = data.get("budget_segment")
        if seg == "unknown":
            score -= 2

        group = data.get("travel_group")
        ambiance = self._safe_lower(data.get("ambiance_voyage"))
        if group == "duo" and not ("romant" in ambiance or "honeymoon" in ambiance):
            # Duo ambigu (ami/couple) → on réduit la confiance
            score -= 4
            score = min(score, 88)

        score = max(40, min(score, 96))
        return int(round(score))

    def _confidence_level(self, score: int) -> str:
        if score >= self.CONFIDENCE_HIGH:
            return "HAUT"
        if score >= self.CONFIDENCE_MEDIUM:
            return "MOYEN"
        return "FAIBLE"

    # ----------------------------
    # CARACTÉRISTIQUES SURES
    # ----------------------------
    def _extract_sure_characteristics(
        self,
        data: Dict[str, Any],
        macro_label: str,
        best_emergent: Optional[Tuple[str, int]],
    ) -> List[str]:
        items: List[str] = []

        group = data.get("travel_group")
        if group == "solo":
            items.append("Voyage en solo")
        elif group == "duo":
            if "Couple" in macro_label:
                items.append("Voyage en couple")
            else:
                items.append("Voyage en duo (profil exact à préciser)")
        elif group == "family":
            items.append("Voyage en famille")
        elif group in ("friends", "group35", "group"):
            items.append("Voyage en groupe d'amis")

        nb = data.get("nombre_voyageurs")
        if isinstance(nb, int) and nb > 0:
            items.append(f"Nombre de voyageurs: {nb}")

        enfants = data.get("enfants")
        if isinstance(enfants, list) and len(enfants) > 0:
            items.append(f"Présence d'enfants (détails fournis pour {len(enfants)}).")

        budget = data.get("budget_par_personne") or data.get("montant_budget")
        if budget:
            items.append(f"Budget indicatif renseigné: {budget}")

        nights = data.get("duration_nights")
        if isinstance(nights, int):
            items.append(f"Durée prévue approximative: {nights} nuits")

        flex = data.get("flexibilite")
        dates_type = data.get("dates_type")
        if dates_type == "fixed":
            items.append("Dates de voyage plutôt fixes.")
        elif dates_type == "flexible":
            if flex:
                items.append(f"Dates de voyage flexibles ({flex}).")
            else:
                items.append("Dates de voyage flexibles.")

        climat = self._as_list(data.get("preference_climat"))
        if climat:
            raw = ", ".join(str(c) for c in climat)
            items.append(f"Préférence de climat: {raw}")

        ambiance = data.get("ambiance_voyage")
        if ambiance:
            items.append(f"Ambiance recherchée: {ambiance}")

        help_with = self._as_list(data.get("aide_avec"))
        if help_with:
            items.append(
                "Aide demandée en priorité sur: " + ", ".join(str(a) for a in help_with)
            )

        langue = data.get("langue")
        if langue:
            items.append(f"Langue principale du questionnaire: {langue}")

        depart = data.get("lieu_depart")
        if depart:
            items.append(f"Lieu de départ: {depart}")

        constraints = self._as_list(data.get("contraintes"))
        if constraints:
            items.append(
                "Contraintes spécifiques indiquées: "
                + ", ".join(str(c) for c in constraints)
            )

        mobility = self._as_list(data.get("mobilite"))
        if mobility:
            items.append(
                "Modes de déplacement envisagés sur place: "
                + ", ".join(str(m) for m in mobility)
            )

        acc_types = self._as_list(data.get("type_hebergement"))
        if acc_types:
            items.append(
                "Types d'hébergement envisagés: " + ", ".join(str(t) for t in acc_types)
            )

        confort = data.get("confort")
        if confort:
            items.append(f"Niveau de confort souhaité: {confort}")

        quartier = data.get("quartier")
        if quartier:
            items.append(f"Préférence de quartier: {quartier}")

        amenities = self._as_list(data.get("equipements"))
        if amenities:
            items.append(
                "Équipements prioritaires pour l'hébergement: "
                + ", ".join(str(e) for e in amenities)
            )

        schedule = self._as_list(data.get("preferences_horaires"))
        if schedule:
            items.append(
                "Préférences de rythme/journée: " + ", ".join(str(s) for s in schedule)
            )

        if best_emergent:
            name, conf = best_emergent
            items.append(f"Profil émergent détecté: {name} (confiance ≈ {conf}%).")

        return items

    # ----------------------------
    # INCERTITUDES
    # ----------------------------
    def _identify_uncertainties(self, data: Dict[str, Any]) -> List[str]:
        items: List[str] = []
        if data.get("has_destination") != "yes" or not data.get("destination"):
            items.append("Destination finale non précisée.")
        if not data.get("date_depart") or not data.get("date_retour"):
            items.append("Dates précises de départ et de retour non renseignées.")
        if not data.get("type_hebergement"):
            items.append("Type d'hébergement souhaité non précisé.")
        if not data.get("rythme"):
            items.append("Rythme de voyage préféré non précisé.")
        if not data.get("mobilite"):
            items.append("Modes de déplacement sur place peu détaillés.")
        if not data.get("securite"):
            items.append("Niveau de sensibilité à la sécurité non précisé.")
        if not data.get("preferences_hotel"):
            items.append("Préférences détaillées pour l'hôtel non renseignées.")
        return items

    # ----------------------------
    # RECOMMANDATIONS (TOP 3)
    # ----------------------------
    def _generate_recommendations(
        self,
        data: Dict[str, Any],
        macro_label: str,
        best_emergent: Optional[Tuple[str, int]],
    ) -> List[Dict[str, Any]]:
        recs: List[Dict[str, Any]] = []

        group = data.get("travel_group")
        nights = data.get("duration_nights")
        seg = data.get("budget_segment")
        climat = self._as_list(data.get("preference_climat"))
        affinities = self._as_list(data.get("affinites_voyage"))
        help_with = self._as_list(data.get("aide_avec"))
        constraints = self._as_list(data.get("contraintes"))
        depart = data.get("lieu_depart")
        flex = data.get("flexibilite")
        pref_vol = self._safe_lower(data.get("preference_vol"))

        # 1. Reco liée au groupe
        if group == "solo":
            recs.append(
                {
                    "texte": "Concevoir un itinéraire simple à naviguer pour un voyageur solo, avec des zones perçues comme sûres et une logistique fluide.",
                    "confiance": 88,
                }
            )
        elif group == "family":
            recs.append(
                {
                    "texte": "Intégrer des temps de repos et des activités adaptées au groupe/famille pour garder le voyage gérable pour tout le monde.",
                    "confiance": 90,
                }
            )
        elif group in ("friends", "group35", "group"):
            recs.append(
                {
                    "texte": "Prévoir des activités faciles à partager en groupe et des hébergements qui facilitent les moments conviviaux.",
                    "confiance": 88,
                }
            )
        elif group == "duo":
            if "Couple" in macro_label:
                recs.append(
                    {
                        "texte": "Structurer le voyage pour un couple avec un bon équilibre entre expériences à deux, découvertes et temps libre.",
                        "confiance": 88,
                    }
                )
            else:
                recs.append(
                    {
                        "texte": "Construire un itinéraire adapté à un duo (amis ou couple), en limitant les contraintes logistiques et en laissant de la marge pour l'improvisation.",
                        "confiance": 86,
                    }
                )

        # 2. Reco liée à la durée
        if isinstance(nights, int):
            if nights <= 4:
                recs.append(
                    {
                        "texte": "Limiter l'itinéraire à une seule zone principale afin d'éviter les déplacements fatigants sur un court séjour.",
                        "confiance": 90,
                    }
                )
            elif 5 <= nights <= 9:
                recs.append(
                    {
                        "texte": "Structurer le voyage autour d'une ou deux zones bien reliées pour garder un bon équilibre entre découvertes et repos.",
                        "confiance": 88,
                    }
                )
            else:
                recs.append(
                    {
                        "texte": "Profiter de la durée plus longue pour proposer une immersion progressive avec plusieurs étapes cohérentes et des temps de pause réguliers.",
                        "confiance": 86,
                    }
                )

        # 3. Reco liée au budget
        if seg == "budget":
            recs.append(
                {
                    "texte": "Optimiser fortement le rapport qualité/prix sur les vols et hébergements, en privilégiant des options simples mais bien notées.",
                    "confiance": 90,
                }
            )
        elif seg == "mid":
            recs.append(
                {
                    "texte": "Rechercher un bon équilibre entre confort et budget, avec quelques expériences à forte valeur ajoutée plutôt qu'un programme surchargé.",
                    "confiance": 88,
                }
            )
        elif seg == "high":
            recs.append(
                {
                    "texte": "Inclure des hébergements et expériences plus premium cohérents avec un positionnement haut de gamme.",
                    "confiance": 86,
                }
            )

        # 4. Vols / optimisation
        if "flights" in help_with:
            texte = "Mettre l'accent sur l'optimisation des vols"
            if depart:
                texte += f" au départ de {depart}"
            texte += ", en comparant plusieurs combinaisons réalistes (durée totale, escales, horaires)."
            base_conf = 88
            if flex:
                base_conf += 2
            if "cheapest" in pref_vol:
                base_conf += 2
            recs.append({"texte": texte, "confiance": min(base_conf, 94)})

        # 5. Hébergement
        if "accommodation" in help_with:
            recs.append(
                {
                    "texte": "Sélectionner des hébergements cohérents avec le niveau de confort et le type de quartier indiqués, en gardant un bon équilibre localisation/qualité/prix.",
                    "confiance": 88,
                }
            )

        # 6. Activités
        if "activities" in help_with:
            if affinities:
                recs.append(
                    {
                        "texte": "Construire un programme d'activités ancré dans les affinités déclarées (ex: "
                        + ", ".join(str(a) for a in affinities)
                        + "), avec une intensité adaptée au rythme souhaité.",
                        "confiance": 90,
                    }
                )
            else:
                recs.append(
                    {
                        "texte": "Proposer un mix d'activités emblématiques et de temps libre, en restant cohérent avec l'ambiance souhaitée.",
                        "confiance": 84,
                    }
                )

        # 7. Contraintes (alimentaires, pratiques, etc.)
        if constraints:
            nb = len(constraints)
            base_conf = 88 if nb >= 2 else 84
            recs.append(
                {
                    "texte": "Tenir systématiquement compte des contraintes déclarées (alimentation, pratiques, santé) dans les propositions de transports, activités et hébergements.",
                    "confiance": min(base_conf + nb, 95),
                }
            )

        # 8. Logique ski vs mer / climat & affinités
        climat_txt = " ".join(self._safe_lower(c) for c in climat)
        affin_txt = " ".join(self._safe_lower(a) for a in affinities)
        if climat or affinities:
            if (
                "cold" in climat_txt
                or "neige" in climat_txt
                or "ski" in affin_txt
                or "winter" in affin_txt
            ) and (
                "hot" in climat_txt
                or "tropical" in climat_txt
                or "beach" in affin_txt
                or "plage" in affin_txt
            ):
                recs.append(
                    {
                        "texte": "Explorer au moins deux scénarios typés (ex: séjour montagne/neige vs destination mer ensoleillée) puis comparer les budgets et contraintes pour aider à trancher.",
                        "confiance": 92,
                    }
                )
            elif "cold" in climat_txt or "neige" in climat_txt or "ski" in affin_txt:
                recs.append(
                    {
                        "texte": "Prioriser des destinations adaptées aux sports d'hiver ou à la montagne, en vérifiant la saisonnalité et l'accès depuis le lieu de départ.",
                        "confiance": 88,
                    }
                )
            elif "hot" in climat_txt or "tropical" in climat_txt or "plage" in affin_txt:
                recs.append(
                    {
                        "texte": "Cibler des destinations à climat chaud/ensoleillé avec un bon accès à la plage ou à la mer, en tenant compte de la saison des pluies et de la fréquentation.",
                        "confiance": 88,
                    }
                )

        # 9. Reco liée au profil émergent (un seul profil retenu)
        if best_emergent:
            name, prof_conf = best_emergent
            if name == "Amateur de Plage & Détente":
                recs.append(
                    {
                        "texte": "Réserver de vrais créneaux 'plage/piscine sans contrainte', sans autre activité structurée, pour respecter le besoin de détente identifié.",
                        "confiance": min(90, prof_conf),
                    }
                )
            elif name == "Amoureux de Nature & Paysages":
                recs.append(
                    {
                        "texte": "Intégrer des panoramas, randonnées accessibles ou excursions nature au cœur de l'itinéraire, plutôt que de rester uniquement en milieu urbain.",
                        "confiance": min(90, prof_conf),
                    }
                )
            elif name == "City Breaker":
                recs.append(
                    {
                        "texte": "Structurer l'itinéraire comme un city-break efficace (quartier central, temps de trajet courts, sélection limitée mais forte de lieux à visiter).",
                        "confiance": min(88, prof_conf),
                    }
                )
            elif name == "Wellness Traveler":
                recs.append(
                    {
                        "texte": "Ajouter des expériences orientées bien-être (spa, thermes, yoga, nature calme) pour aligner le voyage avec le besoin de récupération identifié.",
                        "confiance": min(90, prof_conf),
                    }
                )
            elif name == "Digital Nomad":
                recs.append(
                    {
                        "texte": "Privilégier des hébergements avec connexion fiable et espaces de travail, en limitant le nombre de changements de logement.",
                        "confiance": min(90, prof_conf),
                    }
                )

        if not recs:
            recs.append(
                {
                    "texte": "Clarifier au moins la destination approximative, le budget et la durée pour pouvoir construire un itinéraire exploitable.",
                    "confiance": 70,
                }
            )

        # On garde seulement les 3 meilleures recommandations
        recs_sorted = sorted(recs, key=lambda r: r["confiance"], reverse=True)
        return recs_sorted[:3]

    # ----------------------------
    # UTILITAIRES
    # ----------------------------
    def _as_list(self, value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        return [value]

    def _safe_lower(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).lower()

    def _count_filled_fields(self, data: Dict[str, Any]) -> int:
        if not data:
            return 0
        count = 0
        for v in data.values():
            if v is None:
                continue
            if isinstance(v, str) and v.strip() == "":
                continue
            if isinstance(v, (list, dict)) and not v:
                continue
            count += 1
        return count

    def to_dict(self, result: InferenceResult) -> Dict[str, Any]:
        persona = result.persona_inference
        profil_emergent = (
            {"nom": persona.profil_emergent[0], "confiance": persona.profil_emergent[1]}
            if persona.profil_emergent
            else None
        )
        return {
            "persona": {
                "principal": persona.persona_principal,
                "confiance": persona.confiance,
                "niveau": persona.niveau,
                "profil_emergent": profil_emergent,
            },
            "caracteristiques_sures": persona.caracteristiques_sures,
            "incertitudes": persona.incertitudes,
            "recommandations": result.recommandations,
        }


persona_engine = PersonaInferenceEngine()
