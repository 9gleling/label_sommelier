FROM python:3.11-slim

WORKDIR /app

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 의존성 파일 복사
COPY pyproject.toml .
COPY README.md .
COPY src/ src/

# 의존성 설치 (non-editable, 프로덕션 안정)
RUN uv pip install --system .

# 데이터 디렉토리
RUN mkdir -p /app/data
ENV LABEL_SOMMELIER_DB_DIR="/app/data"

# 환경변수 (Private repo에서만 사용)
ARG ANTHROPIC_API_KEY=""
ARG KAKAO_REST_API_KEY=""
ENV ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
ENV KAKAO_REST_API_KEY=${KAKAO_REST_API_KEY}

EXPOSE 8080

CMD ["label-sommelier-http"]
