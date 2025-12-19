"""
파일명: exporters.py
결과 객체를 JSON으로 저장
"""

import json
from typing import Any

def save_json(obj: Any, path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)