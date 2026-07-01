"""Wine search tool using Anthropic AI."""
import json
import os
from typing import Any, Sequence

import anthropic
from mcp.types import TextContent, Tool

from .toolhandler import ToolHandler


class SearchWineHandler(ToolHandler):
    def __init__(self):
        super().__init__("search_wine")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="와인 이름으로 국내 가격, 평점, 페어링 정보를 검색합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "검색어 (와인명, 생산자, 품종 등)",
                    },
                    "wine_type": {
                        "type": "string",
                        "description": "와인 종류 필터 (Red/White/Rosé/Sparkling, 선택)",
                    },
                    "max_budget_krw": {
                        "type": "integer",
                        "description": "최대 예산 (원, 선택)",
                    },
                },
                "required": ["query"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        query = args.get("query", "")
        wine_type = args.get("wine_type", "")
        budget = args.get("max_budget_krw")

        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            return [TextContent(type="text", text=json.dumps(
                {"error": "ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다."}, ensure_ascii=False
            ))]

        filter_str = ""
        if wine_type:
            filter_str += f", 타입: {wine_type}"
        if budget:
            filter_str += f", 예산: {budget:,}원 이하"

        prompt = f"""'{query}'{filter_str} 와인을 검색하여 관련 와인 목록(최대 5개)을 아래 JSON으로 반환해주세요:
{{
  "query": "{query}",
  "results": [
    {{
      "wine_name": "와인명",
      "producer": "생산자",
      "vintage": 2020,
      "wine_type": "종류",
      "region": "원산지",
      "grape_variety": ["품종"],
      "score_vivino": 4.1,
      "price_range_krw": "한국 가격대 (예: 3만~5만원)",
      "description": "짧은 설명",
      "why_recommend": "추천 이유"
    }}
  ]
}}
JSON만 반환하세요."""

        client = anthropic.Anthropic(api_key=key)
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return [TextContent(type="text", text=json.dumps(
                {"error": "검색 결과 파싱 실패", "raw": raw}, ensure_ascii=False
            ))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
