import json
import yaml
import re
import logging
import ast
from datetime import datetime, timedelta
from typing import Dict, Any, List

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("Travliaq.SystemContractMerger")

class SystemContractMerger:
    
    @staticmethod
    def generate_contract(questionnaire: Dict[str, Any], step_3_trip_specifications_design: Dict[str, Any]) -> Dict[str, Any]:
        req_id = questionnaire.get("id", "unknown")
        
        ai_data = SystemContractMerger._parse_phase1_data(step_3_trip_specifications_design)

        meta = {
            "request_id": req_id,
            "user_id": questionnaire.get("user_id"),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "source_version": "merger_v9.0_system_contract",
            "pipeline_phase": "phase1_to_phase2_transition"
        }

        narrative_text = SystemContractMerger._extract_narrative(ai_data)
        metadata = ai_data.get("metadata", {}) if isinstance(ai_data, dict) else {}
        additional_info = ai_data.get("additional_info", {}) if isinstance(ai_data, dict) else {}
        confidence_data = {}
        if isinstance(additional_info, dict) and isinstance(additional_info.get("confidence_level"), dict):
            confidence_data.update(additional_info.get("confidence_level"))
        if isinstance(metadata, dict):
            if "macro_confidence" in metadata:
                confidence_data["macro_confidence"] = metadata.get("macro_confidence")
            if "emerging_confidence_avg" in metadata:
                confidence_data["persona_confidence"] = metadata.get("emerging_confidence_avg")
            if "data_completeness" in metadata:
                confidence_data["data_completeness"] = metadata.get("data_completeness")
        
        budget_flag = str(questionnaire.get("budget_par_personne") or questionnaire.get("montant_budget") or "").lower()
        unknown_budget_tokens = ["know", "sais pas", "don't", "dont", "indéfini", "indefini", "tbd", "undefined", "none"]
        is_budget_unknown = any(x in budget_flag for x in unknown_budget_tokens) or not budget_flag.strip()

        user_intelligence = {
            "email": questionnaire.get("email"),
            "narrative_summary": narrative_text,
            "persona_metrics": {
                "macro_confidence": confidence_data.get("macro_confidence"),
                "persona_confidence": confidence_data.get("persona_confidence"),
                "data_completeness": confidence_data.get("data_completeness")
            },
            "strategic_recommendations": ai_data.get("recommendations", []) if isinstance(ai_data, dict) else [],
            "feasibility_status": "WARNING" if is_budget_unknown else "VALID",
            "feasibility_alerts": ["Budget undefined"] if is_budget_unknown else []
        }

        pax_count = SystemContractMerger._compute_pax_count(questionnaire)
        timing = SystemContractMerger._compute_timing_matrix(questionnaire, ai_data)
        geography = SystemContractMerger._resolve_geography(questionnaire, ai_data)
        financials = SystemContractMerger._compute_financials_logic(questionnaire, pax_count)
        specifications = SystemContractMerger._normalize_specs(questionnaire)

        contract = {
            "meta": meta,
            "user_intelligence": user_intelligence,
            "timing": timing,
            "geography": geography,
            "financials": financials,
            "specifications": specifications
        }

        return contract

    @staticmethod
    def _compute_pax_count(q: Dict) -> int:
        group_type = q.get("groupe_voyage", "solo")
        if group_type == "solo":
            return 1
        if group_type == "duo":
            return 2
        try:
            return int(q.get("nombre_voyageurs", 1))
        except:
            return 1

    @staticmethod
    def _compute_timing_matrix(q: Dict, ai: Dict) -> Dict:
        type_dates = q.get("type_dates", "flexible")
        
        duration = None
        if isinstance(ai, dict):
            trip_details = ai.get("trip_details") or {}
            if isinstance(trip_details, dict):
                duration_block = trip_details.get("duration") or {}
                if isinstance(duration_block, dict) and isinstance(duration_block.get("nights"), int):
                    duration = duration_block.get("nights")
        if duration is None:
            raw_duree = str(q.get("nuits_exactes") or q.get("duree") or "7")
            match_duree = re.search(r'(\d+)', raw_duree)
            duration = int(match_duree.group(1)) if match_duree else 7

        request_type = type_dates
        if type_dates == "fixed":
            request_type = "FIXED"
        elif type_dates == "no_dates":
            request_type = "OPEN_TIMING"
        elif type_dates == "flexible":
            request_type = "FLEXIBLE_RANGE"
        else:
            request_type = str(type_dates).upper()

        timing = {
            "request_type": request_type,
            "duration_target": duration,
            "duration_min_nights": duration,
            "duration_max_nights": duration,
            "departure_dates_whitelist": [],
            "return_dates_whitelist": []
        }

        if type_dates == "fixed":
            if q.get("date_depart"):
                timing["departure_dates_whitelist"] = [q.get("date_depart")]
            if q.get("date_retour"):
                timing["return_dates_whitelist"] = [q.get("date_retour")]
            return timing

        if type_dates == "no_dates":
            timing["request_type"] = "OPEN_TIMING"
            start_window = datetime.utcnow() + timedelta(days=90)
            for i in range(14):
                timing["departure_dates_whitelist"].append((start_window + timedelta(days=i)).strftime("%Y-%m-%d"))
            return timing

        pivot_str = None
        if isinstance(ai, dict):
            trip_frame = ai.get("trip_frame") or {}
            if isinstance(trip_frame, dict):
                dates = trip_frame.get("dates") or {}
                if isinstance(dates, dict):
                    departure_dates = dates.get("departure_dates") or []
                    if isinstance(departure_dates, list) and departure_dates:
                        pivot_str = str(departure_dates[0])
                    return_dates = dates.get("return_dates") or []
                    if isinstance(return_dates, list) and return_dates:
                        timing["return_dates_whitelist"] = [str(d) for d in return_dates]

        if not pivot_str:
            pivot_str = q.get("date_depart_approximative") or q.get("date_depart")

        if not pivot_str:
            return timing

        try:
            clean_date = str(pivot_str).split("T")[0]
            pivot = datetime.fromisoformat(clean_date)
        except:
            return timing

        flex_str = str(q.get("flexibilite", "0"))
        match_flex = re.search(r'(\d+)', flex_str)
        flex_count = int(match_flex.group(1)) if match_flex else 0

        if flex_count <= 0:
            timing["departure_dates_whitelist"] = [pivot.strftime("%Y-%m-%d")]
        else:
            dates = []
            for offset in range(flex_count):
                dates.append((pivot + timedelta(days=offset)).strftime("%Y-%m-%d"))
            timing["departure_dates_whitelist"] = dates

        return timing

    @staticmethod
    def _resolve_geography(q: Dict, ai: Dict) -> Dict:
        origin_city = None
        if isinstance(ai, dict):
            trip_frame = ai.get("trip_frame") or {}
            if isinstance(trip_frame, dict):
                origin_block = trip_frame.get("origin") or {}
                if isinstance(origin_block, dict):
                    origin_city = origin_block.get("city") or origin_block.get("name")
        origin_raw = q.get("lieu_depart")
        if not origin_city and origin_raw:
            origin_city = origin_raw.split(",")[0].strip()
        if not origin_city:
            origin_city = "Unknown"

        origin_iata = None
        if isinstance(ai, dict):
            trip_frame = ai.get("trip_frame") or {}
            if isinstance(trip_frame, dict):
                origin_block = trip_frame.get("origin") or {}
                if isinstance(origin_block, dict):
                    origin_iata = origin_block.get("iata")

        if not origin_iata and origin_city:
            origin_iata = origin_city[:3].upper()

        has_dest = q.get("a_destination") == "yes"
        dest_city = None
        dest_country = None

        if isinstance(ai, dict):
            trip_frame = ai.get("trip_frame") or {}
            if isinstance(trip_frame, dict):
                destinations = trip_frame.get("destinations") or []
                if isinstance(destinations, list) and destinations:
                    dest_block = destinations[0]
                    if isinstance(dest_block, dict):
                        dest_city = dest_block.get("city") or dest_block.get("name")
                        dest_country = dest_block.get("country")

        if has_dest and not dest_city:
            dest_raw = q.get("destination", "") or ""
            if dest_raw:
                parts = dest_raw.split(",")
                dest_city = parts[0].strip()
                if len(parts) > 1:
                    raw_country = parts[1]
                    cleaned_country = re.sub(r"[^\w\s\-]", "", raw_country).strip()
                    dest_country = cleaned_country or None

        discovery_criteria = {}
        if not has_dest:
            discovery_criteria = {
                "climate": SystemContractMerger._parse_json_field(q.get("preference_climat")),
                "vibe": SystemContractMerger._parse_json_field(q.get("ambiance_voyage"))
            }

        return {
            "origin_city": origin_city,
            "origin_iata": origin_iata,
            "destination_is_defined": has_dest,
            "destination_city": dest_city,
            "destination_country": dest_country,
            "discovery_criteria": discovery_criteria
        }

    @staticmethod
    def _compute_financials_logic(q: Dict, pax: int) -> Dict:
        raw_budget = str(q.get("budget_par_personne") or q.get("montant_budget") or "").lower()
        
        ignorer = ["know", "sais pas", "don't", "dont", "indéfini", "indefini", "tbd", "undefined", "none"]
        
        if any(x in raw_budget for x in ignorer) or not raw_budget.strip() or raw_budget == "none":
            return {
                "currency": "EUR",
                "status": "OPEN_DISCOVERY", 
                "total_hard_cap": None,
                "total_soft_cap": None,
                "pax_count": pax
            }

        clean_str = re.sub(r'(?<=\d)\s(?=\d)', '', raw_budget)
        nums = [int(n) for n in re.findall(r'\d+', clean_str)]
        
        if not nums:
            return {
                "currency": "EUR",
                "status": "OPEN_DISCOVERY",
                "total_hard_cap": None,
                "total_soft_cap": None,
                "pax_count": pax
            }

        return {
            "currency": "EUR",
            "status": "DEFINED",
            "total_hard_cap": max(nums) * pax,
            "total_soft_cap": min(nums) * pax,
            "pax_count": pax
        }

    @staticmethod
    def _normalize_specs(q: Dict) -> Dict:
        help_with = SystemContractMerger._parse_json_field(q.get("help_with") or q.get("aide_avec"))

        accommodation_specs = {"required": False, "details": None}
        if "accommodation" in help_with or "hébergement" in help_with:
            raw_amenities = SystemContractMerger._parse_json_field(q.get("equipements"))
            
            raw_dump = json.dumps(raw_amenities).lower()
            if "dont_mind" in raw_dump:
                req_amenities = []
            else:
                req_amenities = raw_amenities
            
            confort_raw = str(q.get("confort", "7.0"))
            match_rating = re.search(r'(\d+\.?\d*)', confort_raw)
            min_rating = float(match_rating.group(1)) if match_rating else 7.0
            
            types_allowed = SystemContractMerger._parse_json_field(q.get("type_hebergement"))
            location_vibe = q.get("quartier") or "Balanced"

            accommodation_specs = {
                "required": True,
                "types_allowed": types_allowed,
                "min_rating_10": min_rating,
                "required_amenities": req_amenities,
                "location_vibe": location_vibe
            }
        
        flight_specs = {"required": False, "details": None}
        if "flights" in help_with or "vols" in help_with:
            pref_vol = str(q.get("preference_vol", "cheapest")).lower()
            
            stopover = "2+" 
            if "fastest" in pref_vol or "rapide" in pref_vol:
                stopover = "1"
            if "direct" in pref_vol:
                stopover = "0"
            
            bagages_data = q.get("bagages", {})
            if isinstance(bagages_data, str):
                try:
                    bagages_data = json.loads(bagages_data)
                except:
                    bagages_data = {}
            
            has_hold = False
            if isinstance(bagages_data, dict):
                has_hold = any("hold" in str(v).lower() or "checked" in str(v).lower() for v in bagages_data.values())

            cabin_class = "ECONOMY"
            if "business" in pref_vol:
                cabin_class = "BUSINESS"
            elif "premium" in pref_vol:
                cabin_class = "PREMIUM_ECONOMY"

            flight_specs = {
                "required": True,
                "cabin_class": cabin_class,
                "luggage_policy": "CHECKED" if has_hold else "CARRY_ON",
                "stopover_tolerance": stopover
            }

        experience_required = "activities" in help_with or "activités" in help_with or "activity" in help_with
        experience_specs = {
            "required": experience_required,
            "pace": str(q.get("rythme", "BALANCED")).upper(),
            "interest_vectors": SystemContractMerger._parse_json_field(q.get("styles")),
            "constraints": SystemContractMerger._parse_json_field(q.get("securite")) + SystemContractMerger._parse_json_field(q.get("contraintes"))
        }

        return {
            "flights": flight_specs,
            "accommodation": accommodation_specs,
            "experience": experience_specs
        }

    @staticmethod
    def _parse_phase1_data(phase1_raw: Any) -> Dict:
        try:
            data = phase1_raw
            if isinstance(phase1_raw, str):
                clean = re.sub(r'```yaml|```json|```', '', phase1_raw).strip()
                try:
                    data = yaml.safe_load(clean)
                except:
                    try:
                        data = json.loads(clean)
                    except:
                        data = {}
            if not isinstance(data, dict):
                return {}
            if "normalized_trip_request" in data:
                return data.get("normalized_trip_request") or {}
            structured_output = data.get("structured_output")
            if isinstance(structured_output, dict) and "normalized_trip_request" in structured_output:
                return structured_output.get("normalized_trip_request") or {}
            if "trip_frame" in data or "recommendations" in data or "metadata" in data:
                return data
            return {}
        except:
            return {}

    @staticmethod
    def _extract_narrative(ai_data: Dict) -> str:
        if not isinstance(ai_data, dict):
            return ""
        if "recommendations" in ai_data:
            recs = ai_data.get("recommendations") or []
            if isinstance(recs, list) and len(recs) > 0:
                texts = [str(r.get("text", "")).strip() for r in recs if isinstance(r, dict) and r.get("text")]
                texts = [t for t in texts if t]
                if texts:
                    return " | ".join(texts)
        if "user_intelligence" in ai_data and isinstance(ai_data.get("user_intelligence"), dict):
            return str(ai_data["user_intelligence"].get("narrative_summary") or "")
        return ""

    @staticmethod
    def _parse_json_field(field: Any) -> List[str]:
        if field is None:
            return []
        if isinstance(field, list):
            return field
        s_field = str(field).strip()
        if not s_field:
            return []
        try:
            value = json.loads(s_field)
            if isinstance(value, list):
                return value
        except:
            pass
        try:
            val = ast.literal_eval(s_field)
            if isinstance(val, list):
                return val
        except:
            pass
        clean = s_field.replace("[", "").replace("]", "").replace('"', "").replace("'", "")
        if "," in clean:
            return [x.strip() for x in clean.split(",") if x.strip()]
        return [s_field]
