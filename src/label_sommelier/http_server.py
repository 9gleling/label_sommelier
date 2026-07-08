"""Flask HTTP server for Kakao PlayMCP."""
import json
import os

from flask import Flask, request, jsonify
from flask_cors import CORS

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

app = Flask(__name__)
CORS(app)

# 핸들러 등록
_handlers = {
    "scan_wine_label": ScanWineLabelHandler(),
    "match_preference": MatchPreferenceHandler(),
    "get_wine_detail": GetWineDetailHandler(),
    "save_preference": SavePreferenceHandler(),
    "get_history": GetHistoryHandler(),
    "recommend_wine": RecommendWineHandler(),
    "find_wine_shops": FindWineShopsHandler(),
    "search_wine": SearchWineHandler(),
    "share_tasting_note": ShareTastingNoteHandler(),
    "get_preference_stats": GetPreferenceStatsHandler(),
}


def _run(tool_name: str, args: dict):
    handler = _handlers.get(tool_name)
    if not handler:
        return jsonify({"error": f"Unknown tool: {tool_name}"}), 404
    try:
        results = handler.run_tool(args)
        if results:
            text = results[0].text
            try:
                return jsonify(json.loads(text))
            except json.JSONDecodeError:
                return jsonify({"result": text})
        return jsonify({"result": None})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "tools": list(_handlers.keys())})


@app.route("/tools/<tool_name>", methods=["GET", "POST"])
def tool_endpoint(tool_name):
    if request.method == "POST":
        args = request.get_json(force=True, silent=True) or {}
    else:
        args = dict(request.args)
    return _run(tool_name, args)


def main():
    db.init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
