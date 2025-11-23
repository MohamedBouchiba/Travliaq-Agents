"""Service pour interagir avec Supabase PostgreSQL."""

import json
import logging
from typing import Dict, Any, Optional
from uuid import UUID
import psycopg2
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
            # Force IPv4 resolution for Railway compatibility
            import socket
            conn_params = {}
            
            if settings.pg_host and '.' in settings.pg_host:  # Not empty and looks like a hostname
                try:
                    # Resolve hostname to IPv4 address only
                    ipv4_addr = socket.getaddrinfo(
                        settings.pg_host, 
                        settings.pg_port, 
                        socket.AF_INET,  # Force IPv4
                        socket.SOCK_STREAM
                    )[0][4][0]
                    
                    # Use resolved IPv4 address
                    conn_params = {
                        'hostaddr': ipv4_addr,
                        'host': settings.pg_host,  # Keep for SSL verification
                        'dbname': settings.pg_database,
                        'user': settings.pg_user,
                        'password': settings.pg_password,
                        'port': settings.pg_port,
                        'sslmode': settings.pg_sslmode,
                    }
                    logger.info(f"Resolved {settings.pg_host} to IPv4: {ipv4_addr}")
                except socket.gaierror as dns_err:
                    logger.warning(f"DNS resolution failed: {dns_err}, using connection string")
                    conn_params = None
            
            # Use connection params dict if we have it, otherwise use conn_string
            if conn_params:
                conn = psycopg2.connect(**conn_params)
            else:
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
