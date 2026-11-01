# worship-ppt 스킬 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 주보 사진과 준비찬양 HWP만 받으면 Claude가 16:9 주일 예배 PPT를 만들어 확인까지 하는 스킬 `worship-ppt`를 만들고, 4:3 기준 옛 스킬 두 개를 대체한다.

**Architecture:** 매주 흐름(날짜 계산 → 주보·준비찬양 판독 → 곡 찾기/내려받기 → 후렴 처리 → 조립 → 확인 → 정리)은 `.claude/skills/worship-ppt/SKILL.md`의 지침으로, 코드가 필요한 부분(곡 찾기·티스토리 `_Wide` 내려받기·후렴 장 떼기·배경 보완)은 `도구/worship_ppt/`의 모듈과 명령으로 둔다. 옛 스킬 코드는 필요한 함수만 옮기고 스킬 폴더는 지운다.

**Tech Stack:** Python 3.13(`python -X utf8`), python-pptx, lxml, requests, beautifulsoup4, LibreOffice, poppler, 한글 COM(PowerShell).

**Spec:** 이 문서 + 대화에서 승인된 설계(아래 Global Constraints), 상위 설계 `docs/superpowers/specs/2026-11-01-예배PPT-템플릿-구조-설계.md`.

## Global Constraints

- **16:9만 쓴다.** 준비찬양은 `1_자료/찬양곡/`의 16:9 파일만, 없으면 티스토리(cwy0675)에서 `_Wide` 첨부만 받는다. 4:3(`9_보관/4_3/`)으로 대신하지 않는다. `_Wide`가 없으면 멈추고 알린다.
- 입력: `prompt.txt` 형식(주보 이미지 경로, 준비찬양 HWP 경로, `YYMMDD`). 날짜는 오늘 다음에 오는 일요일(오늘이 일요일이면 7일 뒤), 명시 날짜가 있으면 그것.
- 준비찬양 HWP는 한글 COM으로 PDF 변환 후 렌더링해 읽는다(옛 `references/hwp-pdf-reading.md` 규칙 유지).
- `후렴으로`/`후렴부터` 지시는 `후렴 장 → 그 곡 전체` 순서(옛 스킬 규칙 유지).
- 기본 조립: `2_템플릿/구조/구조-주일기본.txt` × `2_템플릿/테마/테마-초록잎들꽃.pptx` → `4_예배PPT/주일/YYMMDD_주일.pptx`.
- 임시 폴더: `로컬전용/작업/YYMMDD/` (git 무시). 끝나면 이번 작업 파일만 지운다.
- 커밋 메시지는 AGENTS.md 규칙(날짜 없는 공통 작업은 한국어 설명형).

## Review Focus

- 티스토리 첨부에 `_Wide`가 없을 때: 4:3을 받지 말고 None.
- 후렴 장 번호가 곡의 장 수를 넘을 때: 조립 전에 알리고 멈춤.
- 준비찬양 목록에 문자열과 후렴 지정 항목이 섞여 있을 때 둘 다 처리.
- 배경 보완 대상 섹션 이름이 없을 때: 예외가 아니라 알리는 메시지.
- 옛 스킬 폴더를 지운 뒤에도 도구 테스트가 모두 통과해야 함(옛 경로 참조 없음).

---

### Task 1: 곡 찾기·티스토리 `_Wide` 내려받기 (`songs.py`)

**Files:** Create `도구/worship_ppt/songs.py`, Test `도구/worship_ppt/tests/test_songs.py`(옛 `test_tistory_search.py`를 옮겨 새 모듈 기준으로)

**Interfaces — Produces:** `normalize(text)->str`, `search_file(folder, title)->list[dict]`, `build_site_search_url`, `extract_site_search_candidates`, `is_password_protected_post`, `choose_site_search_result`, `select_ppt_attachment(attachments)->str|None` (**`_Wide`만 선택**), `tistory_download(title, folder)->str|None`, `SONG_DIR = REPO/"1_자료/찬양곡"`

