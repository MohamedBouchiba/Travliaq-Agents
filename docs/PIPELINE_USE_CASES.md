# Cas d'Usage Critiques - Pipeline CrewAI

**Version** : 1.0
**Date** : 2025-12-10
**Objectif** : Documenter les scénarios critiques pour valider le comportement de la pipeline

---

## 📋 TABLE DES CAS D'USAGE

| # | Cas d'Usage | Priorité | Complexité | Statut Actuel |
|---|-------------|----------|------------|---------------|
| 1 | Success Complet | 🔴 CRITIQUE | Moyenne | ✅ Fonctionnel |
| 2 | Success Partiel - MCP Failure | 🔴 CRITIQUE | Haute | ⚠️ Partiellement OK |
| 3 | Failure - Destination Invalide | 🟡 HAUTE | Moyenne | ❌ À améliorer |
| 4 | Failure - Budget Insuffisant | 🟡 HAUTE | Faible | ✅ Fonctionnel |
| 5 | Partial - Aucun Service Demandé | 🟢 NORMALE | Faible | ✅ Fonctionnel |

---

## 🎯 CAS 1 : SUCCESS COMPLET

### Description
Exécution complète et réussie de la pipeline avec tous les services demandés.

### Préconditions
- Questionnaire valide avec destination connue
- MCP server disponible et fonctionnel
- Budget cohérent avec destination/durée
- Services demandés : flights, accommodation, activities

### Input
```json
{
  "questionnaire_data": {
    "destination": "Paris, France",
    "has_destination": "yes",
    "duree": "7",
    "date_depart": "2025-06-01",
    "date_retour": "2025-06-08",
    "rythme": "balanced",
    "nombre_voyageurs": 2,
    "budget_par_personne": 1500,
    "lieu_depart": "Bruxelles, Belgique",
    "help_with": ["flights", "accommodation", "activities"],
    "affinites_voyage": ["culture", "gastronomie"]
  },
  "persona_inference": {
    "persona_label": "Explorateur Culturel",
    "persona_score": 0.85
  }
}
```

### Exécution Attendue

**PHASE 1 : Context & Strategy**
- ✅ Normalisation du questionnaire
- ✅ Extraction du contexte (destination, dates, budget, voyageurs)
- ✅ Validation destination via `geo.text_to_place`
- ✅ Génération code trip (format: `PARIS-CULTURE-2025-ABC123`)
- ✅ Initialisation IncrementalTripBuilder avec 10 steps vides (7 jours × 1.5)

**PHASE 2 : Research**
- ✅ Agent Flights : Recherche vols BRU → CDG via `flights.prices`
- ✅ Agent Accommodation : Recherche hôtels Paris via `booking.search`
- ✅ Agent Structure Planner : Définit rythme 1-2 steps/jour, zones (Marais, Montmartre, etc.)
- ✅ Génération templates avec GPS via `geo.place`
- ✅ Agent Itinerary : Enrichit 10 steps avec contenu FR détaillé
- ✅ Enrichissement avec images Supabase via `images.background`

**PHASE 3 : Budget & Assembly**
- ✅ Agent Budget : Calcule total (vols + hébergement + activités + transport)
- ✅ Vérification budget : delta < 15% → OK
- ✅ Agent Assembler : Consolide JSON final avec validation

**POST-PROCESSING**
- ✅ Traduction FR → EN automatique via `translate_en`
- ✅ Validation JSON schema
- ✅ Régénération images avec prompts enrichis

**PERSISTENCE**
- ✅ Sauvegarde trip en base (table `trips`)
- ✅ Sauvegarde steps (table `steps`)
- ✅ Envoi email notification (si activé)

