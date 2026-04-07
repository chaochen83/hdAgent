from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row

from .config import settings


def ensure_database_url() -> str:
    # 在真正连库前先做一次显式校验，避免 psycopg 报错信息不够直观。
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL is not configured.")
    return settings.database_url


@contextmanager
def get_db() -> Iterator[psycopg.Connection]:
    # 这里使用最轻量的“按请求/按调用开连接”模式。
    # 当前阶段已经足够，后续再按吞吐量考虑连接池。
    conn = psycopg.connect(ensure_database_url(), row_factory=dict_row)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
