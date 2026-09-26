#!/usr/bin/env python3
"""
교회 예배 PPT 섹션 교체 스크립트

사용법:
  # 섹션 교체 (파일 경로 직접 지정)
  python3 ppt_section_replacer.py --replace \\
    --target "260329주일.pptx" \\
    --section "교독문" --source "교독문_129.ppt" \\
    --section "찬양 1"  --source "새찬송가_150장.ppt" \\
    --section "찬양 2"  --source "새찬송가_147장.ppt"

  # 제목으로 찬양곡 검색 (퍼지 매칭)
  python3 ppt_section_replacer.py --search \\
    --folder "/mnt/c/.../5. 찬양곡ppt" \\
    --title "호산나"

  # PPT 섹션 목록 확인
  python3 ppt_section_replacer.py --list-sections "파일.pptx"
"""

import argparse
import copy
import datetime
import io
import os
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

TEMPLATE_PATH = "/mnt/c/Oddments_Repository/교회/주일 예배자료/1. 주일오전예배ppt/template.pptx"
OUTPUT_FOLDER = "/mnt/c/Oddments_Repository/교회/주일 예배자료/1. 주일오전예배ppt"

try:
    from pptx import Presentation
    from pptx.oxml.ns import qn
    from lxml import etree
except ImportError:
    print("ERROR: python-pptx가 설치되지 않았습니다. 설치: pip install python-pptx")
    sys.exit(1)

P14_NS     = 'http://schemas.microsoft.com/office/powerpoint/2010/main'
P14        = {'p14': P14_NS}
RELS_NS    = 'http://schemas.openxmlformats.org/package/2006/relationships'
PML_NS     = 'http://schemas.openxmlformats.org/presentationml/2006/main'
R_NS       = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
SLIDE_CT   = 'application/vnd.openxmlformats-officedocument.presentationml.slide+xml'
SLIDE_REL  = R_NS + '/slide'
LAYOUT_REL = R_NS + '/slideLayout'

PRAISE_FOLDER      = "/mnt/c/Oddments_Repository/교회/주일 예배자료/5. 찬양곡ppt"
HYMN_FOLDER        = "/mnt/c/Oddments_Repository/교회/주일 예배자료/4. 찬송가ppt"
DOKMUN_FOLDER      = "/mnt/c/Oddments_Repository/교회/주일 예배자료/3. 교독문ppt"
PRAISE_PREP_FOLDER = "/mnt/c/Oddments_Repository/교회/주일 예배자료/6. 준비찬양"


def normalize(text: str) -> str:
    """비교용 정규화: 공백·특수문자 제거, 소문자화"""
    return re.sub(r'[\s\(\)\[\]_\-\.·]', '', text).lower()


def search_file(folder: str, title: str) -> list[dict]:
    """
    folder 안에서 title을 퍼지 매칭으로 검색.
    반환: [{'file': Path, 'score': int}, ...] (score 높을수록 좋은 매칭)
      score 2 = 정규화 후 완전 일치
      score 1 = 정규화 후 부분 포함
    결과는 score 내림차순 정렬.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        return []

    query = normalize(title)
    results = []

    for f in sorted(folder_path.iterdir()):
        if f.suffix.lower() not in ('.ppt', '.pptx'):
            continue
        stem_norm = normalize(f.stem)
        if stem_norm == query:
            results.append({'file': f, 'score': 2})
        elif query in stem_norm:
            results.append({'file': f, 'score': 1})

    results.sort(key=lambda x: x['score'], reverse=True)
    return results


def build_site_search_url(title: str, base_url: str = "https://cwy0675.tistory.com") -> str:
    """cwy0675 티스토리의 사이트 내부 검색 URL을 만든다."""
    return f"{base_url.rstrip('/')}/search/{quote(title, safe='')}"


def extract_site_search_candidates(
    html: str, base_url: str = "https://cwy0675.tistory.com"
) -> list[dict]:
    """티스토리 내부 검색 HTML에서 같은 사이트의 글 후보만 추출한다."""
    from bs4 import BeautifulSoup

    base = urlparse(base_url)
    soup = BeautifulSoup(html, 'html.parser')
    candidates = []
    seen = set()

    for anchor in soup.find_all('a', href=True):
        href = urljoin(base_url.rstrip('/') + '/', anchor['href'].strip())
        parsed = urlparse(href)
        if parsed.netloc.lower() != base.netloc.lower():
            continue
        if not parsed.path.startswith('/entry/'):
            continue

        url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if url in seen:
            continue
        seen.add(url)
        candidates.append({
            'url': url,
            'text': anchor.get_text(' ', strip=True) or anchor.get('title', ''),
        })

    return candidates


def is_password_protected_post(html: str) -> bool:
    """댓글 입력창의 비밀번호 필드와 티스토리 보호글을 구분한다."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, 'html.parser')
    if soup.select_one('.entryProtected, .entry-protected, [id*="entryProtected"]'):
        return True

    page_text = soup.get_text(' ', strip=True)
    return bool(re.search(r'보호되어\s*있는\s*글|비밀번호를\s*입력하세요', page_text))