### Output Attendu
```json
{
  "status": "success",
  "run_id": "abc123...",
  "questionnaire_id": "q456...",
  "assembly": {
    "trip": {
      "code": "PARIS-CULTURE-2025-ABC123",
      "destination": "Paris, France 🇫🇷",
      "total_days": 7,
      "main_image": "https://supabase.co/...",
      "flight_from": "Bruxelles",
      "flight_to": "Paris",
      "hotel_name": "Hotel XYZ",
      "hotel_rating": 8.5,
      "total_price": "2800€",
      "steps": [ /* 10 activity steps + 1 summary */ ]
    }
  },
  "validation": {
    "schema_valid": true,
    "completeness": "95%"
  }
}
```

### KPIs de Succès
- ✅ Toutes les steps ont `title`, `main_image` (Supabase), `latitude`, `longitude`
- ✅ Summary step (99) avec 4-8 `summary_stats`
- ✅ Budget total delta < 15% du budget demandé
- ✅ Validation JSON schema OK
- ✅ Temps exécution < 5min

---

## ⚠️ CAS 2 : SUCCESS PARTIEL - MCP FAILURE

### Description
Pipeline réussit malgré échec partiel ou total du MCP server (fallback activé).

### Préconditions
- Questionnaire valide
- **MCP server down OU erreur réseau**
- Budget cohérent

### Input
(Même que Cas 1)

### Exécution Attendue

**PHASE 1**
- ✅ Context OK (pas de MCP requis)
- ⚠️ Destination Strategy : Échec `geo.text_to_place` → Utilise destination string directe sans GPS
- ✅ Génération code trip OK

**PHASE 2**
- ⚠️ Flights : Échec `flights.prices` → **Estimation prudente** basée sur distance
  - Log: `"⚠️ MCP flights.prices failed, using fallback estimation"`
  - Estimation: "1000-1200€ (estimation basée sur route moyenne)"
- ⚠️ Accommodation : Échec `booking.search` → **Estimation** basée sur standing
  - Log: `"⚠️ MCP booking.search failed, using fallback estimation"`
  - Estimation: "800€ pour 7 nuits en hôtel 3★"
- ⚠️ Itinerary : Échec `geo.place` → **GPS approximatifs** (centre-ville)
  - Latitude/Longitude = Centre de Paris (48.8566, 2.3522)
- ⚠️ Images : Échec `images.background` → **Fallback Unsplash**
  - URLs: `https://source.unsplash.com/...`

**PHASE 3**
- ✅ Budget : Utilise estimations
- ⚠️ Assembly : Accepte trip avec images Unsplash (fallback acceptable)

**POST-PROCESSING**
- ⚠️ Traduction : Peut échouer si service externe
- ✅ Validation : Accepte trip avec données fallback

### Output Attendu
```json
{
  "status": "success",  // ✅ Malgré MCP failure
  "warnings": [
    "MCP tools unavailable - used fallback estimations",
    "Images are Unsplash fallback - not Supabase",
    "GPS coordinates are approximate (city center)"
  ],
  "assembly": {
    "trip": {
      // ... trip valide mais avec fallbacks ...
      "flight_from": "Bruxelles",
      "flight_to": "Paris",
      "flight_duration": "1h30 (estimé)",  // ⚠️ Estimation
      "flight_type": "Estimation moyenne",
      "hotel_name": "Hôtel 3★ estimé",    // ⚠️ Estimation
      "hotel_rating": 7.5,                 // ⚠️ Estimation
      "total_price": "2900€ (estimation)",
      "steps": [
        {
          "step_number": 1,
          "latitude": 48.8566,  // ⚠️ GPS approximatif
          "longitude": 2.3522,
          "main_image": "https://source.unsplash.com/..."  // ⚠️ Fallback
        }
      ]
    }
  }
}
```

### KPIs de Succès
- ✅ Pipeline ne crash pas
- ⚠️ Trip généré avec warnings clairs
- ⚠️ Estimations réalistes et prudentes
- ✅ Logs explicites sur fallbacks utilisés

---

## ❌ CAS 3 : FAILURE - DESTINATION INVALIDE

### Description
Utilisateur fournit une destination inexistante ou mal formatée.

### Préconditions
- Questionnaire avec destination invalide
- MCP server fonctionnel

