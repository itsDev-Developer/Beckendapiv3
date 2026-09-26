from aiohttp.web import Application
from cryptography.fernet import Fernet
from aiohttp_session import setup
from aiohttp_session.cookie_storage import EncryptedCookieStorage

from bot.server.stream_routes import routes
from bot.server.hls_routes import hls_routes
from bot.server.health_routes import health_routes
from bot.server.cors import cors_middleware
from bot.server.rate_limit import rate_limit_middleware

secret_key = Fernet.generate_key()

async def web_server():
    web_app = Application(
        client_max_size=30000000,
        middlewares=[cors_middleware, rate_limit_middleware],
    )
    setup(web_app, EncryptedCookieStorage(Fernet(secret_key)))
    web_app.add_routes(routes)
    web_app.add_routes(hls_routes)
    web_app.add_routes(health_routes)
    return web_app
