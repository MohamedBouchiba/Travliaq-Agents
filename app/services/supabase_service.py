"""Service pour interagir avec Supabase PostgreSQL."""

import json
import logging
from typing import Dict, Any, Optional
from uuid import UUID
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from app.config import settings

logger = logging.getLogger(__name__)


class SupabaseService:
    """Service pour récupérer les données depuis Supabase PostgreSQL."""

    def __init__(self):
        """Initialise le service."""
        self.conn_string = settings.pg_connection_string

    def _get_connection(self):
        """Crée une connexion PostgreSQL."""
        try:
            conn = psycopg2.connect(self.conn_string)
            logger.info("✅ Connexion PostgreSQL établie")
            return conn
        except Exception as e:
            logger.error(f"❌ Erreur connexion PostgreSQL: {e}")
            raise

    def _convert_to_json_serializable(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Convertit les types non-JSON en types sérialisables."""
        result = {}
        for key, value in data.items():
            if isinstance(value, UUID):
                result[key] = str(value)
            elif hasattr(value, 'isoformat'):  # datetime, date
                result[key] = value.isoformat()
            elif isinstance(value, (dict, list)):
                result[key] = value  # JSONB déjà converti
            else:
                result[key] = value
        return result

    def get_questionnaire_by_id(self, questionnaire_id: str) -> Optional[Dict[str, Any]]:
        """
        Récupère un questionnaire par son ID.

        Args:
            questionnaire_id: UUID du questionnaire

        Returns:
            Dict contenant toutes les données du questionnaire ou None
        """
        conn = None
        try:
            # Valider l'UUID
            try:
                UUID(questionnaire_id)
            except ValueError:
                logger.error(f"❌ ID invalide (pas un UUID): {questionnaire_id}")
                return None

            conn = self._get_connection()
            cursor = conn.cursor(cursor_factory=RealDictCursor)

            query = """
                SELECT 
                    id, user_id, email, groupe_voyage, nombre_voyageurs,
                    a_destination, destination, preference_climat, affinites_voyage,
                    ambiance_voyage, type_dates, date_depart, date_retour,
                    flexibilite, duree, nuits_exactes, budget_par_personne,
                    type_budget, montant_budget, devise_budget, styles, rythme,
                    preference_vol, bagages, mobilite, type_hebergement, confort,
                    quartier, equipements, contraintes, infos_supplementaires,
                    created_at, updated_at, lieu_depart, a_date_depart_approximative,
                    date_depart_approximative, enfants, securite, biorythme,
                    langue, preferences_horaires, aide_avec, preferences_hotel
                FROM questionnaire_responses
                WHERE id = %s
            """

            cursor.execute(query, (questionnaire_id,))
            row = cursor.fetchone()

            if not row:
                logger.warning(f"⚠️  Questionnaire introuvable: {questionnaire_id}")
                return None

            # Convertir RealDictRow en dict standard
            data = dict(row)

            # Convertir les types non-JSON
            data = self._convert_to_json_serializable(data)

            logger.info(f"✅ Questionnaire récupéré: {questionnaire_id}")
            logger.debug(f"Données: {json.dumps(data, indent=2, default=str)}")

            cursor.close()
            return data

        except Exception as e:
            logger.error(f"❌ Erreur lors de la récupération du questionnaire: {e}")
            raise

        finally:
            if conn:
                conn.close()
                logger.debug("Connexion PostgreSQL fermée")

    def save_trip_recommendation(
        self,
        *,
        run_id: str,
        questionnaire_id: Optional[str],
        trip_json: Dict[str, Any],
        status: str,
        schema_valid: bool,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Persiste le JSON final du trip dans Supabase."""

        if not self.conn_string:
            logger.warning("⚠️  Chaîne de connexion PostgreSQL absente, persistence ignorée")
            return False

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            table_ident = sql.Identifier(settings.trip_recommendations_table)
            query = sql.SQL(
                """
                INSERT INTO {table} (run_id, questionnaire_id, trip_json, status, schema_valid, metadata)
                VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET
                    trip_json = EXCLUDED.trip_json,
                    status = EXCLUDED.status,
                    schema_valid = EXCLUDED.schema_valid,
                    metadata = EXCLUDED.metadata,
                    updated_at = timezone('utc', now())
                RETURNING run_id
                """
            ).format(table=table_ident)

            cursor.execute(
                query,
                (
                    run_id,
                    questionnaire_id,
                    json.dumps(trip_json),
                    status,
                    schema_valid,
                    json.dumps(metadata or {}),
                ),
            )
            cursor.fetchone()
            conn.commit()
            logger.info("💾 Trip JSON persisté dans Supabase", extra={"run_id": run_id})
            return True
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"❌ Échec de persistence du trip: {e}")
            raise
        finally:
            if conn:
                conn.close()
                logger.debug("Connexion PostgreSQL fermée après persistence")

    def insert_trip_from_json(self, trip_json: Dict[str, Any]) -> Optional[str]:
        """Insère un voyage complet via la fonction SQL `insert_trip_from_json`.

        La fonction Supabase doit accepter un JSONB et retourner l'identifiant du trip créé.
        """

        if not self.conn_string:
            logger.warning("⚠️ Chaîne de connexion PostgreSQL absente, insertion ignorée")
            return None

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            cursor.execute("SELECT insert_trip_from_json(%s::jsonb) AS trip_id", (json.dumps(trip_json),))
            result = cursor.fetchone()
            conn.commit()

            trip_id = result[0] if result else None
            logger.info("💾 Trip enregistré via insert_trip_from_json", extra={"trip_id": trip_id})
            return trip_id
        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"❌ Échec insert_trip_from_json: {exc}")
            raise
        finally:
            if conn:
                conn.close()
                logger.debug("Connexion PostgreSQL fermée après insert_trip_from_json")

    def check_connection(self) -> bool:
        """Vérifie que la connexion PostgreSQL fonctionne."""
        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            result = cursor.fetchone()
            cursor.close()
            return result is not None
        except Exception as e:
            logger.error(f"❌ Health check failed: {e}")
            return False
        finally:
            if conn:
                conn.close()


# Instance globale
supabase_service = SupabaseService()
