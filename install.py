"""
Label Sommelier v2 - Claude Desktop 자동 등록 스크립트

실행:
    python install.py
    python install.py --env ANTHROPIC_API_KEY=sk-ant-... --env KAKAO_REST_API_KEY=...
"""

import argparse
import json
import os
import platform
import sys
from pathlib import Path


def get_claude_config_path():
    system = platform.system()
    if system == "Darwin":
        p = Path.home() / "Library" / "Application Support" / "Claude"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", "")
        p = Path(appdata) / "Claude" if appdata else None
    else:
        p = Path.home() / ".config" / "Claude"

    if p and p.exists():
        return p
    if p:
        try:
            p.mkdir(parents=True, exist_ok=True)
            return p
        except Exception:
            pass
    return None


def get_python_executable():
    venv = os.environ.get("VIRTUAL_ENV")
    if venv:
        exe = (Path(venv) / "Scripts" / "python.exe"
               if platform.system() == "Windows"
               else Path(venv) / "bin" / "python")
        if exe.exists():
            return str(exe)

    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        exe = (Path(conda) / "python.exe"
               if platform.system() == "Windows"
               else Path(conda) / "bin" / "python")
        if exe.exists():
            return str(exe)

    return sys.executable


def update_claude_config(server_name, server_script, python_exe, env_vars):
    config_dir = get_claude_config_path()
    if not config_dir:
        print("❌ Claude Desktop 설정 폴더를 찾을 수 없습니다.")
        print("   Claude Desktop을 먼저 설치하고 한 번 실행해주세요.")
        print("   https://claude.ai/download")
        return False

    config_file = config_dir / "claude_desktop_config.json"

    if not config_file.exists():
        config_file.write_text("{}", encoding="utf-8")
        print(f"  ℹ️  설정 파일 생성: {config_file}")

    try:
        config = json.loads(config_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print("  ⚠️  기존 설정 파일이 손상됨 → 초기화합니다.")
        config = {}

    if "mcpServers" not in config:
        config["mcpServers"] = {}

    existing_env = config["mcpServers"].get(server_name, {}).get("env", {})
    merged_env   = {**existing_env, **env_vars}

    config["mcpServers"][server_name] = {
        "command": python_exe,
        "args":    [str(server_script.resolve())],
        "env":     merged_env,
    }

    config_file.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True, config_file


def main():
    parser = argparse.ArgumentParser(
        description="라벨소믈리에 v2를 Claude Desktop에 등록합니다."
    )
    parser.add_argument(
        "--env", "-e",
        action="append",
        metavar="KEY=VALUE",
        help="환경변수 지정 (여러 번 사용 가능)",
    )
    args = parser.parse_args()

    print()
    print("=" * 60)
    print("  🍷 라벨소믈리에 v2 × Claude Desktop 등록")
    print("=" * 60)

    env_dict = {}

    if args.env:
        for item in args.env:
            if "=" not in item:
                print(f"  ⚠️  잘못된 형식 (KEY=VALUE 필요): {item}")
                sys.exit(1)
            k, v = item.split("=", 1)
            env_dict[k.strip()] = v.strip()

    # ── Anthropic API 키
    if "ANTHROPIC_API_KEY" not in env_dict:
        existing = os.environ.get("ANTHROPIC_API_KEY", "")
        if existing:
            print(f"  ℹ️  환경변수에서 Anthropic API 키 감지: {existing[:12]}...")
            ans = input("  → 이 키를 사용할까요? [Y/n] ").strip().lower()
            if ans in ("", "y", "yes"):
                env_dict["ANTHROPIC_API_KEY"] = existing
        if "ANTHROPIC_API_KEY" not in env_dict:
            key = input("  ANTHROPIC_API_KEY 입력 (sk-ant-...): ").strip()
            if not key.startswith("sk-"):
                print("  ⚠️  유효하지 않은 키 형식입니다.")
                sys.exit(1)
            env_dict["ANTHROPIC_API_KEY"] = key

    # ── 카카오 REST API 키 (선택)
    if "KAKAO_REST_API_KEY" not in env_dict:
        existing_k = os.environ.get("KAKAO_REST_API_KEY", "")
        if existing_k:
            print(f"  ℹ️  환경변수에서 카카오 API 키 감지: {existing_k[:8]}...")
            ans_k = input("  → 이 키를 사용할까요? [Y/n] ").strip().lower()
            if ans_k in ("", "y", "yes"):
                env_dict["KAKAO_REST_API_KEY"] = existing_k
        if "KAKAO_REST_API_KEY" not in env_dict:
            print()
            print("  카카오 로컬 API 키 (와인샵 검색에 필요, 선택 사항)")
            print("  발급: https://developers.kakao.com → 내 애플리케이션 → REST API 키")
            key_k = input("  KAKAO_REST_API_KEY 입력 (없으면 Enter 스킵): ").strip()
            if key_k:
                env_dict["KAKAO_REST_API_KEY"] = key_k
            else:
                print("  ⏭  카카오 API 키 생략 (나중에 재실행하면 추가 가능)")

    # ── 경로
    server_script = Path(__file__).parent / "server.py"
    if not server_script.exists():
        print(f"  ❌ server.py를 찾을 수 없습니다: {server_script}")
        sys.exit(1)

    python_exe = get_python_executable()
    print(f"\n  Python    : {python_exe}")
    print(f"  server    : {server_script.resolve()}")
    print(f"  Anthropic : {env_dict['ANTHROPIC_API_KEY'][:12]}...")
    if "KAKAO_REST_API_KEY" in env_dict:
        print(f"  Kakao     : {env_dict['KAKAO_REST_API_KEY'][:8]}...")

    # ── config 업데이트
    result = update_claude_config(
        server_name="label-sommelier",
        server_script=server_script,
        python_exe=python_exe,
        env_vars=env_dict,
    )

    if result and result[0]:
        config_file = result[1]
        print(f"\n  ✅ 등록 완료!")
        print(f"     설정 파일: {config_file}")
        print()
        print("  ⚡ 다음 단계:")
        print("     1. Claude Desktop을 완전히 종료합니다 (트레이 아이콘까지)")
        print("     2. Claude Desktop을 다시 시작합니다")
        print("     3. 채팅창 하단 🔨 아이콘에서 라벨소믈리에 툴 10개 확인")
        print()
        print("  💬 시작해보세요:")
        print('     "내 와인 취향을 저장해줘. 드라이하고 산도 높은 레드 선호."')
        print('     "이 와인 라벨 분석해줘" + 이미지 첨부')
        print('     "강남역 근처 와인샵 찾아줘"')
        print('     "샤또 마고 검색해줘"')
        print('     "내 취향 통계 보여줘"')
    else:
        print("\n  ❌ 등록 실패. 위 오류 메시지를 확인해주세요.")
        sys.exit(1)

    print("=" * 60)


if __name__ == "__main__":
    main()
