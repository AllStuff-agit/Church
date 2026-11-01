"""찬송·준비찬양 PPT를 예배 PPT의 빈 섹션에 끼우기.

.claude/skills/church-worship-ppt/scripts/ppt_section_replacer.py에서 필요한 부분만 옮겨 온 것(동작 동일).
조립 도구가 스킬 파일에 의존하지 않도록 독립시켰다.
"""
import copy
import io
import os
import posixpath
import re
import shutil
import subprocess
import sys
import uuid
import warnings
import zipfile
from pathlib import Path

from lxml import etree
from pptx import Presentation
from pptx.oxml.ns import qn

P14_NS     = 'http://schemas.microsoft.com/office/powerpoint/2010/main'
P14        = {'p14': P14_NS}
RELS_NS    = 'http://schemas.openxmlformats.org/package/2006/relationships'
PML_NS     = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R_NS       = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
SLIDE_CT   = 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'
SLIDE_REL  = R_NS + '/slide'
LAYOUT_REL = R_NS + '/slideLayout'


def soffice() -> str:
    """LibreOffice 실행 파일. Windows는 PATH에 없어도 기본 설치 경로에서 찾는다."""
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for path in (r"C:\Program Files\LibreOffice\program\soffice.exe",
                 r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"):
        if os.path.exists(path):
            return path
    print("ERROR: LibreOffice(soffice)를 찾을 수 없습니다. 설치: winget install TheDocumentFoundation.LibreOffice")
    sys.exit(1)


def deduplicate_zip(pptx_path: str):
    """LibreOffice 변환 후 zip 내 중복 항목 제거 (마지막 항목 기준으로 유지)"""
    seen = {}
    with zipfile.ZipFile(pptx_path, 'r') as zin:
        for item in zin.infolist():
            # zin.open(item) 으로 특정 항목을 직접 읽어야 마지막 항목이 정확히 저장됨
            # (zin.read(name) 은 항상 첫 번째 매칭을 반환하므로 사용 금지)
            with zin.open(item) as f:
                seen[item.filename] = f.read()
    tmp = pptx_path + '.dedup'
    with zipfile.ZipFile(tmp, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in seen.items():
            zout.writestr(name, data)
    os.replace(tmp, pptx_path)


def save_deduplicated(prs: Presentation, target: str):
    """
    python-pptx Presentation을 BytesIO에 저장 후 zip 중복 제거하여 깨끗한 파일로 기록.
    prs.save(target) + deduplicate_zip(target) 대체.
    중복 발생 원인: copy_slide() 가 다른 Presentation의 슬라이드를 복사할 때
    미디어 파트 이름이 겹쳐 python-pptx 내부에서 같은 zip 항목을 여러 번 기록.
    BytesIO 경유로 저장 후 ZipInfo 단위로 읽어 last-wins 중복 제거.
    """
    import warnings
    buf = io.BytesIO()
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Duplicate name')
        prs.save(buf)
    buf.seek(0)

    seen = {}
    with zipfile.ZipFile(buf, 'r') as zin:
        for item in zin.infolist():
            with zin.open(item) as f:
                seen[item.filename] = f.read()

    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as zout:
        for name, data in seen.items():
            zout.writestr(name, data)


def convert_to_pptx(src_path: str, tmp_dir: str) -> str:
    """
    .ppt 파일을 LibreOffice로 .pptx 변환 후 경로 반환.
    이미 .pptx면 그대로 반환.
    """
    src = Path(src_path)
    if src.suffix.lower() == '.pptx':
        return str(src)

    result = subprocess.run(
        [soffice(), '--headless', '--convert-to', 'pptx', str(src), '--outdir', tmp_dir],
        capture_output=True, text=True
    )
    converted = Path(tmp_dir) / (src.stem + '.pptx')
    if not converted.exists():
        print(f"ERROR: 변환 실패 - {src_path}")
        print(result.stderr)
        sys.exit(1)
    deduplicate_zip(str(converted))
    return str(converted)



def _load_zip(path: str) -> dict:
    files = {}
    with zipfile.ZipFile(path, 'r') as z:
        for name in z.namelist():
            files[name] = z.read(name)
    return files


def _write_zip(path: str, files: dict):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
            z.writestr(name, data)


def _parse_rels(xml_bytes: bytes) -> list:
    """rels XML → [{Id, Type, Target, TargetMode}] 리스트"""
    if not xml_bytes:
        return []
    tree = etree.fromstring(xml_bytes)
    result = []
    for rel in tree.findall(f'{{{RELS_NS}}}Relationship'):
        result.append({
            'Id':         rel.get('Id', ''),
            'Type':       rel.get('Type', ''),
            'Target':     rel.get('Target', ''),
            'TargetMode': rel.get('TargetMode', ''),
        })
    return result


def _build_rels_xml(rels: list) -> bytes:
    """rels 리스트 → XML bytes"""
    root = etree.Element(f'{{{RELS_NS}}}Relationships')
    for r in rels:
        rel = etree.SubElement(root, f'{{{RELS_NS}}}Relationship')
        rel.set('Id',     r['Id'])
        rel.set('Type',   r['Type'])
        rel.set('Target', r['Target'])
        if r.get('TargetMode'):
            rel.set('TargetMode', r['TargetMode'])
    return etree.tostring(root, xml_declaration=True, encoding='UTF-8', standalone=True)


def _resolve_zip_target(source_part: str, target: str) -> str:
    """OOXML 관계의 상대 Target을 ZIP 내부 경로로 변환한다."""
    if target.startswith('/'):
        return target.lstrip('/')
    return posixpath.normpath(posixpath.join(posixpath.dirname(source_part), target))


def _part_rels_path(part_path: str) -> str:
    """파트 경로에 대응하는 .rels 경로를 반환한다."""
    return posixpath.join(
        posixpath.dirname(part_path),
        '_rels',
        posixpath.basename(part_path) + '.rels',
    )


def _extract_background_from_part(src_files: dict, part_path: str) -> tuple:
    """특정 슬라이드/레이아웃/마스터 파트의 배경과 배경 이미지를 추출한다."""
    PML = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    R   = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    IMG = R + '/image'

    xml = src_files.get(part_path)
    if xml is None:
        return None, {}

    tree = etree.fromstring(xml)
    bg_elem = tree.find(f'.//{{{PML}}}bg')
    if bg_elem is None:
        return None, {}

    rels = _parse_rels(src_files.get(_part_rels_path(part_path), b''))
    rid_to_target = {
        r['Id']: r['Target']
        for r in rels
        if r['Type'] == IMG and r.get('TargetMode', '') != 'External'
    }
    media = {}
    embed_ids = set(bg_elem.xpath('.//@r:embed', namespaces={'r': R}))
    for rid in embed_ids:
        target = rid_to_target.get(rid)
        if not target:
            continue
        src_img_path = _resolve_zip_target(part_path, target)
        if src_img_path in src_files:
            media[rid] = (src_img_path, src_files[src_img_path])

    return bg_elem, media


def _extract_master_background(
    src_files: dict,
    src_slide_path: str | None = None,
    src_slide_rels: list | None = None,
) -> tuple:
    """
    소스 슬라이드가 실제로 사용하는 레이아웃/마스터에서 배경 (<p:bg>) 요소와
    배경 이미지(있는 경우)를 추출한다.

    슬라이드별 배경이 없으면 슬라이드 레이아웃을 먼저 확인하고, 레이아웃에도
    없을 때 그 레이아웃이 연결된 마스터를 확인한다. 기존 구현처럼 presentation.xml
    의 첫 번째 마스터를 무조건 선택하면 다중 마스터 PPT의 배경을 잃어버릴 수 있다.
    반환: (bg_elem, {zip_path: bytes}) 또는 (None, {})
    """
    if src_slide_path and src_slide_rels is not None:
        layout_rel = next(
            (r for r in src_slide_rels if r['Type'] == LAYOUT_REL),
            None,
        )
        if layout_rel:
            layout_path = _resolve_zip_target(src_slide_path, layout_rel['Target'])

            # 레이아웃 자체에 지정된 배경이 있으면 그것이 마스터보다 우선한다.
            bg_elem, media = _extract_background_from_part(src_files, layout_path)
            if bg_elem is not None:
                return bg_elem, media

            layout_rels = _parse_rels(src_files.get(_part_rels_path(layout_path), b''))
            master_rel = next(
                (r for r in layout_rels if r['Type'].endswith('/slideMaster')),
                None,
            )
            if master_rel:
                master_path = _resolve_zip_target(layout_path, master_rel['Target'])
                bg_elem, media = _extract_background_from_part(src_files, master_path)
                if bg_elem is not None:
                    return bg_elem, media

    # 관계 정보가 없는 오래된 자료에 대한 안전한 fallback.
    prs_rels = _parse_rels(src_files.get('ppt/_rels/presentation.xml.rels', b''))
    for r in prs_rels:
        if 'slideMaster' in r['Type']:
            master_path = _resolve_zip_target('ppt/presentation.xml', r['Target'])
            bg_elem, media = _extract_background_from_part(src_files, master_path)
            if bg_elem is not None:
                return bg_elem, media

    return None, {}


def _inject_background(slide_xml: bytes, bg_elem, bg_media: dict,
                       new_rels: list, new_media: dict) -> bytes:
    """
    슬라이드 XML의 <p:cSld> 안에 <p:bg>를 삽입.
    bg_media의 이미지를 new_media에 등록하고 rId를 new_rels에 추가.
    """
    PML = 'http://schemas.openxmlformats.org/presentationml/2006/main'
    R   = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    IMG = R + '/image'

    import copy

    try:
        tree = etree.fromstring(slide_xml)
    except Exception:
        return slide_xml

    cSld = tree.find(f'{{{PML}}}cSld')
    if cSld is None:
        return slide_xml

    # 기존 <p:bg> 제거 후 새로 삽입
    existing_bg = cSld.find(f'{{{PML}}}bg')
    if existing_bg is not None:
        cSld.remove(existing_bg)

    new_bg = copy.deepcopy(bg_elem)

    # 이미지 rId → 새 UUID 이름으로 교체
    rid_map = {}
    for old_rid, (src_path, img_bytes) in bg_media.items():
        ext = Path(src_path).suffix
        uid = uuid.uuid4().hex[:12]
        new_name = f'media_{uid}{ext}'
        new_zip_path = f'ppt/media/{new_name}'
        new_media[new_zip_path] = img_bytes

        # 다음 rId 번호 계산
        existing_nums = [int(m.group(1)) for r in new_rels
                         for m in [re.match(r'rId(\d+)$', r['Id'])] if m]
        next_num = max(existing_nums, default=0) + 1
        new_rid = f'rId{next_num}'
        rid_map[old_rid] = new_rid

        new_rels.append({'Id': new_rid, 'Type': IMG,
                         'Target': f'../media/{new_name}', 'TargetMode': ''})

    # bg XML에서 r:embed 값 교체
    if rid_map:
        bg_str = etree.tostring(new_bg).decode('utf-8')
        for old_rid, new_rid in rid_map.items():
            bg_str = bg_str.replace(f'r:embed="{old_rid}"', f'r:embed="{new_rid}"')
            bg_str = bg_str.replace(f'embed="{old_rid}"', f'embed="{new_rid}"')
        new_bg = etree.fromstring(bg_str)

    # <p:spTree> 앞에 삽입
    spTree = cSld.find(f'{{{PML}}}spTree')
    if spTree is not None:
        spTree.addprevious(new_bg)
    else:
        cSld.insert(0, new_bg)

    return etree.tostring(tree, xml_declaration=True, encoding='UTF-8', standalone=True)


BG_FIX_RID = 'rIdBackgroundFix'



def _get_layout_target_for_new_slides(target_files: dict) -> str:
    """target 파일에서 기존 슬라이드가 사용하는 레이아웃 참조 경로 반환."""
    for name in sorted(target_files.keys()):
        if re.match(r'ppt/slides/_rels/slide\d+\.xml\.rels$', name):
            for r in _parse_rels(target_files[name]):
                if LAYOUT_REL in r['Type']:
                    return r['Target']  # e.g. '../slideLayouts/slideLayout6.xml'
    return '../slideLayouts/slideLayout6.xml'


def _count_slides_in_zip(pptx_path: str) -> int:
    count = 0
    with zipfile.ZipFile(pptx_path, 'r') as z:
        for name in z.namelist():
            if re.match(r'ppt/slides/slide\d+\.xml$', name):
                count += 1
    return count


def _update_content_types(target_files: dict, new_slide_paths: list, new_media_paths: list):
    """[Content_Types].xml 슬라이드 Override 동기화 및 미디어 Default 추가."""
    CT_NS = 'http://schemas.openxmlformats.org/package/2006/content-types'
    tree = etree.fromstring(target_files['[Content_Types].xml'])

    # 실제 존재하는 슬라이드 경로 집합
    actual_slide_partnames = {
        '/' + k for k in target_files
        if k.startswith('ppt/slides/slide') and k.endswith('.xml')
    }

    # 존재하지 않는 슬라이드 Override 항목 제거
    for e in list(tree):
        local = e.tag.split('}')[-1] if '}' in e.tag else e.tag
        if local == 'Override':
            pname = e.get('PartName', '')
            if '/slides/slide' in pname and pname not in actual_slide_partnames:
                tree.remove(e)

    existing_overrides: set = set()
    existing_defaults: set = set()
    for e in tree:
        local = e.tag.split('}')[-1] if '}' in e.tag else e.tag
        if local == 'Override':
            existing_overrides.add(e.get('PartName', ''))
        elif local == 'Default':
            existing_defaults.add(e.get('Extension', '').lower())

    MEDIA_CT = {
        'png': 'image/png',   'jpg': 'image/jpeg',  'jpeg': 'image/jpeg',
        'gif': 'image/gif',   'bmp': 'image/bmp',   'tiff': 'image/tiff',
        'emf': 'image/x-emf', 'wmf': 'image/x-wmf', 'svg':  'image/svg+xml',
    }

    for path in new_slide_paths:
        pname = '/' + path.lstrip('/')
        if pname not in existing_overrides:
            e = etree.SubElement(tree, f'{{{CT_NS}}}Override')
            e.set('PartName', pname)
            e.set('ContentType', SLIDE_CT)
            existing_overrides.add(pname)

    for path in new_media_paths:
        ext = path.rsplit('.', 1)[-1].lower() if '.' in path else ''
        # ppt/media/ 안의 .xml 파일은 실제 슬라이드 XML일 수 있으므로
        # 내용을 확인해 슬라이드면 Override로 정확한 ContentType 등록
        if ext == 'xml' and path in target_files:
            content = target_files[path]
            if b'<p:sld ' in content or b'<p:sld\n' in content or b'<p:sld>' in content:
                pname = '/' + path.lstrip('/')
                if pname not in existing_overrides:
                    e = etree.SubElement(tree, f'{{{CT_NS}}}Override')
                    e.set('PartName', pname)
                    e.set('ContentType', SLIDE_CT)
                    existing_overrides.add(pname)
                continue
        if ext and ext not in existing_defaults and ext in MEDIA_CT:
            e = etree.SubElement(tree, f'{{{CT_NS}}}Default')
            e.set('Extension', ext)
            e.set('ContentType', MEDIA_CT[ext])
            existing_defaults.add(ext)

    target_files['[Content_Types].xml'] = etree.tostring(
        tree, xml_declaration=True, encoding='UTF-8', standalone=True
    )


def replace_section_zip(target_path: str, section_name: str, src_pptx_paths: list, tmp_dir: str):
    """
    ZIP 레벨에서 직접 섹션 교체.
    python-pptx OPC 레이어를 우회하여 .rels / [Content_Types].xml 을 올바르게 처리.
    이전 방식(copy_slide + prs.save)의 깨진 파일 문제를 근본적으로 해결.
    반환: (이전 슬라이드 수, 새 슬라이드 수)
    """
    if isinstance(src_pptx_paths, str):
        src_pptx_paths = [src_pptx_paths]

    # ── 1. target 로드 ─────────────────────────────────────────────────────────
    target_files = _load_zip(target_path)
    prs_xml_bytes   = target_files['ppt/presentation.xml']
    prs_rels_bytes  = target_files['ppt/_rels/presentation.xml.rels']
    prs_tree  = etree.fromstring(prs_xml_bytes)
    prs_rels  = _parse_rels(prs_rels_bytes)

    # ── 2. 섹션의 슬라이드 ID 목록 ─────────────────────────────────────────────
    section_lst = prs_tree.find(f'.//{{{P14_NS}}}sectionLst')
    if section_lst is None:
        print(f"  경고: 섹션 '{section_name}' 을 찾을 수 없습니다 (sectionLst 없음). 건너뜁니다.")
        return 0, 0

    target_section = None
    for sec in section_lst.findall(f'{{{P14_NS}}}section'):
        if sec.get('name') == section_name:
            target_section = sec
            break
    if target_section is None:
        print(f"  경고: 섹션 '{section_name}' 을 찾을 수 없습니다. 건너뜁니다.")
        return 0, 0

    section_slide_ids = {s.get('id') for s in target_section.findall(f'.//{{{P14_NS}}}sldId')}

    # ── 3. sldIdLst에서 섹션 슬라이드 위치 파악 ────────────────────────────────
    R_ID_ATTR = f'{{{R_NS}}}id'
    sld_id_lst_elem = prs_tree.find(f'.//{{{PML_NS}}}sldIdLst')
    all_sld_elems   = list(sld_id_lst_elem)

    old_section_indices = [i for i, e in enumerate(all_sld_elems) if e.get('id') in section_slide_ids]

    if not old_section_indices:
        # 빈 섹션: 슬라이드가 없는 템플릿 섹션 → 다음 섹션의 첫 슬라이드 위치에 삽입
        all_sections = section_lst.findall(f'{{{P14_NS}}}section')
        target_idx = next((i for i, s in enumerate(all_sections) if s is target_section), -1)
        insert_idx = len(all_sld_elems)  # 기본: 끝에 삽입
        for subsequent_sec in all_sections[target_idx + 1:]:
            subsequent_ids = {s.get('id') for s in subsequent_sec.findall(f'.//{{{P14_NS}}}sldId')}
            for i, e in enumerate(all_sld_elems):
                if e.get('id') in subsequent_ids:
                    insert_idx = i
                    break
            if insert_idx < len(all_sld_elems):
                break
        old_count = 0
        old_section_rids = []
        old_section_paths = []
    else:
        insert_idx       = old_section_indices[0]
        old_count        = len(old_section_indices)
        old_section_rids = [all_sld_elems[i].get(R_ID_ATTR) for i in old_section_indices]

    if old_section_rids:
        rid_to_path = {}
        for r in prs_rels:
            if r['Type'] == SLIDE_REL:
                t = r['Target']
                rid_to_path[r['Id']] = 'ppt/' + t if not t.startswith('/') else t.lstrip('/')
        old_section_paths = [rid_to_path.get(rid) for rid in old_section_rids]

    # ── 4. target 레이아웃 참조 경로 ────────────────────────────────────────────
    layout_target = _get_layout_target_for_new_slides(target_files)

    # ── 5. 소스 슬라이드 처리 ────────────────────────────────────────────────────
    # slide XML bytes는 변경 없이 복사, .rels만 재작성 (미디어 경로 + 레이아웃 교체)
    new_slide_data = []  # [(slide_xml_bytes, new_rels_bytes, {media_zip_path: bytes})]

    for src_path in src_pptx_paths:
        src_pptx  = convert_to_pptx(src_path, tmp_dir)
        src_files = _load_zip(src_pptx)
        src_prs_rels = _parse_rels(src_files['ppt/_rels/presentation.xml.rels'])

        slide_rels_sorted = sorted(
            [r for r in src_prs_rels if r['Type'] == SLIDE_REL],
            key=lambda r: int(re.search(r'slide(\d+)', r['Target']).group(1))
                          if re.search(r'slide(\d+)', r['Target']) else 0
        )

        for src_rel in slide_rels_sorted:
            src_slide_path = 'ppt/' + src_rel['Target'].lstrip('/')
            src_rels_path  = 'ppt/slides/_rels/' + Path(src_slide_path).name + '.rels'

            slide_xml = src_files.get(src_slide_path)
            if slide_xml is None:
                continue

            src_slide_rels = _parse_rels(src_files.get(src_rels_path, b''))
            new_media: dict = {}
            new_rels:  list = []
            skip_rids: set  = set()  # hlinkSlide jump 대상 rId (slide XML에서도 제거)

            for r in src_slide_rels:
                rtype   = r['Type']
                rtarget = r['Target']
                rmode   = r.get('TargetMode', '')

                if LAYOUT_REL in rtype or 'slideMaster' in rtype:
                    # target의 레이아웃으로 교체 (rId 유지)
                    new_rels.append({'Id': r['Id'], 'Type': rtype,
                                     'Target': layout_target, 'TargetMode': ''})
                elif rmode == 'External':
                    new_rels.append(r)
                else:
                    # 내부 파일: 미디어 bytes 복사 + 새 UUID 이름 부여
                    if rtarget.startswith('../'):
                        src_media_path = 'ppt/' + rtarget[3:]
                    elif rtarget.startswith('/'):
                        src_media_path = rtarget.lstrip('/')
                    else:
                        src_media_path = 'ppt/slides/' + rtarget

                    media_bytes = src_files.get(src_media_path)
                    if media_bytes is None:
                        continue  # 없는 미디어 참조는 관계 자체를 제외

                    # slide 타입 관계 = 소스 프레젠테이션 내부 슬라이드 점프 참조
                    # 타겟 프레젠테이션에서는 무효이므로 관계와 hlinkClick 모두 제거
                    if SLIDE_REL in rtype:
                        skip_rids.add(r['Id'])
                        continue

                    ext          = Path(src_media_path).suffix  # '.png', '.emf', ...
                    uid          = uuid.uuid4().hex[:12]
                    new_name     = f'media_{uid}{ext}'
                    new_zip_path = f'ppt/media/{new_name}'
                    new_media[new_zip_path] = media_bytes
                    new_rels.append({'Id': r['Id'], 'Type': rtype,
                                     'Target': f'../media/{new_name}', 'TargetMode': ''})

            # hlinkSlide jump 대상 rId를 참조하는 hlinkClick 요소 제거
            if skip_rids and slide_xml:
                try:
                    A_NS = 'http://schemas.openxmlformats.org/drawingml/2006/main'
                    R_NS2 = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
                    sld_tree = etree.fromstring(slide_xml)
                    for hlink in sld_tree.findall(f'.//{{{A_NS}}}hlinkClick'):
                        if hlink.get(f'{{{R_NS2}}}id') in skip_rids:
                            parent = hlink.getparent()
                            if parent is not None:
                                parent.remove(hlink)
                    slide_xml = etree.tostring(sld_tree, xml_declaration=True,
                                               encoding='UTF-8', standalone=True)
                except Exception:
                    pass  # 파싱 실패 시 원본 유지

            # 소스 슬라이드 자체의 <p:bg>가 없는 경우에만 마스터 배경 주입
            # (소스 슬라이드에 bg가 있으면 그대로 보존 — rId 재매핑은 rels 재작성으로 처리됨)
            src_has_bg = b'<p:bg' in slide_xml or b'<p:bg>' in slide_xml
            if not src_has_bg:
                src_bg_elem, src_bg_media = _extract_master_background(
                    src_files,
                    src_slide_path=src_slide_path,
                    src_slide_rels=src_slide_rels,
                )
                if src_bg_elem is not None:
                    slide_xml = _inject_background(slide_xml, src_bg_elem, src_bg_media,
                                                   new_rels, new_media)

            new_slide_data.append((slide_xml, _build_rels_xml(new_rels), new_media))

    # ── 6. 새 슬라이드 번호·ID·rId 계산 ────────────────────────────────────────
    next_num = max(
        (int(m.group(1)) for name in target_files
         for m in [re.match(r'ppt/slides/slide(\d+)\.xml$', name)] if m),
        default=0
    ) + 1

    max_sld_id = max(
        (int(e.get('id', 0)) for e in all_sld_elems),
        default=255
    ) + 1

    max_prs_rid_num = max(
        (int(m.group(1)) for r in prs_rels
         for m in [re.match(r'rId(\d+)$', r['Id'])] if m),
        default=0
    ) + 1

    new_sld_items:      list = []
    new_slide_paths_ct: list = []
    new_media_paths_ct: list = []

    for (slide_xml, rels_bytes, new_media) in new_slide_data:
        num            = next_num; next_num += 1
        slide_zip_path = f'ppt/slides/slide{num}.xml'
        rels_zip_path  = f'ppt/slides/_rels/slide{num}.xml.rels'

        target_files[slide_zip_path] = slide_xml
        target_files[rels_zip_path]  = rels_bytes
        for mp, mb in new_media.items():
            target_files[mp] = mb
            new_media_paths_ct.append(mp)

        sld_id_str = str(max_sld_id); max_sld_id += 1
        prs_rid    = f'rId{max_prs_rid_num}'; max_prs_rid_num += 1

        new_sld_items.append({'id': sld_id_str, 'rId': prs_rid, 'path': slide_zip_path})
        new_slide_paths_ct.append(slide_zip_path)

    # ── 7. presentation.xml 업데이트 ─────────────────────────────────────────────
    remaining = [e for e in all_sld_elems if e.get('id') not in section_slide_ids]
    new_elems_to_insert = []
    for item in new_sld_items:
        ne = etree.Element(f'{{{PML_NS}}}sldId')
        ne.set('id', item['id'])
        ne.set(R_ID_ATTR, item['rId'])
        new_elems_to_insert.append(ne)

    final_order = remaining[:insert_idx] + new_elems_to_insert + remaining[insert_idx:]
    for e in list(sld_id_lst_elem):
        sld_id_lst_elem.remove(e)
    for e in final_order:
        sld_id_lst_elem.append(e)

    # p14:sectionLst 업데이트
    sld_id_container = target_section.find(f'{{{P14_NS}}}sldIdLst')
    if sld_id_container is None:
        sld_id_container = etree.SubElement(target_section, f'{{{P14_NS}}}sldIdLst')
    for e in list(sld_id_container):
        sld_id_container.remove(e)
    for item in new_sld_items:
        ne = etree.SubElement(sld_id_container, f'{{{P14_NS}}}sldId')
        ne.set('id', item['id'])

    target_files['ppt/presentation.xml'] = etree.tostring(
        prs_tree, xml_declaration=True, encoding='UTF-8', standalone=True
    )

    # ── 8. presentation.xml.rels 업데이트 ────────────────────────────────────────
    prs_rels_tree = etree.fromstring(prs_rels_bytes)
    old_rid_set   = set(old_section_rids)
    for rel in list(prs_rels_tree):
        if rel.get('Id') in old_rid_set:
            prs_rels_tree.remove(rel)
    for item in new_sld_items:
        rel_elem = etree.SubElement(prs_rels_tree, f'{{{RELS_NS}}}Relationship')
        rel_elem.set('Id',     item['rId'])
        rel_elem.set('Type',   SLIDE_REL)
        rel_elem.set('Target', item['path'][4:])  # 'ppt/' 제거 → 'slides/slideN.xml'

    target_files['ppt/_rels/presentation.xml.rels'] = etree.tostring(
        prs_rels_tree, xml_declaration=True, encoding='UTF-8', standalone=True
    )

    # ── 9. 기존 섹션 슬라이드 파일 제거 ─────────────────────────────────────────
    for path in old_section_paths:
        if path:
            target_files.pop(path, None)
            rels_key = 'ppt/slides/_rels/' + Path(path).name + '.rels'
            target_files.pop(rels_key, None)

    # ── 10. 고아 미디어 파일 제거 ────────────────────────────────────────────────
    referenced_media: set = set()
    for key, data in target_files.items():
        if key.endswith('.rels'):
            for t in re.findall(rb'Target="\.\./media/([^"]+)"', data):
                referenced_media.add(f'ppt/media/{t.decode()}')
    for key in [k for k in list(target_files) if k.startswith('ppt/media/') and k not in referenced_media]:
        del target_files[key]

    # ── 11. [Content_Types].xml 업데이트 ────────────────────────────────────────
    _update_content_types(target_files, new_slide_paths_ct, new_media_paths_ct)

    # ── 11. 저장 ──────────────────────────────────────────────────────────────────
    _write_zip(target_path, target_files)

    return old_count, len(new_slide_data)


