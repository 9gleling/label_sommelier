"""Wine core tools: scan, match, detail, preference, history, recommend."""
import base64
import json
import os
from pathlib import Path
from typing import Any, Sequence

import anthropic
from mcp.types import TextContent, Tool

from . import db
from .toolhandler import ToolHandler

_DEFAULT_USER = "default"


def _ai_client() -> anthropic.Anthropic:
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
    return anthropic.Anthropic(api_key=key)


def _score_wine(pref: dict, wine: dict) -> tuple[int, str, list[str]]:
    """취향 매칭 점수(0~100) 계산."""
    score = 0
    reasons: list[str] = []
    wtype = wine.get("wine_type", "")

    # 타입 매칭 (30점)
    fav_types = pref.get("favorite_types", ["Red"])
    if wtype in fav_types:
        score += 30
        reasons.append(f"선호 타입({wtype}) 일치 +30")
    else:
        reasons.append(f"선호 타입({', '.join(fav_types)})과 불일치 -0")

    # 특성 매칭 (각 15점, 총 60점)
    taste_map = [
        ("sweetness", "당도"),
        ("acidity", "산도"),
        ("tannin", "탄닌"),
        ("body", "바디"),
    ]
    wine_tastes = wine.get("taste_profile", {})
    for key, label in taste_map:
        pref_val = pref.get(key, 3)
        wine_val = wine_tastes.get(key)
        if wine_val is None:
            score += 8
            reasons.append(f"{label} 정보 없음 (기본 +8)")
        else:
            diff = abs(pref_val - wine_val)
            w = 15
            pts = max(0, w - diff * max(1, w // 3))
            score += pts
            reasons.append(f"{label} 차이 {diff} → +{pts}")

    # 품종 매칭 (10점)
    fav_vars = [v.lower() for v in pref.get("favorite_varieties", [])]
    wine_vars = [v.lower() for v in wine.get("grape_variety", [])]
    if fav_vars and wine_vars:
        if any(fv in wv or wv in fv for fv in fav_vars for wv in wine_vars):
            score += 10
            reasons.append("선호 품종 일치 +10")
        else:
            reasons.append(f"선호 품종({', '.join(fav_vars)}) 미일치")

    score = min(100, score)
    if score >= 80:
        grade = "⭐⭐⭐⭐⭐ 완벽한 매칭"
    elif score >= 60:
        grade = "⭐⭐⭐⭐ 좋은 매칭"
    elif score >= 40:
        grade = "⭐⭐⭐ 보통"
    elif score >= 20:
        grade = "⭐⭐ 아쉬운 매칭"
    else:
        grade = "⭐ 취향과 다름"
    return score, grade, reasons


# ──────────────────────────────────────────────────────────────────────────────
class ScanWineLabelHandler(ToolHandler):
    def __init__(self):
        super().__init__("scan_wine_label")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description=(
                "와인 라벨 이미지를 분석하여 와인 정보(이름, 생산자, 빈티지, 타입, "
                "원산지, 품종, 도수, 가격대, 취향 프로필)를 추출합니다."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "image_path": {
                        "type": "string",
                        "description": "라벨 이미지 파일 경로 (JPEG/PNG)",
                    },
                    "image_url": {
                        "type": "string",
                        "description": "라벨 이미지 URL (image_path 없을 때 사용)",
                    },
                    "user_id": {
                        "type": "string",
                        "description": "사용자 ID (기본값: default)",
                        "default": "default",
                    },
                },
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        user_id = args.get("user_id", _DEFAULT_USER)
        image_path = args.get("image_path")
        image_url = args.get("image_url")

        if not image_path and not image_url:
            return [TextContent(type="text", text=json.dumps(
                {"error": "image_path 또는 image_url을 제공해주세요."}, ensure_ascii=False
            ))]

        client = _ai_client()

        if image_path:
            p = Path(image_path)
            if not p.exists():
                return [TextContent(type="text", text=json.dumps(
                    {"error": f"파일을 찾을 수 없습니다: {image_path}"}, ensure_ascii=False
                ))]
            suffix = p.suffix.lower()
            media_type = "image/jpeg" if suffix in (".jpg", ".jpeg") else "image/png"
            with open(p, "rb") as f:
                b64 = base64.standard_b64encode(f.read()).decode("utf-8")
            image_content = {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}}
        else:
            image_content = {"type": "image", "source": {"type": "url", "url": image_url}}

        prompt = """이 와인 라벨을 분석하여 다음 JSON 형식으로 정보를 추출해주세요:
{
  "wine_name": "와인 전체 이름",
  "producer": "생산자/와이너리",
  "vintage": 2020,
  "wine_type": "Red|White|Rosé|Sparkling|Dessert|Fortified",
  "region": "원산지 (국가, 지역)",
  "grape_variety": ["품종1", "품종2"],
  "alcohol": "도수 (예: 13.5%)",
  "price_range": "예상 가격대 (예: 3만-5만원)",
  "description": "와인 특징 간단 설명",
  "taste_profile": {
    "sweetness": 1,
    "acidity": 4,
    "tannin": 3,
    "body": 3
  },
  "food_pairing": ["음식1", "음식2"],
  "serving_temp": "권장 서빙 온도"
}
taste_profile 값은 1(매우 낮음)~5(매우 높음) 정수. 라벨에서 확인 불가한 항목은 null로 반환.
반드시 JSON만 반환하세요."""

        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": [image_content, {"type": "text", "text": prompt}]}],
        )
        raw = resp.content[0].text.strip()

        # JSON 추출
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            wine_info = json.loads(raw)
        except json.JSONDecodeError:
            return [TextContent(type="text", text=json.dumps(
                {"error": "라벨 분석 실패", "raw": raw}, ensure_ascii=False
            ))]

        # 취향 매칭
        pref = db.get_preference(user_id)
        if pref:
            score, grade, reasons = _score_wine(pref, wine_info)
            row_id = db.save_scan(user_id, wine_info, score, grade, reasons)
        else:
            score, grade, reasons = 0, "취향 미설정", []
            row_id = db.save_scan(user_id, wine_info, 0, "미평가", [])

        result = {
            "scan_id": row_id,
            "wine_info": wine_info,
            "matching": {"score": score, "grade": grade, "reasons": reasons},
            "message": "라벨 분석 완료! 취향 매칭을 확인하려면 save_preference로 취향을 먼저 저장하세요." if not pref else "분석 완료",
        }
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]