### Input
```json
{
  "questionnaire_data": {
    "destination": "Atlantide, Océan Atlantique",  // ❌ Invalide
    "has_destination": "yes",
    "duree": "7",
    // ... autres champs ...
  }
}
```

### Exécution Attendue

**PHASE 1**
- ✅ Context extraction OK
- ❌ **Destination Strategy ÉCHOUE**
  - Appel `geo.text_to_place("Atlantide, Océan Atlantique")` → Erreur 404
  - Log: `"❌ Destination 'Atlantide' non trouvée via geo.text_to_place"`
  - Agent propose 3 alternatives basées sur affinités :
    ```yaml
    options_alternatives:
      - city: "Lisbonne, Portugal"
        score: 85
        justification: "Destination côtière, culture, proche Atlantique"
      - city: "Reykjavik, Islande"
        score: 80
        justification: "Paysages uniques, nature, aventure"
      - city: "Canaries, Espagne"
        score: 75
        justification: "Îles atlantiques, plages, climat doux"
    ```

**PHASE 2+** : **NON EXÉCUTÉES** (stop après Phase 1)

### Output Attendu
```json
{
  "status": "failed_destination",
  "error_message": "Destination 'Atlantide, Océan Atlantique' introuvable",
  "suggested_alternatives": [
    {
      "city": "Lisbonne, Portugal",
      "country": "Portugal",
      "score": 85,
      "justification": "Destination côtière avec forte culture, proche de l'océan Atlantique"
    },
    {
      "city": "Reykjavik, Islande",
      "country": "Islande",
      "score": 80,
      "justification": "Paysages uniques et nature préservée, aventure garantie"
    },
    {
      "city": "Canaries, Espagne",
      "country": "Espagne",
      "score": 75,
      "justification": "Îles de l'Atlantique avec plages et climat agréable"
    }
  ],
  "action_required": "Veuillez choisir une destination parmi les suggestions ou modifier votre recherche"
}
```

### KPIs de Succès
- ✅ Erreur claire et actionable
- ✅ 3-5 suggestions pertinentes
- ✅ Pas de crash ni d'exception non gérée
- ✅ Temps réponse < 30s

---

## 💰 CAS 4 : FAILURE - BUDGET INSUFFISANT

### Description
Budget utilisateur trop bas pour la destination/durée demandée.

### Préconditions
- Questionnaire valide
- Budget très faible par rapport à destination

### Input
```json
{
  "questionnaire_data": {
    "destination": "Tokyo, Japan",
    "duree": "10",
    "nombre_voyageurs": 2,
    "budget_par_personne": 500,  // ❌ Trop bas pour Tokyo 10j
    "help_with": ["flights", "accommodation", "activities"]
  }
}
```

### Exécution Attendue

**PHASE 1 & 2**
- ✅ Exécution normale jusqu'à Phase 3

**PHASE 3**
- ✅ Flights: 1200€/personne = 2400€ total
- ✅ Accommodation: 1000€ pour 10 nuits
- ✅ Activities: 300€
- ✅ Transport local: 150€
- **❌ TOTAL: 3850€ vs Budget: 1000€ (2×500) → DELTA: +285%**

- Agent Budget détecte dépassement >15%
- Propose ajustements :
  ```yaml
  adjustments:
    - category: "Hébergement"
      action: "Passer de confort à économique (auberge/capsule)"
      saving: 600€
    - category: "Vols"
      action: "Accepter 1 escale au lieu de direct"
      saving: 400€
    - category: "Activités"
      action: "Réduire activités payantes (musées gratuits)"
      saving: 150€
    - category: "Durée"
      action: "Réduire de 10 à 7 jours"
      saving: 900€
  ```

