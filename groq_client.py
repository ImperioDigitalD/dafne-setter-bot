"""
Cliente de OpenAI para generar las respuestas de Dafne.
"""
from openai import AsyncOpenAI
from config import settings
from prompts import build_system_prompt, get_summary_prompt
from conversation_manager import Conversation
import asyncio

class GroqClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    async def generate_response(self, conv: Conversation) -> str:
        system_prompt = build_system_prompt(
            current_step=conv.current_step,
            prospect_name=conv.name,
            prospect_nicho=conv.nicho,
            flow_type=conv.flow_type,
            programa=conv.programa,
        )
        for attempt in range(3):
            try:
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system_prompt}] + conv.messages,
                    max_tokens=500,
                    temperature=0.7,
                )
                return completion.choices[0].message.content
            except Exception as e:
                if attempt < 2:
                    await asyncio.sleep(2)
                    continue
                return "Hola! Un momento por favor."