def choose_site_search_result(title: str, candidates: list[dict]) -> str | None:
    """검색어가 제목 앞에 오는 직접 곡 포스트를 우선 선택한다."""
    query = normalize(title)
    ranked = []

    for candidate in candidates:
        url = candidate.get('url', '')
        text = candidate.get('text', '')
        path_title = unquote(urlparse(url).path).split('/entry/', 1)[-1]
        path_norm = normalize(path_title)
        text_norm = normalize(text)
        path_index = path_norm.find(query)
        text_index = text_norm.find(query)
        if path_index < 0 and text_index < 0:
            continue

        # /entry/찬송을-부르세요... 는 /entry/어린이-찬송가-412장-찬송을...보다
        # 검색어가 앞에 있으므로 같은 검색 결과에서 직접 곡 포스트로 간주한다.
        if path_index == 0:
            placement = 0
        elif path_index >= 0:
            placement = 1
        elif text_index == 0:
            placement = 2
        else:
            placement = 3

        ranked.append((placement, path_index if path_index >= 0 else 999999,
                       text_index if text_index >= 0 else 999999,
                       len(path_norm), url))

    if not ranked:
        return None
    ranked.sort()
    return ranked[0][-1]


def select_ppt_attachment(attachments: list[dict]) -> str | None:
    """첨부 목록에서 일반 .ppt/.pptx를 고르고 .nwc와 _Wide를 제외한다."""
    candidates = []
    for attachment in attachments:
        url = attachment.get('url', '')
        label = attachment.get('label', '')
        url_name = unquote(urlparse(url).path).rsplit('/', 1)[-1]
        name = url_name if url_name.lower().endswith(('.ppt', '.pptx')) else label
        lower_name = name.lower()
        if not lower_name.endswith(('.ppt', '.pptx')):
            continue
        stem = Path(name).stem
        if re.search(r'_wide(?:$|[._-])', stem, re.IGNORECASE):
            continue
        extension_rank = 0 if lower_name.endswith('.ppt') else 1
        candidates.append((extension_rank, len(candidates), url))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][-1]


def cmd_search(args):
    """제목으로 파일 검색 후 결과 출력"""
    folder = args.folder or PRAISE_FOLDER
    title = args.title
    results = search_file(folder, title)

    if not results:
        print(f"NOT_FOUND: '{title}' 에 해당하는 파일 없음")
        print(f"FOLDER: {folder}")
        sys.exit(2)  # exit code 2 = 파일 없음 (Claude가 감지용)

    print(f"검색어: '{title}'  →  {len(results)}개 후보")
    for i, r in enumerate(results):
        marker = "★" if r['score'] == 2 else "○"
        print(f"  {marker} [{i+1}] {r['file'].name}  ({r['file']})")

    # 첫 번째 결과(최고 매칭)를 BEST_MATCH 로 출력 → Claude가 파싱 가능
    print(f"\nBEST_MATCH: {results[0]['file']}")


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
        ['libreoffice', '--headless', '--convert-to', 'pptx', str(src), '--outdir', tmp_dir],
        capture_output=True, text=True
    )
    converted = Path(tmp_dir) / (src.stem + '.pptx')
    if not converted.exists():
        print(f"ERROR: 변환 실패 - {src_path}")
        print(result.stderr)
        sys.exit(1)
    deduplicate_zip(str(converted))
    return str(converted)


