# 🏗️ Plan: Incremental Trip JSON Builder

## 📋 Philosophie de la Nouvelle Approche

### ❌ Ancien Système (Consolidation Finale)
```
Agents → Outputs séparés → Assembleur final → JSON complet → BDD
              ↓
   Problème: Images manquantes, GPS manquants, etc.
```

### ✅ Nouveau Système (Construction Progressive)
```
PHASE1 → Initialiser JSON vide → PHASE2 (agents enrichissent) → PHASE3 (validation) → BDD
                ↓                          ↓                           ↓
         Structure créée           Chaque agent ajoute         Vérification qualité
         avec N steps vides        ses données au JSON         vs préférences user
```

**Avantages**:
- ✅ **Garantie de complétude**: Chaque agent remplit ses champs, on voit immédiatement ce qui manque
- ✅ **Images en temps réel**: Dès qu'un step a un titre, on génère l'image
- ✅ **Validation progressive**: On peut vérifier à chaque étape si le JSON est complet
- ✅ **Meilleure traçabilité**: On sait exactement quel agent a ajouté quelle donnée
- ✅ **Pas de perte d'information**: Le JSON est l'état central, pas de mapping à faire

---

## 🏗️ Architecture: IncrementalTripBuilder

### 1. Classe IncrementalTripBuilder

