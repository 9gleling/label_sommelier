"""
Label Sommelier - MCP Server v2
fastmcp 기반, Claude Desktop 연동용

v2: SQLite DB, JSON 자동 마이그레이션, 카카오맵 와인샵 검색,
    와인 검색, 소셜 공유 카드, 취향 통계
"""

import base64
import json
import os
import re
import sqlite3
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

import anthropic
from fastmcp import FastMCP

# ── MCP 서버 초기화
mcp = FastMCP(name="label-sommelier")

# ── 클라이언트
claude = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
KAKAO_REST_API_KEY = os.environ.get("KAKAO_REST_API_KEY", "")

# ── SQLite
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = DATA_DIR / "sommelier.db"


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db():
    with _get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS preferences (
                user_id            TEXT PRIMARY KEY,
                sweetness          INTEGER DEFAULT 3,
                acidity            INTEGER DEFAULT 3,
                tannin             INTEGER DEFAULT 2,
                body               INTEGER DEFAULT 3,
                favorite_varieties TEXT    DEFAULT '[]',
                favorite_types     TEXT    DEFAULT '["Red"]',
                budget_max_krw     INTEGER DEFAULT NULL,
                memo               TEXT    DEFAULT NULL,
                updated_at         TEXT    DEFAULT (datetime('now','localtime'))
            );

            CREATE TABLE IF NOT EXISTS scan_history (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id       TEXT    NOT NULL,
                wine_name     TEXT,
                producer      TEXT,
                vintage       INTEGER,
                wine_type     TEXT,
                region        TEXT,
                grape_variety TEXT    DEFAULT '[]',
                alcohol       TEXT,
                price_range   TEXT,
                score         INTEGER,
                grade         TEXT,
                reasons       TEXT    DEFAULT '[]',
                wine_info     TEXT    DEFAULT '{}',
                scanned_at    TEXT    DEFAULT (datetime('now','localtime'))
            );

            CREATE INDEX IF NOT EXISTS idx_history_user
                ON scan_history(user_id, scanned_at DESC);
            CREATE INDEX IF NOT EXISTS idx_history_score
                ON scan_history(user_id, score DESC);
        """)


_init_db()


def _migrate_json():
    """기존 JSON 파일 -> SQLite 마이그레이션."""
    old_pref    = DATA_DIR / "preferences.json"
    old_history = DATA_DIR / "scan_history.json"

    if old_pref.exists():
        try:
            data = json.loads(old_pref.read_text(encoding="utf-8"))
            with _get_db() as conn:
                for user_id, p in data.items():
                    conn.execute("""
                        INSERT OR IGNORE INTO preferences
                        (user_id, sweetness, acidity, tannin, body,
                         favorite_varieties, favorite_types)
                        VALUES (?,?,?,?,?,?,?)
                    """, (
                        user_id,
                        p.get("sweetness", 3), p.get("acidity", 3),
                        p.get("tannin", 2),    p.get("body", 3),
                        json.dumps(p.get("favorite_varieties", []), ensure_ascii=False),
                        json.dumps(p.get("favorite_types", ["Red"]),  ensure_ascii=False),
                    ))
            old_pref.rename(old_pref.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[migrate] preferences: {e}", file=sys.stderr)

    if old_history.exists():
        try:
            data = json.loads(old_history.read_text(encoding="utf-8"))
            with _get_db() as conn:
                for user_id, records in data.items():
                    for r in records:
                        wi = r.get("wine_info") or {}
                        conn.execute("""
                            INSERT INTO scan_history
                            (user_id, wine_name, producer, vintage, wine_type, region,
                             grape_variety, alcohol, price_range,
                             score, grade, reasons, wine_info)
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """, (
                            user_id,
                            r.get("wine_name") or wi.get("wine_name"),
                            wi.get("producer"), wi.get("vintage"),
                            r.get("wine_type") or wi.get("wine_type"),
                            wi.get("region"),
                            json.dumps(wi.get("grape_variety", []), ensure_ascii=False),
                            wi.get("alcohol"), wi.get("price_range"),
                            r.get("score"),    r.get("grade"),
                            json.dumps(r.get("reasons", []), ensure_ascii=False),
                            json.dumps(wi, ensure_ascii=False),
                        ))
            old_history.rename(old_history.with_suffix(".json.bak"))
        except Exception as e:
            print(f"[migrate] scan_history: {e}", file=sys.stderr)


_migrate_json()


# ── 유틸 ─────────────────────────────────────────────────────────────
def _parse_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return json.loads(text.strip())


def _load_image(image_path: str):
    if image_path.startswith("data:image"):
        header, data = image_path.split(",", 1)
        mime = header.split(";")[0].replace("data:", "")
        return data, mime
    p = Path(image_path)
    if p.exists():
        ext  = p.suffix.lower()
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".png": "image/png",  ".webp": "image/webp",
                ".gif": "image/gif"}.get(ext, "image/jpeg")
        return base64.standard_b64encode(p.read_bytes()).decode(), mime
    if len(image_path) > 200:
        return image_path, "image/jpeg"
    raise FileNotFoundError(f"이미지를 찾을 수 없습니다: {image_path}")


def _kakao_get(url: str, params: dict) -> dict:
    if not KAKAO_REST_API_KEY:
        raise RuntimeError(
            "KAKAO_REST_API_KEY가 설정되지 않았습니다. "
            "install.py --env KAKAO_REST_API_KEY=... 로 등록하세요."
        )
    query = urllib.parse.urlencode(params)
    req   = urllib.request.Request(
        f"{url}?{query}",
        headers={"Authorization": f"KakaoAK {KAKAO_REST_API_KEY}"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode())


# ────────────────────────────────────────────────────────────────────
# Tool 1 · scan_wine_label
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="scan_wine_label",
    description=(
        "와인 라벨 이미지를 분석해 와인 이름, 생산자, 빈티지, 지역, 품종, "
        "테이스팅 노트(당도/산도/타닌/바디 1-5점) 등 상세 정보를 반환합니다. "
        "이미지 파일 경로(C:/...jpg) 또는 base64 문자열을 입력하세요."
    ),
)
def scan_wine_label(image_path: str) -> dict:
    try:
        image_data, media_type = _load_image(image_path)
    except FileNotFoundError as e:
        return {"error": str(e)}
    except Exception as e:
        return {"error": f"이미지 로드 실패: {e}"}

    prompt = (
        "Analyze this wine label image and respond ONLY with a JSON object. "
        "No markdown, no explanation, just raw JSON.\n\n"
        "{\n"
        '  "wine_name": "string",\n'
        '  "producer": "string or null",\n'
        '  "vintage": integer_or_null,\n'
        '  "region": "Country, Region",\n'
        '  "grape_variety": ["list of grapes"],\n'
        '  "alcohol": "e.g. 13.5% or null",\n'
        '  "wine_type": "Red | White | Rose | Sparkling | Dessert",\n'
        '  "tasting_notes": {\n'
        '    "aroma": "string", "taste": "string", "finish": "string",\n'
        '    "sweetness": 1-5, "acidity": 1-5, "tannin": 1-5, "body": 1-5\n'
        "  },\n"
        '  "food_pairing": ["food1", "food2"],\n'
        '  "price_range": "e.g. 30,000-50,000 KRW or null",\n'
        '  "label_language": "French | Italian | English | etc",\n'
        '  "confidence": 0.0-1.0\n'
        "}\n"
        "Scale: 1=very low, 3=medium, 5=very high. null for unknown fields."
    )

    resp = None
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image",
                     "source": {"type": "base64", "media_type": media_type, "data": image_data}},
                    {"type": "text", "text": prompt},
                ],
            }],
        )
        raw_text = resp.content[0].text
        result   = _parse_json(raw_text)
        result["_source"] = image_path
        return result
    except json.JSONDecodeError as e:
        raw_text = resp.content[0].text if resp else ""
        return {"error": f"JSON 파싱 실패: {e}", "raw": raw_text[:400]}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# Tool 2 · match_preference
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="match_preference",
    description=(
        "scan_wine_label 결과와 저장된 취향 프로필을 비교해 "
        "0~100점 매칭 점수와 이유를 반환합니다. "
        "wine_info에 scan_wine_label 결과를 그대로 전달하세요."
    ),
)
def match_preference(wine_info: dict, user_id: str = "default") -> dict:
    if "error" in wine_info:
        return {"error": f"wine_info 오류: {wine_info['error']}"}

    with _get_db() as conn:
        row = conn.execute(
            "SELECT * FROM preferences WHERE user_id = ?", (user_id,)
        ).fetchone()

    if not row:
        return {
            "score": None, "grade": None,
            "message": "취향 프로필이 없습니다. save_preference 툴로 먼저 저장해주세요.",
        }

    pref = dict(row)
    pref["favorite_varieties"] = json.loads(pref.get("favorite_varieties") or "[]")
    pref["favorite_types"]     = json.loads(pref.get("favorite_types")     or '["Red"]')

    notes = wine_info.get("tasting_notes") or {}
    reasons, mismatches = [], []
    total_w = earned = 0

    def _check(label, wv, pv, w):
        nonlocal total_w, earned
        if wv is None or pv is None:
            return
        total_w += w
        diff   = abs(int(wv) - int(pv))
        score  = max(0, w - diff * max(1, w // 3))
        earned += score
        (reasons if diff <= 1 else mismatches).append(
            f"{label} {'취향 일치' if diff <= 1 else '차이'} "
            f"(와인:{wv}/5, 선호:{pv}/5)"
        )

    _check("당도", notes.get("sweetness"), pref.get("sweetness"), 20)
    _check("산도", notes.get("acidity"),   pref.get("acidity"),   20)
    _check("타닌", notes.get("tannin"),    pref.get("tannin"),    20)
    _check("바디", notes.get("body"),      pref.get("body"),      15)

    fav_v  = [v.lower() for v in pref["favorite_varieties"]]
    wine_v = [v.lower() for v in (wine_info.get("grape_variety") or [])]
    if fav_v and wine_v:
        total_w += 15
        if any(fv in " ".join(wine_v) for fv in fav_v):
            earned += 15
            reasons.append(f"선호 품종 포함 ({', '.join(wine_info.get('grape_variety', []))})")
        else:
            mismatches.append(f"선호 품종({', '.join(pref['favorite_varieties'])})과 다름")

    fav_t  = [t.lower() for t in pref["favorite_types"]]
    wine_t = (wine_info.get("wine_type") or "").lower()
    if fav_t and wine_t:
        total_w += 10
        if any(ft in wine_t or wine_t in ft for ft in fav_t):
            earned += 10
            reasons.append(f"{wine_info.get('wine_type')} 타입 선호")
        else:
            mismatches.append(f"선호 타입({', '.join(pref['favorite_types'])})과 다름")

    score = round((earned / total_w) * 100) if total_w > 0 else 50
    grade = ("💎 완벽한 매칭" if score >= 85 else
             "🍷 좋은 매칭"   if score >= 70 else
             "👍 무난한 매칭" if score >= 50 else
             "⚠️ 취향과 다소 다름")

    result = {
        "score": score, "grade": grade,
        "reasons": reasons, "mismatch_reasons": mismatches,
        "wine_name": wine_info.get("wine_name"),
        "vintage":   wine_info.get("vintage"),
        "wine_type": wine_info.get("wine_type"),
    }

    wi = wine_info
    with _get_db() as conn:
        conn.execute("""
            INSERT INTO scan_history
            (user_id, wine_name, producer, vintage, wine_type, region,
             grape_variety, alcohol, price_range, score, grade, reasons, wine_info)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            user_id,
            wi.get("wine_name"), wi.get("producer"), wi.get("vintage"),
            wi.get("wine_type"), wi.get("region"),
            json.dumps(wi.get("grape_variety", []), ensure_ascii=False),
            wi.get("alcohol"), wi.get("price_range"),
            score, grade,
            json.dumps(reasons, ensure_ascii=False),
            json.dumps(wi,      ensure_ascii=False),
        ))

    return result


