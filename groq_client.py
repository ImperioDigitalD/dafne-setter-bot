"""
Cliente de OpenAI para generar las respuestas de Dafne.
"""

from openai import AsyncOpenAI
from config import settings
from prompts import build_system_prompt, get_summary_prompt
from conversation_manager import Conversation


class GroqClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model

    async def generate_response(self, conv: Conversation) -> str:
        """Genera el siguiente mensaje de Dafne para el paso actual de la conversación."""
        system_prompt = build_system_prompt(
            current_step=conv.current_step,
            prospect_name=conv.name,
            prospect_nicho=conv.nicho,
            flow_type=conv.flow_type,
            programa=conv.programa,
        )

        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                *conv.history[-20:],
            ],
            temperature=0.7,
            max_tokens=300,
        )

        response = completion.choices[0].message.content.strip()
        if response.startswith('"') and response.endswith('"'):
            response = response[1:-1].strip()
        return response

    async def generate_summary(self, conv: Conversation) -> str:
        """Genera el resumen del prospecto para el closer."""
        prompt = get_summary_prompt(conv.history)
        completion = await self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=500,
        )
        return completion.choices[0].message.content.strip()
