# 🍷 Label Sommelier MCP Server v2

와인 라벨 스캔 · 취향 매칭 · 카카오맵 와인샵 검색  
Claude Desktop MCP 서버

---

## 파일 구조

```
label_sommelier/
├── src/
│   └── label_sommelier/
│       ├── __init__.py        # 엔트리포인트
│       ├── server.py          # MCP 서버 (tool 라우팅)
│       ├── db.py              # SQLite 데이터 레이어
│       ├── toolhandler.py     # 추상 베이스 클래스
│       ├── tools_wine.py      # 6개 핵심 와인 툴
│       ├── tools_kakao.py     # 카카오맵 와인샵 검색
│       ├── tools_search.py    # 와인 정보 검색
│       └── tools_social.py    # 테이스팅 노트 공유 · 통계
├── pyproject.toml             # 패키지 메타데이터 (hatchling)
├── smithery.yaml              # Smithery 배포 설정
└── claude_desktop_config.example.json
```

데이터: `~/.label_sommelier/sommelier.db` (자동 생성)

---

## 설치 방법

### 방법 1: 로컬 소스 실행 (개발용)

**uv 설치** (없는 경우):
```powershell
# Windows
winget install astral-sh.uv
```

`%APPDATA%\Claude\claude_desktop_config.json`에 추가:
```json
{
  "mcpServers": {
    "label-sommelier": {
      "command": "uv",
      "args": [
        "--directory", "C:\\workspace\\kakao_mcp\\label_sommelier",
        "run", "label-sommelier"
      ],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "KAKAO_REST_API_KEY": "카카오REST키(선택)"
      }
    }
  }
}
```

### 방법 2: Git에서 직접 설치

```json
{
  "mcpServers": {
    "label-sommelier": {
      "command": "uvx",
      "args": [
        "--from", "git+https://github.com/9gleling/label_sommelier",
        "label-sommelier"
      ],
      "env": {
        "ANTHROPIC_API_KEY": "sk-ant-...",
        "KAKAO_REST_API_KEY": "카카오REST키(선택)"
      }
    }
  }
}
```

Claude Desktop 완전 종료 후 재시작.

---

## API 키

| 키 | 용도 | 발급 |
|---|---|---|
| `ANTHROPIC_API_KEY` | 라벨 분석 · 추천 **(필수)** | [console.anthropic.com](https://console.anthropic.com) |
| `KAKAO_REST_API_KEY` | 근처 와인샵 검색 (선택) | [developers.kakao.com](https://developers.kakao.com) → REST API 키 |

---

## Tools (10개)

| # | Tool | 설명 |
|---|------|------|
| 1 | `scan_wine_label` | 라벨 이미지 → 와인 정보 분석 + 취향 매칭 |
| 2 | `match_preference` | 와인 정보와 취향 프로필 매칭 점수 계산 |
| 3 | `get_wine_detail` | 와인 이름으로 상세 정보 조회 |
| 4 | `save_preference` | 취향 프로필 저장 (당도/산도/탄닌/바디/예산) |
| 5 | `get_history` | 스캔 기록 조회 (점수 필터 지원) |
| 6 | `recommend_wine` | 취향 기반 와인 3종 AI 추천 |
| 7 | `find_wine_shops` | 카카오맵으로 근처 와인샵 검색 |
| 8 | `search_wine` | 와인 이름으로 가격·평점 검색 |
| 9 | `share_tasting_note` | 공유용 테이스팅 노트 카드 생성 |
| 10 | `get_preference_stats` | 내 취향 통계 분석 리포트 |

---

## 사용 예시

```
"내 취향 저장해줘. 드라이하고 산도 높은 레드, 예산 10만원"
"이 와인 라벨 분석해줘" + 이미지 첨부
"샤또 마고 2018 상세 정보 알려줘"
"강남역 근처 와인샵 찾아줘"
"지금까지 스캔한 와인 기록 보여줘"
"내 취향에 맞는 와인 3종 추천해줘"
"이번 와인 테이스팅 노트 카드로 만들어줘"
"내 와인 취향 통계 분석해줘"
```