def get_section_map(prs: Presentation):
    """
    섹션명 → 슬라이드 인덱스 리스트 (0-based) 반환.
    슬라이드 ID → 인덱스 매핑도 함께 반환.
    """
    sld_id_list = prs.slides._sldIdLst
    id_to_idx = {elem.get('id'): i for i, elem in enumerate(sld_id_list)}

    section_lst = prs._element.find('.//p14:sectionLst', P14)
    if section_lst is None:
        return {}, id_to_idx

    section_map = {}
    for section in section_lst.findall('p14:section', P14):
        name = section.get('name')
        ids = [s.get('id') for s in section.findall('.//p14:sldId', P14)]
        indices = sorted([id_to_idx[sid] for sid in ids if sid in id_to_idx])
        section_map[name] = indices

    return section_map, id_to_idx


def copy_slide(src_prs: Presentation, src_idx: int, dest_prs: Presentation):
    """
    src_prs의 src_idx 슬라이드를 dest_prs 맨 끝에 복사.
    이미지/미디어 등 모든 관계(relationship)를 새 슬라이드에 올바르게 등록하여
    PowerPoint 복구 다이얼로그가 뜨지 않도록 함.
    """
    from pptx.opc.package import Part as OpcPart
    from pptx.opc.packuri import PackURI

    R_NS = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
    # 건너뛸 관계 타입 (add_slide()가 이미 처리하거나 필요 없는 것)
    SKIP = ('slideLayout', 'slideMaster', 'notesMaster', 'handoutMaster',
            'notesSlide', 'thumbnail')

    src_slide = src_prs.slides[src_idx]
    blank_layout = dest_prs.slide_layouts[6]
    new_slide = dest_prs.slides.add_slide(blank_layout)

    # ── 관계 복사 및 rId 매핑 구축 ─────────────────────────────────────────
    rId_map: dict[str, str] = {}

    # add_slide()가 생성한 slideLayout 관계의 새 rId 파악
    for rel in new_slide.part.rels.values():
        if 'slideLayout' in rel.reltype:
            # 소스의 slideLayout rId → 새 슬라이드의 rId 매핑
            for src_rel in src_slide.part.rels.values():
                if 'slideLayout' in src_rel.reltype:
                    rId_map[src_rel.rId] = rel.rId
            break

    for src_rel in src_slide.part.rels.values():
        if any(t in src_rel.reltype for t in SKIP):
            continue

        if src_rel.is_external:
            new_rId = new_slide.part.relate_to(
                src_rel.target_ref, src_rel.reltype, is_external=True
            )
        else:
            src_part = src_rel.target_part
            blob = getattr(src_part, 'blob', None)
            if blob is None:
                continue  # 바이너리가 없는 파트는 건너뜀

            # 고유 파일명으로 새 파트 생성 (이름 충돌 방지)
            orig_name = str(src_part.partname)
            ext = orig_name.rsplit('.', 1)[-1].lower() if '.' in orig_name else 'bin'
            uid = uuid.uuid4().hex[:12]
            new_partname = PackURI(f'/ppt/media/media_{uid}.{ext}')
            dest_pkg = dest_prs.part.package
            new_part = OpcPart(new_partname, src_part.content_type, dest_pkg, blob)
            new_rId = new_slide.part.relate_to(new_part, src_rel.reltype)

        rId_map[src_rel.rId] = new_rId

    # ── rId 참조 업데이트 헬퍼 ─────────────────────────────────────────────
    def update_rids(elem):
        """elem과 하위 요소의 r: 네임스페이스 속성을 rId_map 기준으로 교체."""
        for attr, val in list(elem.attrib.items()):
            if R_NS in attr and val in rId_map:
                elem.set(attr, rId_map[val])
        for child in elem:
            update_rids(child)

    # ── 도형 트리 교체 ─────────────────────────────────────────────────────
    sp_tree_new = new_slide.shapes._spTree
    sp_tree_src = src_slide.shapes._spTree
    for child in list(sp_tree_new):
        sp_tree_new.remove(child)
    for child in sp_tree_src:
        child_copy = copy.deepcopy(child)
        update_rids(child_copy)
        sp_tree_new.append(child_copy)

    # ── 배경 복사 ──────────────────────────────────────────────────────────
    bg_src = src_slide._element.find(qn('p:bg'))
    if bg_src is not None:
        bg_copy = copy.deepcopy(bg_src)
        update_rids(bg_copy)
        bg_new = new_slide._element.find(qn('p:bg'))
        if bg_new is not None:
            new_slide._element.remove(bg_new)
        c_sld = new_slide._element.find(qn('p:cSld'))
        if c_sld is not None:
            c_sld.insert(0, bg_copy)


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


