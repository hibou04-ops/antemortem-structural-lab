# Antemortem Structural Lab v0.1.0

**실행 가능한 연구용 실험판 — 공개 릴리스 / 프로덕션 감사기 / AGI 안전성 판정기가 아닙니다.**

Omega Aile의 기존 `antemortem-cli`를 변경하거나 대체하지 않는 독립 실험입니다.
첫 목표는 **MRI형 정적 구조 관측 → CAST형 실행 관측 → 미관측 분기에 대한 표적 실험 → 재현 가능한 반례**의 루프를 최소 실험 환경에서 검증하는 것입니다. 성능상의 신규성은 아직 입증하지 않았습니다.

## 핵심 구성

| 부품 | 현재 실제 동작 | 지금은 하지 않는 것 |
|---|---|---|
| MRI | Python 소스 AST에서 정수 변수의 단일 비교 및 중첩 `if` 조건을 읽고, 소스 SHA256과 입력 후보를 생성 | 전체 데이터 흐름·SMT·타입·외부 모듈 분석 |
| CAST | 명시적으로 신뢰한 로컬 Python 함수에 입력을 주입해 실제 실행한 줄과 반환값/예외를 기록 | 격리·실행시간 제한·비신뢰 코드 실행 |
| 교차 피드백 | 실제 도달했지만 참 분기에는 진입하지 못한 조건을 MRI 조건식과 결합해 새로운 입력 생성 | 범용 최적 실험 설계·임의 수학 증명 |
| 오라클 | `implementation`과 명시된 `reference` 함수를 같은 입력으로 실행·비교. 별도 참조 소스 지정 가능 | 참조 구현이 절대적으로 옳다는 자동 증명 |
| Jev | TypeSafe Jev/Vercel의 공식 HTTP `/v1/evaluate` Choice 요청 형식에 맞춰 선택적으로 다음 입력 후보를 선택 | 사용하지 않은 API를 실제 사용했다고 보고, 판단을 진실의 증거로 채택 |
| 증거 재검사 | 소스·오라클의 SHA256 및 입력·출력 관계를 다시 확인 | 암호학적 서명, 불신 환경에서의 실행 증명 |

## 실행하기

Python 3.11 이상. 테스트 외에는 제3자 Python 의존성이 없습니다.

```bash
# 압축 해제한 프로젝트 폴더에서
python -m tomolab inspect examples/nested_equal.py
python -m tomolab demo --case nested_equal --mode cross --budget 12 --seed 7 \
    --output results/new_evidence.json
python -m tomolab replay results/new_evidence.json --allow-local-execution
python -m tomolab bench --budget 12 --seeds 30 --output results/new_benchmark.json

# 별도의 개발 환경에 pytest가 설치된 경우
python -m pytest -q
```

**실제 로컬 코드(스스로 작성했거나 신뢰한 코드만)**

```bash
python -m tomolab inspect path/to/module.py --function implementation
python -m tomolab run path/to/module.py --function implementation \
    --oracle reference --oracle-file path/to/independent_oracle.py \
    --mode cross --budget 20 --low -25 --high 25 \
    --allow-local-execution --output evidence.json
python -m tomolab replay evidence.json --allow-local-execution
```

`run`과 `replay`는 Python 코드를 **실제로 import하고 실행합니다**. 파일 접근·프로세스 생성·네트워크 전송·무한 루프를 차단하는 OS 샌드박스가 **없습니다**. 외부에서 받은 저장소나 불신 코드는 실행하지 마세요. `inspect`만 실행을 하지 않습니다.

예제에 포함된 `results/demo_cross_evidence.json`은 작성 당시 경로를 사용하므로 압축을 다른 폴더에 풀었다면 경로를 명시해야 합니다.

```bash
python -m tomolab replay results/demo_cross_evidence.json \
    --source examples/nested_equal.py --oracle-file examples/nested_equal.py \
    --allow-local-execution
```

## 실제 반례 예시

`examples/nested_equal.py`는 참조값 `x+y`를 반환해야 하지만, `x==17`이고 `y==-3`일 때만 `x+y+1`을 반환하는 의도적인 결함을 갖습니다.

1. MRI가 바깥 분기 `x == 17`을 발견해 `(17, 0)`을 제안합니다.
2. CAST가 그 입력을 실행해 바깥 분기에는 들어갔지만 내부 `y == -3` 참 분기에는 진입하지 못했음을 기록합니다.
3. MRI의 중첩 조건 정보와 CAST의 실제 실행 흔적을 결합해 `(17, -3)`을 생성합니다.
4. 그 입력을 실행한 결과 `implementation = 15`, `reference = 14`이므로 구체적인 **오라클과의 불일치**를 발견합니다.
5. `replay`는 같은 소스와 오라클의 해시를 검증한 뒤 해당 입력·출력 불일치를 재실행합니다.

여기서 발견한 것은 **참조 함수에 대한 반례**이지, 모든 가능한 의미에서의 오류 증명이 아닙니다. 참조 구현이 틀리면 결과 판정도 틀릴 수 있습니다. 참조 함수와 시험 함수가 공통으로 틀린 경우에는 발견되지 않습니다.

## 실험 / 비교

```bash
python -m tomolab bench --budget 12 --seeds 30
```

기본 `bench`는 3개의 의도적 결함과 1개의 정상 예제를 각각 30개 시드로 테스트합니다. 결함에 대한 90개의 시행, 정상에 대한 30개의 시행을 모드별로 실행합니다. 비교 모드는 `cast`, `mri`, `parallel`, `cross`입니다. **발견 시점에서 조기 중단하며 한 모드당 최대 12개 대상 함수 호출**을 사용합니다.

