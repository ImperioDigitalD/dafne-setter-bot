"""
Bot de Discord para Dafne — Coral Mujeres.
Funciones:
  1. Alertas en tiempo real de mensajes entrantes/salientes.
  2. Resumen completo de leads cuando el setting termina (paso 8).
  3. Comandos slash /bot para controlar el bot desde Discord.
  4. Detección automática de prospectos: cualquier mensaje que contenga
     "coral" + nombre + teléfono dispara el primer mensaje de WhatsApp.
"""

import re
import unicodedata

import discord
from discord.ext import commands
from discord import app_commands
from config import settings
from conversation_manager import ConversationManager, Conversation

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)
tree = bot.tree

# Estado global del bot (pausado/activo) — compartido con main.py
bot_paused: bool = False
_conv_manager: ConversationManager | None = None


def set_conversation_manager(manager: ConversationManager):
    global _conv_manager
    _conv_manager = manager


def is_paused() -> bool:
    return bot_paused


# ──────────────────────────────────────────
# Notificaciones
# ──────────────────────────────────────────

async def notify_message(phone: str, inbound: str, outbound: str, step: int, name: str = ""):
    """Alerta en #alertas-whatsapp cuando hay un intercambio de mensajes."""
    channel = bot.get_channel(settings.discord_alerts_channel_id)
    if not channel:
        return

    display_name = name if name else "Desconocido"
    phone_masked = phone[:-4] + "****" if len(phone) > 4 else phone

    embed = discord.Embed(
        title=f"Mensaje — {display_name} ({phone_masked})",
        color=discord.Color.blue(),
    )
    embed.add_field(name="Prospecto dijo:", value=inbound[:500] or "—", inline=False)
    embed.add_field(name="Dafne respondió:", value=outbound[:500] or "—", inline=False)
    embed.set_footer(text=f"Paso {step}/8")
    await channel.send(embed=embed)


async def notify_lead_summary(conv: Conversation, summary: str):
    """Manda el resumen completo al canal #leads-terminados."""
    channel = bot.get_channel(settings.discord_leads_channel_id)
    if not channel:
        return

    embed = discord.Embed(
        title=f"Lead completado — {conv.name or conv.phone}",
        color=discord.Color.green(),
        description=summary,
    )
    embed.add_field(name="Temperatura", value=conv.temperature, inline=True)
    embed.add_field(name="Instagram", value=conv.instagram or "No compartido", inline=True)
    embed.add_field(name="Número", value=conv.phone[-4:].rjust(len(conv.phone), "*"), inline=True)
    await channel.send(embed=embed)


async def notify_paused_message(phone: str, inbound: str):
    """Avisa cuando llega un mensaje pero el bot está pausado."""
    channel = bot.get_channel(settings.discord_alerts_channel_id)
    if not channel:
        return

    phone_masked = phone[:-4] + "****" if len(phone) > 4 else phone
    embed = discord.Embed(
        title=f"Mensaje recibido (bot PAUSADO) — {phone_masked}",
        description=inbound[:500],
        color=discord.Color.orange(),
    )
    embed.set_footer(text="El bot no respondió. Usa /bot enviar para responder manualmente.")
    await channel.send(embed=embed)


# ──────────────────────────────────────────
# Comandos slash /bot
# ──────────────────────────────────────────

@tree.command(name="bot", description="Controla el bot de setting de Dafne")
@app_commands.describe(
    accion="pausar | activar | estado | prospecto | enviar",
    numero="Número del prospecto (para 'prospecto' y 'enviar')",
    mensaje="Mensaje a enviar (solo para 'enviar')",
)
async def bot_command(
    interaction: discord.Interaction,
    accion: str,
    numero: str = "",
    mensaje: str = "",
):
    global bot_paused

    accion = accion.strip().lower()

    if accion == "pausar":
        bot_paused = True
        await interaction.response.send_message("Bot **pausado**. No responderá hasta que uses `/bot activar`.")

    elif accion == "activar":
        bot_paused = False
        await interaction.response.send_message("Bot **activado**. Volviendo a responder automáticamente.")

    elif accion == "estado":
        if _conv_manager:
            count = await _conv_manager.get_active_count()
        else:
            count = 0
        estado = "PAUSADO" if bot_paused else "ACTIVO"
        await interaction.response.send_message(
            f"Estado del bot: **{estado}**\nSetteos activos: **{count}**"
        )

    elif accion == "prospecto":
        if not numero:
            await interaction.response.send_message("Debes indicar el número. Ej: `/bot prospecto 521XXXXXXXXXX`")
            return
        if not _conv_manager:
            await interaction.response.send_message("Error: gestor de conversaciones no disponible.")
            return
        conv = await _conv_manager.get_by_phone(numero)
        if not conv:
            await interaction.response.send_message(f"No encontré conversación con el número `{numero}`.")
            return

        history_text = "\n".join(
            f"{'Dafne' if m['role'] == 'assistant' else 'Prospecto'}: {m['content']}"
            for m in conv.history[-10:]  # últimos 10 mensajes
        )
        embed = discord.Embed(
            title=f"Prospecto: {conv.name or conv.phone}",
            color=discord.Color.purple(),
        )
        embed.add_field(name="Nicho", value=conv.nicho or "—", inline=True)
        embed.add_field(name="Paso actual", value=str(conv.current_step), inline=True)
        embed.add_field(name="Temperatura", value=conv.temperature, inline=True)
        embed.add_field(name="Instagram", value=conv.instagram or "—", inline=True)
        embed.add_field(name="Historial (últimos 10 mensajes)", value=history_text[:1000] or "—", inline=False)
        await interaction.response.send_message(embed=embed)

    elif accion == "enviar":
        if not numero or not mensaje:
            await interaction.response.send_message(
                "Debes indicar número y mensaje. Ej: `/bot enviar 521XXXXXXXXXX Hola, ¿cómo estás?`"
            )
            return
        # Importar aquí para evitar circular import
        from whapi_client import WhapiClient
        whapi = WhapiClient()
        success = await whapi.send_message(numero, mensaje)
        if success:
            await interaction.response.send_message(f"Mensaje enviado a `{numero}`.")
            # Guardar el mensaje manual en el historial si existe la conversación
            if _conv_manager:
                conv = await _conv_manager.get_by_phone(numero)
                if conv:
                    conv.add_message("assistant", mensaje)
                    await _conv_manager.save(conv)
        else:
            await interaction.response.send_message(f"Error al enviar mensaje a `{numero}`.")

    else:
        await interaction.response.send_message(
            "Acciones disponibles: `pausar`, `activar`, `estado`, `prospecto <número>`, `enviar <número> <mensaje>`"
        )