# ────────────────────────────────────────────────────────────────────
# Tool 3 · get_wine_detail
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="get_wine_detail",
    description="scan_wine_label 결과를 사람이 읽기 좋은 마크다운 형태로 정리해 반환합니다.",
)
def get_wine_detail(wine_info: dict) -> str:
    if "error" in wine_info:
        return f"ERROR: {wine_info['error']}"

    notes = wine_info.get("tasting_notes") or {}

    def bar(v):
        if v is None:
            return "정보 없음"
        v = int(round(v))
        return "●" * v + "○" * (5 - v) + f"  ({v}/5)"

    return "\n".join([
        f"# 🍷 {wine_info.get('wine_name', '알 수 없음')}",
        "",
        "| 항목 | 내용 |",
        "|------|------|",
        f"| 생산자 | {wine_info.get('producer') or '-'} |",
        f"| 빈티지 | {wine_info.get('vintage') or '-'} |",
        f"| 지역 | {wine_info.get('region') or '-'} |",
        f"| 품종 | {', '.join(wine_info.get('grape_variety') or ['-'])} |",
        f"| 타입 | {wine_info.get('wine_type') or '-'} |",
        f"| 알코올 | {wine_info.get('alcohol') or '-'} |",
        f"| 가격대 | {wine_info.get('price_range') or '-'} |",
        "",
        "## 🧪 테이스팅 노트",
        f"- **향(Aroma):** {notes.get('aroma') or '-'}",
        f"- **맛(Taste):** {notes.get('taste') or '-'}",
        f"- **피니쉬:** {notes.get('finish') or '-'}",
        "",
        "## 📊 수치 프로필",
        f"- 당도  {bar(notes.get('sweetness'))}",
        f"- 산도  {bar(notes.get('acidity'))}",
        f"- 타닌  {bar(notes.get('tannin'))}",
        f"- 바디  {bar(notes.get('body'))}",
        "",
        "## 🍽️ 어울리는 음식",
        ", ".join(wine_info.get("food_pairing") or ["-"]),
    ])