def parse_section_sources(argv: list) -> list:
    """
    argv에서 --section / --source 그룹을 파싱.
    --section A --source X --source Y --section B --source Z
    → [('A', ['X', 'Y']), ('B', ['Z'])]
    한 섹션에 여러 --source를 지정하면 슬라이드가 순서대로 이어붙여진다.
    """
    pairs = []
    current_section = None
    current_sources = []
    i = 0
    while i < len(argv):
        if argv[i] == '--section' and i + 1 < len(argv):
            if current_section is not None:
                pairs.append((current_section, current_sources))
            current_section = argv[i + 1]
            current_sources = []
            i += 2
        elif argv[i] == '--source' and i + 1 < len(argv):
            current_sources.append(argv[i + 1])
            i += 2
        else:
            i += 1
    if current_section is not None:
        pairs.append((current_section, current_sources))
    return pairs


def cmd_replace(args):
    target = args.target
    if not Path(target).exists():
        print(f"ERROR: 파일 없음 - {target}")
        sys.exit(1)

    # sys.argv에서 직접 파싱 (한 섹션에 여러 --source 지원)
    section_source_pairs = parse_section_sources(sys.argv)
    if not section_source_pairs:
        print("ERROR: --section / --source 쌍이 없습니다.")
        sys.exit(1)

    total_before = _count_slides_in_zip(target)
    results = []

    with tempfile.TemporaryDirectory() as tmp_dir:
        for section_name, source_paths in section_source_pairs:
            valid_paths = []
            for p in source_paths:
                if not Path(p).exists():
                    print(f"  경고: 파일 없음 - {p}")
                else:
                    valid_paths.append(p)
            if not valid_paths:
                continue
            before, after = replace_section_zip(target, section_name, valid_paths, tmp_dir)
            src_names = ' + '.join(Path(p).name for p in valid_paths)
            results.append((section_name, before, after, src_names))

    total_after = _count_slides_in_zip(target)

    order = {sec: i for i, (sec, _) in enumerate(section_source_pairs)}
    for section_name, before, after, src_name in sorted(results, key=lambda x: order.get(x[0], 0)):
        print(f"  [{section_name}] {before}장 → {after}장  ({src_name})")

    print(f"\n완료: {target}")
    print(f"총 슬라이드: {total_before}장 → {total_after}장")


def cmd_list_sections(pptx_path: str):
    if not Path(pptx_path).exists():
        print(f"ERROR: 파일 없음 - {pptx_path}")
        sys.exit(1)
    prs = Presentation(pptx_path)
    section_map, _ = get_section_map(prs)
    if not section_map:
        print("섹션 없음")
        return
    print(f"섹션 목록: {pptx_path}")
    for name, indices in section_map.items():
        slides = [i + 1 for i in indices]
        print(f"  [{name}] → 슬라이드 {slides} ({len(slides)}장)")


def cmd_init(date_str: str | None):
    """템플릿을 복사해서 날짜별 주일 파일 생성"""
    if date_str:
        date_label = date_str
    else:
        date_label = datetime.date.today().strftime('%y%m%d')

    template = Path(TEMPLATE_PATH)
    if not template.exists():
        print(f"ERROR: 템플릿 없음 - {TEMPLATE_PATH}")
        sys.exit(1)

    dest = Path(OUTPUT_FOLDER) / f"{date_label}주일.pptx"
    if dest.exists():
        print(f"이미 존재함: {dest}")
        sys.exit(0)

    shutil.copy2(str(template), str(dest))
    print(f"생성: {dest}")


