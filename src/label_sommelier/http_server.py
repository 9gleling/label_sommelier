"""MCP Streamable HTTP server for Kakao PlayMCP.

Endpoint: /mcp  (transport: streamable-http)

API 키 주입 방법 (우선순위):
  1. HTTP 요청 헤더 (MCP Inspector 등 클라이언트에서 설정)
     - X-Anthropic-Api-Key: sk-ant-...
     - X-Kakao-Api-Key: ...
     - Authorization: Bearer sk-ant-...  (Anthropic 키 대안)
  2. 환경변수 ANTHROPIC_API_KEY, KAKAO_REST_API_KEY (로컬 개발)
"""
import os
from typing import Optional

import anyio
import uvicorn
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from . import db
from .key_context import anthropic_key_var, get_anthropic_key, get_kakao_key, kakao_key_var
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


# ── ASGI 미들웨어: 요청 헤더에서 API 키 추출 ──────────────────────────────
class ApiKeyMiddleware:
    """HTTP 요청 헤더에서 API 키를 읽어 contextvars에 주입.

    asyncio.to_thread()가 ContextVar를 전파하므로
    스레드에서 실행되는 동기 tool handler에서도 값이 유지됩니다.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.lower(): v for k, v in scope.get("headers", [])}

            anthropic_key = (
                headers.get(b"x-anthropic-api-key", b"").decode()
                or headers.get(b"authorization", b"").decode().removeprefix("Bearer ").strip()
                or os.environ.get("ANTHROPIC_API_KEY", "")
            )
            kakao_key = (
                headers.get(b"x-kakao-api-key", b"").decode()
                or os.environ.get("KAKAO_REST_API_KEY", "")
            )

            t1 = anthropic_key_var.set(anthropic_key)
            t2 = kakao_key_var.set(kakao_key)
            try:
                await self.app(scope, receive, send)
            finally:
                anthropic_key_var.reset(t1)
                kakao_key_var.reset(t2)
        else:
            await self.app(scope, receive, send)


# ── FastMCP 서버 설정 ────────────────────────────────────────────────────
mcp = FastMCP(
    "label-sommelier",
    host="0.0.0.0",
    port=int(os.environ.get("PORT", 8080)),
    stateless_http=True,
    transport_security=None,
)

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


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 와인 라벨 스캔",
    readOnlyHint=False, destructiveHint=False,
    idempotentHint=False, openWorldHint=True,
))
def scan_wine_label(
    image_url: str = "",
    image_path: str = "",
    user_id: str = "default",
) -> str:
    """라벨소믈리에: 와인 라벨 이미지를 AI로 분석하여 이름, 생산자, 빈티지, 타입, 원산지, 품종, 도수, 가격대 정보를 추출합니다."""
    return _call(_scan, {"image_url": image_url, "image_path": image_path, "user_id": user_id})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 취향 매칭",
    readOnlyHint=True, openWorldHint=False,
))
def match_preference(wine_info: dict, user_id: str = "default") -> str:
    """라벨소믈리에: 와인 정보와 저장된 취향 프로필을 비교하여 매칭 점수(0~100)와 등급을 계산합니다."""
    return _call(_match, {"wine_info": wine_info, "user_id": user_id})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 와인 상세 정보",
    readOnlyHint=True, openWorldHint=True,
))
def get_wine_detail(wine_name: str, vintage: Optional[int] = None) -> str:
    """라벨소믈리에: 와인 이름으로 상세 정보(산지, 품종, 특징, 음식 페어링, 보관법)를 AI를 통해 조회합니다."""
    return _call(_detail, {"wine_name": wine_name, "vintage": vintage})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 취향 저장",
    readOnlyHint=False, destructiveHint=False,
    idempotentHint=True, openWorldHint=False,
))
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
    """라벨소믈리에: 사용자 취향(당도, 산도, 탄닌, 바디, 선호 품종/타입, 예산)을 저장합니다. 각 값은 1(낮음)~5(높음) 정수."""
    return _call(_save_pref, {
        "sweetness": sweetness, "acidity": acidity, "tannin": tannin, "body": body,
        "favorite_varieties": favorite_varieties or [],
        "favorite_types": favorite_types or ["Red"],
        "budget_max_krw": budget_max_krw, "memo": memo, "user_id": user_id,
    })


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 스캔 히스토리",
    readOnlyHint=True, openWorldHint=False,
))
def get_history(limit: int = 20, min_score: int = 0, user_id: str = "default") -> str:
    """라벨소믈리에: 사용자의 와인 스캔 히스토리를 조회합니다."""
    return _call(_history, {"limit": limit, "min_score": min_score, "user_id": user_id})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 와인 추천",
    readOnlyHint=True, openWorldHint=True,
))
def recommend_wine(
    occasion: str = "",
    budget_krw: Optional[int] = None,
    user_id: str = "default",
) -> str:
    """라벨소믈리에: 저장된 취향을 기반으로 AI가 와인을 추천합니다. occasion 예: 생일, 데이트, 가성비."""
    return _call(_recommend, {"occasion": occasion, "budget_krw": budget_krw, "user_id": user_id})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 주변 와인샵 검색",
    readOnlyHint=True, openWorldHint=True,
))
def find_wine_shops(location: str, radius_m: int = 1000, max_results: int = 10) -> str:
    """라벨소믈리에: 카카오맵 API로 주변 와인샵을 검색합니다. location 예: 강남역, 홍대입구."""
    return _call(_shops, {"location": location, "radius_m": radius_m, "max_results": max_results})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 와인 검색",
    readOnlyHint=True, openWorldHint=True,
))
def search_wine(
    query: str,
    wine_type: str = "",
    max_budget_krw: Optional[int] = None,
) -> str:
    """라벨소믈리에: 와인 이름으로 국내 가격, 평점, 페어링 정보를 AI를 통해 검색합니다."""
    return _call(_search, {"query": query, "wine_type": wine_type, "max_budget_krw": max_budget_krw})


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 테이스팅 노트 공유",
    readOnlyHint=True, openWorldHint=False,
))
def share_tasting_note(
    scan_id: Optional[int] = None,
    wine_name: str = "",
    personal_note: str = "",
    user_id: str = "default",
) -> str:
    """라벨소믈리에: 최근 스캔 결과로 공유용 테이스팅 노트 카드(마크다운)를 생성합니다."""
    return _call(_share, {
        "scan_id": scan_id, "wine_name": wine_name,
        "personal_note": personal_note, "user_id": user_id,
    })


@mcp.tool(annotations=ToolAnnotations(
    title="라벨소믈리에: 취향 통계",
    readOnlyHint=True, openWorldHint=False,
))
def get_preference_stats(user_id: str = "default") -> str:
    """라벨소믈리에: 지금까지 스캔한 와인 기록을 분석하여 취향 통계 리포트를 생성합니다."""
    return _call(_stats, {"user_id": user_id})


# ── 진입점 ──────────────────────────────────────────────────────────────
def main():
    db.init_db()

    # FastMCP의 Starlette 앱을 가져와 API 키 미들웨어로 감쌈
    starlette_app = mcp.streamable_http_app()
    wrapped_app = ApiKeyMiddleware(starlette_app)

    config = uvicorn.Config(
        wrapped_app,
        host=mcp.settings.host,
        port=mcp.settings.port,
        log_level=mcp.settings.log_level.lower(),
    )
    server = uvicorn.Server(config)
    anyio.run(server.serve)


if __name__ == "__main__":
    main()
