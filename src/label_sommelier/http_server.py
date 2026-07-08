"""MCP Streamable HTTP server for Kakao PlayMCP.

Endpoint: /mcp  (transport: streamable-http)
"""
import os
from typing import Optional

from mcp.server.fastmcp import FastMCP

from . import db
from .tools_kakao import FindWineShopsHandler
from .tools_search import SearchWineHandler
from .tools_social import GetPreferenceStatsHandler, ShareTastingNoteHandler
from .tools_wine import (
    GetHistoryHandler,
    GetWineDetailHandler,
    MatchPreferenceHandler,
    RecommendWineHandler,
    SavePreferenceHandler,
    ScanWineLabelHandler,
)

mcp = FastMCP("label-sommelier")

# 핸들러 인스턴스
_scan = ScanWineLabelHandler()
_match = MatchPreferenceHandler()
_detail = GetWineDetailHandler()
_save_pref = SavePreferenceHandler()
_history = GetHistoryHandler()
_recommend = RecommendWineHandler()
_shops = FindWineShopsHandler()
_search = SearchWineHandler()
_share = ShareTastingNoteHandler()
_stats = GetPreferenceStatsHandler()


def _call(handler, args: dict) -> str:
    result = handler.run_tool(args)
    return result[0].text if result else "{}"


@mcp.tool()
def scan_wine_label(
    image_url: str = "",
    image_path: str = "",
    user_id: str = "default",
) -> str:
    """와인 라벨 이미지를 분석하여 와인 정보(이름, 생산자, 빈티지, 타입, 원산지, 품종, 도수, 가격대)를 추출합니다."""
    return _call(_scan, {"image_url": image_url, "image_path": image_path, "user_id": user_id})


@mcp.tool()
def match_preference(wine_info: dict, user_id: str = "default") -> str:
    """와인 정보와 저장된 취향 프로필을 비교하여 매칭 점수(0~100)와 등급을 계산합니다."""
    return _call(_match, {"wine_info": wine_info, "user_id": user_id})


@mcp.tool()
def get_wine_detail(wine_name: str, vintage: Optional[int] = None) -> str:
    """와인 이름으로 상세 정보(산지, 품종, 특징, 음식 페어링, 보관법)를 조회합니다."""
    return _call(_detail, {"wine_name": wine_name, "vintage": vintage})


@mcp.tool()
def save_preference(
    sweetness: int = 3,
    acidity: int = 3,
    tannin: int = 2,
    body: int = 3,
    favorite_varieties: Optional[list] = None,
    favorite_types: Optional[list] = None,
    budget_max_krw: Optional[int] = None,
    memo: str = "",
    user_id: str = "default",
) -> str:
    """사용자 취향을 저장합니다. sweetness/acidity/tannin/body는 1(낮음)~5(높음) 정수."""
    return _call(_save_pref, {
        "sweetness": sweetness,
        "acidity": acidity,
        "tannin": tannin,
        "body": body,
        "favorite_varieties": favorite_varieties or [],
        "favorite_types": favorite_types or ["Red"],
        "budget_max_krw": budget_max_krw,
        "memo": memo,
        "user_id": user_id,
    })


@mcp.tool()
def get_history(limit: int = 20, min_score: int = 0, user_id: str = "default") -> str:
    """사용자의 와인 스캔 히스토리를 조회합니다."""
    return _call(_history, {"limit": limit, "min_score": min_score, "user_id": user_id})


@mcp.tool()
def recommend_wine(
    occasion: str = "",
    budget_krw: Optional[int] = None,
    user_id: str = "default",
) -> str:
    """저장된 취향을 기반으로 와인을 추천합니다. occasion 예: 생일, 데이트, 가성비."""
    return _call(_recommend, {"occasion": occasion, "budget_krw": budget_krw, "user_id": user_id})


@mcp.tool()
def find_wine_shops(location: str, radius_m: int = 1000, max_results: int = 10) -> str:
    """카카오맵 API로 주변 와인샵을 검색합니다. location 예: 강남역, 홍대입구."""
    return _call(_shops, {"location": location, "radius_m": radius_m, "max_results": max_results})


@mcp.tool()
def search_wine(
    query: str,
    wine_type: str = "",
    max_budget_krw: Optional[int] = None,
) -> str:
    """와인 이름으로 국내 가격, 평점, 페어링 정보를 검색합니다."""
    return _call(_search, {"query": query, "wine_type": wine_type, "max_budget_krw": max_budget_krw})


@mcp.tool()
def share_tasting_note(
    scan_id: Optional[int] = None,
    wine_name: str = "",
    personal_note: str = "",
    user_id: str = "default",
) -> str:
    """최근 스캔 결과로 공유용 테이스팅 노트 카드(마크다운)를 생성합니다."""
    return _call(_share, {
        "scan_id": scan_id,
        "wine_name": wine_name,
        "personal_note": personal_note,
        "user_id": user_id,
    })


@mcp.tool()
def get_preference_stats(user_id: str = "default") -> str:
    """지금까지 스캔한 와인 기록을 분석하여 취향 통계 리포트를 생성합니다."""
    return _call(_stats, {"user_id": user_id})


def main():
    db.init_db()
    port = int(os.environ.get("PORT", 8080))
    mcp.run(transport="streamable-http", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
