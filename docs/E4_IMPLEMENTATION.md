# E4 소프트웨어 통합과 검증 범위

E4는 `v0.3.0a1`의 Mold·Version Space를 재사용하여 Hypothesis 생성·축소,
AST 구조 관계식, Z3 일관성 검사, Generator 정보 경계를 확장합니다.
기존 MRI·CAST·Claim-to-Witness와 E1/E2/E3 문서·태그는 보존합니다.
외부 프로그램 수집·실행, 제3자 서비스 검사, 비공개 연구 자료 공개는 하지 않습니다.

## 실제 구현

| 파일 | 기능 | 범위 |
| --- | --- | --- |
| `tomolab/mold/property_testing.py` | Hypothesis `find`, 정수 전략, 반례 축소, 중복 평가 캐시 | 공개 명세의 두 정수 입력, 신뢰하는 순수 함수 |
| `tomolab/mold/structural.py` | 실행 없는 AST 해석, 역할 정규화 JSON, 관계식 후보 제거 | 산술·비교·Boolean 복합 관계 |
| `tomolab/mold/structural.py` | enum/Z3 conjunction 검사, SAT witness 재검증, UNSAT core, UNKNOWN | 명세 bounds와 제외 입력 안에서만 성립 |
| `tomolab/mold/protocol.py` | 전송 전·수신 후 동일 허용 필드 검증 | 코드·정답 출력·모델 점수는 메시지 필드 없음 |
| `tomolab/mold/boundary.py` | 요청 직렬화, 크기·응답 형식 검증, 동결 후 feedback 차단 | 기본 subprocess는 논리적 분리 |
| `tomolab/cli.py` | `pbt-demo`, `pbt-run`, `constraints-check` | 기존 명령 보존 |

AST 입력은 승인된 공개 관계식입니다. 대상 소스의 의미를 자동 추론하지 않습니다.
지원 문법: `+`, `-`, 상수 곱, 양의 상수 `%`, `abs`, 비교 체인, `and/or/not`.
속성 접근, 임의 호출, 리스트·문자열, 변수끼리 곱셈은 거부합니다.
변수 이름은 `left/right` 역할로 정규화하며 `eval/exec`는 사용하지 않습니다.
기존 명세 한계인 정수 변수 두 개와 각 범위 폭 최대65개를 유지합니다.

## 검색·학습·축소

1. 기존 Mold가 중복 없는 후보를 라운드별로 고정합니다. 기본 라운드는8개입니다.
2. Hypothesis `find(sampled_from(...))`가 후보에서 실패를 찾고 인덱스를 축소합니다.
3. 평가기가 처음 실행한 제안 입력만 `FAILURE/REFUTATION` 증거로 Generator에 보냅니다.
4. 기존 Version Space가 충돌하는 가설을 제거하고 다음 라운드를 선택합니다.
5. Generator 동결 후 평가기 안에서 별도 정수 전략으로 수치 반례를 축소합니다.
6. 마지막 반례를 두 번 재실행합니다. 축소 결과는 학습에 되돌리지 않습니다.

`budget`은 후보 수이며 전부 실행되는 것은 아닙니다. `max_examples`는 Hypothesis 설정으로
실제 Oracle 호출 상한과 다릅니다. 실제 호출수는 `development_calls + shrink_calls + replay_calls`,
최대치는 `budget + shrink_budget + 2`입니다. 중복 검색은 캐시로 제거하며 검사하지 않은
입력을 평가한 것으로 계산하지 않습니다. 축소는 전역 최소성을 증명하지 않습니다.
캐시는 결정론적 순수 함수라는 호출자의 계약을 전제로 합니다. 두 번의 재실행만으로
임의 함수의 순수성을 증명하지 않습니다.

`filter_hypotheses(spec, relations, evidence)`는 같은 구조 증거로 AST 대안 가설을
필터링하며 `check_consistency`는 관계식 conjunction을 검사합니다. AST 후보는 기존
Mold 자동 선택 문법에 주입되지 않는 별도 공개 API입니다. 기존 snapshot은 보존합니다.
UNSAT core는 최소성을 보장하지 않으며 Solver 결과는 함수의 정답 판정이 아닙니다.

## 실행

