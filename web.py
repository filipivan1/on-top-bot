from fastapi import FastAPI
from fastapi.responses import HTMLResponse

def create_app(bot):
    app = FastAPI(title="ModBot Dashboard")

    @app.get("/", response_class=HTMLResponse)
    async def home():
        return '<html><body style="font-family:Arial;background:#111827;color:white;padding:40px"><h1>ModBot Dashboard</h1><p>Bot is online.</p><p><a href="/health" style="color:#93c5fd">Health check</a></p><p><a href="/appeal" style="color:#93c5fd">Appeal page</a></p></body></html>'

    @app.get("/health")
    async def health():
        return {"status":"ok","discord_connected":bot.is_ready()}

    @app.get("/appeal", response_class=HTMLResponse)
    async def appeal():
        return '<html><body style="font-family:Arial;background:#111827;color:white;padding:40px"><h1>Moderation Appeal</h1><p>Use the Discord /appeal command to submit an appeal.</p></body></html>'

    return app
