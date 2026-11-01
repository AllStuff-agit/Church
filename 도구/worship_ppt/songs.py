"""준비찬양 곡 파일 찾기와 티스토리(cwy0675) 16:9 내려받기.

옛 church-worship-ppt 스킬(2026-11 삭제)의 ppt_section_replacer.py에서 옮겨 왔다.
16:9만 쓰므로 첨부 선택만 _Wide 전용으로 바꿨다.
"""
import re
import sys
from pathlib import Path
from urllib.parse import quote, unquote, urljoin, urlparse

from sources import REPO

SONG_DIR = REPO / "1_자료" / "찬양곡"


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
    """첨부 목록에서 16:9(_Wide) .ppt/.pptx만 고른다. 4:3 일반 파일과 .nwc는 받지 않는다."""
    candidates = []
    for attachment in attachments:
        url = attachment.get('url', '')
        label = attachment.get('label', '')
        url_name = unquote(urlparse(url).path).rsplit('/', 1)[-1]
        name = url_name if url_name.lower().endswith(('.ppt', '.pptx')) else label
        lower_name = name.lower()
        if not lower_name.endswith(('.ppt', '.pptx')):
            continue
        if not re.search(r'_wide(?:$|[._-])', Path(name).stem, re.IGNORECASE):
            continue
        extension_rank = 0 if lower_name.endswith('.pptx') else 1
        candidates.append((extension_rank, len(candidates), url))

    if not candidates:
        return None
    candidates.sort()
    return candidates[0][-1]


def tistory_download(title: str, folder: str) -> str | None:
    """
    cwy0675.tistory.com 내부 검색으로 제목을 찾은 뒤 PPT 첨부파일을 다운로드.
    비밀번호 보호 포스트는 자동으로 0675 입력.
    첨부 목록에서는 16:9(_Wide) .ppt/.pptx만 선택한다.
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
        print(f"  NOT_FOUND: '{title}' 포스트에서 16:9(_Wide) PPT 첨부파일 없음 ({post_url})")
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