```python
class IncrementalTripBuilder:
    """
    Builder qui construit le trip JSON progressivement pendant l'exécution de la pipeline.

    Flow:
    1. Après PHASE1 (destination connue) → initialize_structure()
    2. Pendant PHASE2 → Chaque agent enrichit via setters
    3. Après PHASE3 → get_json() pour sauvegarder
    """

    def __init__(self, questionnaire: Dict[str, Any]):
        """Initialiser avec le questionnaire."""
        self.questionnaire = questionnaire
        self.trip_json = None  # Sera créé dans initialize_structure()
        self.mcp_tools = []  # Pour appels directs si besoin

    # ===================================================================
    # INITIALIZATION (après PHASE1 - dès qu'on a destination + dates)
    # ===================================================================

    def initialize_structure(
        self,
        destination: str,
        destination_en: str,
        start_date: str,
        rhythm: str,  # "relaxed", "balanced", "intense"
        mcp_tools: List[Any],
    ) -> None:
        """
        Crée la structure JSON vide avec le bon nombre de steps.

        Calcul du nombre de steps:
        - Nombre de jours = (end_date - start_date) ou durée questionnaire
        - Nombre de steps = jours × multiplicateur selon rythme:
          * relaxed: 1-2 steps/jour → multiplicateur 1.5
          * balanced: 1-2 steps/jour → multiplicateur 1.5
          * intense: 2-3 steps/jour → multiplicateur 2.5
        """
        self.mcp_tools = mcp_tools

        # Calculer nombre de jours
        total_days = self._calculate_total_days(start_date)

        # Calculer nombre de steps selon rythme
        num_steps = self._calculate_steps_count(total_days, rhythm)

        # Générer code unique
        code = self._generate_code(destination)

        # Créer structure vide
        self.trip_json = {
            "trip": {
                "code": code,
                "destination": destination,
                "destination_en": destination_en,
                "total_days": total_days,
                "main_image": "",
                "flight_from": "",
                "flight_to": "",
                "flight_duration": "",
                "flight_type": "",
                "hotel_name": "",
                "hotel_rating": 0,
                "total_price": "",
                "total_budget": "",
                "average_weather": "",
                "travel_style": "",
                "travel_style_en": "",
                "start_date": start_date,
                "travelers": self.questionnaire.get("nombre_voyageurs", 2),
                "price_flights": "",
                "price_hotels": "",
                "price_transport": "",
                "price_activities": "",
            },
            "steps": []
        }

        # Créer steps vides (activités)
        for i in range(1, num_steps + 1):
            day_number = self._calculate_day_number(i, rhythm)
            self.trip_json["steps"].append({
                "step_number": i,
                "day_number": day_number,
                "title": "",
                "title_en": "",
                "subtitle": "",
                "subtitle_en": "",
                "main_image": "",
                "step_type": "",
                "is_summary": False,
                "latitude": 0,
                "longitude": 0,
                "why": "",
                "why_en": "",
                "tips": "",
                "tips_en": "",
                "transfer": "",
                "transfer_en": "",
                "suggestion": "",
                "suggestion_en": "",
                "weather_icon": "",
                "weather_temp": "",
                "weather_description": "",
                "weather_description_en": "",
                "price": 0,
                "duration": "",
                "images": []
            })

        # Ajouter step summary (toujours la dernière)
        self.trip_json["steps"].append({
            "step_number": 99,
            "day_number": 0,
            "title": "Résumé du voyage",
            "title_en": "Trip Summary",
            "subtitle": "",
            "subtitle_en": "",
            "main_image": "",
            "step_type": "summary",
            "is_summary": True,
            "latitude": 0,
            "longitude": 0,
            "why": "",
            "why_en": "",
            "tips": "",
            "tips_en": "",
            "transfer": "",
            "transfer_en": "",
            "suggestion": "",
            "suggestion_en": "",
            "weather_icon": "",
            "weather_temp": "",
            "weather_description": "",
            "weather_description_en": "",
            "price": 0,
            "duration": "",
            "images": [],
            "summary_stats": [
                {"type": "days", "value": total_days},
                {"type": "budget", "value": ""},
                {"type": "weather", "value": ""},
                {"type": "style", "value": ""},
                {"type": "people", "value": self.questionnaire.get("nombre_voyageurs", 2)},
                {"type": "activities", "value": num_steps},
                {"type": "cities", "value": 0}
            ]
        })

        logger.info(f"🏗️ Structure JSON initialisée: {code}")
        logger.info(f"   - Destination: {destination}")
        logger.info(f"   - Jours: {total_days}")
        logger.info(f"   - Rythme: {rhythm}")
        logger.info(f"   - Steps: {num_steps} activités + 1 summary")

    # ===================================================================
    # TRIP-LEVEL SETTERS (pour enrichir le trip principal)
    # ===================================================================

    def set_hero_image(self, url: str) -> None:
        """Définir l'image hero du trip."""
        self.trip_json["trip"]["main_image"] = url
        logger.info(f"🖼️ Hero image définie: {url[:80]}")

    def set_flight_info(
        self,
        flight_from: str,
        flight_to: str,
        duration: str = "",
        flight_type: str = "",
        price: str = "",
    ) -> None:
        """Définir les informations de vol."""
        trip = self.trip_json["trip"]
        trip["flight_from"] = flight_from
        trip["flight_to"] = flight_to
        trip["flight_duration"] = duration
        trip["flight_type"] = flight_type
        trip["price_flights"] = price
        logger.info(f"✈️ Vol défini: {flight_from} → {flight_to}")

    def set_hotel_info(
        self,
        hotel_name: str,
        hotel_rating: float = 0,
        price: str = "",
    ) -> None:
        """Définir les informations d'hébergement."""
        trip = self.trip_json["trip"]
        trip["hotel_name"] = hotel_name
        trip["hotel_rating"] = hotel_rating
        trip["price_hotels"] = price
        logger.info(f"🏨 Hébergement défini: {hotel_name} ({hotel_rating}⭐)")

    def set_prices(
        self,
        total_price: str,
        price_flights: str = "",
        price_hotels: str = "",
        price_transport: str = "",
        price_activities: str = "",
    ) -> None:
        """Définir les prix."""
        trip = self.trip_json["trip"]
        trip["total_price"] = total_price
        trip["total_budget"] = total_price
        if price_flights:
            trip["price_flights"] = price_flights
        if price_hotels:
            trip["price_hotels"] = price_hotels
        if price_transport:
            trip["price_transport"] = price_transport
        if price_activities:
            trip["price_activities"] = price_activities
        logger.info(f"💰 Budget défini: {total_price}")

    def set_weather(self, average_weather: str) -> None:
        """Définir la météo moyenne."""
        self.trip_json["trip"]["average_weather"] = average_weather

    def set_travel_style(self, style: str, style_en: str) -> None:
        """Définir le style de voyage."""
        self.trip_json["trip"]["travel_style"] = style
        self.trip_json["trip"]["travel_style_en"] = style_en

    # ===================================================================
    # STEP-LEVEL SETTERS (pour enrichir chaque step)
    # ===================================================================

    def set_step_title(
        self,
        step_number: int,
        title: str,
        title_en: str = "",
        subtitle: str = "",
        subtitle_en: str = "",
    ) -> None:
        """Définir le titre d'une step."""
        step = self._get_step(step_number)
        step["title"] = title
        step["title_en"] = title_en or title
        step["subtitle"] = subtitle
        step["subtitle_en"] = subtitle_en or subtitle
        logger.info(f"📝 Step {step_number}: Titre défini '{title}'")

    def set_step_image(self, step_number: int, image_url: str) -> None:
        """
        Définir l'image d'une step.

        Si l'image est vide ou invalide, appeler images.background() directement.
        """
        step = self._get_step(step_number)

        # Vérifier si l'image est valide (Supabase)
        if image_url and "supabase.co" in image_url:
            step["main_image"] = image_url
            logger.info(f"🖼️ Step {step_number}: Image définie (Supabase)")
        else:
            # Appel MCP direct en fallback
            logger.warning(f"⚠️ Step {step_number}: Image invalide, appel MCP...")
            city = self.trip_json["trip"]["destination"].split(',')[0].strip()
            country = self.trip_json["trip"]["destination"].split(',')[-1].strip()

            mcp_image = self._call_mcp_images_background(
                query=step.get("title", f"Activity {step_number}"),
                city=city,
                country=country,
                step_number=step_number,
            )

            if mcp_image:
                step["main_image"] = mcp_image
                logger.info(f"✅ Step {step_number}: Image générée via MCP")
            else:
                # Fallback Unsplash
                fallback_url = self._build_fallback_image(step.get("title", "travel"))
                step["main_image"] = fallback_url
                logger.warning(f"⚠️ Step {step_number}: Fallback Unsplash")

    def set_step_gps(
        self,
        step_number: int,
        latitude: float,
        longitude: float,
    ) -> None:
        """Définir les coordonnées GPS d'une step."""
        step = self._get_step(step_number)
        step["latitude"] = latitude
        step["longitude"] = longitude
        logger.info(f"📍 Step {step_number}: GPS défini ({latitude}, {longitude})")

    def set_step_content(
        self,
        step_number: int,
        why: str = "",
        why_en: str = "",
        tips: str = "",
        tips_en: str = "",
        transfer: str = "",
        transfer_en: str = "",
    ) -> None:
        """Définir le contenu textuel d'une step."""
        step = self._get_step(step_number)
        if why:
            step["why"] = why
        if why_en:
            step["why_en"] = why_en
        if tips:
            step["tips"] = tips
        if tips_en:
            step["tips_en"] = tips_en
        if transfer:
            step["transfer"] = transfer
        if transfer_en:
            step["transfer_en"] = transfer_en

    def set_step_weather(
        self,
        step_number: int,
        icon: str,
        temp: str,
        description: str = "",
        description_en: str = "",
    ) -> None:
        """Définir la météo d'une step."""
        step = self._get_step(step_number)
        step["weather_icon"] = icon
        step["weather_temp"] = temp
        step["weather_description"] = description
        step["weather_description_en"] = description_en

    def set_step_price_duration(
        self,
        step_number: int,
        price: float = 0,
        duration: str = "",
    ) -> None:
        """Définir le prix et la durée d'une step."""
        step = self._get_step(step_number)
        step["price"] = price
        step["duration"] = duration

    def set_step_type(self, step_number: int, step_type: str) -> None:
        """Définir le type d'une step (activity, restaurant, transport, etc.)."""
        step = self._get_step(step_number)
        step["step_type"] = step_type

    # ===================================================================
    # SUMMARY STATS
    # ===================================================================

    def update_summary_stats(self) -> None:
        """Mettre à jour les summary_stats de la step summary."""
        summary_step = self._get_summary_step()
        trip = self.trip_json["trip"]

        # Calculer les activités (steps hors summary)
        activities_count = len([s for s in self.trip_json["steps"] if not s.get("is_summary", False)])

        summary_step["summary_stats"] = [
            {"type": "days", "value": trip["total_days"]},
            {"type": "budget", "value": trip["total_price"] or trip["total_budget"]},
            {"type": "weather", "value": trip["average_weather"]},
            {"type": "style", "value": trip["travel_style"]},
            {"type": "people", "value": trip["travelers"]},
            {"type": "activities", "value": activities_count},
            {"type": "cities", "value": 1},  # TODO: Compter les villes uniques
        ]

        logger.info(f"📊 Summary stats mis à jour: {len(summary_step['summary_stats'])} stats")

    # ===================================================================
    # GETTERS & UTILITIES
    # ===================================================================

    def get_json(self) -> Dict[str, Any]:
        """Retourner le JSON complet."""
        return self.trip_json

    def get_current_state_yaml(self) -> str:
        """
        Retourner l'état courant en YAML pour le passer aux agents.

        Les agents peuvent voir ce qui a déjà été rempli et ce qui manque.
        """
        import yaml
        return yaml.dump(self.trip_json, allow_unicode=True, sort_keys=False)

    def get_completeness_report(self) -> Dict[str, Any]:
        """
        Générer un rapport de complétude pour debug/validation.

        Retourne:
        - % de champs trip remplis
        - % de steps avec titre
        - % de steps avec image
        - % de steps avec GPS
        """
        trip = self.trip_json["trip"]
        steps = [s for s in self.trip_json["steps"] if not s.get("is_summary", False)]

        # Trip-level completeness
        trip_fields_filled = sum([1 for v in trip.values() if v and v != "" and v != 0])
        trip_total_fields = len(trip)
        trip_completeness = (trip_fields_filled / trip_total_fields) * 100

        # Steps completeness
        steps_with_title = sum([1 for s in steps if s.get("title")])
        steps_with_image = sum([1 for s in steps if s.get("main_image") and s["main_image"] != ""])
        steps_with_gps = sum([1 for s in steps if s.get("latitude") and s.get("longitude")])

        return {
            "trip_completeness": f"{trip_completeness:.1f}%",
            "steps_with_title": f"{steps_with_title}/{len(steps)}",
            "steps_with_image": f"{steps_with_image}/{len(steps)}",
            "steps_with_gps": f"{steps_with_gps}/{len(steps)}",
            "missing_critical": self._find_missing_critical_fields(),
        }

    def _get_step(self, step_number: int) -> Dict[str, Any]:
        """Récupérer une step par son numéro."""
        for step in self.trip_json["steps"]:
            if step["step_number"] == step_number:
                return step
        raise ValueError(f"Step {step_number} not found")

    def _get_summary_step(self) -> Dict[str, Any]:
        """Récupérer la step summary."""
        for step in self.trip_json["steps"]:
            if step.get("is_summary", False):
                return step
        raise ValueError("Summary step not found")

    def _calculate_total_days(self, start_date: str) -> int:
        """Calculer le nombre total de jours."""
        # Essayer depuis questionnaire
        duree_str = self.questionnaire.get("duree", "")
        match = re.search(r'(\d+)', str(duree_str))
        if match:
            return int(match.group(1))

        # Défaut
        return 7

    def _calculate_steps_count(self, total_days: int, rhythm: str) -> int:
        """
        Calculer le nombre de steps selon le rythme.

        - relaxed: 1-2 steps/jour → 1.5 steps/jour en moyenne
        - balanced: 1-2 steps/jour → 1.5 steps/jour en moyenne
        - intense: 2-3 steps/jour → 2.5 steps/jour en moyenne
        """
        multipliers = {
            "relaxed": 1.5,
            "balanced": 1.5,
            "intense": 2.5,
        }

        multiplier = multipliers.get(rhythm, 1.5)
        return max(3, int(total_days * multiplier))  # Minimum 3 steps

    def _calculate_day_number(self, step_number: int, rhythm: str) -> int:
        """Calculer le numéro du jour pour une step donnée."""
        if rhythm == "relaxed":
            # 1-2 steps/jour → step 1-2 = jour 1, step 3-4 = jour 2
            return (step_number - 1) // 2 + 1
        elif rhythm == "balanced":
            return (step_number - 1) // 2 + 1
        else:  # intense
            # 2-3 steps/jour → step 1-2 = jour 1, step 3-5 = jour 2
            return (step_number - 1) // 3 + 1

    def _generate_code(self, destination: str) -> str:
        """Générer un code unique pour le trip."""
        import uuid
        clean_dest = re.sub(r'[^A-Z0-9]', '', destination.upper().split(',')[0])[:15]
        year = datetime.utcnow().year
        unique_id = str(uuid.uuid4())[:6].upper()
        return f"{clean_dest}-{year}-{unique_id}"

    def _call_mcp_images_background(
        self,
        query: str,
        city: str,
        country: str,
        step_number: int,
    ) -> Optional[str]:
        """Appeler images.background MCP directement."""
        for tool in self.mcp_tools:
            if hasattr(tool, 'name') and tool.name == "images.background":
                try:
                    result = tool.func(
                        query=query,
                        city=city,
                        country=country,
                        trip_code=self.trip_json["trip"]["code"],
                        step_number=step_number,
                    )
                    return result
                except Exception as e:
                    logger.error(f"❌ MCP images.background failed: {e}")
                    return None
        return None

    def _build_fallback_image(self, query: str) -> str:
        """Construire une URL Unsplash fallback."""
        clean_query = re.sub(r'[^a-zA-Z0-9\s]', '', query).strip().replace(' ', '%20')
        return f"https://source.unsplash.com/800x600/?{clean_query},travel,activity"

    def _find_missing_critical_fields(self) -> List[str]:
        """Identifier les champs critiques manquants."""
        missing = []
        trip = self.trip_json["trip"]

        if not trip.get("main_image"):
            missing.append("trip.main_image")
        if not trip.get("total_price") and not trip.get("total_budget"):
            missing.append("trip.total_price")

        steps = [s for s in self.trip_json["steps"] if not s.get("is_summary", False)]
        for step in steps:
            step_num = step["step_number"]
            if not step.get("title"):
                missing.append(f"step_{step_num}.title")
            if not step.get("main_image"):
                missing.append(f"step_{step_num}.main_image")

        return missing
```

