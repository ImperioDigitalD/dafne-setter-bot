"""
Servidor principal de Dafne Bot — Coral Mujeres.
FastAPI + webhook de Whapi + Groq AI + Discord.
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException

from config import settings
from conversation_manager import ConversationManager
from groq_client import GroqClient
from whapi_client import WhapiClient
import discord_bot as discord_module

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

conv_manager = ConversationManager()
groq = GroqClient()
whapi = WhapiClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Inicializar base de datos
    await conv_manager.init_db()
    log.info("Base de datos inicializada.")

    # Pasar el gestor de conversaciones al bot de Discord
    discord_module.set_conversation_manager(conv_manager)

    # Iniciar bot de Discord en segundo plano
    discord_task = asyncio.create_task(discord_module.start_discord_bot())
    log.info("Bot de Discord iniciando...")

    yield

    discord_task.cancel()


app = FastAPI(title="Dafne Bot — Coral Mujeres", lifespan=lifespan)


def _extract_message_data(payload: dict) -> tuple[str, str]:
    """
    Extrae el número de teléfono y el texto del mensaje del payload de Whapi.
    Retorna (phone, text). Si no se puede extraer, retorna ("", "").
    """
    try:
        # Whapi envía un array de mensajes en 'messages'
        messages = payload.get("messages", [])
        if not messages:
            return "", ""

        msg = messages[0]

        # Solo procesamos mensajes entrantes (from_me = False)
        if msg.get("from_me", True):
            return "", ""

        # El número viene en el campo 'from' o 'chat_id'
        phone = msg.get("from", "") or msg.get("chat_id", "")
        # Eliminar sufijos de grupo (@g.us) — solo individuales (@s.whatsapp.net)
        if "@g.us" in phone:
            return "", ""
        phone = phone.replace("@s.whatsapp.net", "").replace("+", "")

        # Extraer texto del mensaje
        text = ""
        msg_type = msg.get("type", "")
        if msg_type == "text":
            text = msg.get("text", {}).get("body", "")
        elif msg_type == "image":
            text = msg.get("image", {}).get("caption", "") or "[imagen]"
        elif msg_type == "document":
            text = "[documento]"
        else:
            text = msg.get("body", "") or "[mensaje no soportado]"

        return phone, text.strip()
    except Exception as e:
        log.warning(f"Error extrayendo datos del webhook: {e}")
        return "", ""


@app.post("/webhook")
async def webhook(request: Request):
    """Endpoint principal que recibe mensajes de Whapi."""

    # Validar secret si está configurado
    if settings.webhook_secret:
        token = request.headers.get("X-Whapi-Token", "")
        if token != settings.webhook_secret:
            raise HTTPException(status_code=403, detail="Token inválido")

    payload = await request.json()
    phone, text = _extract_message_data(payload)

    if not phone or not text:
        return {"status": "ignored"}

    log.info(f"Mensaje de {phone}: {text[:80]}")

    # Si el bot está pausado, alertar en Discord sin responder
    if discord_module.is_paused():
        await discord_module.notify_paused_message(phone, text)
        return {"status": "paused"}

    # Cargar o crear conversación
    conv = await conv_manager.get_or_create(phone)

    # Si el setting ya terminó, ignorar mensajes nuevos (o reiniciar)
    if conv.status == "closed":
        return {"status": "closed"}

    # Agregar mensaje del prospecto al historial
    conv.add_message("user", text)

    # Generar respuesta con Groq
    response_text = await groq.generate_response(conv)

    # Enviar por WhatsApp
    sent = await whapi.send_message(phone, response_text)
    if not sent:
        log.error(f"Error enviando mensaje a {phone}")

    # Agregar respuesta al historial
    conv.add_message("assistant", response_text)

    # Actualizar datos del prospecto extraídos de la conversación
    conv_manager.extract_prospect_data(conv, response_text)

    # Alertar en Discord
    await discord_module.notify_message(
        phone=phone,
        inbound=text,
        outbound=response_text,
        step=conv.current_step,
        name=conv.name,
    )

    # Avanzar al siguiente paso si la respuesta del prospecto parece satisfactoria
    # La lógica de avance es simple: cada mensaje avanza el paso.
    # El modelo maneja los matices de cada paso internamente.
    if conv.current_step < 8:
        conv.advance_step()

    # Si llegamos al paso 8 y el bot acaba de enviar el cierre
    if conv.current_step == 8:
        summary = await groq.generate_summary(conv)
        await discord_module.notify_lead_summary(conv, summary)
        conv.close()
        log.info(f"Setting completado para {phone}")

    # Guardar estado
    await conv_manager.save(conv)

    return {"status": "ok"}


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok", "bot": "Dafne — Coral Mujeres"}


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)