def _extract_hwpx(path: str, out_dir: str) -> list[dict]:
    """HWPX(ZIP 기반)에서 이미지와 페이지/열 레이아웃 정보 추출"""
    import zlib as zlib_mod
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow 미설치. pip install Pillow")
        sys.exit(1)

    HP = 'http://www.hancom.co.kr/hwpml/2011/paragraph'
    HC = 'http://www.hancom.co.kr/hwpml/2011/core'

    with zipfile.ZipFile(path, 'r') as z:
        bin_data = {}
        for name in z.namelist():
            if name.startswith('BinData/') and name.lower().endswith('.bmp'):
                key = Path(name).stem.lower()  # 'image1', 'image2', ...
                bin_data[key] = z.read(name)
        from xml.etree import ElementTree as ET
        root = ET.fromstring(z.read('Contents/section0.xml'))

    # 단락 순서대로 pic 요소와 위치 정보 추출
    pics = []
    for p in root.iter(f'{{{HP}}}p'):
        for pic in p.findall(f'.//{{{HP}}}pic'):
            img_elem = pic.find(f'.//{{{HC}}}img')
            pos_elem = pic.find(f'{{{HP}}}pos')
            if img_elem is None:
                continue
            ref = img_elem.get('binaryItemIDRef')
            horz = int(pos_elem.get('horzOffset', 0)) if pos_elem is not None else 0
            vert = int(pos_elem.get('vertOffset', 0)) if pos_elem is not None else 0
            pics.append({'ref': ref, 'horz': horz, 'vert': vert})

    # 페이지 결정
    # vertOffset이 매우 작은 양수(0 < vert < 1000) → 새 페이지 상단에 앵커된 이미지
    # vertOffset이 큰 uint32 값(>2^31) → 현재 페이지에서 float (signed 음수)
    page = 1
    on_new_page_group = False
    for pic in pics:
        vert = pic['vert']
        if 0 < vert < 1000:
            if not on_new_page_group:
                page += 1
                on_new_page_group = True
        else:
            on_new_page_group = False
        pic['page'] = page
        pic['col'] = '오른쪽' if pic['horz'] > 0 else '왼쪽'

    # 이미지 저장 및 결과 반환
    results = []
    for seq, pic in enumerate(pics, 1):
        ref = pic['ref']
        raw = bin_data.get(ref)
        if raw is None:
            continue
        out_path = os.path.join(out_dir, f'{seq:02d}_{ref}.png')
        try:
            img = Image.open(io.BytesIO(raw))
        except Exception:
            raw = zlib_mod.decompress(raw, -15)
            img = Image.open(io.BytesIO(raw))
        img.save(out_path)
        results.append({
            'seq': seq, 'ref': ref,
            'page': pic['page'], 'col': pic['col'],
            'path': out_path,
        })
    return results


def _extract_hwp_ole(path: str, out_dir: str) -> list[dict]:
    """HWP(OLE 기반)에서 이미지 추출 (레이아웃 정보 없음)"""
    import zlib as zlib_mod
    try:
        import olefile
    except ImportError:
        print("ERROR: olefile 미설치. pip install olefile")
        sys.exit(1)
    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow 미설치. pip install Pillow")
        sys.exit(1)

    ole = olefile.OleFileIO(path)
    bin_entries = sorted([e[1] for e in ole.listdir() if len(e) == 2 and e[0] == 'BinData'])

    results = []
    for seq, name in enumerate(bin_entries, 1):
        raw = ole.openstream(['BinData', name]).read()
        try:
            raw = zlib_mod.decompress(raw, -15)
        except Exception:
            pass
        try:
            img = Image.open(io.BytesIO(raw))
            # Some HWP files store normal images with non-image extensions such
            # as .tmp. Always write a PNG so Pillow can save every decoded
            # image consistently.
            out_path = os.path.join(out_dir, f'{seq:02d}_{Path(name).stem.lower()}.png')
            img.save(out_path)
        except Exception as e:
            print(f"  경고: {name} 변환 실패 - {e}")
            continue
        results.append({
            'seq': seq, 'ref': name,
            'page': None, 'col': None,
            'path': out_path,
        })
    return results


def find_hwp_by_date(date_str: str | None) -> Path | None:
    """준비찬양 폴더에서 날짜에 해당하는 HWP/HWPX 파일 자동 탐색"""
    label = date_str or datetime.date.today().strftime('%y%m%d')
    folder = Path(PRAISE_PREP_FOLDER)
    if not folder.exists():
        return None
    for ext in ('.hwpx', '.hwp'):
        matches = list(folder.glob(f'{label}*{ext}'))
        if matches:
            return matches[0]
    return None


