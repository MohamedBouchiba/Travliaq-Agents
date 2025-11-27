# Workflow de Génération de Voyage (Trip Generation)

Ce document décrit le flux de travail complet des agents IA pour la génération de propositions de voyage dans `Travliaq-Agents`. Ce workflow est conçu en trois phases principales, allant de l'analyse du besoin utilisateur jusqu'à l'optimisation des réservations.

> [!NOTE]
> Actuellement, la **Phase 1** est implémentée dans le codebase (`agents.yaml`, `tasks.yaml`). Les **Phases 2 et 3** représentent les étapes ultérieures du pipeline (sélection de destination et réservation).

## Diagramme de Flux Global

### Légende

- **Rectangles Bleus** : Tâches réalisées par des **Agents IA**.
- **Arrondis Gris** : Tâches réalisées par des **Fonctions Python** ou Inputs/Outputs.

## Description des Phases

- **7. Analyse comparative** :
  - _Résumé Destination_ : Attraits principaux.
  - _Prix Moyen Vols_ : Estimation des coûts de transport.
  - _Prix Moyen Hotel_ : Estimation des coûts d'hébergement.
- **8. Choix de la destination** : Sélection de la meilleure option basée sur les critères (budget, intérêts) (Agent).
- **9. Challenger Destination** : Validation finale du choix de destination (Agent).
- **10. Output structuré** : Détails confirmés de la destination choisie (Output).

### Phase 3 : Optimisation et Réservation (Cible)

Cette phase finale génère les détails concrets du voyage pour la destination retenue.

- **11. Choix vols optimiser** : Recherche des meilleurs vols réels (Agent).
- **11. Choix hôtel optimiser** : Sélection des hébergements spécifiques (Agent).
- **11. Choix X activity** : Suggestion d'activités concrètes (Agent).
- **11. Choix x restaurant** : Recommandations gastronomiques (Agent).
