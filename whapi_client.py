"""
Cliente para enviar mensajes de WhatsApp vía Whapi REST API.
"""

import httpx
from config import settings


class WhapiClient:
    def __init__(self):
        self.base_url = settings.whapi_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.whapi_token}",
            "Content-Type": "application/json",
        }

    async def send_message(self, phone: str, text: str) -> bool:
        """
        Envía un mensaje de texto a un número de WhatsApp.
        El número debe incluir lada internacional sin '+' (ej: 521XXXXXXXXXX).
        """
        url = f"{self.base_url}/messages/text"
        payload = {
            "to": phone,
            "body": text,
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=payload, headers=self.headers)
            return response.status_code in (200, 201)

    async def get_profile(self, phone: str) -> dict:
        """Obtiene el perfil básico de un contacto (nombre si está disponible)."""
        url = f"{self.base_url}/contacts/{phone}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 200:
                return response.json()
        return {}
