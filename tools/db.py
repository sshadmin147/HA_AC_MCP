import psycopg2
import psycopg2.extras
import os
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

def execute_query(sql: str, params=None, fetch=True):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        if fetch:
            return cursor.fetchall()
        else:
            conn.commit()
            return cursor.rowcount
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()

def execute_returning(sql: str, params=None):
    conn = get_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(sql, params)
        result = cursor.fetchone()
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()