# ────────────────────────────────────────────────────────────────────
# Tool 4 · save_preference
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="save_preference",
    description=(
        "사용자 와인 취향 프로필을 저장합니다. "
        "당도/산도/타닌/바디는 1(낮음)~5(높음) 척도입니다. "
        "budget_max_krw에 최대 예산(원)을 입력하면 추천에 반영됩니다."
    ),
)
def save_preference(
    user_id: str = "default",
    sweetness: int = 3,
    acidity: int = 3,
    tannin: int = 2,
    body: int = 3,
    favorite_varieties: list = None,
    favorite_types: list = None,
    budget_max_krw: int = None,
    memo: str = None,
) -> dict:
    fav_v = favorite_varieties or []
    fav_t = favorite_types     or ["Red"]
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with _get_db() as conn:
        conn.execute("""
            INSERT INTO preferences
                (user_id, sweetness, acidity, tannin, body,
                 favorite_varieties, favorite_types, budget_max_krw, memo, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(user_id) DO UPDATE SET
                sweetness          = excluded.sweetness,
                acidity            = excluded.acidity,
                tannin             = excluded.tannin,
                body               = excluded.body,
                favorite_varieties = excluded.favorite_varieties,
                favorite_types     = excluded.favorite_types,
                budget_max_krw     = excluded.budget_max_krw,
                memo               = excluded.memo,
                updated_at         = excluded.updated_at
        """, (
            user_id,
            max(1, min(5, sweetness)),
            max(1, min(5, acidity)),
            max(1, min(5, tannin)),
            max(1, min(5, body)),
            json.dumps(fav_v, ensure_ascii=False),
            json.dumps(fav_t, ensure_ascii=False),
            budget_max_krw, memo, now,
        ))

    return {
        "status": "saved",
        "user_id": user_id,
        "preference": {
            "sweetness": sweetness, "acidity": acidity,
            "tannin": tannin,       "body": body,
            "favorite_varieties": fav_v,
            "favorite_types":     fav_t,
            "budget_max_krw":     budget_max_krw,
            "memo":               memo,
        },
    }