---

## 🔄 Nouveau Flow de la Pipeline

### PHASE 1: Context + Destination (INCHANGÉ)

```python
# Agents
- trip_context_builder: Analyse questionnaire + persona
- destination_strategist: Choisit/valide destination + code voyage

# Outputs
- trip_context: Dict avec infos normalisées
- destination_choice: Dict avec destination, destination_en, dates, etc.
```

### 🆕 INITIALIZATION (Nouveau point d'entrée)

**Quand**: Dès qu'on a la destination et les dates (fin PHASE1)

```python
# Créer le builder
builder = IncrementalTripBuilder(questionnaire=normalized_questionnaire)

# Initialiser la structure JSON vide
builder.initialize_structure(
    destination=destination_choice["destination"],
    destination_en=destination_choice["destination_en"],
    start_date=destination_choice.get("start_date") or questionnaire["date_depart"],
    rhythm=questionnaire["rythme"],  # "relaxed", "balanced", "intense"
    mcp_tools=mcp_tools,
)

# À ce stade, on a un JSON avec:
# - trip: code, destination, total_days remplis, reste vide
# - steps: N steps vides + 1 summary step
```

### PHASE 2: Enrichment Progressif

**Chaque agent enrichit le JSON au lieu de produire son output séparé**

#### Agent 3: flights_specialist

