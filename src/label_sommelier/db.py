"""SQLite database layer for Label Sommelier."""
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_DB_DIR = Path(os.environ.get("LABEL_SOMMELIER_DB_DIR", str(Path.home() / ".label_sommelier")))
_DB_PATH = _DB_DIR / "sommelier.db"


def _get_db() -> sqlite3.Connection:
    _DB_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    conn = _get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS preferences (
            user_id TEXT PRIMARY KEY,
            sweetness INTEGER DEFAULT 3,
            acidity INTEGER DEFAULT 3,
            tannin INTEGER DEFAULT 2,
            body INTEGER DEFAULT 3,
            favorite_varieties TEXT DEFAULT '[]',
            favorite_types TEXT DEFAULT '["Red"]',
            budget_max_krw INTEGER DEFAULT NULL,
            memo TEXT DEFAULT NULL,
            updated_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS scan_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            wine_name TEXT,
            producer TEXT,
            vintage INTEGER,
            wine_type TEXT,
            region TEXT,
            grape_variety TEXT DEFAULT '[]',
            alcohol TEXT,
            price_range TEXT,
            score INTEGER,
            grade TEXT,
            reasons TEXT DEFAULT '[]',
            wine_info TEXT DEFAULT '{}',
            scanned_at TEXT DEFAULT (datetime('now','localtime'))
        );
    """)
    conn.commit()
    conn.close()


def get_preference(user_id: str) -> dict[str, Any] | None:
    conn = _get_db()
    row = conn.execute(
        "SELECT * FROM preferences WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["favorite_varieties"] = json.loads(d["favorite_varieties"] or "[]")
    d["favorite_types"] = json.loads(d["favorite_types"] or '["Red"]')
    return d


def save_preference(user_id: str, data: dict[str, Any]) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO preferences
            (user_id, sweetness, acidity, tannin, body,
             favorite_varieties, favorite_types, budget_max_krw, memo, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
        ON CONFLICT(user_id) DO UPDATE SET
            sweetness = excluded.sweetness,
            acidity = excluded.acidity,
            tannin = excluded.tannin,
            body = excluded.body,
            favorite_varieties = excluded.favorite_varieties,
            favorite_types = excluded.favorite_types,
            budget_max_krw = excluded.budget_max_krw,
            memo = excluded.memo,
            updated_at = excluded.updated_at
    """, (
        user_id,
        data.get("sweetness", 3),
        data.get("acidity", 3),
        data.get("tannin", 2),
        data.get("body", 3),
        json.dumps(data.get("favorite_varieties", []), ensure_ascii=False),
        json.dumps(data.get("favorite_types", ["Red"]), ensure_ascii=False),
        data.get("budget_max_krw"),
        data.get("memo"),
    ))
    conn.commit()
    conn.close()


def save_scan(user_id: str, wine_info: dict, score: int, grade: str, reasons: list) -> int:
    conn = _get_db()
    cur = conn.execute("""
        INSERT INTO scan_history
            (user_id, wine_name, producer, vintage, wine_type,
             region, grape_variety, alcohol, price_range,
             score, grade, reasons, wine_info)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        wine_info.get("wine_name"),
        wine_info.get("producer"),
        wine_info.get("vintage"),
        wine_info.get("wine_type"),
        wine_info.get("region"),
        json.dumps(wine_info.get("grape_variety", []), ensure_ascii=False),
        wine_info.get("alcohol"),
        wine_info.get("price_range"),
        score,
        grade,
        json.dumps(reasons, ensure_ascii=False),
        json.dumps(wine_info, ensure_ascii=False),
    ))
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    return row_id


def get_history(user_id: str, limit: int = 20, min_score: int = 0) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM scan_history
        WHERE user_id = ? AND score >= ?
        ORDER BY scanned_at DESC
        LIMIT ?
    """, (user_id, min_score, limit)).fetchall()
    conn.close()
    results = []
    for row in rows:
        d = dict(row)
        d["grape_variety"] = json.loads(d.get("grape_variety") or "[]")
        d["reasons"] = json.loads(d.get("reasons") or "[]")
        d["wine_info"] = json.loads(d.get("wine_info") or "{}")
        results.append(d)
    return results


def get_stats(user_id: str) -> dict[str, Any]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM scan_history WHERE user_id = ? ORDER BY scanned_at DESC",
        (user_id,)
    ).fetchall()
    conn.close()

    if not rows:
        return {"total": 0}

    total = len(rows)
    scores = [r["score"] for r in rows if r["score"] is not None]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0
    best_row = max(rows, key=lambda r: r["score"] or 0)

    type_count: dict[str, int] = {}
    region_count: dict[str, int] = {}
    for r in rows:
        wt = r["wine_type"] or "Unknown"
        type_count[wt] = type_count.get(wt, 0) + 1
        rg = r["region"] or "Unknown"
        region_count[rg] = region_count.get(rg, 0) + 1

    favorite_type = max(type_count, key=type_count.get)
    favorite_region = max(region_count, key=region_count.get)

    grade_dist: dict[str, int] = {}
    for r in rows:
        g = r["grade"] or "?"
        grade_dist[g] = grade_dist.get(g, 0) + 1

    return {
        "total": total,
        "avg_score": avg_score,
        "best_wine": best_row["wine_name"],
        "best_score": best_row["score"],
        "favorite_type": favorite_type,
        "type_distribution": type_count,
        "favorite_region": favorite_region,
        "region_distribution": region_count,
        "grade_distribution": grade_dist,
        "recent_10": [
            {"wine": r["wine_name"], "score": r["score"], "date": r["scanned_at"][:10]}
            for r in rows[:10]
        ],
    }