# ────────────────────────────────────────────────────────────────────
# Tool 5 · get_history
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="get_history",
    description=(
        "사용자의 와인 스캔 및 매칭 기록을 최신순으로 반환합니다. "
        "min_score로 특정 점수 이상만 필터링할 수 있습니다."
    ),
)
def get_history(
    user_id: str = "default",
    limit: int = 10,
    min_score: int = None,
) -> list:
    query  = "SELECT * FROM scan_history WHERE user_id = ?"
    params = [user_id]
    if min_score is not None:
        query  += " AND score >= ?"
        params.append(min_score)
    query += f" ORDER BY scanned_at DESC LIMIT {min(limit, 100)}"

    with _get_db() as conn:
        rows = conn.execute(query, params).fetchall()

    result = []
    for r in rows:
        entry = dict(r)
        entry["grape_variety"] = json.loads(entry.get("grape_variety") or "[]")
        entry["reasons"]       = json.loads(entry.get("reasons")       or "[]")
        entry.pop("wine_info", None)
        result.append(entry)
    return result


# ────────────────────────────────────────────────────────────────────
# Tool 6 · recommend_wine
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="recommend_wine",
    description=(
        "저장된 취향 프로필과 스캔 기록을 분석해 어울리는 와인 3종을 추천합니다. "
        "occasion에 상황(일상/선물/모임/기념일 등)을 입력하세요."
    ),
)
def recommend_wine(user_id: str = "default", occasion: str = "일상") -> dict:
    with _get_db() as conn:
        pref_row = conn.execute(
            "SELECT * FROM preferences WHERE user_id = ?", (user_id,)
        ).fetchone()
        top_rows = conn.execute(
            "SELECT wine_info FROM scan_history "
            "WHERE user_id = ? AND score >= 70 ORDER BY score DESC LIMIT 10",
            (user_id,),
        ).fetchall()

    if not pref_row:
        return {"error": "취향 프로필이 없습니다. save_preference 툴로 먼저 등록해주세요."}

    pref   = dict(pref_row)
    fav_v  = json.loads(pref.get("favorite_varieties") or "[]")
    fav_t  = json.loads(pref.get("favorite_types")     or '["Red"]')
    budget = pref.get("budget_max_krw")

    fav_regions   = list({json.loads(r["wine_info"]).get("region")
                          for r in top_rows
                          if json.loads(r["wine_info"]).get("region")} - {None})
    fav_varieties = list({v
                          for r in top_rows
                          for v in json.loads(r["wine_info"]).get("grape_variety", [])})

    prompt = f"""User wine preference:
- Sweetness:{pref['sweetness']}/5  Acidity:{pref['acidity']}/5
- Tannin:{pref['tannin']}/5  Body:{pref['body']}/5
- Favorite varieties: {', '.join(fav_v) or 'none'}
- Favorite types: {', '.join(fav_t) or 'none'}
- Enjoyed regions: {', '.join(fav_regions[:5]) or 'none yet'}
- Enjoyed varieties: {', '.join(fav_varieties[:8]) or 'none yet'}
- Budget: {'under {:,} KRW'.format(budget) if budget else 'not specified'}
- Occasion: {occasion}

Recommend 3 wines. Respond ONLY with JSON (no markdown):
{{
  "recommended_style": "한국어로 한 문장 스타일 설명",
  "wines": [
    {{
      "name":"","producer":"","region":"","grape":"",
      "price_range":"XX,000-XX,000 KRW",
      "vivino_rating":"e.g. 4.2",
      "why":"한국어 추천 이유"
    }}
  ],
  "buying_tip": "한국어 구매 팁"
}}"""

    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=900,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json(resp.content[0].text)
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# Tool 7 · find_wine_shops  (카카오 로컬 API)
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="find_wine_shops",
    description=(
        "카카오 로컬 API로 근처 와인샵을 검색합니다. "
        "address에 지역명/주소를 입력하거나 lat/lng 좌표를 직접 지정하세요. "
        "radius는 검색 반경(미터, 최대 20000). "
        "KAKAO_REST_API_KEY 환경변수가 필요합니다."
    ),
)
def find_wine_shops(
    query: str = "와인샵",
    address: str = None,
    lat: float = None,
    lng: float = None,
    radius: int = 2000,
    limit: int = 10,
) -> dict:
    # 주소 -> 좌표 변환
    if (lat is None or lng is None) and address:
        try:
            geo  = _kakao_get(
                "https://dapi.kakao.com/v2/local/search/address.json",
                {"query": address, "size": 1},
            )
            docs = geo.get("documents", [])
            if docs:
                lat = float(docs[0]["y"])
                lng = float(docs[0]["x"])
        except RuntimeError as e:
            return {"error": str(e)}
        except Exception as e:
            return {"error": f"주소 변환 실패: {e}"}

    params = {
        "query": query,
        "size":  min(limit, 15),
        "sort":  "distance" if (lat and lng) else "accuracy",
    }
    if lat and lng:
        params["y"]      = lat
        params["x"]      = lng
        params["radius"] = min(radius, 20000)

    try:
        data = _kakao_get(
            "https://dapi.kakao.com/v2/local/search/keyword.json",
            params,
        )
    except RuntimeError as e:
        return {"error": str(e)}
    except urllib.error.HTTPError as e:
        return {"error": f"카카오 API 오류 {e.code}: {e.reason}"}
    except Exception as e:
        return {"error": str(e)}

    shops = []
    for d in data.get("documents", []):
        shops.append({
            "name":       d.get("place_name"),
            "address":    d.get("road_address_name") or d.get("address_name"),
            "phone":      d.get("phone") or "-",
            "distance_m": int(d["distance"]) if d.get("distance") else None,
            "kakao_url":  d.get("place_url"),
            "category":   d.get("category_name"),
        })

    meta = data.get("meta", {})
    return {
        "total_count":     meta.get("total_count", len(shops)),
        "search_radius_m": radius if (lat and lng) else None,
        "shops":           shops,
    }