이 벤치마크는 교차 피드백 엔진이 잘 작동하도록 설계된 중첩 조건식으로 구성되어 있습니다. 따라서 결과는 **코드 경로 작동 확인**에만 사용할 수 있습니다. CtxFuzz, Hypothesis, CrossHair, SAGE 또는 실제 AI 감사 시스템보다 우수하다는 증거로 사용해서는 안 됩니다.

특히 다음이 아직 없는 상태입니다.

- 서로 다른 연구자가 작성한 블라인드 벤치마크와 실제 오픈소스 결함
- 커버리지와 오류 탐지의 별도 측정, 시간/메모리/API 비용의 공정한 정규화
- CrossHair·Hypothesis·기존 하이브리드 도구와의 동일 계약 비교
- 통계적 신뢰구간 및 문제 외 분포에서의 검증
- 실제 Jev vs 결정적 정책의 성능 차이를 측정한 실험

## Jev: 선택 사항이며 실제 호출하지 않은 모드를 엄격하게 구별

공식 Vercel 문서: https://vercel.com/changelog/ai-gateway-now-supports-typesafe-clients-and-http-api-for-jev

```bash
export AI_GATEWAY_API_KEY=...  # 직접 구성하는 경우만
python -m tomolab demo --case two_paths --mode cross --jev --budget 8
```

- `--jev` 없이 네트워크 요청은 없습니다.
- `--jev` 사용 시 2개 이상의 후보가 있을 때만 실제 모델 선택 요청을 수행하며, API 비용이 발생할 수 있습니다.
- 인증 키가 없거나 호출이 실패하면 **실제 Jev가 작동한 것처럼 보고하지 않고** `jev_error_deterministic_fallback`이라고 기록합니다.
- 전송 페이로드에는 후보의 작은 정수 입력값·분기 대상 여부·시험 횟수만 포함하며 소스코드·파일명·비밀정보는 포함하지 않습니다. 그러나 **입력값 자체가 민감하다면 사용하지 마세요**.
- `jev_live`는 요청·응답을 처리했다는 상태일 뿐 Jev가 더 좋은 선택을 했다는 뜻은 아닙니다. 포함된 모의 응답 테스트는 API 호환성/후보 화이트리스트 계약만 테스트합니다. 실제 계정 호출은 **실행하지 않았습니다**.

## 판정 의미

- `ORACLE_CONTRADICTION_FOUND`: 최소 하나의 입력에 대해 관측 결과가 주어진 참조 함수와 달랐습니다.
- `NO_COUNTEREXAMPLE_FOUND`: 예산 안에서 반례를 못 찾았을 뿐 **검증 성공이나 정확성 증명이 아닙니다**.
- `MODEL_UNCERTAIN_NOT_A_PROGRAM_DEFECT`: 제한적 AST 분석의 경로 예측과 실행 흔적이 충돌했습니다. 코드 오류라고 판정하지 않습니다.
- `SOURCE_DRIFT`, `ORACLE_DRIFT`: 소스 바이트 또는 참조 소스 바이트가 보고서 작성 시점과 달라져 재검사를 중단했습니다.
- `REPRODUCED`: 같은 소스 해시와 참조 함수 조건 아래 기존의 불일치 입력·출력이 재현됐습니다.

## 범위와 보안

- Python 순수 함수, `1–4`개 일반 정수 위치인자, 중첩된 단일 변수-정수 상수 비교, 제한적인 `if` 구조만 지원합니다.
- 비동기·제너레이터·기본값 인자·리스트/딕셔너리 상태·데이터베이스·네트워크 서비스는 대상이 아닙니다.
- `else`, 복합 표현식, 정수 아닌 상수, 함수 호출 조건, 루프 등은 탐사 가능성으로 계산하지 않습니다. 관련 제한은 `limitations`로 기록합니다.
- 실행 줄(line) 추적은 해당 함수의 최상위 코드 객체만 관측합니다. 다른 함수로 내려가 발생한 효과를 완전히 측정하지 않습니다.
- `--allow-local-execution` 플래그는 보안 격리가 아니라 사용자의 인지된 실행 승인 표시입니다.
- 증거의 SHA256은 출처 동일성 점검 용도이지 신뢰할 수 없는 작성자에 대한 서명은 아닙니다.
- 공개 Omega Aile 테스트용 샘플만 들어 있습니다. 개인 연구·비공개 전략 정보는 포함하지 않습니다.

## 다음 연구의 세 고정보량 실험

**G1 — 실제 결함 기준:** 다중 파일·복합 조건·상태 전이가 포함된 제3자 검증 벤치마크를 확보해 기존 CrossHair / Hypothesis와 동일 입력·비용으로 비교. 차이가 없으면 본 엔진을 확장하지 않습니다.

**G2 — 검사기 불일치 학습:** 단순 경로 커버리지보다 정적 예측과 실제 실행의 설명 불일치를 기준으로 탐색 정책을 바꾸었을 때 실제 결함 탐지력이 상승하는지 독립 평가.

**G3 — Jev 순수 기여:** G1/G2에 살아남은 알고리즘에서 동일 후보·예산·시드를 유지한 채 결정적 점수 정책과 실 Jev 선택을 정면 비교. 동등하거나 열등하면 Jev를 코어 의존성에서 제외합니다.

**완료 조건:** 실제 저장소의 다양한 결함에서 강한 기준선보다 확실히 우수한 반례 발견률/비용 효율을 보여주고, 잘못된 성공 판정과 미검증 영역을 끝까지 분리해야 합니다. 그전까지는 연구용 샌드박스 외에 배포하지 않습니다.
