"""Kakao Local API: wine shop search."""
import json
import os
import urllib.parse
import urllib.request
from typing import Any, Sequence

from mcp.types import TextContent, Tool

from .toolhandler import ToolHandler


class FindWineShopsHandler(ToolHandler):
    def __init__(self):
        super().__init__("find_wine_shops")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="카카오맵 API로 주변 와인샵을 검색합니다. 위치(주소 또는 랜드마크)와 반경을 입력하세요.",
            inputSchema={
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "검색 중심 위치 (예: 강남역, 홍대입구, 서울 마포구)",
                    },
                    "radius_m": {
                        "type": "integer",
                        "description": "검색 반경 미터 (기본 1000, 최대 20000)",
                        "default": 1000,
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "최대 결과 수 (기본 10)",
                        "default": 10,
                    },
                },
                "required": ["location"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        api_key = os.environ.get("KAKAO_REST_API_KEY", "")
        if not api_key:
            return [TextContent(type="text", text=json.dumps(
                {"error": "KAKAO_REST_API_KEY 환경변수가 설정되지 않았습니다. claude_desktop_config.json에 키를 추가해주세요."},
                ensure_ascii=False
            ))]

        location = args.get("location", "")
        radius = min(int(args.get("radius_m", 1000)), 20000)
        max_results = min(int(args.get("max_results", 10)), 15)

        # 1단계: 위치 좌표 조회
        geo_url = "https://dapi.kakao.com/v2/local/search/address.json?" + urllib.parse.urlencode({"query": location})
        req = urllib.request.Request(geo_url, headers={"Authorization": f"KakaoAK {api_key}"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                geo = json.loads(r.read())
        except Exception as e:
            return [TextContent(type="text", text=json.dumps(
                {"error": f"위치 조회 실패: {e}"}, ensure_ascii=False
            ))]

        # 좌표 없으면 키워드 검색으로 중심 추정
        if geo.get("documents"):
            doc = geo["documents"][0]
            x, y = doc["x"], doc["y"]
        else:
            # 키워드 검색으로 좌표 추정
            kw_url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode({
                "query": location, "size": 1
            })
            req2 = urllib.request.Request(kw_url, headers={"Authorization": f"KakaoAK {api_key}"})
            try:
                with urllib.request.urlopen(req2, timeout=5) as r:
                    kw = json.loads(r.read())
                if not kw.get("documents"):
                    return [TextContent(type="text", text=json.dumps(
                        {"error": f"'{location}' 위치를 찾을 수 없습니다."}, ensure_ascii=False
                    ))]
                x, y = kw["documents"][0]["x"], kw["documents"][0]["y"]
            except Exception as e:
                return [TextContent(type="text", text=json.dumps(
                    {"error": f"위치 조회 실패: {e}"}, ensure_ascii=False
                ))]

        # 2단계: 와인샵 검색
        shop_url = "https://dapi.kakao.com/v2/local/search/keyword.json?" + urllib.parse.urlencode({
            "query": "와인샵",
            "x": x,
            "y": y,
            "radius": radius,
            "size": max_results,
            "sort": "distance",
        })
        req3 = urllib.request.Request(shop_url, headers={"Authorization": f"KakaoAK {api_key}"})
        try:
            with urllib.request.urlopen(req3, timeout=5) as r:
                shops = json.loads(r.read())
        except Exception as e:
            return [TextContent(type="text", text=json.dumps(
                {"error": f"와인샵 검색 실패: {e}"}, ensure_ascii=False
            ))]

        docs = shops.get("documents", [])
        if not docs:
            return [TextContent(type="text", text=json.dumps(
                {"message": f"'{location}' 반경 {radius}m 내 와인샵이 없습니다.", "results": []},
                ensure_ascii=False
            ))]

        results = []
        for d in docs:
            results.append({
                "name": d.get("place_name"),
                "address": d.get("road_address_name") or d.get("address_name"),
                "phone": d.get("phone"),
                "distance_m": int(d.get("distance", 0)),
                "kakao_map_url": d.get("place_url"),
                "category": d.get("category_name"),
            })

        return [TextContent(type="text", text=json.dumps({
            "location": location,
            "radius_m": radius,
            "total_found": len(results),
            "shops": results,
        }, ensure_ascii=False, indent=2))]