```bash
python -m pip install -e ".[qa,solver]"
python -m tomolab pbt-demo --budget 32 --shrink-budget 128 --output results/pbt.json
python -m tomolab constraints-check --spec examples/mold/spec.json --expression "abs(x - y) <= 3 and x + y >= 2" --solver z3
python -m tomolab pbt-run examples/mold/target.py --oracle-file examples/mold/oracle.py --spec examples/mold/spec.json --allow-local-execution --output results/pbt-run.json
```

Python API: `run_properties(target_callable, oracle_callable, spec, trusted_execution=True)`.
함수는 평가기에만 있고 Generator에 전달되지 않습니다. 정답 판정은 정수 동등성입니다.
`subjective_assessment.status=NOT_RUN`, `used_for_verdict=false`이며 모델 평점으로 판정을
덮어쓸 수 없습니다. 신뢰 옵션은 대상 코드를 안전하게 바꾸는 장치가 아닙니다.

## 개발·최종 검증 분리

개발 테스트와 `scripts/evaluate-e4.py`의 최종 사례는 다릅니다. 직접 작성한 새 순수 함수만
사용하고 기존 E1/E2/E3 비공개 정답·소비된 홀드아웃을 읽지 않습니다. 제품 코드 SHA-256과
최종 후보 계획을 고정한 뒤 평가하며 최종 feedback0회와 계획·코드 해시 유지를 검사합니다.
공개 합성 사례이므로 `NOT_BLIND`, 외적 일반화는 `NOT_ESTABLISHED`입니다.

```bash
python -m pytest -q
python scripts/evaluate-e4.py --output results/e4-validation.json
python -m build
python scripts/check-public-scope.py
python scripts/check-wheel.py
python scripts/check-wheel.py --qa
```

로컬 Python3.12에서 기존76개+신규69개, 총 **145 PASS**(4.69초).
별도 측정에서 개발 후보48개·중복0, 반례 `(6,-7)` → `(3,0)`, 개발 Oracle39회
(축소·재실행 포함), AST 가설4개 → 1개, enum/Z3 상태3/3 일치를 관측했습니다.
최종 함수별 동결 후보64개에서 오류 함수 mismatch5회, clean 함수0회, feedback0회였습니다.
같은 오류 함수의 mismatch5회를 독립 결함5개로 해석하지 않습니다. 개발 실행 약0.39초이며
시간·Hypothesis 경로는 환경·버전에 따라 달라집니다. 우위 비교 실험은 아닙니다.

CI는 Ubuntu/Windows × Python3.11/3.12/3.13 회귀, sdist/wheel, 별도 환경의 기본·선택
의존성 설치를 검사합니다. 해당 커밋의 Actions 결과가 CI 성공 여부의 정본입니다.
모든 검사가 성공한 main에서만 prerelease를 게시하며 wheel·sdist·체크섬의 원격 바이트를
다시 다운로드해 SHA-256을 비교합니다.

## 정보 경계와 미구현 범위

- 프로토콜은 명세·제안 입력·최소 구조 증거만 허용하고 금지 필드는 전송 전에 거부합니다.
- Generator 복사 목록에서 평가기·Hypothesis·대상·Oracle·환경 비밀정보를 제외합니다.
- `freeze` 또는 frozen `transfer` 후 `observe`는 전송 전에 거부합니다.
- 기본 subprocess는 `LOGICAL_ISOLATION_ONLY`이며 OS 파일 접근 차단을 제공하지 않습니다.
- Docker는 공개 코드만 read-only mount, `--network=none`, 비특권 사용자로 실행합니다.
  CI는 실제 네트워크 모드·비 loopback 인터페이스 부재·sentinel 읽기 및 쓰기 실패를 검사합니다.
  제3자 주소 접속 시도는 하지 않으므로 외부 연결 실행 검사는 `NOT_TESTED`입니다.
- 기본 Docker 이미지에는 Z3가 없습니다. 함께 쓰려면 검토한 이미지에 사전 설치해야 합니다.
  자동 약화나 자동 이미지 다운로드는 없습니다.

미구현: 임의 Python 의미 추론, 일반 자료형·상태 있는 함수, 외부 코드 수집, 자동 AST 가설
합성, AST 후보의 기존 Mold 선택 정책 편입, 실제 프로젝트 블라인드 일반화 평가.
유한 정수 계약·정보 경계를 유지하기 위한 범위 제한입니다. 기존 연구 판정은 변경하지 않습니다.
