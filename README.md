# 대용량 파일 올리는 방법 - LFS

> ℹ️ **정보** 
> - 50MB 이상 파일부터 Git LFS 사용을 고려하면 좋음
> - 100MB 이상 파일은 GitHub에서 일반 git push가 차단됨 → Git LFS 필수
> - Git LFS를 사용하면 대용량 파일을 효율적으로 관리 가능하지만, 무료 사용자는 1GB까지만 업로드 가능
> - Git LFS를 적용하려면 git lfs track을 사용해야 하며, 한 번 설정하면 자동 적용됨

---

- **Git LFS 설치**:
    
    먼저 Git LFS를 설치해야 합니다. 다음 명령어를 사용해 설치할 수 있습니다.
    
    ```bash
    git lfs install
    ```
    

### 1. **대용량 파일을 Git LFS로 추적**

```bash
git lfs track "파일명.확장자"  # 예: git lfs track "*.zip"
```

이 단계에서 `.gitattributes` 파일이 생성되고, 해당 파일이 LFS로 추적됩니다.

### 2. **.gitattributes 파일을 Git에 추가 및 커밋**

```bash
git add .gitattributes
git commit -m "Track 파일명.확장자 files using Git LFS"
```

이 단계에서 `.gitattributes` 파일이 Git에 추가되어 LFS 추적 정보가 저장됩니다.

### 3. **모든 파일 추가 및 커밋**

이제 대용량 파일과 다른 파일들을 함께 추가하고 커밋할 수 있습니다.

```bash
git add .
git commit -m "240911
```

이 명령어로 대용량 파일 및 일반 파일 모두를 한 번에 추가하고 커밋합니다.

### 4. **변경 사항 푸시**

```bash
git push origin main
```

마지막으로 변경 사항을 원격 저장소에 푸시합니다.

---

### 순서 정리:

1. **Git LFS로 대용량 파일 추적**: 
    
    `git lfs track "파일명.확장자"`
    
2. **.gitattributes 파일을 추가하고 커밋**: 
    
    `git add .gitattributes && git commit -m "Add Git LFS tracking for pptx files"`
    
3. **모든 파일을 추가하고 커밋**: 
    
    `git add . && git commit -m "240911"`
    
4. **푸시**: 
    
    `git push`
    
