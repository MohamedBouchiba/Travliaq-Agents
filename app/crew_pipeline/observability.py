"""Module d'observabilité pour la pipeline CrewAI.

Fournit des métriques de performance, logging structuré et évaluation
de la qualité des outputs selon les best practices CrewAI.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class AgentMetrics:
    """Métriques d'exécution pour un agent individuel."""
    
    agent_name: str
    task_name: str
    start_time: float
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    tokens_used: Optional[int] = None
    success: bool = True
    error_message: Optional[str] = None
    output_size_chars: int = 0
    
    def complete(self, success: bool = True, error: Optional[str] = None) -> None:
        """Marque l'exécution comme terminée."""
        self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time
        self.success = success
        self.error_message = error
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "agent_name": self.agent_name,
            "task_name": self.task_name,
            "duration_seconds": round(self.duration_seconds, 2) if self.duration_seconds else None,
            "tokens_used": self.tokens_used,
            "success": self.success,
            "error_message": self.error_message,
            "output_size_chars": self.output_size_chars,
        }


@dataclass
class PipelineMetrics:
    """Métriques globales de la pipeline."""
    
    run_id: str
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_seconds: Optional[float] = None
    agent_metrics: List[AgentMetrics] = field(default_factory=list)
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def start_agent(self, agent_name: str, task_name: str) -> AgentMetrics:
        """Démarre le tracking d'un agent."""
        metrics = AgentMetrics(
            agent_name=agent_name,
            task_name=task_name,
            start_time=time.time(),
        )
        self.agent_metrics.append(metrics)
        logger.info(
            f"🚀 Agent démarré: {agent_name}",
            extra={"agent": agent_name, "task": task_name},
        )
        return metrics
    
    def complete_agent(
        self,
        metrics: AgentMetrics,
        output: Any,
        tokens: Optional[int] = None,
        success: bool = True,
        error: Optional[str] = None,
    ) -> None:
        """Termine le tracking d'un agent."""
        metrics.complete(success=success, error=error)
        
        if tokens:
            metrics.tokens_used = tokens
            self.total_tokens += tokens
        
        if output:
            metrics.output_size_chars = len(str(output))
        
        if error:
            self.errors.append(f"{metrics.agent_name}: {error}")
        
        status = "✅" if success else "❌"
        logger.info(
            f"{status} Agent terminé: {metrics.agent_name} ({metrics.duration_seconds:.2f}s)",
            extra={
                "agent": metrics.agent_name,
                "duration": metrics.duration_seconds,
                "success": success,
            },
        )
    
    def add_warning(self, message: str) -> None:
        """Ajoute un avertissement."""
        self.warnings.append(message)
        logger.warning(message)
    
    def complete_pipeline(self) -> None:
        """Marque la pipeline comme terminée."""
        self.end_time = time.time()
        self.duration_seconds = self.end_time - self.start_time
        
        # Estimation simple du coût (à ajuster selon le provider)
        # Exemple: GPT-4o-mini à ~$0.15/1M input tokens, $0.60/1M output tokens
        if self.total_tokens > 0:
            self.estimated_cost_usd = (self.total_tokens / 1_000_000) * 0.30  # Moyenne
        
        logger.info(
            f"🎯 Pipeline terminée: {self.run_id} ({self.duration_seconds:.2f}s)",
            extra={
                "run_id": self.run_id,
                "duration": self.duration_seconds,
                "total_tokens": self.total_tokens,
                "estimated_cost": self.estimated_cost_usd,
                "errors_count": len(self.errors),
                "warnings_count": len(self.warnings),
            },
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convertit les métriques en dictionnaire."""
        return {
            "run_id": self.run_id,
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": round(self.duration_seconds, 2) if self.duration_seconds else None,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": round(self.estimated_cost_usd, 4),
            "agent_metrics": [m.to_dict() for m in self.agent_metrics],
            "errors_count": len(self.errors),
            "warnings_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
        }
    
    def save_to_file(self, output_dir: Path) -> None:
        """Sauvegarde les métriques dans un fichier JSON."""
        metrics_file = output_dir / self.run_id / "metrics.json"
        try:
            metrics_file.parent.mkdir(parents=True, exist_ok=True)
            metrics_file.write_text(
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.debug(f"📊 Métriques sauvegardées: {metrics_file}")
        except OSError as exc:
            logger.warning(f"⚠️ Impossible de sauvegarder les métriques: {exc}")


class QualityScorer:
    """Évalue la qualité des outputs des agents."""
    
    @staticmethod
    def score_completeness(output: Dict[str, Any], required_fields: List[str]) -> float:
        """Évalue la complétude de l'output (0.0 à 1.0)."""
        if not output:
            return 0.0
        
        present = sum(1 for field in required_fields if output.get(field))
        return present / len(required_fields) if required_fields else 1.0
    
    @staticmethod
    def score_narrative_quality(narrative: str) -> float:
        """Évalue la qualité d'un narratif (0.0 à 1.0)."""
        if not narrative:
            return 0.0
        
        score = 0.0
        
        # Longueur minimale
        if len(narrative) >= 100:
            score += 0.3
        elif len(narrative) >= 50:
            score += 0.15
        
        # Présence de phrases complètes
        sentences = narrative.split(".")
        if len(sentences) >= 3:
            score += 0.3
        
        # Pas trop court ni trop long
        if 100 <= len(narrative) <= 1000:
            score += 0.2
        
        # Vérifier qu'il n'y a pas de placeholders évidents
        placeholders = ["TODO", "XXX", "FIXME", "..."]
        has_placeholders = any(p in narrative.upper() for p in placeholders)
        if not has_placeholders:
            score += 0.2
        
        return min(score, 1.0)
    
    @staticmethod
    def score_list_quality(items: List[str], min_items: int = 1) -> float:
        """Évalue la qualité d'une liste (0.0 à 1.0)."""
        if not items:
            return 0.0
        
        score = 0.0
        
        # Nombre d'items
        if len(items) >= min_items:
            score += 0.5
        
        # Items non vides
        non_empty = [item for item in items if item and item.strip()]
        if len(non_empty) == len(items):
            score += 0.3
        
        # Items avec une longueur raisonnable
        adequate_length = [item for item in non_empty if len(item) >= 10]
        if adequate_length:
            score += 0.2 * (len(adequate_length) / len(items))
        
        return min(score, 1.0)
    
    @classmethod
    def evaluate_persona_analysis(cls, output: Dict[str, Any]) -> Dict[str, float]:
        """Évalue un output PersonaAnalysisOutput."""
        scores = {
            "completeness": cls.score_completeness(
                output,
                ["persona_summary", "narrative", "pros", "cons", "critical_needs"],
            ),
            "narrative_quality": cls.score_narrative_quality(output.get("narrative", "")),
            "pros_quality": cls.score_list_quality(output.get("pros", []), min_items=1),
            "cons_quality": cls.score_list_quality(output.get("cons", []), min_items=1),
            "needs_quality": cls.score_list_quality(output.get("critical_needs", []), min_items=1),
        }
        
        scores["overall"] = sum(scores.values()) / len(scores)
        return scores


def log_structured_input(run_id: str, questionnaire: Dict, persona: Dict) -> None:
    """Log structuré des inputs de la pipeline."""
    logger.info(
        "📥 Inputs de la pipeline",
        extra={
            "run_id": run_id,
            "questionnaire_id": questionnaire.get("id"),
            "persona_id": persona.get("id"),
            "persona_confidence": persona.get("confidence_score"),
        },
    )


def log_structured_output(run_id: str, output: Dict[str, Any], scores: Optional[Dict] = None) -> None:
    """Log structuré des outputs de la pipeline."""
    extra_data = {
        "run_id": run_id,
        "has_normalized_trip": "normalized_trip_request" in output,
        "has_persona_analysis": "persona_analysis" in output,
    }
    
    if scores:
        extra_data["quality_scores"] = scores
    
    logger.info("📤 Output de la pipeline", extra=extra_data)
