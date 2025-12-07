"""Service pour interagir avec Supabase PostgreSQL."""

import json
import logging
from typing import Dict, Any, Optional
from uuid import UUID
import psycopg2
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from app.config import settings

DEFAULT_TRIP_IMAGE = (
    "https://images.unsplash.com/photo-1476514525535-07fb3b4ae5f1?w=1920&q=80"
)

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
        """Persiste le trip final dans la table `trips` en respectant le schéma SQL."""

        if not self.conn_string:
            logger.warning("⚠️  Chaîne de connexion PostgreSQL absente, persistence ignorée")
            return False

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            table_ident = sql.Identifier(settings.trip_recommendations_table)

            start_date = trip_json.get("start_date")
            if isinstance(start_date, str) and "T" in start_date:
                # Le champ SQL est de type DATE ; on ne garde que la partie date
                start_date = start_date.split("T", 1)[0]

            payload = {
                "code": trip_json.get("code"),
                "destination": trip_json.get("destination") or "UNKNOWN",
                "main_image": trip_json.get("main_image") or DEFAULT_TRIP_IMAGE,
                "flight_from": trip_json.get("flight_from"),
                "flight_to": trip_json.get("flight_to"),
                "flight_duration": trip_json.get("flight_duration"),
                "flight_type": trip_json.get("flight_type"),
                "hotel_name": trip_json.get("hotel_name"),
                "hotel_rating": trip_json.get("hotel_rating"),
                "total_price": trip_json.get("total_price"),
                "total_days": trip_json.get("total_days") or 7,
                "total_budget": trip_json.get("total_budget"),
                "average_weather": trip_json.get("average_weather"),
                "travel_style": trip_json.get("travel_style"),
                "start_date": start_date,
                "destination_en": trip_json.get("destination_en"),
                "travel_style_en": trip_json.get("travel_style_en"),
                "travelers": trip_json.get("travelers"),
                "price_flights": trip_json.get("price_flights"),
                "price_hotels": trip_json.get("price_hotels"),
                "price_transport": trip_json.get("price_transport"),
                "price_activities": trip_json.get("price_activities"),
            }

            # Le schéma SQL utilise une clé unique sur `code`
            query = sql.SQL(
                """
                INSERT INTO {table} (
                    code, destination, main_image, flight_from, flight_to, flight_duration, flight_type,
                    hotel_name, hotel_rating, total_price, total_days, total_budget, average_weather,
                    travel_style, start_date, destination_en, travel_style_en, travelers,
                    price_flights, price_hotels, price_transport, price_activities
                )
                VALUES (
                    %(code)s, %(destination)s, %(main_image)s, %(flight_from)s, %(flight_to)s, %(flight_duration)s, %(flight_type)s,
                    %(hotel_name)s, %(hotel_rating)s, %(total_price)s, %(total_days)s, %(total_budget)s, %(average_weather)s,
                    %(travel_style)s, %(start_date)s, %(destination_en)s, %(travel_style_en)s, %(travelers)s,
                    %(price_flights)s, %(price_hotels)s, %(price_transport)s, %(price_activities)s
                )
                ON CONFLICT (code) DO UPDATE SET
                    destination = EXCLUDED.destination,
                    main_image = EXCLUDED.main_image,
                    flight_from = EXCLUDED.flight_from,
                    flight_to = EXCLUDED.flight_to,
                    flight_duration = EXCLUDED.flight_duration,
                    flight_type = EXCLUDED.flight_type,
                    hotel_name = EXCLUDED.hotel_name,
                    hotel_rating = EXCLUDED.hotel_rating,
                    total_price = EXCLUDED.total_price,
                    total_days = EXCLUDED.total_days,
                    total_budget = EXCLUDED.total_budget,
                    average_weather = EXCLUDED.average_weather,
                    travel_style = EXCLUDED.travel_style,
                    start_date = EXCLUDED.start_date,
                    destination_en = EXCLUDED.destination_en,
                    travel_style_en = EXCLUDED.travel_style_en,
                    travelers = EXCLUDED.travelers,
                    price_flights = EXCLUDED.price_flights,
                    price_hotels = EXCLUDED.price_hotels,
                    price_transport = EXCLUDED.price_transport,
                    price_activities = EXCLUDED.price_activities,
                    updated_at = timezone('utc', now())
                RETURNING code
                """
            ).format(table=table_ident)

            cursor.execute(query, payload)
            cursor.fetchone()
            conn.commit()
            logger.info(
                "💾 Trip JSON persisté dans Supabase",
                extra={"run_id": run_id, "trip_code": payload.get("code")},
            )
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

            # 🛡️ FALLBACK: Vérifier que toutes les steps ont été insérées
            if trip_id:
                steps = trip_json.get("steps", [])
                if steps:
                    cursor = conn.cursor()
                    cursor.execute("SELECT COUNT(*) FROM steps WHERE trip_id = %s", (trip_id,))
                    count_result = cursor.fetchone()
                    steps_count = count_result[0] if count_result else 0

                    if steps_count < len(steps):
                        logger.warning(f"⚠️ Seulement {steps_count}/{len(steps)} steps insérées. Tentative d'insertion manuelle...")
                        self._insert_steps_manually(conn, trip_id, steps)

            return trip_id
        except psycopg2.IntegrityError as exc:
            if conn:
                conn.rollback()

            # 🛡️ ROBUSTESSE: Gérer les conflits de clé unique
            error_msg = str(exc)
            if "trips_code_key" in error_msg or "duplicate key" in error_msg:
                logger.warning(f"⚠️ Conflit de code trip détecté, tentative avec code modifié: {exc}")

                # Regénérer un code unique en ajoutant un nouveau suffixe UUID
                import uuid
                original_code = trip_json.get("code", "TRIP")
                new_code = f"{original_code.split('-')[0]}-{uuid.uuid4().hex[:6].upper()}"
                trip_json["code"] = new_code

                logger.info(f"🔄 Nouvelle tentative avec code: {new_code}")

                # Réessayer avec le nouveau code
                try:
                    conn = self._get_connection()
                    cursor = conn.cursor()
                    cursor.execute("SELECT insert_trip_from_json(%s::jsonb) AS trip_id", (json.dumps(trip_json),))
                    result = cursor.fetchone()
                    conn.commit()

                    trip_id = result[0] if result else None
                    logger.info("✅ Trip enregistré avec code modifié", extra={"trip_id": trip_id, "new_code": new_code})

                    # Vérifier les steps
                    if trip_id:
                        steps = trip_json.get("steps", [])
                        if steps:
                            cursor = conn.cursor()
                            cursor.execute("SELECT COUNT(*) FROM steps WHERE trip_id = %s", (trip_id,))
                            count_result = cursor.fetchone()
                            steps_count = count_result[0] if count_result else 0

                            if steps_count < len(steps):
                                logger.warning(f"⚠️ Seulement {steps_count}/{len(steps)} steps insérées. Tentative d'insertion manuelle...")
                                self._insert_steps_manually(conn, trip_id, steps)

                    return trip_id
                except Exception as retry_exc:
                    if conn:
                        conn.rollback()
                    logger.error(f"❌ Échec même après modification du code: {retry_exc}")
                    raise
            else:
                logger.error(f"❌ Erreur d'intégrité non gérée: {exc}")
                raise
        except Exception as exc:
            if conn:
                conn.rollback()
            logger.error(f"❌ Échec insert_trip_from_json: {exc}")
            raise
        finally:
            if conn:
                conn.close()
                logger.debug("Connexion PostgreSQL fermée après insert_trip_from_json")

    def _insert_steps_manually(self, conn, trip_id: str, steps: list) -> None:
        """Insère manuellement les steps si la fonction SQL a échoué."""
        cursor = conn.cursor()

        for step in steps:
            try:
                # Convertir les images list en JSONB pour PostgreSQL
                images = step.get("images", [])
                images_jsonb = json.dumps(images) if images else '[]'

                # Convertir summary_stats en JSONB
                summary_stats = step.get("summary_stats")
                summary_stats_jsonb = json.dumps(summary_stats) if summary_stats else None

                # Requête adaptée au schéma SQL exact de insert_trip_from_json
                query = """
                    INSERT INTO steps (
                        trip_id, step_number, day_number, title, title_en, subtitle, subtitle_en,
                        main_image, is_summary, step_type, latitude, longitude,
                        why, why_en, tips, tips_en, transfer, transfer_en, suggestion, suggestion_en,
                        weather_icon, weather_temp, weather_description, weather_description_en,
                        price, duration, images, summary_stats
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb
                    )
                    ON CONFLICT (trip_id, step_number) DO UPDATE SET
                        day_number = EXCLUDED.day_number,
                        title = EXCLUDED.title,
                        subtitle = EXCLUDED.subtitle,
                        main_image = EXCLUDED.main_image,
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        why = EXCLUDED.why,
                        tips = EXCLUDED.tips,
                        is_summary = EXCLUDED.is_summary,
                        step_type = EXCLUDED.step_type,
                        images = EXCLUDED.images,
                        summary_stats = EXCLUDED.summary_stats,
                        updated_at = timezone('utc', now())
                """

                cursor.execute(query, (
                    trip_id,
                    step.get("step_number"),
                    step.get("day_number"),
                    step.get("title"),
                    step.get("title_en"),
                    step.get("subtitle"),
                    step.get("subtitle_en"),
                    step.get("main_image"),
                    step.get("is_summary", False),
                    step.get("step_type"),
                    step.get("latitude"),
                    step.get("longitude"),
                    step.get("why"),
                    step.get("why_en"),
                    step.get("tips"),
                    step.get("tips_en"),
                    step.get("transfer"),
                    step.get("transfer_en"),
                    step.get("suggestion"),
                    step.get("suggestion_en"),
                    step.get("weather_icon"),
                    step.get("weather_temp"),
                    step.get("weather_description"),
                    step.get("weather_description_en"),
                    step.get("price"),
                    step.get("duration"),
                    images_jsonb,
                    summary_stats_jsonb
                ))

                logger.info(f"✅ Step {step.get('step_number')} insérée manuellement")
            except Exception as exc:
                logger.error(f"❌ Erreur insertion step {step.get('step_number')}: {exc}")
                # Continue avec les autres steps même si une échoue

        conn.commit()
        logger.info(f"✅ {len(steps)} steps insérées manuellement")

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

    def save_trip_summary(
        self,
        *,
        questionnaire_id: str,
        questionnaire_data: Dict[str, Any],
        persona_inference: Dict[str, Any],
        persona_analysis: Dict[str, Any],
        trip_json: Optional[Dict[str, Any]] = None,
        run_id: str,
        pipeline_status: str = "SUCCESS",
    ) -> Optional[str]:
        """
        Sauvegarde un résumé du trip dans la table trip_summaries.
        
        Robuste: extrait les données de multiples sources avec fallbacks.
        
        Args:
            questionnaire_id: UUID du questionnaire
            questionnaire_data: Données brutes du questionnaire
            persona_inference: Résultat de l'inférence persona
            persona_analysis: Résultat de l'analyse CrewAI
            trip_json: Trip JSON généré (optionnel)
            run_id: ID d'exécution pipeline
            pipeline_status: SUCCESS, PARTIAL, FAILED
            
        Returns:
            UUID du record créé ou None si erreur
        """
        if not self.conn_string:
            logger.warning("⚠️ Chaîne de connexion PostgreSQL absente, save_trip_summary ignorée")
            return None

        conn = None
        try:
            conn = self._get_connection()
            cursor = conn.cursor()

            # ============================================================
            # EXTRACTION ROBUSTE DES DONNÉES
            # ============================================================
            
            # 1. Email utilisateur (obligatoire)
            user_email = questionnaire_data.get("email", "unknown@travliaq.com")
            
            # 2. Persona
            persona = "Inconnu"
            if persona_inference:
                persona_data = persona_inference.get("persona", {})
                if isinstance(persona_data, dict):
                    persona = persona_data.get("principal", "Inconnu")
                elif isinstance(persona_data, str):
                    persona = persona_data
            
            # 3. Summary paragraph (le paragraphe clé!)
            summary_paragraph = None
            if persona_analysis:
                # Chercher dans différentes structures possibles
                summary_paragraph = (
                    persona_analysis.get("narrative") or
                    persona_analysis.get("persona_summary") or
                    persona_analysis.get("summary") or
                    persona_analysis.get("description")
                )
                # Si c'est un dict imbriqué
                if not summary_paragraph and isinstance(persona_analysis.get("analysis"), dict):
                    summary_paragraph = persona_analysis["analysis"].get("narrative")
            
            # Fallback: générer un résumé basique si pas de narrative
            if not summary_paragraph:
                destination = trip_json.get("destination") if trip_json else questionnaire_data.get("destination", "")
                summary_paragraph = f"Voyage personnalisé vers {destination} pour un profil {persona}."
            
            # 4. Destination
            destination = "Destination à définir"
            destination_en = None
            if trip_json:
                destination = trip_json.get("destination", destination)
                destination_en = trip_json.get("destination_en")
            elif questionnaire_data.get("destination"):
                destination = questionnaire_data.get("destination")
            
            # 5. Country code (extrait de destination)
            country_code = None
            if destination and "," in destination:
                country_part = destination.split(",")[-1].strip()
                # Mapping simplifié pays -> code
                country_codes = {
                    "France": "FR", "Indonésie": "ID", "Indonesia": "ID",
                    "Italie": "IT", "Italy": "IT", "Espagne": "ES", "Spain": "ES",
                    "Japon": "JP", "Japan": "JP", "Thaïlande": "TH", "Thailand": "TH",
                    "États-Unis": "US", "USA": "US", "United States": "US",
                    "Portugal": "PT", "Grèce": "GR", "Greece": "GR",
                    "Maroc": "MA", "Morocco": "MA", "Belgique": "BE", "Belgium": "BE",
                }
                country_code = country_codes.get(country_part)
            
            # 6. Dates
            start_date = None
            end_date = None
            total_days = None
            total_nights = None
            
            if trip_json:
                start_date = trip_json.get("start_date")
                total_days = trip_json.get("total_days")
            
            if not start_date:
                start_date = questionnaire_data.get("date_depart")
            
            if start_date and isinstance(start_date, str) and "T" in start_date:
                start_date = start_date.split("T")[0]
            
            if not total_days:
                total_days = questionnaire_data.get("nuits_exactes")
                if total_days:
                    total_days = int(total_days) + 1
            
            if total_days:
                total_nights = total_days - 1
                # Calculer end_date
                if start_date:
                    try:
                        from datetime import datetime, timedelta
                        start_dt = datetime.fromisoformat(start_date)
                        end_dt = start_dt + timedelta(days=total_days - 1)
                        end_date = end_dt.date().isoformat()
                    except Exception:
                        pass
            
            # 7. Voyageurs
            travelers_count = questionnaire_data.get("nombre_voyageurs", 1)
            if travelers_count:
                travelers_count = int(travelers_count)
            
            travel_style = None
            rhythm = questionnaire_data.get("rythme")
            
            if trip_json:
                travel_style = trip_json.get("travel_style")
            
            # 8. Budget
            total_price = None
            price_flights = None
            price_hotels = None
            price_activities = None
            budget_currency = questionnaire_data.get("devise_budget", "EUR")
            
            if trip_json:
                total_price = self._parse_price(trip_json.get("total_price"))
                price_flights = self._parse_price(trip_json.get("price_flights"))
                price_hotels = self._parse_price(trip_json.get("price_hotels"))
                price_activities = self._parse_price(trip_json.get("price_activities"))
            
            # 9. Vols
            flight_from = trip_json.get("flight_from") if trip_json else None
            flight_to = trip_json.get("flight_to") if trip_json else None
            flight_duration = trip_json.get("flight_duration") if trip_json else None
            
            # 10. Hébergement
            hotel_name = trip_json.get("hotel_name") if trip_json else None
            hotel_rating = self._parse_price(trip_json.get("hotel_rating")) if trip_json else None
            
            # 11. Météo
            average_weather = trip_json.get("average_weather") if trip_json else None
            
            # 12. Images
            main_image_url = trip_json.get("main_image") if trip_json else None
            gallery_urls = []
            if trip_json and trip_json.get("steps"):
                for step in trip_json["steps"][:5]:  # Top 5 steps
                    if step.get("main_image"):
                        gallery_urls.append(step["main_image"])
            
            # 13. Stats
            steps_count = len(trip_json.get("steps", [])) if trip_json else 0
            activities_summary = []
            if trip_json and trip_json.get("steps"):
                for step in trip_json["steps"][:5]:
                    title = step.get("title") or step.get("title_en")
                    if title and not step.get("is_summary"):
                        activities_summary.append(title)

            # 14. Trip code
            trip_code = trip_json.get("code") if trip_json else None

            # 15. Langue (NOUVEAU)
            language = questionnaire_data.get("langue")
            if not language:
                # Tentative de déduction
                if questionnaire_data.get("locale"):
                    language = questionnaire_data.get("locale")
                else:
                    language = "fr" # Default

            # ============================================================
            # INSERT ROBUSTE
            # ============================================================

            query = """
                INSERT INTO trip_summaries (
                    questionnaire_id, run_id, user_email, persona, summary_paragraph,
                    destination, destination_en, country_code,
                    start_date, end_date, total_days, total_nights,
                    travelers_count, travel_style, rhythm,
                    total_price, price_flights, price_hotels, price_activities, budget_currency,
                    flight_from, flight_to, flight_duration,
                    hotel_name, hotel_rating,
                    average_weather,
                    main_image_url, gallery_urls,
                    steps_count, activities_summary,
                    trip_code, pipeline_status, generated_at, language
                ) VALUES (
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s,
                    %s, %s,
                    %s,
                    %s, %s,
                    %s, %s,
                    %s, %s, timezone('utc', now()), %s
                )
                ON CONFLICT (questionnaire_id) DO UPDATE SET
                    run_id = EXCLUDED.run_id,
                    persona = EXCLUDED.persona,
                    summary_paragraph = EXCLUDED.summary_paragraph,
                    destination = EXCLUDED.destination,
                    destination_en = EXCLUDED.destination_en,
                    total_price = EXCLUDED.total_price,
                    price_flights = EXCLUDED.price_flights,
                    price_hotels = EXCLUDED.price_hotels,
                    price_activities = EXCLUDED.price_activities,
                    main_image_url = EXCLUDED.main_image_url,
                    gallery_urls = EXCLUDED.gallery_urls,
                    steps_count = EXCLUDED.steps_count,
                    activities_summary = EXCLUDED.activities_summary,
                    trip_code = EXCLUDED.trip_code,
                    pipeline_status = EXCLUDED.pipeline_status,
                    language = EXCLUDED.language,
                    generated_at = timezone('utc', now()),
                    updated_at = timezone('utc', now())
                RETURNING id
            """

            cursor.execute(query, (
                questionnaire_id, run_id, user_email, persona, summary_paragraph,
                destination, destination_en, country_code,
                start_date, end_date, total_days, total_nights,
                travelers_count, travel_style, rhythm,
                total_price, price_flights, price_hotels, price_activities, budget_currency,
                flight_from, flight_to, flight_duration,
                hotel_name, hotel_rating,
                average_weather,
                main_image_url, gallery_urls,
                steps_count, activities_summary,
                trip_code, pipeline_status, language
            ))
            
            result = cursor.fetchone()
            conn.commit()
            
            summary_id = str(result[0]) if result else None
            logger.info(f"💾 Trip summary sauvegardé: {summary_id}", extra={
                "questionnaire_id": questionnaire_id,
                "persona": persona,
                "destination": destination,
            })
            
            return summary_id
            
        except Exception as e:
            if conn:
                conn.rollback()
            logger.error(f"❌ Échec save_trip_summary: {e}")
            # Ne pas lever l'exception pour ne pas bloquer le reste du pipeline
            return None
        finally:
            if conn:
                conn.close()

    def _parse_price(self, value: Any) -> Optional[float]:
        """Parse une valeur de prix en float, robuste aux différents formats."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            # Nettoyer: "1,234.56€" -> 1234.56
            import re
            cleaned = re.sub(r'[^\d.,]', '', value)
            if not cleaned:
                return None
            # Gérer virgule comme séparateur décimal
            if ',' in cleaned and '.' not in cleaned:
                cleaned = cleaned.replace(',', '.')
            elif ',' in cleaned and '.' in cleaned:
                cleaned = cleaned.replace(',', '')
            try:
                return float(cleaned)
            except ValueError:
                return None
        return None


# Instance globale
supabase_service = SupabaseService()
