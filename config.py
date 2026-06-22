from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    # Groq
    groq_api_key: str
    groq_model: str = "llama-3.3-70b-versatile"

    # Whapi
    whapi_url: str = "https://gate.whapi.cloud/"
    whapi_token: str

    # Discord
    discord_bot_token: str
    discord_alerts_channel_id: int
    discord_leads_channel_id: int

    # Seguridad del webhook
    webhook_secret: str = ""

    # Base de datos
    db_path: str = "dafne_bot.db"


settings = Settings()