# ────────────────────────────────────────────────────────────────────
# Tool 8 · search_wine
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="search_wine",
    description=(
        "와인 이름으로 국내 가격대, Vivino 평점, 페어링, 음용 시기 등을 검색합니다. "
        "scan_wine_label 없이 이름만으로도 정보를 조회할 수 있습니다."
    ),
)
def search_wine(wine_name: str, vintage: int = None) -> dict:
    query = f"{wine_name} {vintage}" if vintage else wine_name

    prompt = f"""You are a wine expert database. Provide accurate information about:
Wine: {query}

Respond ONLY with JSON (no markdown):
{{
  "wine_name": "{wine_name}",
  "vintage": {vintage if vintage else "null"},
  "producer": "string",
  "region": "Country, Region, Appellation",
  "grape_variety": ["list"],
  "wine_type": "Red | White | Rose | Sparkling | Dessert",
  "alcohol": "e.g. 13.5%",
  "tasting_notes": {{
    "aroma": "string",
    "taste": "string",
    "finish": "string",
    "sweetness": 1,
    "acidity": 1,
    "tannin": 1,
    "body": 1
  }},
  "food_pairing": ["food1", "food2", "food3"],
  "drinking_window": "e.g. 2024-2032 or Now",
  "serving_temp_c": "e.g. 16-18",
  "decanting": false,
  "vivino_rating": "e.g. 4.2 or null",
  "price_range_krw": "e.g. 80,000-120,000 KRW or null",
  "awards": [],
  "summary": "한국어로 2-3문장 와인 소개"
}}
Use actual integer values (1-5) for sweetness/acidity/tannin/body. null for unknown fields."""

    resp = None
    try:
        resp = claude.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return _parse_json(resp.content[0].text)
    except json.JSONDecodeError as e:
        raw = resp.content[0].text if resp else ""
        return {"error": f"JSON 파싱 실패: {e}", "raw": raw[:300]}
    except Exception as e:
        return {"error": str(e)}


