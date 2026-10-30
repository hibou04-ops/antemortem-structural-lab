# 기존 E7 공개 배포물의 PyPI 채널 추가

배포 이름은 `antemortem-structural-lab`, Python import와 CLI는 `tomolab`, 발행 대상은 실험적 alpha `0.7.0a1`이다. 이번 작업은 이미 공개한 파일의 배포 채널을 추가한다. 연구 판정은 계속 `INCONCLUSIVE`이며 새로운 결함 발견 우위나 외적 일반화를 뜻하지 않는다.

[수동 발행 workflow](../.github/workflows/publish-pypi.yml)와 [검증기](../scripts/verify-pypi-release.py)를 사용한다. workflow 파일이 존재하거나 Pending Publisher를 등록한 상태만으로 PyPI 게시 완료라고 판단하지 않는다. 실제 발행 결과는 해당 Actions 실행과 공개 PyPI에서 확인한다.

## 발행 대상과 원본 연결

| 항목 | 고정된 값 |
|---|---|
| GitHub 저장소 | `hibou04-ops/antemortem-structural-lab` |
| 기존 공개 Release | [`v0.7.0a1`](https://github.com/hibou04-ops/antemortem-structural-lab/releases/tag/v0.7.0a1) |
| Annotated tag 객체 | `5a7e9c74cc2aa898e794ef75507d2bc7ad27e566` |
| 실제 package source commit | [`2edfb1230bd8519072845d9b9b0e2d4c42ab3837`](https://github.com/hibou04-ops/antemortem-structural-lab/commit/2edfb1230bd8519072845d9b9b0e2d4c42ab3837) |
| 배포 Name / Version | `antemortem-structural-lab` / `0.7.0a1` |
| E7 동결 | [`E7_CODE_FREEZE.json`](https://github.com/hibou04-ops/antemortem-structural-lab/blob/v0.7.0a1/docs/E7_CODE_FREEZE.json)의 제품 57개 |

| 공개 파일 | SHA-256 |
|---|---|
| `antemortem_structural_lab-0.7.0a1-py3-none-any.whl` | `c15fed1666eac1a1e0878413059de212150eb98f77a919967cc8a7bd84cab979` |
| `antemortem_structural_lab-0.7.0a1.tar.gz` | `3643ca44dda5ef3feb44a15fea10618421e11e683358ce47dc2e164ec68504e7` |
| `SHA256SUMS.txt` | `c1bd735880170b9eac31d58f866625945b631d1de3a3a3a19e91bb3cc717d480` |

검증은 `Release → tag 객체 → 실제 source commit → E7 동결 → 파일 내부 Name/Version·소스 → 공개 SHA256SUMS → 업로드할 동일 파일`을 연결한다. PyPI에 전송하는 파일은 wheel·sdist 두 개이며 checksum이나 검사 영수증을 배포 파일처럼 올리지 않는다.

발행 workflow commit은 패키지 source commit과 다를 수 있다. 두 commit을 검사 기록에서 구분한다. 새로운 workflow의 OIDC·attestation은 현재 업로드 맥락을 결속하며, 과거 태그의 빌드 출처 전체를 새로 증명하지 않는다.

## 현재 문서와 과거 패키지 문서

현재 저장소의 README는 PyPI 채널을 안내하지만 업로드할 원본 wheel·sdist는 E7 공개 시점의 README를 그대로 포함한다. 새 README로 로컬 재빌드한 파일을 같은 버전의 원본인 것처럼 게시하지 않는다. 원본 `pyproject.toml`·실행 코드·동결 manifest·기존 GitHub 자산·태그를 변경할 필요가 없다.

과거 Release·변경 이력의 “PyPI 게시 미포함”은 당시의 기록으로 보존한다. 이 채널의 실제 게시 여부는 별도의 workflow 실행·PyPI 버전·공개 파일 해시로 확인한다. 계정 귀속에는 `authors` 메타데이터가 아니라 실제 PyPI 프로젝트 권한을 사용한다.

## 프로젝트에 한정한 Trusted Publisher

| PyPI 설정 항목 | 값 |
|---|---|
| 로그인할 PyPI 계정 | `hibou` |
| PyPI project name | `antemortem-structural-lab` |
| GitHub owner | `hibou04-ops` |
| GitHub repository name | `antemortem-structural-lab` |
| Workflow filename | `publish-pypi.yml` |
| GitHub environment name | `pypi` |

GitHub owner와 PyPI username은 서로 다르다. 프로젝트가 아직 없으면 `hibou` 계정의 Publishing 화면에서 위 조합으로 Pending Trusted Publisher를 등록한다. Pending 등록은 이름 예약이나 프로젝트 생성이 아니다. 최초 정상 업로드에서 프로젝트가 생성되고 publisher가 정상 publisher로 전환되는지 확인한다. 조회 오류나 JSON API의 404만으로 등록 가능성이 보장되지는 않는다.

이 절차는 다른 다섯 프로젝트의 publisher·소유자·배포 설정을 변경하지 않는다. 비밀번호·2FA 코드·API token을 채팅이나 실행 로그로 전달하지 않는다. 로그인이나 재인증·필수 environment approval이 필요하면 해당 화면에서 직접 완료한다.

공식 근거: [첫 프로젝트 생성](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/), [Trusted Publisher 사용](https://docs.pypi.org/trusted-publishers/using-a-publisher/), [권한·workflow 보안 모델](https://docs.pypi.org/trusted-publishers/security-model/).

## 수동 발행 흐름

1. 정상 작업 브랜치·PR의 필수 CI를 통과하고 PyPI 설정과 같은 파일명의 workflow를 main에 반영한다. 연구 PR #1·#8의 임의 병합이나 연구 readiness 변경은 하지 않는다.
2. Actions에서 `publish-pypi.yml`에 해당하는 workflow를 선택하고 main에서 명시적으로 실행한다. PR·문서 변경·일반 main push만으로 PyPI 업로드를 시작하지 않는다.
3. 검증 job은 고정된 기존 공개 자산을 새로 다운로드한다. 태그·소스·동결 제품·메타데이터·허용 파일·SHA-256·설치를 검사한 뒤 wheel·sdist만 publish job에 전달한다.
4. publish job만 `pypi` environment와 OIDC `id-token: write`를 사용한다. 검증 실패는 업로드를 차단한다. 계정 비밀번호나 장기 API token을 workflow에 넣지 않는다.
5. 같은 대상 버전의 동시 발행을 막고, 이미 공개된 두 파일의 이름·버전·해시가 모두 일치할 때만 중복 업로드를 생략한다. 충돌이나 일부 파일만 존재하는 상태를 정상으로 덮어쓰지 않는다.
6. 업로드 뒤 공개 PyPI에서 두 파일을 다시 다운로드해 기존 GitHub 파일과 동일한지 확인한다. wheel·sdist의 새 설치 환경을 구분해 `pip check`·import·CLI·공개 fixture를 검사하고 실제 결과를 남긴다.

기존 E7 GitHub 발행과 이번 PyPI 발행은 별도 경로다. 문서·workflow 변경이 반영된 새 main을 이유로 E7 태그를 옮기거나 기존 GitHub Release를 다시 만들지 않는다. 기존 공개 자산과 제품 바이트를 읽기 전용으로 확인하고, 제품 변경이나 해시 불일치는 실패로 처리한다. 과거 동결 해시를 다시 계산하거나 실패를 무시하여 검사를 통과시키지 않는다.

## 공개 PyPI 설치 검증

다음은 **수동 발행 성공 뒤 공개 레지스트리에서 실행하여 확인하는 명령**이다. 정확한 alpha 버전을 지정하므로 다른 버전 선택과 구분한다. 저장소 checkout 밖의 새 환경에서 실행하며 실제 설치 출처가 PyPI인지 확인한다.

기본 설치:

```bash
python -m pip install "antemortem-structural-lab==0.7.0a1"
python -m pip check
python -c "import tomolab; from importlib.metadata import version; print(version('antemortem-structural-lab'))"
tomolab --help
python -m tomolab --help
python -m tomolab demo --mode cross --budget 12
```

E7 탐색의 선택 의존성과 동봉 공개 예제:

```bash
python -m pip install "antemortem-structural-lab[qa,solver]==0.7.0a1"
python -m pip check
python -m tomolab knowledge-demo --budget 16 --guidance-budget 4 --pool-size 16 --shrink-budget 16 --output results/e7.json
```

`qa`는 Hypothesis, `solver`는 Z3 통합에 사용한다. `analysis`는 별도의 선택 의존성이며 위 최소 예제에는 필요하지 않다. `tomolab`과 `python -m tomolab`은 같은 CLI다. 공개 데모는 기능 검사이며 독립 프로젝트 일반화·새 연구 성능·제품 정확성을 입증하지 않는다.

파일 검증은 [공개 PyPI 프로젝트](https://pypi.org/project/antemortem-structural-lab/), [정확한 버전](https://pypi.org/project/antemortem-structural-lab/0.7.0a1/), [JSON 파일 목록](https://pypi.org/pypi/antemortem-structural-lab/0.7.0a1/json)과 기존 GitHub Release의 해시를 연결한다. wheel과 sdist 설치를 별도로 수행하며 GitHub URL이나 로컬 checkout 설치로 대체하지 않는다.

## 계정 귀속과 완료 기록

실제 완료 기록은 다음을 구분한다.

- 사용한 source tag·commit과 발행 workflow commit·실행 URL.
- PyPI의 정확한 Name·Version, wheel·sdist 파일명·SHA-256과 기존 GitHub 파일의 동일성.
- 공개 PyPI 새 다운로드, wheel·sdist 새 환경 설치·`pip check`·import·CLI·공개 예제의 실제 결과.
- `hibou`의 프로젝트 권한과 [공개 프로필](https://pypi.org/user/hibou/) 표시. author 문자열만으로 소유권을 판단하지 않는다.
- 기존 다섯 프로젝트가 유지되고 새 프로젝트가 추가되는지 확인. 다른 변화가 없으면 여섯 프로젝트로 표시돼야 한다.
- PR·병합, 기존 태그·동결 기록 보존, 연구 PR #1·#8의 별도 상태와 남은 인증·권한 단계.

공개 프로젝트 생성·업로드 성공, 실제 계정 권한, 프로필 표시, 재다운로드·설치 성공은 각각 확인한다. 전파 지연에는 조회를 다시 확인하고 업로드를 중복 실행하지 않는다. 연구 입력·정답·소비된 final 평가를 재실행하거나 공개하지 않는다.
