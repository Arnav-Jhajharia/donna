from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings


def _clean_url(url: str) -> tuple[str, dict]:
    """Strip sslmode from URL (asyncpg uses connect_args ssl= instead)."""
    parsed = urlparse(url)
    params = parse_qs(parsed.query, keep_blank_values=True)
    ssl_mode = params.pop("sslmode", ["disable"])[0]
    clean = urlunparse(parsed._replace(query=urlencode(params, doseq=True)))
    connect_args: dict = {"statement_cache_size": 0}
    if ssl_mode in ("require", "verify-ca", "verify-full"):
        connect_args["ssl"] = "require"
    else:
        connect_args["ssl"] = False
    return clean, connect_args


_url, _connect_args = _clean_url(settings.database_url or "postgresql+asyncpg://localhost/donna")
_engine = create_async_engine(
    _url, pool_pre_ping=True, pool_size=5, max_overflow=10,
    connect_args=_connect_args,
)
async_session = async_sessionmaker(_engine, class_=AsyncSession, expire_on_commit=False)