class MatchPreferenceHandler(ToolHandler):
    def __init__(self):
        super().__init__("match_preference")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="와인 정보와 저장된 취향 프로필을 비교하여 매칭 점수(0~100)를 계산합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "wine_info": {
                        "type": "object",
                        "description": "와인 정보 (wine_type, grape_variety, taste_profile 포함)",
                    },
                    "user_id": {"type": "string", "default": "default"},
                },
                "required": ["wine_info"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        user_id = args.get("user_id", _DEFAULT_USER)
        wine_info = args.get("wine_info", {})
        pref = db.get_preference(user_id)
        if not pref:
            return [TextContent(type="text", text=json.dumps(
                {"error": "저장된 취향 프로필이 없습니다. save_preference로 먼저 취향을 저장해주세요."},
                ensure_ascii=False
            ))]
        score, grade, reasons = _score_wine(pref, wine_info)
        return [TextContent(type="text", text=json.dumps(
            {"score": score, "grade": grade, "reasons": reasons}, ensure_ascii=False, indent=2
        ))]


class GetWineDetailHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_wine_detail")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="와인 이름으로 상세 정보(산지, 품종, 특징, 음식 페어링, 보관법)를 마크다운으로 출력합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "wine_name": {"type": "string", "description": "와인 이름"},
                    "vintage": {"type": "integer", "description": "빈티지 연도 (선택)"},
                },
                "required": ["wine_name"],
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        wine_name = args.get("wine_name", "")
        vintage = args.get("vintage")
        query = f"{wine_name} {vintage}" if vintage else wine_name

        client = _ai_client()
        prompt = f"""와인 '{query}'에 대해 다음 JSON으로 상세 정보를 제공해주세요:
{{
  "wine_name": "{wine_name}",
  "vintage": {vintage or "null"},
  "producer": "생산자",
  "region": "원산지",
  "grape_variety": ["품종"],
  "wine_type": "종류",
  "alcohol": "도수",
  "description": "와인 설명 (3-4문장)",
  "taste_profile": {{"sweetness": 1, "acidity": 4, "tannin": 3, "body": 3}},
  "food_pairing": ["음식1", "음식2", "음식3"],
  "serving_temp": "서빙 온도",
  "aging_potential": "숙성 잠재력",
  "price_range_krw": "한국 예상 가격대",
  "notable_vintages": ["2018", "2016"]
}}
JSON만 반환하세요."""
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        try:
            info = json.loads(raw)
        except json.JSONDecodeError:
            info = {"wine_name": wine_name, "description": raw}

        return [TextContent(type="text", text=json.dumps(info, ensure_ascii=False, indent=2))]