```python
# Prompt enrichi avec le JSON courant
inputs = {
    "trip_context": trip_context_yaml,
    "destination": destination_choice_yaml,
    "current_trip_json": builder.get_current_state_yaml(),  # ← NOUVEAU
}

output = flights_specialist.run(inputs)

# Extraire les infos et mettre à jour le builder
flight_info = parse_flight_output(output)
builder.set_flight_info(
    flight_from=flight_info["from"],
    flight_to=flight_info["to"],
    duration=flight_info["duration"],
    flight_type=flight_info["type"],
    price=flight_info["price"],
)
```

#### Agent 4: accommodation_specialist

```python
# Prompt avec JSON courant
output = accommodation_specialist.run({
    "current_trip_json": builder.get_current_state_yaml(),
    ...
})

# Mettre à jour
hotel_info = parse_hotel_output(output)
builder.set_hotel_info(
    hotel_name=hotel_info["name"],
    hotel_rating=hotel_info["rating"],
    price=hotel_info["price"],
)
```

#### Agent 5: trip_structure_planner (optionnel)

**Note**: La structure est déjà créée dans `initialize_structure()`, donc cet agent peut être:
- Soit supprimé (structure calculée automatiquement)
- Soit gardé pour affiner la répartition des activités par jour

#### Agent 6: itinerary_designer ⭐ (AGENT CRITIQUE)

