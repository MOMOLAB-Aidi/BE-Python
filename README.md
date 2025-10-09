## 🛠️ Branch Strategy

### 브랜치 유형

| 브랜치 유형 | 내용 |
| --- | --- |
| `main` | 완성된 버전의 코드를 저장하는 브랜치 |
| `dev` | 개발이 진행되는 동안 완성된 코드를 저장하는 브랜치 |
| `feat` | 작은 단위의 작업이 진행되는 브랜치 |
| `hotfix` | 긴급한 오류를 해결하는 브랜치 |

### 브랜치 명

- 유형/#이슈번호
    
    ex) feat/#30,  setting/#1
    

| 카테고리 | 내용 |
| --- | --- |
| `feat` | 구현 |
| `mod` | 수정 |
| `add` | 추가 |
| `del` | 삭제 |
| `fix` | 버그 수정 |
| `refactor` | 리팩토링 |

## 📔 Git Convention

### Git Flow

1. Issue 생성
2. Branch 생성
3. Add - Commit - Push - Pull Request(PR)
    1. Commit은 최대한 자주, 적은 양
    2. Commit시에 Issue를 연결
4. PR이 작성되면 작성자 이외의 다른 팀원이 Code Review를 진행합니다.
5. Code Review가 완료되면 PR 작성자가 dev Branch로 Merge 합니다.
    1. Merge 후 카톡방에 무조건 공유합니다.
6. Merge 된 작업이 있으면 다른 브랜치에서 작업을 진행 중이던 개발자는 본인의 브랜치로 Merge된 작업을 Pull 받아옵니다. (최신화 습관 들이기!)

### 협업 규칙

- dev 브랜치에서의 작업은 금지합니다. 단, 초기 세팅 및 README 작성은 dev 브랜치에서 수행 가능합니다.
- 본인의 PR은 본인이 Merge합니다.
- Commit, Push, Merge, PR 등 모든 작업은 앱이 정상적으로 실행되는지 확인 후 수행합니다.

### Issue Convention

[카테고리] 제목 

ex) [INIT] 프로젝트 초기 세팅 

### Commit Convention

[커밋 카테고리/#이슈번호] 커밋 내용 (대문자)

ex) [FEAT/#30] 홈 뷰 구현, [ADD/#1] 폰트 파일 추가

| 커밋 카테고리 | 내용 |
| --- | --- |
| `feat` | 기능 (feature) |
| `fix` | 버그 수정 |
| `docs` | 문서 작업 (documentation) |
| `style` | 포맷팅, 세미콜론 누락 등, 코드 자체의 변경이 없는 경우 |
| `refactor` | 리팩토링 : 결과의 변경 없이 코드의 구조를 재조정 |
| `test` | 테스트 |
| `chore` | 변수명, 함수명 등 사소한 수정 *ex) .gitignore* |

### PR Convention

[카테고리/#이슈번호] 제목

ex) [FEAT/#6] 로그인 뷰 구현