def cmd_extract_hwp(args):
    """HWP/HWPX 파일에서 이미지를 추출하고 페이지/열 배치를 출력"""
    # 파일 경로가 없으면 날짜로 자동 탐색
    if args.hwp:
        src = Path(args.hwp)
    else:
        src = find_hwp_by_date(args.date)
        if src is None:
            label = args.date or datetime.date.today().strftime('%y%m%d')
            print(f"ERROR: 준비찬양 파일 없음 - {PRAISE_PREP_FOLDER}/{label}*.hwp(x)")
            sys.exit(1)
        print(f"자동 탐색: {src.name}")

    if not src.exists():
        print(f"ERROR: 파일 없음 - {src}")
        sys.exit(1)

    out_dir = args.out_dir or '/tmp/hwp_extract'
    os.makedirs(out_dir, exist_ok=True)
    ext = src.suffix.lower()

    print(f"파일: {src.name}  형식: {'HWPX' if ext == '.hwpx' else 'HWP'}")

    if ext == '.hwpx':
        results = _extract_hwpx(str(src), out_dir)
    elif ext == '.hwp':
        results = _extract_hwp_ole(str(src), out_dir)
    else:
        print(f"ERROR: 지원하지 않는 형식 - {ext}")
        sys.exit(1)

    print(f"이미지 {len(results)}개 발견\n")

    has_layout = any(r['page'] is not None for r in results)
    if has_layout:
        print(f"{'순서':>4}  {'페이지':>6}  {'열':>6}  경로")
        print('─' * 70)
        for r in results:
            print(f"  {r['seq']:>2}     {r['page']:>2}    {r['col']:>5}  {r['path']}")
    else:
        print("(HWP 형식은 레이아웃 정보를 제공하지 않습니다)")
        print("WARNING: HWP BinData 추출 순서는 실제 준비찬양/예배 순서가 아닐 수 있습니다.")
        print("WARNING: layout=unknown이면 이 순서로 준비찬양 1~4를 자동 배정하지 말고 사용자/주보 순서를 확인하세요.")
        print("ORDER_RELIABILITY: unknown")
        print(f"{'순서':>4}  경로")
        print('─' * 50)
        for r in results:
            print(f"  {r['seq']:>2}  {r['path']}")

    print("\nEXTRACTED_IMAGES:")
    for r in results:
        layout = f"page={r['page']} col={r['col']}" if r['page'] else "layout=unknown"
        print(f"  [{r['seq']}] {layout}  {r['path']}")


def cmd_add_section(args):
    """PPTX에 새 섹션을 추가 (기존 섹션 슬라이드를 복사해서 placeholder로 사용)"""
    target = args.target
    if not Path(target).exists():
        print(f"ERROR: 파일 없음 - {target}")
        sys.exit(1)

    new_name = args.name
    copy_from = args.copy_from

    prs = Presentation(target)
    section_map, _ = get_section_map(prs)

    if new_name in section_map:
        print(f"이미 존재: '{new_name}'")
        sys.exit(0)

    if copy_from not in section_map:
        print(f"ERROR: 복사 원본 섹션 없음 - '{copy_from}'")
        sys.exit(1)

    src_indices = section_map[copy_from]
    insert_at = src_indices[-1] + 1  # copy_from 섹션 마지막 슬라이드 바로 다음
    new_count = len(src_indices)
    sld_id_list = prs.slides._sldIdLst

    # 슬라이드 복사 (같은 prs 내에서 복사)
    for i in src_indices:
        copy_slide(prs, i, prs)

    # 맨 끝에 추가된 슬라이드들을 insert_at 위치로 이동
    all_ids = list(sld_id_list)
    total = len(all_ids)
    new_elems = all_ids[total - new_count:]
    remaining = all_ids[:total - new_count]
    final = remaining[:insert_at] + new_elems + remaining[insert_at:]
    for e in list(sld_id_list):
        sld_id_list.remove(e)
    for e in final:
        sld_id_list.append(e)

    # sectionLst에 새 섹션 추가 (copy_from 바로 다음 위치)
    section_lst = prs._element.find('.//p14:sectionLst', P14)
    sections = section_lst.findall('p14:section', P14)
    copy_from_elem = next((s for s in sections if s.get('name') == copy_from), None)

    new_section = etree.Element(f'{{{P14_NS}}}section')
    new_section.set('name', new_name)
    new_section.set('id', '{' + str(uuid.uuid4()).upper() + '}')
    sld_id_container = etree.SubElement(new_section, f'{{{P14_NS}}}sldIdLst')

    refreshed = list(sld_id_list)
    for i in range(new_count):
        new_id_elem = etree.SubElement(sld_id_container, f'{{{P14_NS}}}sldId')
        new_id_elem.set('id', refreshed[insert_at + i].get('id'))

    if copy_from_elem is not None:
        idx = list(section_lst).index(copy_from_elem)
        section_lst.insert(idx + 1, new_section)
    else:
        section_lst.append(new_section)

    save_deduplicated(prs, target)
    print(f"섹션 추가: '{new_name}' ({new_count}장 placeholder) → {target}")


