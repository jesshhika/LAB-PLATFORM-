from pathlib import Path
from typing import Any

import yaml
from fastapi import HTTPException

from api.app.core.config import get_settings


def get_labs_root() -> Path:
    configured = get_settings().labs_dir
    root = Path(configured).resolve() if configured else Path(__file__).resolve().parents[2] / "labs"
    if not root.is_dir():
        raise RuntimeError(f"Lab catalog directory does not exist: {root}")
    return root


def load_courses() -> list[dict[str, Any]]:
    root = get_labs_root()
    courses: list[dict[str, Any]] = []
    for manifest in sorted(root.glob("*/course.yaml")):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or not isinstance(data.get("labs"), list):
            raise RuntimeError(f"Invalid course manifest: {manifest}")
        data["course_dir"] = manifest.parent
        for lab in data["labs"]:
            lab["course_id"] = data["id"]
            lab["course_title"] = data["title"]
            lab["course_dir"] = manifest.parent
        courses.append(data)
    return courses


def get_course(course_id: str) -> dict[str, Any]:
    for course in load_courses():
        if course["id"] == course_id:
            return course
    raise HTTPException(status_code=404, detail="Course not found.")


def get_lab(lab_id: str) -> dict[str, Any]:
    for course in load_courses():
        for lab in course["labs"]:
            if lab["id"] == lab_id:
                return lab
    raise HTTPException(status_code=404, detail="Lab not found.")


def get_guide_path(lab: dict[str, Any]) -> Path:
    root = get_labs_root()
    path = (Path(lab["course_dir"]) / str(lab["guide"])).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Lab guide not found.")
    return path