# ──────────────────────────────────────────
# Detección de prospectos desde Discord
# ──────────────────────────────────────────

def _normalize(text: str) -> str:
    """Quita tildes y convierte a minúsculas para comparación flexible."""
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    ).lower()


def _clean_phone(raw: str) -> str:
    """
    Convierte cualquier formato de teléfono a solo dígitos con + al inicio.
    Ejemplos:
      +1 (214) 436-2760  → 12144362760
      +52 33 1234 5678   → 523312345678
      214-436-2760       → 12144362760  (se conservan dígitos, sin asumir país)
      (214) 436 2760     → 2144362760
    """
    digits = re.sub(r"\D", "", raw)
    return digits


def parse_prospect_from_message(text: str) -> tuple[str, str] | None:
    """
    Detecta nombre y teléfono en mensajes como:
      "confirmación de agenda coral Carlos +5233123456"
      "conf agenda coral Carlos García +52 33 1234 5678"
      "coral Carlos +1 (214) 436-2760"
      "coral María (214) 436 2760"

    Retorna (nombre, telefono) o None si no aplica.
    """
    normalized = _normalize(text)

    # Debe contener "coral"
    if "coral" not in normalized:
        return None

    # Regex amplio: + opcional, seguido de dígitos con espacios/paréntesis/guiones
    # Captura: +1 (214) 436-2760 | +52 33 1234 5678 | 214-436-2760 | (214) 436 2760
    phone_match = re.search(r"\+?[\d][\d\s\(\)\-\.]{6,22}[\d]", text)
    if not phone_match:
        return None

    phone = _clean_phone(phone_match.group(0))
    if len(phone) < 7:
        return None

    # Extraer nombre: texto entre "coral" y el teléfono
    coral_pos = normalized.find("coral")
    before_phone = text[coral_pos + len("coral"):phone_match.start()].strip()

    # Quitar palabras de relleno comunes
    filler = r"\b(de|agenda|confirmacion|confirmaci[oó]n|conf|para|el|la|los|las)\b"
    name = re.sub(filler, "", before_phone, flags=re.IGNORECASE).strip()
    name = re.sub(r"\s+", " ", name).strip()

    if not name:
        return None

    return name, phone


@bot.event
async def on_message(message: discord.Message):
    """Detecta mensajes con 'coral + nombre + teléfono' y dispara el setting."""
    # Ignorar mensajes del propio bot
    if message.author == bot.user:
        return

    result = parse_prospect_from_message(message.content)
    if not result:
        await bot.process_commands(message)
        return

    name, phone = result

    if not _conv_manager:
        await message.channel.send("Error: gestor de conversaciones no disponible.")
        return

    # Crear conversación y guardar el nombre
    conv = await _conv_manager.get_or_create(phone)
    conv.name = name
    await _conv_manager.save(conv)

    # Enviar primer mensaje de WhatsApp
    from whapi_client import WhapiClient
    from groq_client import GroqClient

    groq = GroqClient()
    whapi = WhapiClient()

    first_message = await groq.generate_response(conv)
    sent = await whapi.send_message(phone, first_message)

    conv.add_message("assistant", first_message)
    await _conv_manager.save(conv)

    # Confirmar en Discord
    status = "Mensaje enviado" if sent else "Error al enviar"
    embed = discord.Embed(
        title=f"Nuevo setting iniciado — {name}",
        color=discord.Color.green() if sent else discord.Color.red(),
    )
    embed.add_field(name="Nombre detectado", value=name, inline=True)
    embed.add_field(name="Teléfono detectado", value=f"+{phone}", inline=True)
    embed.add_field(name="Primer mensaje enviado", value=first_message[:300], inline=False)
    embed.set_footer(text=status)
    await message.channel.send(embed=embed)

    await bot.process_commands(message)


# ──────────────────────────────────────────
# Startup
# ──────────────────────────────────────────

@bot.event
async def on_ready():
    await tree.sync()
    print(f"Discord bot listo: {bot.user}")


async def start_discord_bot():
    """Inicia el bot de Discord en segundo plano."""
    await bot.start(settings.discord_bot_token)