**C'est l'agent le plus important: il remplit TOUTES les steps**

```python
# Prompt avec JSON courant + structure
output = itinerary_designer.run({
    "current_trip_json": builder.get_current_state_yaml(),
    "destination": destination_choice_yaml,
    "structure_plan": structure_plan_yaml,
})

# Parser l'output (agent retourne les steps remplies)
steps_data = parse_itinerary_output(output)

# Pour chaque step, enrichir le JSON
for step_num, step_data in steps_data.items():
    # 1. Titre
    builder.set_step_title(
        step_number=step_num,
        title=step_data["title"],
        title_en=step_data["title_en"],
        subtitle=step_data.get("subtitle", ""),
        subtitle_en=step_data.get("subtitle_en", ""),
    )

    # 2. GPS
    if step_data.get("latitude") and step_data.get("longitude"):
        builder.set_step_gps(
            step_number=step_num,
            latitude=step_data["latitude"],
            longitude=step_data["longitude"],
        )

    # 3. Image (CRITIQUE - génération en temps réel)
    image_url = step_data.get("main_image")
    builder.set_step_image(step_number=step_num, image_url=image_url)
    # ↑ Si image_url vide ou invalide, le builder appellera MCP automatiquement

    # 4. Contenu
    builder.set_step_content(
        step_number=step_num,
        why=step_data.get("why", ""),
        why_en=step_data.get("why_en", ""),
        tips=step_data.get("tips", ""),
        tips_en=step_data.get("tips_en", ""),
    )

    # 5. Météo
    if step_data.get("weather_icon"):
        builder.set_step_weather(
            step_number=step_num,
            icon=step_data["weather_icon"],
            temp=step_data.get("weather_temp", ""),
        )

    # 6. Prix et durée
    builder.set_step_price_duration(
        step_number=step_num,
        price=step_data.get("price", 0),
        duration=step_data.get("duration", ""),
    )

# Générer l'image hero du trip
hero_image = parse_hero_image(output)
builder.set_hero_image(hero_image)
```

