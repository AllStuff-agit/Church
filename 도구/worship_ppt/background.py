"""흰 바탕 악보 슬라이드에 배경 넣기(준비찬양 배경 보완).

옛 church-worship-ppt 스킬(2026-11 삭제)의 ppt_section_replacer.py에서 옮겨 왔다(동작 동일, 오류는 예외로).
"""
import posixpath

from lxml import etree

from insert import (P14_NS, PML_NS, R_NS, _build_rels_xml, _extract_background_from_part, _load_zip,
                    _parse_rels, _part_rels_path, _resolve_zip_target, _write_zip)

BG_FIX_RID = 'rIdBackgroundFix'


def _move_bg_to_transparent_pic(slide_xml: bytes, slide_cx: int, slide_cy: int) -> bytes | None:
    """
    <p:bg>에 악보+흰 바탕이 한 이미지로 들어 있는 슬라이드를 고친다.
    그 이미지를 흰색 투명(a:clrChange) 그림으로 전체 화면에 깔고, <p:bg>는 BG_FIX_RID를 가리키게 한다.
    배경 이미지가 없거나 이미 고친 슬라이드면 None.
    """
    A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
    tree = etree.fromstring(slide_xml)
    blip = tree.find(f'.//{{{PML_NS}}}bg//{{{A}}}blip')
    if blip is None or blip.get(f'{{{R_NS}}}embed') == BG_FIX_RID:
        return None
    score_rid = blip.get(f'{{{R_NS}}}embed')
    blip.set(f'{{{R_NS}}}embed', BG_FIX_RID)

    sp_tree = tree.find(f'.//{{{PML_NS}}}spTree')
    next_id = max([int(e.get('id')) for e in sp_tree.iter(f'{{{PML_NS}}}cNvPr') if e.get('id', '').isdigit()], default=1) + 1
    pic = etree.fromstring(
        f'<p:pic xmlns:p="{PML_NS}" xmlns:a="{A}" xmlns:r="{R_NS}">'
        f'<p:nvPicPr><p:cNvPr id="{next_id}" name="악보"/><p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr><p:nvPr/></p:nvPicPr>'
        f'<p:blipFill><a:blip r:embed="{score_rid}"><a:clrChange><a:clrFrom><a:srgbClr val="FFFFFF"/></a:clrFrom>'
        f'<a:clrTo><a:srgbClr val="FFFFFF"><a:alpha val="0"/></a:srgbClr></a:clrTo></a:clrChange></a:blip>'
        f'<a:stretch><a:fillRect/></a:stretch></p:blipFill>'
        f'<p:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{slide_cx}" cy="{slide_cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr></p:pic>')
    grp_sp_pr = sp_tree.find(f'{{{PML_NS}}}grpSpPr')
    # 그룹 속성 바로 뒤 = 가장 뒤쪽 레이어. 기존 제목·쪽번호 도형은 악보 위에 그대로 보인다.
    grp_sp_pr.addnext(pic)
    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)




def fix_section_background(target_path: str, section_name: str, bg_from: str) -> int:
    """section_name의 흰 바탕 악보 슬라이드에 bg_from 섹션 첫 슬라이드의 배경 이미지를 깐다. 고친 장수 반환."""
    files = _load_zip(target_path)
    prs_tree = etree.fromstring(files['ppt/presentation.xml'])
    rid_to_part = {r['Id']: _resolve_zip_target('ppt/presentation.xml', r['Target'])
                   for r in _parse_rels(files['ppt/_rels/presentation.xml.rels'])}
    id_to_part = {s.get('id'): rid_to_part[s.get(f'{{{R_NS}}}id')]
                  for s in prs_tree.find(f'.//{{{PML_NS}}}sldIdLst')}
    sections = {s.get('name'): [i.get('id') for i in s.iter(f'{{{P14_NS}}}sldId')]
                for s in prs_tree.iter(f'{{{P14_NS}}}section')}
    for name in (section_name, bg_from):
        if not sections.get(name):
            raise ValueError(f"섹션이 없거나 비어 있음 - '{name}'")

    # 배경 원본: bg_from 첫 슬라이드의 <p:bg> 이미지 (같은 ppt/slides/ 폴더라 상대 Target을 그대로 쓸 수 있다)
    good_part = id_to_part[sections[bg_from][0]]
    good_bg, good_media = _extract_background_from_part(files, good_part)
    if good_bg is None or not good_media:
        raise ValueError(f"'{bg_from}' 첫 슬라이드에 이미지 배경이 없습니다")
    good_img_path = next(iter(good_media.values()))[0]
    good_target = posixpath.relpath(good_img_path, posixpath.dirname(good_part))

    sld_sz = prs_tree.find(f'{{{PML_NS}}}sldSz')
    cx, cy = int(sld_sz.get('cx')), int(sld_sz.get('cy'))
    fixed = 0
    for sid in sections[section_name]:
        part = id_to_part[sid]
        new_xml = _move_bg_to_transparent_pic(files[part], cx, cy)
        if new_xml is None:
            continue
        rels_path = _part_rels_path(part)
        rels = [r for r in _parse_rels(files.get(rels_path, b'')) if r['Id'] != BG_FIX_RID]
        rels.append({'Id': BG_FIX_RID, 'Type': R_NS + '/image', 'Target': good_target, 'TargetMode': ''})
        files[part] = new_xml
        files[rels_path] = _build_rels_xml(rels)
        fixed += 1

    _write_zip(target_path, files)
    return fixed


