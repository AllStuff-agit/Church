"""같은 pptx 안에서 슬라이드 복제·삭제, 섹션 목록 다시 쓰기."""
import copy
import uuid

from pptx.opc.constants import RELATIONSHIP_TYPE as RT

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
SECTION_EXT_URI = "{521415D9-36F7-43E2-AB2F-B90AF26B5E84}"
SKIP_RELS = (RT.SLIDE_LAYOUT, RT.NOTES_SLIDE)


def duplicate_slide(prs, index: int) -> int:
    """index 장을 복제해 맨 뒤에 붙인다. 그림 등 연결 파일은 원본과 공유한다. 새 장의 인덱스를 돌려준다."""
    src = prs.slides[index]
    new = prs.slides.add_slide(src.slide_layout)
    rid_map = {}
    for rid, rel in src.part.rels.items():
        if rel.reltype in SKIP_RELS:
            continue
        if rel.is_external:
            rid_map[rid] = new.part.relate_to(rel.target_ref, rel.reltype, is_external=True)
        else:
            rid_map[rid] = new.part.relate_to(rel.target_part, rel.reltype)
    # python-pptx가 새 장의 spTree 요소를 붙잡아 두므로(shapes 캐시) 그 요소는 그대로 두고 안쪽만 바꾼다
    sld, src_sld = new._element, src._element
    tree, src_tree = sld.cSld.spTree, src_sld.cSld.spTree
    for child in list(tree):
        tree.remove(child)
    for child in src_tree:
        tree.append(copy.deepcopy(child))
    for child in src_sld.cSld:
        if child is not src_tree:
            tree.addprevious(copy.deepcopy(child)) if child.tag.endswith("}bg") else sld.cSld.append(copy.deepcopy(child))
    for child in list(sld):
        if child is not sld.cSld:
            sld.remove(child)
    for child in src_sld:
        if child is not src_sld.cSld:
            sld.append(copy.deepcopy(child))
    for el in sld.iter():
        for attr, value in list(el.attrib.items()):
            if attr.startswith(f"{{{R}}}") and value in rid_map:
                el.set(attr, rid_map[value])
    return len(prs.slides) - 1


def delete_slides(prs, indices: list) -> None:
    sld_ids = prs.slides._sldIdLst
    items = list(sld_ids)
    for i in sorted(set(indices), reverse=True):
        sld_id = items[i]
        prs.part.drop_rel(sld_id.get(f"{{{R}}}id"))
        sld_ids.remove(sld_id)


def _section_list(prs, create: bool):
    pres = prs.part._element
    ext_lst = pres.find(f"{{{P}}}extLst")
    if ext_lst is None:
        if not create:
            return None
        ext_lst = pres.makeelement(f"{{{P}}}extLst", {})
        pres.append(ext_lst)
    for ext in ext_lst.findall(f"{{{P}}}ext"):
        if ext.get("uri") == SECTION_EXT_URI:
            return ext.find(f"{{{P14}}}sectionLst")
    if not create:
        return None
    ext = ext_lst.makeelement(f"{{{P}}}ext", {"uri": SECTION_EXT_URI})
    ext_lst.insert(0, ext)
    lst = ext.makeelement(f"{{{P14}}}sectionLst", {}, nsmap={"p14": P14})
    ext.append(lst)
    return lst


def set_sections(prs, sections: list) -> None:
    """[(섹션 이름, 장 수)] 순서대로 섹션을 다시 만든다. 장 수 합은 전체 장 수와 같아야 한다."""
    ids = [s.get("id") for s in prs.slides._sldIdLst]
    if sum(n for _, n in sections) != len(ids):
        raise ValueError(f"섹션 장 수 합 {sum(n for _, n in sections)} ≠ 전체 장 수 {len(ids)}")
    lst = _section_list(prs, create=True)
    for child in list(lst):
        lst.remove(child)
    pos = 0
    for name, count in sections:
        sec = lst.makeelement(f"{{{P14}}}section", {"name": name, "id": "{" + str(uuid.uuid4()).upper() + "}"})
        id_lst = sec.makeelement(f"{{{P14}}}sldIdLst", {})
        for sid in ids[pos:pos + count]:
            id_lst.append(id_lst.makeelement(f"{{{P14}}}sldId", {"id": sid}))
        sec.append(id_lst)
        lst.append(sec)
        pos += count


def sections(prs) -> list:
    """[(섹션 이름, [슬라이드 인덱스])]"""
    lst = _section_list(prs, create=False)
    if lst is None:
        return []
    index_of = {s.get("id"): i for i, s in enumerate(prs.slides._sldIdLst)}
    out = []
    for sec in lst.findall(f"{{{P14}}}section"):
        idx = [index_of[s.get("id")] for s in sec.iter(f"{{{P14}}}sldId") if s.get("id") in index_of]
        out.append((sec.get("name"), idx))
    return out


def section_names(prs) -> list:
    return [name for name, _ in sections(prs)]
