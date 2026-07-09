"""API 키 컨텍스트 관리.

HTTP 요청 헤더에서 API 키를 읽어 요청 단위로 관리합니다.
환경변수 폴백을 지원하여 로컬 개발과 클라우드 배포 모두 호환됩니다.

헤더 우선순위:
  Anthropic: X-Anthropic-Api-Key > Authorization: Bearer <key> > ANTHROPIC_API_KEY env
  Kakao:     X-Kakao-Api-Key > KAKAO_REST_API_KEY env
"""
import contextvars
import os

anthropic_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "anthropic_key", default=""
)
kakao_key_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "kakao_key", default=""
)


def get_anthropic_key() -> str:
    return anthropic_key_var.get() or os.environ.get("ANTHROPIC_API_KEY", "")


def get_kakao_key() -> str:
    return kakao_key_var.get() or os.environ.get("KAKAO_REST_API_KEY", "")