### PHASE 3: Budget + Validation

#### Agent 7: budget_calculator

```python
output = budget_calculator.run({
    "current_trip_json": builder.get_current_state_yaml(),
    ...
})

# Mettre à jour les prix
budget_data = parse_budget_output(output)
builder.set_prices(
    total_price=budget_data["total"],
    price_flights=budget_data["flights"],
    price_hotels=budget_data["hotels"],
    price_transport=budget_data["transport"],
    price_activities=budget_data["activities"],
)

# Mettre à jour summary stats
builder.update_summary_stats()
```

#### 🆕 Agent 8: final_validator (NOUVEAU - remplace final_assembler)

**Rôle**: Valider la qualité du trip vs préférences utilisateur, pas juste le schéma

```python
# Prompt spécial: valider la qualité
inputs = {
    "questionnaire": questionnaire_yaml,
    "persona_inference": persona_yaml,
    "current_trip_json": builder.get_current_state_yaml(),
    "completeness_report": builder.get_completeness_report(),
}

output = final_validator.run(inputs)

# Parser la validation
validation = parse_validation_output(output)

if validation["status"] == "OK":
    logger.info("✅ Validation OK: Trip conforme aux préférences")
elif validation["status"] == "WARNING":
    logger.warning(f"⚠️ Validation avec warnings: {validation['warnings']}")
else:  # ERROR
    logger.error(f"❌ Validation échouée: {validation['errors']}")
    # Décision: sauvegarder quand même ou rejeter ?
```

