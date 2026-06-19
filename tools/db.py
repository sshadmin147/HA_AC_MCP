import psycopg2
import psycopg2.extras
import os
from typing import Any, Literal, cast, overload
from dotenv import load_dotenv

load_dotenv()

_conn = None

def get_connection():
    global _conn
    try:
        if _conn is None or _conn.closed:
            _conn = psycopg2.connect(
                os.getenv("DATABASE_URL"),
                cursor_factory=psycopg2.extras.RealDictCursor
            )
        return _conn
    except Exception as e:
        _conn = None
        raise e

@overload
def execute_query(sql: str, params: Any = ..., fetch: Literal[True] = ...) -> list[dict[str, Any]]: ...
@overload
def execute_query(sql: str, params: Any = ..., *, fetch: Literal[False]) -> int: ...
def execute_query(sql: str, params: Any = None, fetch: bool = True) -> list[dict[str, Any]] | int:
    global _conn
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        if fetch:
            result = cast(list[dict[str, Any]], cursor.fetchall())
            conn.commit()
            return result
        else:
            conn.commit()
            return cursor.rowcount
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        _conn = None
        conn.rollback()
        raise e
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def execute_returning(sql: str, params: Any = None) -> dict[str, Any] | None:
    global _conn
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        result = cast(dict[str, Any] | None, cursor.fetchone())
        conn.commit()
        return result
    except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
        _conn = None
        conn.rollback()
        raise e
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()