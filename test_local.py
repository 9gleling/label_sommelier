"""
Label Sommelier - 실제 API 연동 E2E 테스트
실행: python test_local.py [이미지경로]

이미지 경로를 주면 실제 라벨 스캔까지 테스트합니다.
예) python test_local.py C:/Users/me/wine.jpg
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

# ── 환경 점검 ──────────────────────────────────────────────────────
api_key = os.environ.get("ANTHROPIC_API_KEY", "")
HAS_KEY = bool(api_key)

print("=" * 62)
print("  🍷 라벨소믈리에 - 실제 작동 테스트")
print("=" * 62)

if HAS_KEY:
    print(f"  ✅ API Key: {api_key[:12]}...")
else:
    print("  ⚠️  ANTHROPIC_API_KEY 없음 → DB 기능만 테스트합니다")

image_arg = sys.argv[1] if len(sys.argv) > 1 else None
if image_arg:
    p = Path(image_arg)
    print(f"  📸 이미지: {p.resolve()}")
    if not p.exists():
        print(f"  ❌ 파일 없음: {p}")
        sys.exit(1)
print("=" * 62)

# ── 공통 유틸 ──────────────────────────────────────────────────────
PASS  = "  ✅ PASS"
FAIL  = "  ❌ FAIL"
SKIP  = "  ⏭  SKIP"

def section(title):
    print(f"\n{'─'*62}")
    print(f"  {title}")
    print(f"{'─'*62}")

def dump(obj, indent=4):
    print(json.dumps(obj, ensure_ascii=False, indent=2)
          .replace("\n", "\n" + " " * indent))

errors = []

def run(name, fn):
    try:
        result = fn()
        print(PASS)
        return result
    except AssertionError as e:
        msg = f"{name}: assertion failed – {e}"
        errors.append(msg)
        print(f"{FAIL} – {e}")
    except Exception as e:
        errors.append(f"{name}: {e}")
        print(f"{FAIL} – {e}")
        import traceback; traceback.print_exc()
    return None


# ── TEST 1: 취향 저장 ──────────────────────────────────────────────
section("TEST 1 · save_preference  (DB 저장)")

from server import save_preference

result_pref = run("save_preference", lambda: (
    save_preference(
        user_id="test_user",
        sweetness=2,
        acidity=4,
        tannin=3,
        body=4,
        favorite_varieties=["Cabernet Sauvignon", "Pinot Noir"],
        favorite_types=["Red"],
    )
))
if result_pref:
    dump(result_pref)
    assert result_pref["status"] == "saved"
    assert result_pref["preference"]["acidity"] == 4
    print(PASS)


# ── TEST 2: 취향 조회 확인 ──────────────────────────────────────────
section("TEST 2 · preference file read-back")

from server import _load, PREF_FILE

def _check_pref():
    saved = _load(PREF_FILE).get("test_user")
    assert saved is not None, "저장된 취향 없음"
    assert saved["sweetness"] == 2
    assert "Cabernet Sauvignon" in saved["favorite_varieties"]
    return saved

saved_pref = run("pref read-back", _check_pref)
if saved_pref:
    dump(saved_pref)
    print(PASS)


# ── TEST 3: 라벨 스캔 ──────────────────────────────────────────────
section("TEST 3 · scan_wine_label  (Claude Vision API)")

from server import scan_wine_label

MOCK_WINE = {
    "wine_name":     "Château Margaux",
    "producer":      "Château Margaux",
    "vintage":       2018,
    "region":        "France, Bordeaux, Margaux AOC",
    "grape_variety": ["Cabernet Sauvignon", "Merlot", "Petit Verdot"],
    "alcohol":       "13.5%",
    "wine_type":     "Red",
    "tasting_notes": {
        "aroma":     "Blackcurrant, cedar, violet",
        "taste":     "Elegant tannins, rich fruit, perfect balance",
        "finish":    "Velvet smooth, long lingering finish",
        "sweetness": 2,
        "acidity":   4,
        "tannin":    4,
        "body":      5,
    },
    "food_pairing":  ["Steak", "Lamb chops", "Aged cheese"],
    "price_range":   "over 1,000,000 KRW",
    "label_language":"French",
    "confidence":    0.97,
    "_source":       "mock",
}

wine_info = None
if image_arg and HAS_KEY:
    print(f"  → 실제 이미지로 Claude API 호출 중...")
    def _scan():
        r = scan_wine_label(image_arg)
        assert "error" not in r, r.get("error")
        assert "wine_name" in r, "wine_name 키 없음"
        return r
    wine_info = run("scan_wine_label", _scan)
    if wine_info:
        dump(wine_info)
        print(PASS)
elif HAS_KEY:
    print("  ℹ️  이미지 경로 미지정 → Mock 데이터 사용")
    print("     실제 스캔: python test_local.py C:/path/to/wine_label.jpg")
    wine_info = MOCK_WINE
    print(PASS)
else:
    print("  ℹ️  API Key 없음 → Mock 데이터 사용")
    wine_info = MOCK_WINE
    print(PASS)


# ── TEST 4: 매칭 점수 ──────────────────────────────────────────────
section("TEST 4 · match_preference  (점수 계산 + 히스토리 저장)")

from server import match_preference

match_result = None
if wine_info:
    def _match():
        r = match_preference(wine_info=wine_info, user_id="test_user")
        assert "score" in r, "score 키 없음"
        if r["score"] is not None:
            assert 0 <= r["score"] <= 100, f"점수 범위 오류: {r['score']}"
        return r
    match_result = run("match_preference", _match)
    if match_result:
        dump(match_result)
        print(f"\n  🎯 매칭 점수: {match_result['score']}점  |  {match_result['grade']}")
        print(PASS)
else:
    print(SKIP)


# ── TEST 5: 상세 정보 ──────────────────────────────────────────────
section("TEST 5 · get_wine_detail  (마크다운 포맷)")

from server import get_wine_detail

if wine_info:
    def _detail():
        r = get_wine_detail(wine_info=wine_info)
        assert isinstance(r, str), "문자열이 아님"
        assert "테이스팅 노트" in r, "테이스팅 노트 섹션 없음"
        return r
    detail = run("get_wine_detail", _detail)
    if detail:
        print()
        for line in detail.split("\n"):
            print(f"    {line}")
        print(PASS)
else:
    print(SKIP)


# ── TEST 6: 히스토리 조회 ──────────────────────────────────────────
section("TEST 6 · get_history  (스캔 기록 조회)")

from server import get_history

def _history():
    r = get_history(user_id="test_user", limit=5)
    assert isinstance(r, list), "리스트가 아님"
    return r
history = run("get_history", _history)
if history:
    print(f"  기록 {len(history)}건")
    if history:
        h = history[0]
        print(f"  최근: {h.get('wine_name')} — {h.get('score')}점 {h.get('grade','')}")
    dump(history[:1])
    print(PASS)


# ── TEST 7: 와인 추천 ──────────────────────────────────────────────
section("TEST 7 · recommend_wine  (Claude API 추천)")

from server import recommend_wine

if HAS_KEY:
    def _recommend():
        r = recommend_wine(user_id="test_user", occasion="특별한 저녁")
        assert "error" not in r, r.get("error")
        assert "wines" in r, "wines 키 없음"
        assert len(r["wines"]) > 0, "추천 결과 없음"
        return r
    rec = run("recommend_wine", _recommend)
    if rec:
        dump(rec)
        print(PASS)
else:
    print("  ℹ️  API Key 없음 → SKIP")


# ── 결과 요약 ──────────────────────────────────────────────────────
print()
print("=" * 62)
if errors:
    print(f"  ❌ {len(errors)}건 실패:")
    for e in errors:
        print(f"     - {e}")
else:
    print("  🎉 모든 테스트 통과!")

print()
print("  다음 단계:")
if not image_arg:
    print("  · 실제 라벨 스캔:")
    print("    python test_local.py C:/Users/me/wine_label.jpg")
print("  · MCP Inspector 대화형 테스트:")
print("    npx @modelcontextprotocol/inspector python server.py")
print("  · Claude Desktop 연동:")
print("    claude_desktop_config.example.json 참고")
print("=" * 62)