# ────────────────────────────────────────────────────────────────────
# Tool 9 · share_tasting_note
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="share_tasting_note",
    description=(
        "와인 정보와 매칭 점수로 공유용 테이스팅 노트 카드를 생성합니다. "
        "wine_info에 scan_wine_label 결과, "
        "match_result에 match_preference 결과를 전달하세요."
    ),
)
def share_tasting_note(
    wine_info: dict,
    match_result: dict = None,
    personal_note: str = None,
) -> str:
    notes = wine_info.get("tasting_notes") or {}

    def bar(v, size=5):
        if v is None:
            return "—"
        v = int(round(v))
        return "█" * v + "░" * (size - v)

    name_line = wine_info.get("wine_name", "알 수 없음")
    if wine_info.get("vintage"):
        name_line += f"  ·  {wine_info['vintage']}"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"🍷  {name_line}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    meta = []
    if wine_info.get("producer"):    meta.append(f"🏰 {wine_info['producer']}")
    if wine_info.get("region"):      meta.append(f"📍 {wine_info['region']}")
    if wine_info.get("wine_type"):   meta.append(f"🎨 {wine_info['wine_type']}")
    if wine_info.get("alcohol"):     meta.append(f"🌡 {wine_info['alcohol']}")
    if wine_info.get("price_range"): meta.append(f"💰 {wine_info['price_range']}")
    lines += meta + ([""] if meta else [])

    if wine_info.get("grape_variety"):
        lines += [f"🍇 {' · '.join(wine_info['grape_variety'])}", ""]

    lines += [
        "[ 테이스팅 노트 ]",
        f"  당도  {bar(notes.get('sweetness'))}",
        f"  산도  {bar(notes.get('acidity'))}",
        f"  타닌  {bar(notes.get('tannin'))}",
        f"  바디  {bar(notes.get('body'))}",
        "",
    ]

    if notes.get("aroma"):  lines.append(f"🌸 향: {notes['aroma']}")
    if notes.get("taste"):  lines.append(f"👅 맛: {notes['taste']}")
    if notes.get("finish"): lines.append(f"✨ 피니쉬: {notes['finish']}")

    if any(notes.get(k) for k in ("aroma", "taste", "finish")):
        lines.append("")

    if match_result and match_result.get("score") is not None:
        lines += [
            f"[ 내 취향 매칭 ]  {match_result['score']}점  {match_result.get('grade', '')}",
            "",
        ]

    if wine_info.get("food_pairing"):
        lines.append(f"🍽  {' · '.join(wine_info['food_pairing'])}")

    if personal_note:
        lines += ["", f"📝 {personal_note}"]

    lines += [
        "",
        f"📅 {datetime.now().strftime('%Y.%m.%d')}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "#와인 #LabelSommelier #테이스팅노트",
    ]

    return "\n".join(lines)