def tistory_download(title: str, folder: str) -> str | None:
    """
    cwy0675.tistory.com 내부 검색으로 제목을 찾은 뒤 PPT 첨부파일을 다운로드.
    비밀번호 보호 포스트는 자동으로 0675 입력.
    첨부 목록에서는 일반 .ppt/.pptx를 선택하고 .nwc와 _Wide 파일은 제외한다.
    반환: 저장된 파일 경로 (실패 시 None)
    """
    try:
        import requests
        from bs4 import BeautifulSoup
    except ImportError:
        print("ERROR: requests, beautifulsoup4 필요. pip install requests beautifulsoup4")
        sys.exit(1)

    BASE = "https://cwy0675.tistory.com"
    PASSWORD = "0675"

    sess = requests.Session()
    sess.headers['User-Agent'] = (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/120.0.0.0 Safari/537.36'
    )

    # 1. cwy0675 티스토리 사이트 내부 검색
    search_url = build_site_search_url(title, BASE)
    print(f"  티스토리 내부 검색: '{title}'")
    sess.headers['Accept-Language'] = 'ko-KR,ko;q=0.9'
    r = sess.get(search_url, timeout=15)
    r.raise_for_status()
    candidates = extract_site_search_candidates(r.text, BASE)
    post_url = choose_site_search_result(title, candidates)

    if not post_url:
        print(f"  NOT_FOUND: 티스토리 내부 검색에서 '{title}' 검색 결과 없음 ({search_url})")
        return None

    print(f"  포스트: {post_url}")

    # 2. 포스트 접근
    r = sess.get(post_url, timeout=15)
    r.raise_for_status()

    # 댓글 입력창에도 비밀번호 필드가 있으므로 보호글 표식이 있을 때만 처리한다.
    soup = BeautifulSoup(r.text, 'html.parser')
    if is_password_protected_post(r.text):
        pw_input = soup.select_one(
            '.entryProtected input[type="password"], '
            '.entry-protected input[type="password"], '
            '[id*="entryProtected"] input[type="password"]'
        ) or soup.find('input', {'type': 'password'})
        print("  비밀번호 입력 중...")
        form = pw_input.find_parent('form')
        if form:
            action = form.get('action', '') or post_url
            if not action.startswith('http'):
                action = BASE + action
            password_name = pw_input.get('name') or 'password'
            form_data = {
                field.get('name'): field.get('value', '')
                for field in form.find_all('input')
                if field.get('name')
            }
            form_data[password_name] = PASSWORD
            r = sess.post(action, data=form_data,
                          headers={'Referer': post_url}, timeout=15)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, 'html.parser')

    # 3. 첨부파일 링크 탐색
    attach_links = []
    for a in soup.find_all('a', href=True):
        href = urljoin(post_url, a['href'].strip())
        name_part = unquote(urlparse(href).path).rsplit('/', 1)[-1].lower()
        label = a.get_text(' ', strip=True)
        if name_part.endswith('.ppt') or name_part.endswith('.pptx'):
            attach_links.append({'url': href, 'label': label})
        elif 'tistory.com' in urlparse(href).netloc and re.search(r'/attach(ment)?/', urlparse(href).path):
            # href에 확장자 없어도 Content-Disposition으로 확인
            attach_links.append({'url': href, 'label': label})

    target_url = select_ppt_attachment(attach_links)
    if not target_url:
        print(f"  NOT_FOUND: '{title}' 포스트에서 PPT 첨부파일 없음 ({post_url})")
        return None

    print(f"  다운로드: {target_url}")

    # 4. 파일명 결정 (Content-Disposition 헤더 우선)
    r_head = sess.head(target_url, allow_redirects=True, timeout=15)
    cd = r_head.headers.get('Content-Disposition', '')
    fname_match = re.search(r"filename\*?=['\"]?(?:UTF-8'')?([^'\";\r\n]+)", cd, re.IGNORECASE)
    if fname_match:
        fname = unquote(fname_match.group(1).strip(), encoding='utf-8')
    else:
        fname_in_url = Path(r_head.url.split('?')[0]).name
        fname = unquote(fname_in_url) if fname_in_url else f"{title}.ppt"
        if not fname.lower().endswith(('.ppt', '.pptx')):
            fname = f"{title}.ppt"

    # 파일명 안전하게 처리
    fname = re.sub(r'[<>:"/\\|?*]', '_', fname.strip())
    out_path = Path(folder) / fname

    # 5. 다운로드
    r_dl = sess.get(target_url, stream=True, timeout=30)
    r_dl.raise_for_status()
    with open(str(out_path), 'wb') as f:
        for chunk in r_dl.iter_content(chunk_size=8192):
            if chunk:
                f.write(chunk)

    size_kb = out_path.stat().st_size // 1024
    print(f"  저장: {out_path}  ({size_kb} KB)")
    return str(out_path)


