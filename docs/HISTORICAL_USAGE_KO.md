# E9-R1 실제 역사적 결함 실행 안내

이 기능은 연구 브랜치의 미발행 기능이다. 공개 PyPI `0.7.0a1`에는 아래 `historical-*` 명령과 E9-R1 비교가 포함되지 않는다. 기존 PyPI 파일을 수정하거나 다시 게시하지 않는다. PR은 draft, `allow_release=false`를 유지하며 main 병합·태그·GitHub Release·PyPI 업로드는 이번 실행 경로에 포함되지 않는다.

문서 작성 시점의 실제 Docker 실행과 외부 원본 함수 실행은 **CI 검증 대기**다. 아래는 구현된 명령과 사전 계획이며 성공 결과가 아니다. 실제 판정에는 해당 HEAD의 CI 종료 코드, 실행 경계 영수증, 원본 재현·정상 대조 결과, 설치된 wheel의 실행 결과가 필요하다.

## 자료와 판정 범위

검토한 공개 프로젝트는 toolz, more-itertools, boltons의 3개다. `benchmarks/historical/candidate-catalog.json`에 후보 15개의 선정·제외 이유를 남겼다. `manifest.json`에는 Source 결함 2개, Target 결함 6개와 각 함수의 고정 buggy/fixed revision을 기록했다. 실제 case는 Source 2개·Target 6개·정상 수정본 대조 6개다. 수정본 대조는 같은 함수의 다른 revision이며 독립 구현으로 세지 않는다.

| 구분 | 함수 | 적용 입력 |
|---|---|---|
| Source | toolz `interpose`, more-itertools `bucket` | `sequence_int` |
| Target | more-itertools `windowed`, toolz `accumulate`, boltons `split_iter` | `sequence_int` |
| Target | boltons `split_punct_ws`, `iter_splitlines` | `text` |
| Target | boltons `bytes2human` | 유한 `float` |

입력 타입과 결함 메커니즘은 별도 필드다. 두 Source는 정수열만 다루므로 문자열·float Target의 실행은 `ROUTING_FALLBACK_CONTROL`이다. 해당 결과로 양의 구조 전이나 새로운 메커니즘 일반화를 주장하지 않는다. leave-one-mechanism-out에서는 실제 제외되는 Source가 있고 남은 Source와 타입·변이 문법 접점도 있는 fold만 실행한다. 접점이 없거나 제외할 메커니즘이 원래 Source에 없으면 실행하지 않은 이유를 기록한다.

