"""
Validation structurée des URLs d'images.

Remplace le string matching fragile par une validation robuste.
"""
from typing import List
from urllib.parse import urlparse


class ImageValidator:
    """
    Validateur d'URLs d'images pour le trip.

    Usage:
        >>> ImageValidator.is_valid("https://supabase.co/image.jpg")
        True
        >>> ImageValidator.is_supabase("https://supabase.co/image.jpg")
        True
        >>> ImageValidator.get_quality_score("https://supabase.co/image.jpg")
        100
    """

    VALID_HOSTS = [
        "cinbnmlfpffmyjmkwbco.supabase.co",  # Supabase production
        "source.unsplash.com",                # Unsplash fallback
        "images.unsplash.com"                 # Unsplash direct
    ]

    INVALID_MARKERS = ["FAILED", "ERROR", "INVALID"]

    @classmethod
    def is_valid(cls, url: str) -> bool:
        """
        Valider une URL d'image.

        Args:
            url: URL à valider

        Returns:
            True si l'URL est valide et utilisable

        Examples:
            >>> ImageValidator.is_valid("https://cinbnmlfpffmyjmkwbco.supabase.co/...")
            True
            >>> ImageValidator.is_valid("http://example.com/image.jpg")
            False
            >>> ImageValidator.is_valid("FAILED_TO_GENERATE")
            False
        """
        if not url or not isinstance(url, str):
            return False

        # Check pour marqueurs d'échec
        url_upper = url.upper()
        if any(marker in url_upper for marker in cls.INVALID_MARKERS):
            return False

        # Parse URL
        try:
            parsed = urlparse(url)
        except Exception:
            return False

        # Vérifier host valide
        return any(host in parsed.netloc for host in cls.VALID_HOSTS)

    @classmethod
    def is_supabase(cls, url: str) -> bool:
        """
        Check si l'URL est Supabase (préféré).

        Args:
            url: URL à vérifier

        Returns:
            True si URL Supabase
        """
        if not url:
            return False
        return "supabase.co" in url

    @classmethod
    def is_fallback(cls, url: str) -> bool:
        """
        Check si l'URL est un fallback acceptable (Unsplash).

        Args:
            url: URL à vérifier

        Returns:
            True si URL Unsplash
        """
        if not url:
            return False
        return "unsplash.com" in url

    @classmethod
    def get_quality_score(cls, url: str) -> int:
        """
        Score de qualité d'une image (0-100).

        Returns:
            100 : Supabase (idéal)
            50  : Unsplash (fallback acceptable)
            0   : Invalid ou missing
        """
        if not cls.is_valid(url):
            return 0

        if cls.is_supabase(url):
            return 100

        if cls.is_fallback(url):
            return 50

        return 0