- [ ] Step 1: 옛 테스트를 옮기고 첨부 선택 테스트를 바꾼다 — `[.nwc, .PPT, _Wide.PPT]` → `_Wide.PPT` 선택, `_Wide` 없는 목록 → `None`.
- [ ] Step 2: 실패 확인 — `python -X utf8 -m unittest discover -s 도구/worship_ppt/tests -p "test_songs.py"`
- [ ] Step 3: 옛 함수를 옮기고 `select_ppt_attachment`만 `_Wide` 전용으로.
- [ ] Step 4: 통과 확인.
- [ ] Step 5: Commit `예배 PPT 도구 찬양곡 찾기·내려받기 추가`

### Task 2: 후렴 장 떼기와 준비찬양 항목 (`assemble.py`)

**Interfaces — Produces:** 내용 json `준비찬양` 항목은 문자열(파일 경로) 또는 `{"파일": 경로, "후렴": [장번호...]}`(1부터). 후렴 지정 시 `[후렴 장만 담은 사본, 전체 파일]` 순서로 끼움. `extract_slides(src:Path, numbers:list[int], out:Path)->Path`, `check_inputs`가 장 번호 범위를 검사.

- [ ] Step 1: 테스트 — 3장 곡에 `후렴:[2,3]` → 준비찬양 섹션 5장(2,3,1,2,3 순 텍스트); `후렴:[9]` → `check_inputs`에 `후렴 장 번호 9` 포함 메시지.
- [ ] Step 2~4: 실패 확인 → 구현(`.ppt`면 먼저 pptx 변환 후 `slides.delete_slides`로 사본) → 통과.
- [ ] Step 5: Commit `예배 PPT 도구 준비찬양 후렴 시작 처리 추가`

### Task 3: 배경 보완 (`background.py`)

**Files:** Create `도구/worship_ppt/background.py`, Test `tests/test_background.py`(옛 `test_fix_background.py` 옮김)

**Interfaces — Produces:** `fix_section_background(target, section, bg_from)->int` (섹션 없으면 `ValueError("섹션이 없거나 비어 있음 - '…'")`), 내부 `_move_bg_to_transparent_pic`.

- [ ] Step 1~5: 옛 테스트 옮겨 실패 확인 → `insert.py` 헬퍼를 써서 옮김 → 통과 → Commit `예배 PPT 도구 배경 보완 추가`

### Task 4: 명령줄 `search`, `download`, `fix-background`

- [ ] `assemble.py`에 하위 명령 추가: `search 제목`(BEST_MATCH 출력, 없으면 종료 코드 2), `download 제목`(DOWNLOADED/BEST_MATCH, 없으면 2), `fix-background 파일 --섹션 X --배경 Y`. `build`는 verify 실패 시 종료 코드 1.
- [ ] 테스트: `search`가 없는 제목에 종료 코드 2, `build` verify 실패 시 1(subprocess 없이 `main(argv)`로).
- [ ] Commit `예배 PPT 도구 명령 추가`

### Task 5: 스킬 문서와 정리

**Files:** Create `.claude/skills/worship-ppt/SKILL.md`, `.claude/skills/worship-ppt/references/hwp-pdf-reading.md`(옛 문서 옮겨 경로만 수정). Delete `.claude/skills/church-worship-ppt/`, `.claude/skills/sermon-title-verse-grass-template/`. Modify `prompt.txt`(`/worship-ppt`, 새 준비찬양 경로).

- [ ] SKILL.md: 위 흐름 8단계, 각 단계 명령, 내용 json 형식, 판단 규칙(준비찬양 배치·후렴·배경), 확인(render 전 장 보기 + verify), 정리, 보고 형식.
- [ ] 옛 스킬 폴더 삭제 후 `grep -r "church-worship-ppt\|ppt_section_replacer\|주일 예배자료" 도구 .claude prompt.txt docs/superpowers/plans/2026-11-01-worship-ppt-스킬.md` 결과 없음(이 계획 문서 안 언급 제외), 도구 전체 테스트 통과.
- [ ] Commit `예배 PPT 스킬 16:9 조립 도구 기반으로 교체`

### Task 6: 실제 흐름 시험

- [ ] 261101 주보와 준비찬양 HWP가 있으면 스킬 흐름대로 처음부터 실행(없으면 261101 내용 json으로 build/render/verify). 결과를 사용자에게 보여 주고 시험 파일 삭제.