### SAVE: Validation Schema + BDD

```python
# 1. Récupérer le JSON final
trip_json = builder.get_json()

# 2. Validation schema (comme avant)
is_valid, schema_error = validate_trip_schema(trip_json["trip"])

if not is_valid:
    logger.error(f"❌ Schema invalide: {schema_error}")
    # Fallback: Corriger les champs manquants automatiquement
    trip_json = fix_missing_fields(trip_json)

# 3. Sauvegarder en BDD
trip_id = supabase_service.insert_trip_from_json(trip_json["trip"])
```

---

## 📝 Modifications à Apporter

### 1. Créer IncrementalTripBuilder

**Fichier**: `app/crew_pipeline/scripts/incremental_trip_builder.py`

✅ Code complet fourni ci-dessus

### 2. Modifier pipeline.py

**Changements**:

```python
# Après PHASE1
builder = IncrementalTripBuilder(questionnaire=normalized_questionnaire)
builder.initialize_structure(
    destination=destination_choice["destination"],
    destination_en=destination_choice.get("destination_en", ""),
    start_date=destination_choice.get("start_date") or questionnaire.get("date_depart"),
    rhythm=questionnaire.get("rythme", "balanced"),
    mcp_tools=mcp_tools,
)

# Après chaque agent, extraire + update builder
# ... (voir exemples ci-dessus)

# À la fin
trip_json = builder.get_json()
```

### 3. Modifier les Prompts des Agents

**Changements dans tasks.yaml**:

#### flights_specialist task
```yaml
description: >-
  Rechercher les vols pour {destination}.

  🆕 NOUVEAU: Un JSON trip est en cours de construction. Voici l'état actuel:
  {current_trip_json}

  Ton rôle: Ajouter les informations de vol manquantes.

  Output attendu:
  ```yaml
  flight_from: "Bruxelles, Belgique"
  flight_to: "Bali, Indonésie"
  duration: "15h30"
  flight_type: "1 escale"
  price: "620€"
  ```
```

#### itinerary_designer task
```yaml
description: >-
  Concevoir l'itinéraire détaillé pour {destination}.

  🆕 NOUVEAU: La structure JSON est déjà créée avec {num_steps} steps vides:
  {current_trip_json}

  Ton rôle: Remplir CHAQUE step avec:
  - title + title_en (obligatoire)
  - subtitle + subtitle_en
  - GPS (appeler geo.text_to_place)
  - main_image (appeler images.background pour CHAQUE step)
  - why + why_en (2-3 phrases)
  - tips + tips_en (2-3 phrases)
  - weather_icon, weather_temp
  - price, duration

  🚨 CRITIQUE: Appelle images.background() pour CHAQUE step dès que tu as le titre.
  Ne laisse AUCUNE step sans image.

  Output: Retourne les steps complètes en YAML.
```

#### final_validator task (NOUVEAU)
```yaml
task_final_validator:
  description: >-
    Valider la qualité du trip généré vs les préférences utilisateur.

    JSON trip complet:
    {current_trip_json}

    Questionnaire utilisateur:
    {questionnaire}

    Rapport de complétude:
    {completeness_report}

    Ton rôle: Vérifier que:
    1. Toutes les préférences utilisateur sont respectées (rythme, affinités, contraintes)
    2. Le trip est complet (pas de champs manquants critiques)
    3. Les activités correspondent au persona inféré
    4. Le budget est respecté (tolérance ±15%)
    5. La qualité des steps est bonne (titres, descriptions, images)

    Output: Retourne un rapport de validation:
    ```yaml
    status: "OK" | "WARNING" | "ERROR"
    quality_score: 0-100
    warnings: ["liste des warnings"]
    errors: ["liste des erreurs critiques"]
    recommendations: ["recommandations d'amélioration"]
    ```
  expected_output: >-
    Rapport de validation YAML avec status, quality_score, warnings, errors, recommendations.
  agent: final_validator
```

### 4. Créer Agent final_validator

**Fichier**: `config/agents.yaml`

