# 한글 PDF 변환 및 문서 판독

준비찬양 HWP/HWPX의 실제 배치·순서·진행 표시를 읽기 전에 사용한다. 원본을 재작성하지 않고 설치된 한글의 COM PDF 내보내기를 사용한다.

## 실행 전 확인

- 사용자 입력에서 계산한 날짜의 실제 원본 경로를 확인한다. 과거 예배 날짜를 코드에 고정하지 않는다.
- `HWPFrame.HwpObject`와 설치된 한글을 사용한다. 현재 공식 모듈 이름은 `FilePathCheckerModuleExample`이다. 등록 위치는 `HKCU\Software\HNC\HwpAutomation\Modules`, DLL은 `%LOCALAPPDATA%\HancomAutomation\FilePathCheckerModuleExample.dll`이다.
- 문서를 열기 **전에** `RegisterModule('FilePathCheckDLL', 'FilePathCheckerModuleExample')`의 반환값이 `True`인지 확인한다. DLL 존재나 레지스트리 등록만으로 성공했다고 하지 않는다.
- `False`이면 문서 열기를 강행해 승인창에 대기하지 않는다. 실제 한글 실행 계정에서 등록값과 DLL 존재를 확인한다. 에이전트 환경에서 보이는 파일·레지스트리가 사용자 환경에서도 존재한다고 단정하지 않는다. 보안 설정 해제, 승인창 자동 클릭, 무한 재시도는 하지 않는다. 필요한 환경 보완만 알리고 별도 가능한 작업은 계속한다.
- 공식 안내: https://developer.hancom.com/en-us/hwpautomation
- 모듈 DLL은 지속 사용을 위한 설치 파일이며 작업 종료 정리 대상이 아니다. 다운로드·진단 임시 파일은 정리한다.

## 변환과 종료

아래 `$source`와 `$pdf`에 해석한 절대 경로를 넣는다. `$pdf`는 반드시 `C:/Oddments_Repository/교회/gitignore/workspace/` 안의 작업별 임시 폴더에 지정하고 폴더를 먼저 만든다(예: `.build/YYMMDD/준비찬양.pdf`). HWP 원본 폴더나 최종 PPT 저장 폴더에는 PDF를 생성하지 않는다. 단순 PDF 변환 테스트도 같은 규칙을 적용한다. 사용자가 PDF 자체를 최종 파일로 보존하라고 명시한 경우에만 예외로 한다. 기존 사용자 파일을 임의로 덮어쓰지 않는다.

```powershell
$ErrorActionPreference = 'Stop'
# $source: 실제 HWP/HWPX 입력 경로
# $pdf: 이번 작업의 PDF 출력 경로
$beforeHash = (Get-FileHash -LiteralPath $source).Hash
$hwp = New-Object -ComObject HWPFrame.HwpObject
try {
    $hwp.XHwpWindows.Item(0).Visible = $false
    if (-not $hwp.RegisterModule('FilePathCheckDLL', 'FilePathCheckerModuleExample')) {
        throw '공식 보안 모듈 활성화 실패'
    }
    if (-not $hwp.Open($source, '', '')) { throw '한글 파일 열기 실패' }
    if (-not $hwp.SaveAs($pdf, 'PDF', '')) { throw 'PDF 저장 실패' }
    if (-not (Test-Path -LiteralPath $pdf) -or (Get-Item -LiteralPath $pdf).Length -eq 0) {
        throw 'PDF 출력 없음'
    }
}
finally {
    # 이 작업에서 생성한 COM 인스턴스에만 적용한다.
    # 원본에는 저장하지 않고 문서를 비워 종료 시 저장 질문을 방지한다.
    try { $hwp.Clear(1) }
    finally {
        try { $hwp.Quit() }
        finally { [Runtime.InteropServices.Marshal]::ReleaseComObject($hwp) | Out-Null }
    }
}
if ((Get-FileHash -LiteralPath $source).Hash -ne $beforeHash) {
    throw '원본 한글 파일이 변경됨'
}
```

- `SaveAs(..., 'PDF', '')` 뒤 바로 `Quit()`만 호출하지 않는다. `Clear(1)`은 메모리에 열린 문서를 원본에 저장하지 않고 닫기 위한 것으로, 원본 파일이나 이미 저장된 PDF를 삭제하는 동작이 아니다.
- 다른 한글 창이나 사용자 작업 프로세스를 일괄 종료하지 않는다. 실패 시 원본 저장을 시도하지 않으며, 생성되지 않은 PDF를 완료했다고 보고하지 않는다.
- 종료 직후 파일 잠금 때문에 해시 확인이 실패하면 잠깐 기다렸다가 제한적으로 다시 확인한다. 잠금 오류를 원본 변경이나 변환 실패로 단정하지 않는다.

## PDF 확인과 순서 판독

1. `pdfinfo`로 페이지 수와 정상 열림을 확인하고, 모든 페이지를 `pdftoppm -png`로 렌더링해 Read 도구로 본다(scoop poppler).
2. 렌더링 이미지를 직접 읽는다. 빈 쪽·페이지 번호만 있는 쪽, 같은 곡의 연속 악보, 한 단 안의 여러 곡을 구분한다.
3. 각 곡의 제목, 페이지와 단 위치, 진행 문구, 후렴 시작·끝 가사, 판별 근거를 기록한다. 별도 사용자 순서가 없으면 본 스킬 Step A의 문서 배치 규칙을 적용한다.
4. 이 사용자의 자료에서 `후렴으로`는 기본적으로 `다음/지정 곡의 후렴 → 그 곡 전체를 처음부터`라는 진행 지시다. 후렴 슬라이드 뒤에 전체 곡 슬라이드를 붙이고, 전체 곡에 포함된 후렴도 유지한다. `후렴만` 등 별도 명시가 있으면 그것을 우선한다. 후렴 구간 자체가 모호하면 다른 신뢰 가능한 악보·음원으로 대조하고, 그래도 불확실할 때만 필요한 구간을 질문한다.
5. 텍스트 추출이나 HWP BinData 추출은 보조 정보다. 이미지만 있는 PDF에서 텍스트가 추출되지 않아도 빈 문서로 판단하지 않는다.
6. PDF는 곡 순서·진행 지시 판독용 임시 파일이며, 예배 화면은 찬양곡 자료 PPT를 매칭해 구성한다. 작업 중에는 PDF를 작업 폴더 안에 유지하고, 전체 PPT 제작과 최종 검증이 끝나면 이번 작업의 PDF·이미지·사본·백업을 함께 삭제한다. 변환 테스트만 진행 중이면 임시 위치를 유지하며, 별도 정리 요청 시 삭제한다. PDF 자체를 최종 파일로 보존하라는 명시적 요청이 있을 때만 최종 PDF를 남긴다.
