"""테마 템플릿 검사: 종류별 섹션과 약속된 상자 이름."""
from pathlib import Path

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

import slides

REQUIRED_BOXES = {
    "대기": (), "사도신경": (), "참회기도": (), "소식": (), "축도": (), "엔딩": (),
    "교독문": ("교독문제목", "교독문본문"),
    "본문표지": ("성경구절",),
    "말씀구절": ("구절본문", "구절장"),
}
TITLE_BOX, TITLE_GROUP = "설교제목", "본문 타이틀"


def find_shape(slide_or_group, name: str):
    """묶음 안까지 이름으로 찾는다. 없으면 None."""
    for shape in slide_or_group.shapes:
        if shape.name == name:
            return shape
        if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
            found = find_shape(shape, name)
            if found is not None:
                return found
    return None


def find_kind_slides(prs) -> dict:
    """섹션 이름 → 그 섹션 첫 장 인덱스."""
    return {name: idx[0] for name, idx in slides.sections(prs) if idx}


def validate_theme(path: Path, kinds: list) -> list:
    prs = Presentation(str(path))
    found = find_kind_slides(prs)
    problems = []
    for kind in dict.fromkeys(k for k in kinds if k in REQUIRED_BOXES):
        if kind not in found:
            problems.append(f"이 테마에는 {kind} 슬라이드가 없습니다")
            continue
        slide = prs.slides[found[kind]]
        for box in REQUIRED_BOXES[kind]:
            if find_shape(slide, box) is None:
                problems.append(f"{kind} 슬라이드에 '{box}' 상자가 없습니다")
        if kind == "본문표지" and find_shape(slide, TITLE_BOX) is None and find_shape(slide, TITLE_GROUP) is None:
            problems.append(f"본문표지 슬라이드에 '{TITLE_BOX}' 상자나 '{TITLE_GROUP}' 묶음이 없습니다")
    return problems
