"""
Gestión del estado de conversación por número de teléfono usando SQLite asíncrono.
"""

import json
import aiosqlite
from datetime import datetime
from dataclasses import dataclass, field
from config import settings


@dataclass
class Conversation:
    phone: str
    name: str = ""
    nicho: str = ""
    instagram: str = ""
    current_step: int = 1
    history: list = field(default_factory=list)
    temperature: str = "frío"
    status: str = "active"
    created_at: str = ""
    updated_at: str = ""

    def add_message(self, role: str, content: str):
        """Agrega un mensaje al historial. role: 'user' o 'assistant'."""
        self.history.append({"role": role, "content": content})

    def advance_step(self):
        if self.current_step < 8:
            self.current_step += 1

    def close(self):
        self.status = "closed"


class ConversationManager:
    def __init__(self, db_path: str = None):
        self.db_path = db_path or settings.db_path

    async def init_db(self):
        """Crea la tabla si no existe."""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    phone TEXT PRIMARY KEY,
                    name TEXT DEFAULT '',
                    nicho TEXT DEFAULT '',
                    instagram TEXT DEFAULT '',
                    current_step INTEGER DEFAULT 1,
                    history TEXT DEFAULT '[]',
                    temperature TEXT DEFAULT 'frío',
                    status TEXT DEFAULT 'active',
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            await db.commit()

    async def get_or_create(self, phone: str) -> Conversation:
        """Carga la conversación existente o crea una nueva."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM conversations WHERE phone = ?", (phone,)
            ) as cursor:
                row = await cursor.fetchone()

            if row:
                return Conversation(
                    phone=row["phone"],
                    name=row["name"],
                    nicho=row["nicho"],
                    instagram=row["instagram"],
                    current_step=row["current_step"],
                    history=json.loads(row["history"]),
                    temperature=row["temperature"],
                    status=row["status"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )

            now = datetime.utcnow().isoformat()
            conv = Conversation(phone=phone, created_at=now, updated_at=now)
            await db.execute(
                """INSERT INTO conversations
                   (phone, name, nicho, instagram, current_step, history, temperature, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (phone, "", "", "", 1, "[]", "frío", "active", now, now),
            )
            await db.commit()
            return conv

    async def save(self, conv: Conversation):
        """Guarda el estado actualizado de la conversación."""
        conv.updated_at = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                """UPDATE conversations SET
                   name = ?, nicho = ?, instagram = ?, current_step = ?,
                   history = ?, temperature = ?, status = ?, updated_at = ?
                   WHERE phone = ?""",
                (
                    conv.name,
                    conv.nicho,
                    conv.instagram,
                    conv.current_step,
                    json.dumps(conv.history, ensure_ascii=False),
                    conv.temperature,
                    conv.status,
                    conv.updated_at,
                    conv.phone,
                ),
            )
            await db.commit()

    async def get_active_count(self) -> int:
        """Retorna la cantidad de setteos activos."""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT COUNT(*) FROM conversations WHERE status = 'active'"
            ) as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0

    async def get_by_phone(self, phone: str) -> Conversation | None:
        """Busca una conversación por número (parcial o completo)."""
        async with aiosqlite.connect(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM conversations WHERE phone LIKE ?", (f"%{phone}%",)
            ) as cursor:
                row = await cursor.fetchone()
            if not row:
                return None
            return Conversation(
                phone=row["phone"],
                name=row["name"],
                nicho=row["nicho"],
                instagram=row["instagram"],
                current_step=row["current_step"],
                history=json.loads(row["history"]),
                temperature=row["temperature"],
                status=row["status"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def extract_prospect_data(self, conv: Conversation, ai_response: str):
        """
        Intenta extraer nombre, nicho e IG del historial para actualizar el registro.
        Lógica simple basada en palabras clave del historial.
        """
        full_text = " ".join(m["content"] for m in conv.history if m["role"] == "user").lower()

        # Instagram: buscar patrones @usuario
        import re
        ig_match = re.search(r"@[\w._]+", full_text)
        if ig_match and not conv.instagram:
            conv.instagram = ig_match.group(0)

        # Temperatura heurística
        positive_signals = ["sí", "claro", "perfecto", "me interesa", "quiero", "genial", "excelente"]
        negative_signals = ["no me interesa", "no gracias", "no puedo", "no tengo tiempo", "después"]
        positive_count = sum(1 for s in positive_signals if s in full_text)
        negative_count = sum(1 for s in negative_signals if s in full_text)
        if positive_count >= 3:
            conv.temperature = "caliente"
        elif positive_count >= 1 and negative_count == 0:
            conv.temperature = "tibio"
        else:
            conv.temperature = "frío"
