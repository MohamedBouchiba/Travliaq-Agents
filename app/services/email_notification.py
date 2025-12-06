"""
Service pour envoyer des notifications email après génération de trip.

Appelle directement l'endpoint Railway avec le summary_id (questionnaire_id).
"""

import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)

# Configuration
EMAIL_SERVICE_URL = "https://travliaq-sending-mail-production.up.railway.app/send-trip-summary-email"
REQUEST_TIMEOUT = 30  # seconds


def send_trip_summary_email(questionnaire_id: str) -> bool:
    """
    Envoyer un email de notification avec le trip summary.

    Args:
        questionnaire_id: UUID du questionnaire (utilisé comme summary_id)

    Returns:
        True si l'email a été envoyé avec succès, False sinon
    """
    if not questionnaire_id:
        logger.warning("⚠️ Cannot send email: missing questionnaire_id")
        return False

    try:
        logger.info(f"📧 Sending trip summary email for questionnaire {questionnaire_id[:8]}...")

        payload = {
            "summary_id": questionnaire_id
        }

        response = requests.post(
            EMAIL_SERVICE_URL,
            json=payload,
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=REQUEST_TIMEOUT,
        )

        if response.status_code == 200:
            logger.info(f"✅ Email sent successfully for questionnaire {questionnaire_id[:8]}...")
            return True
        else:
            logger.warning(
                f"⚠️ Email service returned status {response.status_code}: {response.text[:200]}"
            )
            return False

    except requests.exceptions.Timeout:
        logger.error(f"❌ Email service timeout after {REQUEST_TIMEOUT}s for questionnaire {questionnaire_id[:8]}...")
        return False

    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to send email for questionnaire {questionnaire_id[:8]}...: {e}")
        return False

    except Exception as e:
        logger.error(f"❌ Unexpected error sending email for questionnaire {questionnaire_id[:8]}...: {e}")
        return False


def send_trip_summary_email_async(questionnaire_id: str) -> None:
    """
    Version asynchrone (fire-and-forget) pour ne pas bloquer la pipeline.

    Args:
        questionnaire_id: UUID du questionnaire
    """
    import threading

    def _send():
        try:
            send_trip_summary_email(questionnaire_id)
        except Exception as e:
            logger.error(f"❌ Async email send failed: {e}")

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()
    logger.debug(f"🔄 Email sending started in background for {questionnaire_id[:8]}...")