# ────────────────────────────────────────────────────────────────────
# Tool 10 · get_preference_stats
# ────────────────────────────────────────────────────────────────────
@mcp.tool(
    name="get_preference_stats",
    description=(
        "스캔 기록 전체를 분석해 취향 통계를 반환합니다. "
        "좋아하는 지역, 품종, 평균 점수, 베스트 와인 목록을 포함합니다."
    ),
)
def get_preference_stats(user_id: str = "default") -> dict:
    with _get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS cnt FROM scan_history WHERE user_id = ?",
            (user_id,),
        ).fetchone()["cnt"]

        if total == 0:
            return {"total_scans": 0, "message": "아직 스캔 기록이 없습니다."}

        avg_score = conn.execute(
            "SELECT ROUND(AVG(score),1) AS s FROM scan_history "
            "WHERE user_id = ? AND score IS NOT NULL",
            (user_id,),
        ).fetchone()["s"]

        best = conn.execute(
            "SELECT wine_name, vintage, score, grade, scanned_at "
            "FROM scan_history WHERE user_id = ? AND score IS NOT NULL "
            "ORDER BY score DESC LIMIT 3",
            (user_id,),
        ).fetchall()

        type_rows = conn.execute(
            "SELECT wine_type, COUNT(*) AS cnt FROM scan_history "
            "WHERE user_id = ? AND wine_type IS NOT NULL "
            "GROUP BY wine_type ORDER BY cnt DESC",
            (user_id,),
        ).fetchall()

        region_rows = conn.execute(
            "SELECT region, COUNT(*) AS cnt FROM scan_history "
            "WHERE user_id = ? AND region IS NOT NULL AND score >= 70 "
            "GROUP BY region ORDER BY cnt DESC LIMIT 5",
            (user_id,),
        ).fetchall()

        variety_rows = conn.execute(
            "SELECT grape_variety FROM scan_history "
            "WHERE user_id = ? AND score >= 70",
            (user_id,),
        ).fetchall()

    variety_count = {}
    for row in variety_rows:
        for v in json.loads(row["grape_variety"] or "[]"):
            variety_count[v] = variety_count.get(v, 0) + 1
    top_varieties = sorted(variety_count, key=lambda x: -variety_count[x])[:5]

    return {
        "total_scans":        total,
        "average_score":      avg_score,
        "top_wines":          [dict(r) for r in best],
        "wine_types":         [dict(r) for r in type_rows],
        "favorite_regions":   [dict(r) for r in region_rows],
        "favorite_varieties": top_varieties,
        "generated_at":       datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


# ────────────────────────────────────────────────────────────────────
# Entrypoint
# ────────────────────────────────────────────────────────────────────
def main():
    mcp.run()


if __name__ == "__main__":
    main()
