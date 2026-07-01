FROM python:3.11-slim

WORKDIR /app

# uv 설치
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 의존성 파일 복사
COPY pyproject.toml .
COPY src/ src/

# 의존성 설치
RUN uv pip install --system -e .

# 환경변수는 .env 파일 또는 docker run -e 로 주입
# docker run --env-file .env label-sommelier
ENV ANTHROPIC_API_KEY=""
ENV KAKAO_REST_API_KEY=""

CMD ["label-sommelier"]