def cmd_download(args):
    """티스토리에서 찬양곡 PPT 검색 및 자동 다운로드"""
    if not args.title:
        print("ERROR: --download 사용 시 --title 필요")
        sys.exit(1)

    folder = args.folder or PRAISE_FOLDER
    result = tistory_download(args.title, folder)

    if result:
        print(f"\nDOWNLOADED: {result}")
        # 다운로드 직후 폴더에 같은 제목의 예전 파일이 있어도 새 파일을 가리킨다.
        print(f"BEST_MATCH: {result}")
    else:
        print(f"\n파일을 티스토리에서 찾지 못했습니다.")
        print(f"직접 저장 후 알려주세요: {folder}")
        sys.exit(2)


def cmd_list_files(folder: str):
    p = Path(folder)
    if not p.exists():
        print(f"ERROR: 폴더 없음 - {folder}")
        sys.exit(1)
    files = sorted(p.glob('*.[pP][pP][tT]')) + sorted(p.glob('*.[pP][pP][tT][xX]'))
    for f in files:
        print(f.name)


def main():
    parser = argparse.ArgumentParser(description="교회 예배 PPT 섹션 교체 도구")
    sub = parser.add_subparsers(dest='cmd')

    # --replace 모드
    p_replace = sub.add_parser('replace', help='섹션 슬라이드 교체')
    p_replace.add_argument('--target', required=True, help='작업할 .pptx 파일 경로')
    p_replace.add_argument('--section', action='append', help='교체할 섹션명 (여러 번 사용 가능)')
    p_replace.add_argument('--source', action='append', help='소스 파일 경로 (--section 과 순서 맞춤)')

    # 플래그 스타일도 지원 (--replace --target ...)
    parser.add_argument('--replace', action='store_true')
    parser.add_argument('--target')
    parser.add_argument('--section', action='append')
    parser.add_argument('--source', action='append')
    parser.add_argument('--list-sections', metavar='파일.pptx')
    parser.add_argument('--list-files', metavar='폴더')
    parser.add_argument('--init', action='store_true', help='템플릿 복사하여 날짜별 주일 파일 생성')
    parser.add_argument('--date', help='날짜 지정 (YYMMDD, 기본: 오늘)')
    parser.add_argument('--search', action='store_true', help='제목으로 찬양곡 파일 검색')
    parser.add_argument('--title', help='검색할 곡 제목')
    parser.add_argument('--folder', help='검색할 폴더 (기본: 찬양곡ppt)')
    parser.add_argument('--extract-hwp', metavar='파일.hwp(x)', dest='hwp',
                        nargs='?', const='',
                        help='HWP/HWPX에서 이미지 추출 및 페이지·열 배치 출력 (값 생략 시 날짜로 자동 탐색)')
    parser.add_argument('--out-dir', help='이미지 저장 폴더 (기본: /tmp/hwp_extract)')
    parser.add_argument('--add-section', action='store_true', help='PPTX에 새 섹션 추가')
    parser.add_argument('--name', help='추가할 섹션 이름')
    parser.add_argument('--copy-from', help='슬라이드를 복사할 기존 섹션 이름')
    parser.add_argument('--download', action='store_true',
                        help='티스토리에서 찬양곡 PPT 검색 및 자동 다운로드 (--title 필요)')

    args = parser.parse_args()

    if args.hwp is not None:
        cmd_extract_hwp(args)
    elif args.add_section:
        if not args.target or not args.name or not args.copy_from:
            print("ERROR: --add-section 사용 시 --target, --name, --copy-from 필요")
            sys.exit(1)
        cmd_add_section(args)
    elif args.init:
        cmd_init(args.date)
    elif args.list_sections:
        cmd_list_sections(args.list_sections)
    elif args.list_files:
        cmd_list_files(args.list_files)
    elif args.search:
        if not args.title:
            print("ERROR: --search 사용 시 --title 이 필요합니다.")
            sys.exit(1)
        cmd_search(args)
    elif args.download:
        cmd_download(args)
    elif args.replace or args.cmd == 'replace':
        cmd_replace(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