### Output Attendu
```json
{
  "status": "budget_exceeded",
  "budget_analysis": {
    "requested": 1000,
    "estimated": 3850,
    "delta_amount": 2850,
    "delta_percent": 285,
    "status": "CRITICAL_EXCEED"
  },
  "breakdown": {
    "flights": 2400,
    "accommodation": 1000,
    "activities": 300,
    "transport": 150
  },
  "adjustments_proposed": [
    {
      "category": "Hébergement",
      "action": "Passer à économique (auberge/capsule)",
      "saving": 600,
      "new_total": 3250
    },
    {
      "category": "Vols",
      "action": "Vols avec escale",
      "saving": 400,
      "new_total": 2850
    },
    {
      "category": "Durée",
      "action": "Réduire à 7 jours",
      "saving": 900,
      "new_total": 1950
    }
  ],
  "recommendation": "Avec tous les ajustements, le budget ajusté serait de 1950€ (2×975€/personne). Cela reste au-dessus du budget initial de 1000€. Envisagez d'augmenter le budget à 1000€/personne minimum ou de choisir une destination moins coûteuse."
}
```

### KPIs de Succès
- ✅ Détection dépassement budget >15%
- ✅ Propositions d'ajustements concrètes
- ✅ Nouveau total calculé pour chaque ajustement
- ✅ Recommandation finale claire

---

## 🔄 CAS 5 : PARTIAL - AUCUN SERVICE DEMANDÉ

### Description
Utilisateur demande uniquement la génération d'itinéraire (pas de vols/hébergement).

### Préconditions
- Questionnaire valide
- `help_with`: `["activities"]` uniquement

### Input
```json
{
  "questionnaire_data": {
    "destination": "Rome, Italy",
    "duree": "5",
    "rythme": "balanced",
    "help_with": ["activities"]  // ✅ Seulement itinéraire
  }
}
```

### Exécution Attendue

**PHASE 1**
- ✅ Context & Strategy OK

**PHASE 2**
- ⏭️ **Flights SKIPPED** (not in help_with)
- ⏭️ **Accommodation SKIPPED** (not in help_with)
- ✅ Structure Planner OK
- ✅ Itinerary Designer OK

**PHASE 3**
- ⚠️ Budget : Seulement activités + transport local
- ✅ Assembly : Trip avec champs vols/hôtel vides

### Output Attendu
```json
{
  "status": "success",
  "assembly": {
    "trip": {
      "code": "ROME-CULTURE-2025-XYZ",
      "destination": "Rome, Italy 🇮🇹",
      "total_days": 5,
      "flight_from": "",       // ⚠️ Vide (not requested)
      "flight_to": "",
      "hotel_name": "",        // ⚠️ Vide (not requested)
      "total_price": "450€",   // ✅ Seulement activités + transport
      "price_flights": "",
      "price_hotels": "",
      "price_activities": "350€",
      "price_transport": "100€",
      "steps": [ /* 7 steps d'activités */ ]
    }
  }
}
```

### KPIs de Succès
- ✅ Pas de crash si services manquants
- ✅ Champs vides pour services non demandés
- ✅ Itinéraire complet et cohérent
- ✅ Budget partiel calculé correctement

---

## 🧪 VALIDATION DES CAS D'USAGE

### Checklist de Test

Pour chaque release, valider :

- [ ] **Cas 1** : Exécution complète avec MCP OK
- [ ] **Cas 2** : Fallback graceful si MCP down
- [ ] **Cas 3** : Suggestions si destination invalide
- [ ] **Cas 4** : Détection dépassement budget
- [ ] **Cas 5** : Support services partiels

### Métriques de Qualité

| Métrique | Objectif | Actuel |
|----------|----------|--------|
| Success rate (Cas 1) | >95% | ? |
| Fallback quality (Cas 2) | >80% usable trips | ? |
| Error clarity (Cas 3) | 100% suggestions | ? |
| Budget detection (Cas 4) | 100% if >15% | ? |
| Partial support (Cas 5) | 100% | ? |

---

## 📝 NOTES

- Ces cas d'usage sont des **contrats** entre pipeline et utilisateurs
- Tout changement de comportement doit être documenté ici
- Tests automatisés doivent couvrir au minimum Cas 1, 2, 4, 5

---

**Auteur** : Claude Sonnet 4.5
**Dernière mise à jour** : 2025-12-10