`split_iter`는 공개 `maxsplit=0` 고정 설정을 검증하는 제한된 사례이며 전체 API의 대표 표본이 아니다. `bytes2human`은 [PR 525](https://github.com/mahmoud/boltons/pull/525)의 표시 반올림 후 단위 선택을 다룬다. 비유한값 거부를 다루는 PR 508의 성과로 세지 않는다. 6개 Target 중 4개는 boltons에 속한다. 프로젝트 수만으로 코드 계보의 독립성을 추정하지 않는다.

모든 사례는 **알려진 과거 비보안 결함의 재발견**이다. 현재 배포판의 새 결함이나 외적 일반화가 입증됐다는 의미가 아니다. 기존 작성 예제의 E9 결과와 이번 실제 역사적 자료의 결과도 합쳐 세지 않는다.

## 먼저 metadata만 확인

연구 소스 또는 후보 wheel의 `tomolab`을 사용하는 환경에서 저장소 루트 기준으로 실행한다. 출력은 새 파일이어야 한다.

```powershell
python -m tomolab historical-inspect `
  --catalog benchmarks/historical `
  --output work/historical-inspection.json
```

이 명령은 manifest를 읽으며 외부 함수나 factory를 import하지 않는다. 결과의 `external_code_executed=false`, `target_calls=0`, `oracle_calls=0`, `execution_scope=METADATA_ONLY`를 확인한다. 이 결과만으로 캡슐 실행이나 전체 원본 검증이 끝났다고 보고하지 않는다. factory의 `cases(load=False)`는 캡슐·라이선스·원문 단락의 해시와 AST를 별도로 검증한다.

## 검토된 Docker 실행

정상 실행 경로는 `.github/workflows/tests.yml`의 `historical-functional`과 명시적으로 dispatch하는 `historical-study`다. 다음은 그 workflow가 사용하는 실제 명령과 같은 launcher 경로다. Docker와 검토된 이미지를 사용할 수 있는 승인된 실행 호스트에서만 수행한다. Work에서 외부 원본을 직접 실행하는 대체 경로로 사용하지 않는다.

```powershell
python -m build
docker build -f containers/historical-review.Dockerfile -t tomolab-historical:reviewed .

python scripts/check-historical-container.py `
  --image tomolab-historical:reviewed --phase preflight `
  --output-directory work/historical-preflight

python scripts/check-historical-container.py `
  --image tomolab-historical:reviewed --phase wheel `
  --output-directory work/historical-wheel
```

각 출력 디렉터리는 새로 생성돼야 한다. 이미 있는 디렉터리를 덮어쓰지 않는다. 이미지 빌드는 Python 3.12와 고정 Hypothesis 의존성만 준비하며, 검토 대상 프로젝트 전체를 설치하거나 실행하지 않는다. launcher는 이미 준비된 이미지의 실제 image ID를 조회하고 이미지를 자동 pull하지 않는다.

launcher는 container를 먼저 생성하고 Docker inspect로 설정을 검증한 뒤 시작한다. 검증 조건은 네트워크 `none`, 읽기 전용 root filesystem, 사용자 `65534:65534`, capability 전체 제거, `no-new-privileges`, PID 64·메모리 512MiB·CPU 1개 상한이다. 저장소 `/app`과 host 검사 문맥 `/boundary`는 읽기 전용, 새 `/output`만 쓰기 가능한 host bind다. `/tmp`는 크기 64MiB의 `noexec,nosuid` tmpfs다. 컨테이너 내부에서도 UID·capability·mount·네트워크 경로 등을 실제 환경과 대조한다. 플래그 하나나 수정된 파일의 해시 재계산만으로 이 검사를 통과할 수 없다.

경계·이미지·실행이 실패하면 약한 격리나 Work 직접 실행으로 대체하지 않는다. 실패 로그와 부분 출력은 보존하며 launcher의 자동 재시도는 0회다. `container-launch.json`, 공개 phase 영수증과 CI 종료 코드를 함께 확인한다.

`preflight`는 먼저 `interpose` Source → Mold → 수정된 `windowed` 정상 대조의 실제 연결을 검사한다. 이 검사는 방법별 Target 성능 비교가 아니다. 이어 평가자 전용 재현 입력에서 원본 직접 호출과 adapter 결과의 일치, buggy 실패의 반복 재현, 수정본 정상 결과와 원본 진입 계측을 검사한다. Source만 사용한 예산 24·48의 개발 probe를 거쳐 Source 수집·학습·타입별 routing을 준비한다. 평가자 재현 입력을 생성기의 예제나 후보 전략으로 전달하지 않는다.

`wheel`은 컨테이너의 새 환경에 후보 wheel을 `--no-index --no-deps`로 설치한다. 설치된 모듈의 출처, CLI 도움말, metadata 조회, 실제 Source 실행 → `online-learn` → 수정된 Target 대조, 잘못된 factory SHA 거부를 검사한다. 검토된 이미지의 고정 의존성을 재사용하며 외부 프로젝트 패키지를 추가 설치하지 않는다. 등록된 Target 연구 비교를 다시 실행하는 설치 검사가 아니다.

## 단일 등록 비교 계획

정상 preflight를 확인한 뒤 연구 브랜치에서 `workflow_dispatch`로 실행하는 phase다. 일반 PR CI는 `study`를 실행하지 않는다.

```powershell
python scripts/check-historical-container.py `
  --image tomolab-historical:reviewed --phase study --timeout 1500 `
  --output-directory work/historical-study
```

계획은 A/B/C/D, 공통 예산 24·48, seed `4201,4211,4229`, 축소 예산 6이다. Source는 방법 B, seed `1811`, 예산 48로 준비한다. Source 수집 결과로 Mold를 만든 뒤 코드·설정·초기 Mold·자료 identity와 실행 profile을 등록하고 Target 방법 비교를 시작한다. Target 결과에 맞춰 사례·예산·기준을 바꾸거나 같은 배치를 최적화하지 않는다.

현재 정적 routing 계획은 총 **384회 실행 예정**이다. implementation-transfer에서 Target 6개와 정상 대조 6개 × 예산 2개 × seed 3개 × 방법 4개 = 288회다. 적격인 empty-iterable leave-one-mechanism-out의 Target 2개와 정상 대조 2개에 같은 조합 96회가 더해진다. Source 준비·preflight·wheel의 기능 검사는 이 수치 밖이며 비용을 별도 기록한다. 384는 완료된 실행 수나 발견 수가 아니다. 실제 완료 수·누락·오류·미발견과 비용은 결과 영수증으로 확인한다.

C와 D는 같은 Source의 입력 전용 replay를 사용하고 같은 호출·축소 예산을 적용한다. A/B는 Source rule provider를 로드하지 않으며 D만 고정 Mold를 로드한다. 결과는 서로 다른 역사적 결함 수, 최초 확정 실패까지의 호출, wall time과 Source 수집·학습 비용을 분리해 보고한다. wall-time 허용 상한을 사후에 만들어 종합 효율 성공으로 포장하지 않는다. C만 발견한 사례, D의 추가 호출·추가 시간과 음의 전이도 보존한다.

## 개별 CLI와 설치 경계

`historical-run`은 후보 wheel이 설치되고 위 검사를 통과하는 컨테이너 내부에서만 사용할 수 있다. 필요한 인자는 다음과 같다. `--allow-local-execution`은 명시적 opt-in이며 OS 경계를 우회하는 허가가 아니다. Work에서 이 플래그만 추가해 실행하면 거부된다.

```text
python -I -m tomolab historical-run
  --catalog /app/benchmarks/historical
  --factory /app/benchmarks/historical.py
  --expected-factory-sha256 <승인된 factory의 64자리 SHA256>
  --case toolz-interpose --method B --seed 11
  --budget 24 --shrink-budget 6 --max-seconds 30
  --usage-ledger /output/usage.jsonl
  --output /output/source.json
  --allow-local-execution
```

이 블록은 인자 안내다. 설치된 wheel의 실제 end-to-end 명령은 `--phase wheel`이 새 컨테이너 환경에서 구성한다. D에는 `--mold`와 외부에서 승인한 `--expected-digest`가 추가로 필요하다. C/D의 replay 파일은 Source 입력만 담은 목록이어야 하며 `--replays`로 전달한다. A/B에 replay나 Mold를 주지 않는다. 승인된 digest를 현재 수정 파일에서 다시 계산해 신뢰 근거로 대체하지 않는다. manifest·factory·원문 파일은 등록 영수증과 읽기 전용 실행 경계에 함께 묶는다.

adapter는 원래 API의 공개 고정 인자를 전달하고 iterator를 list로 materialize하는 역할만 한다. 숨겨진 Oracle 값이나 정답을 생성기 특징으로 보내지 않는다. 검토된 원본 함수의 공개 AST·리터럴·실제 root line을 A/B/C/D에 동일하게 제공한다. 인자 변환 관계는 모델링하지 않아 비교 거리는 UNKNOWN이며 wrapper 리터럴을 원본 분석으로 세지 않는다. 클래스 Source는 지원되지 않아 명시적 black-box로 실행한다. generator 재개 이벤트와 논리적인 Target 호출 수도 구분한다.

## 공개 자료와 암호화된 실행 자료

`benchmarks/historical/vendor`의 원본 단락은 MIT 또는 BSD-3-Clause 저작물이다. 라이선스 전문과 저작권을 함께 보존하며 Structural Lab의 Apache-2.0으로 다시 표시하지 않는다. 공개 manifest의 알려진 upstream 회귀 사례와 새로 생성된 실행 원시 자료를 구분한다. 기존 비공개 E1/E2/E3·R1 평가 자료를 이 corpus에 포함하지 않는다.

`scripts/package-historical-artifacts.py`는 실행 디렉터리 전체를 감사용 ZIP으로 묶고, `docs/HISTORICAL_ARTIFACT_RECIPIENT.pem`의 공개 수신자 인증서로 OpenSSL CMS 암호화한 `*.raw.cms`를 만든다. 원시 자료에는 입력·Oracle 관측·축소 결과가 들어갈 수 있으므로 평문 ZIP을 GitHub artifact에 올리지 않는다. 개인 키는 로컬 소유자에게만 남기며 저장소·CI 업로드에 넣지 않는다. 공개 artifact에는 검토된 `*.public.json`, 설치·launcher 영수증, 암호화된 원시 자료와 SHA256 envelope를 담는다.

암호화 파일의 해시는 보존·동일성 근거이며 연구 성공의 증거가 아니다. 공개 결과는 원시 입력·정답을 제외하면서 미발견·실행 오류·전체 비용·호출·출처·경계 판정을 보존한다. Google Drive 정본이나 기존 비공개 연구 ZIP의 공개·이동은 이 경로에 포함되지 않는다.