class SavePreferenceHandler(ToolHandler):
    def __init__(self):
        super().__init__("save_preference")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="사용자 와인 취향 프로필을 저장합니다. 당도/산도/탄닌/바디 각 1~5, 선호 품종, 예산 등을 저장.",
            inputSchema={
                "type": "object",
                "properties": {
                    "sweetness": {"type": "integer", "description": "당도 1(드라이)~5(스위트)", "minimum": 1, "maximum": 5},
                    "acidity": {"type": "integer", "description": "산도 1(낮음)~5(높음)", "minimum": 1, "maximum": 5},
                    "tannin": {"type": "integer", "description": "탄닌 1(부드러움)~5(강함)", "minimum": 1, "maximum": 5},
                    "body": {"type": "integer", "description": "바디 1(라이트)~5(풀바디)", "minimum": 1, "maximum": 5},
                    "favorite_varieties": {"type": "array", "items": {"type": "string"}, "description": "선호 품종 목록"},
                    "favorite_types": {"type": "array", "items": {"type": "string"}, "description": "선호 타입 (Red/White/Rosé/Sparkling)"},
                    "budget_max_krw": {"type": "integer", "description": "최대 예산 (원)"},
                    "memo": {"type": "string", "description": "기타 메모"},
                    "user_id": {"type": "string", "default": "default"},
                },
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        user_id = args.get("user_id", _DEFAULT_USER)
        data = {k: v for k, v in args.items() if k != "user_id"}
        db.save_preference(user_id, data)
        pref = db.get_preference(user_id)
        return [TextContent(type="text", text=json.dumps(
            {"message": "취향 프로필 저장 완료!", "saved": pref}, ensure_ascii=False, indent=2
        ))]


class GetHistoryHandler(ToolHandler):
    def __init__(self):
        super().__init__("get_history")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="사용자의 와인 스캔 기록을 조회합니다. 점수 필터 및 개수 제한 지원.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "최대 조회 개수 (기본 20)", "default": 20},
                    "min_score": {"type": "integer", "description": "최소 매칭 점수 필터 (기본 0)", "default": 0},
                    "user_id": {"type": "string", "default": "default"},
                },
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        user_id = args.get("user_id", _DEFAULT_USER)
        limit = int(args.get("limit", 20))
        min_score = int(args.get("min_score", 0))
        history = db.get_history(user_id, limit=limit, min_score=min_score)
        if not history:
            return [TextContent(type="text", text=json.dumps(
                {"message": "스캔 기록이 없습니다. scan_wine_label로 라벨을 분석해보세요!", "total": 0},
                ensure_ascii=False
            ))]
        # 요약 형태로 반환
        summary = []
        for h in history:
            summary.append({
                "id": h["id"],
                "wine_name": h["wine_name"],
                "producer": h["producer"],
                "vintage": h["vintage"],
                "wine_type": h["wine_type"],
                "region": h["region"],
                "score": h["score"],
                "grade": h["grade"],
                "scanned_at": h["scanned_at"],
            })
        return [TextContent(type="text", text=json.dumps(
            {"total": len(summary), "history": summary}, ensure_ascii=False, indent=2
        ))]


class RecommendWineHandler(ToolHandler):
    def __init__(self):
        super().__init__("recommend_wine")

    def get_tool_description(self) -> Tool:
        return Tool(
            name=self.name,
            description="저장된 취향 프로필을 기반으로 와인 3종을 AI가 추천합니다.",
            inputSchema={
                "type": "object",
                "properties": {
                    "occasion": {"type": "string", "description": "상황/목적 (예: 생일, 데이트, 가성비)"},
                    "budget_krw": {"type": "integer", "description": "예산 (원, 없으면 취향 저장값 사용)"},
                    "user_id": {"type": "string", "default": "default"},
                },
            },
        )

    def run_tool(self, args: dict[str, Any]) -> Sequence[TextContent]:
        user_id = args.get("user_id", _DEFAULT_USER)
        occasion = args.get("occasion", "")
        budget = args.get("budget_krw")

        pref = db.get_preference(user_id)
        if not pref:
            return [TextContent(type="text", text=json.dumps(
                {"error": "취향 프로필이 없습니다. save_preference로 먼저 취향을 저장해주세요."},
                ensure_ascii=False
            ))]

        if not budget:
            budget = pref.get("budget_max_krw")

        budget_str = f"{budget:,}원 이하" if budget else "제한 없음"
        prompt = f"""사용자 와인 취향 프로필:
- 당도: {pref['sweetness']}/5, 산도: {pref['acidity']}/5, 탄닌: {pref['tannin']}/5, 바디: {pref['body']}/5
- 선호 타입: {', '.join(pref['favorite_types'])}
- 선호 품종: {', '.join(pref['favorite_varieties']) if pref['favorite_varieties'] else '없음'}
- 예산: {budget_str}
- 상황: {occasion or '일반'}

이 취향에 맞는 와인 3종을 추천해주세요. 아래 JSON 형식으로 반환:
{{
  "recommendations": [
    {{
      "rank": 1,
      "wine_name": "와인명",
      "producer": "생산자",
      "region": "원산지",
      "grape_variety": ["품종"],
      "wine_type": "종류",
      "price_range_krw": "한국 가격대",
      "why": "이 취향에 맞는 이유 2-3문장",
      "food_pairing": ["음식1", "음식2"],
      "taste_profile": {{"sweetness": 2, "acidity": 4, "tannin": 3, "body": 3}}
    }}
  ]
}}
JSON만 반환하세요."""

        client = _ai_client()
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
                {"error": "추천 생성 실패", "raw": raw}, ensure_ascii=False
            ))]
        return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