```yaml
final_validator:
  role: "Trip Quality Validator & Coordinator"
  goal: >-
    Valider que le trip généré correspond exactement aux préférences utilisateur
    et que tous les champs critiques sont remplis avec qualité.
  backstory: >-
    Coordinateur qualité expert, tu es le dernier rempart avant la sauvegarde.
    Tu vérifies que le trip respecte TOUTES les préférences utilisateur:
    rythme, affinités voyage, contraintes alimentaires, budget, style.
    Tu valides que chaque step est complète (titre, image, GPS, why, tips).
    Tu détectes les incohérences (activités inadaptées au persona, budget dépassé).
    Tu ne corriges PAS les erreurs, tu les signales avec recommandations.
  allow_delegation: false
  reasoning: true
  max_reasoning_attempts: 2
  memory: true
  max_iter: 10
```

---

## 📊 Avantages de la Nouvelle Architecture

| Aspect | Ancien | Nouveau |
|--------|--------|---------|
| **Construction** | Finale (1 fois) | Progressive (à chaque agent) |
| **Visibilité** | Opaque jusqu'à la fin | Transparente à chaque étape |
| **Images manquantes** | Découvert à la fin | Détecté immédiatement + MCP fallback |
| **GPS manquants** | Découvert à la fin | Détecté immédiatement |
| **Debugging** | Difficile (chercher dans outputs) | Facile (voir l'état du JSON) |
| **Validation** | 1 fois à la fin | Progressive + finale |
| **Qualité** | Dépend de l'agent final | Garantie par le builder + validator |
| **Traçabilité** | Quelle donnée vient d'où ? | Chaque setter est tracé |

---

## 🧪 Test de l'Implémentation

**Commande**:
```bash
python crew_pipeline_cli.py --input examples/traveller_persona_input.json
```

**Logs attendus**:

```
[PHASE1] Running trip context + destination...
✅ Destination choisie: Bali, Indonésie
🏗️ Structure JSON initialisée: BALI-2025-A3F5E1
   - Destination: Bali, Indonésie
   - Jours: 7
   - Rythme: balanced
   - Steps: 10 activités + 1 summary

[PHASE2] Enriching trip JSON...
✈️ Vol défini: Bruxelles → Bali
🏨 Hébergement défini: Ubud Resort (8.5⭐)

[Agent: itinerary_designer]
📝 Step 1: Titre défini 'Temple Tanah Lot au coucher du soleil'
⚠️ Step 1: Image invalide, appel MCP...
✅ Step 1: Image générée via MCP
📍 Step 1: GPS défini (-8.621, 115.087)
📝 Step 2: Titre défini 'Rizières en terrasses de Tegallalang'
✅ Step 2: Image générée via MCP
...

[PHASE3] Budget + Validation...
💰 Budget défini: 1300€
📊 Summary stats mis à jour: 7 stats

[Agent: final_validator]
✅ Validation OK: Trip conforme aux préférences
   - Quality score: 92/100
   - 0 erreurs critiques
   - 2 warnings: Budget légèrement dépassé (+15%)

[SAVE]
✅ Schema validation passed
💾 Trip enregistré via insert_trip_from_json
✅ Trip sauvegardé: BALI-2025-A3F5E1
```

---

## 🎯 Résumé des Actions

1. ✅ **Créer** `incremental_trip_builder.py` avec classe complète
2. ✅ **Modifier** `pipeline.py`:
   - Ajouter initialization après PHASE1
   - Après chaque agent, extraire output → update builder
   - Remplacer final assembly par validation
3. ✅ **Modifier** `tasks.yaml`:
   - Ajouter `current_trip_json` dans les prompts
   - Créer task `final_validator`
4. ✅ **Créer** agent `final_validator` dans `agents.yaml`
5. ✅ **Tester** avec input réel

Cette architecture garantit:
- ✅ Aucune image manquante (MCP fallback automatique)
- ✅ Aucun GPS manquant (calcul automatique)
- ✅ JSON toujours complet (structure créée dès le début)
- ✅ Validation qualité vs préférences utilisateur

Prêt pour l'implémentation ! 🚀
