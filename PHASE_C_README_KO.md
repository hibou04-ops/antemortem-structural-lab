# Phase C — Claim-to-Witness (오라클 없는 조건부 반례 탐색)

**상태:** `v0.2.0` 독립 실험판 / 합성 시험 데이터 / 외부 SOTA 우위 미입증 / 프로덕션 금지.

## 연구 질문과 정확한 범위

> `implementation`과 `reference`를 비교하지 않고, **자연어 주장 → 구체적인 관계식 → 실제 반증 입력 → 동일 소스에서의 재현**을 수행할 수 있는가?

이번 버전에서는 **그렇다. 단, 문장 6종의 정확한 화이트리스트에 대해서만.** arbitrary 자연어 주장을 이해하는 엔진이나 검증 의무를 새로 발견하는 LLM은 아직 없다. 즉 **'오라클 없는 실험'은 실행 가능한 정답 함수가 없다는 뜻**이지, 판단 기준이 전혀 없다는 뜻이 아니다. 사용자 주장으로부터 **관계형 계약(metamorphic relation)**을 명확히 정의해야 한다.

코드가 '정답'이라는 증거는 없다. 유한한 실행에서 위반 예를 찾으면 해당 **관계식**은 거짓이라고 반증할 수 있지만, 위반 예가 없다는 사실로 일반적인 프로그램 정확성을 증명하지는 못한다. 원래 자연어 주장과 관계식이 진짜 동치라는 사실도 독립적으로 검증해야 한다.

## 먼저 실행할 명령 (Windows PowerShell)

프로젝트 압축 해제 폴더에서:

```powershell
# 1. 소스코드 실행 없이, 지원하는 정확한 문장만 형식 계약으로 변환
python -m tomolab claim-compile --claim '두 정수 입력의 순서를 바꿔도 반환값은 같다'

# 2. 참조 함수가 하나도 없는 synthetic target으로 실행 실험
python -m tomolab claim-run examples/claim_only/symmetry_bug.py --claim '두 정수 입력의 순서를 바꿔도 반환값은 같다' --mode cross --budget 12 --allow-local-execution --output results/claim_symmetry_pc.json

# 3. 계약 SHA256, 소스 SHA256 확인 후 같은 위반 입력 재실행
python -m tomolab claim-replay results/claim_symmetry_pc.json --allow-local-execution

# 4. MRI 단독 / CAST 단독 / 병렬 / 교차 탐색. 각 관계 검사는 대상 함수 3회 호출.
python -m tomolab claim-bench --seeds 30 --budget 12 --output results/claim_benchmark_pc.json

# 5. 모든 이전 및 신규 회귀 테스트
python -m pytest -q
```

**TypeSafe API 키 불필요**. Phase C 최초 벤치마크에서는 Jev를 호출하지 않는다. v0.1.1에서 확인한 실제 Jev 연결의 성능 개선은 여전히 **미검증**이다.

## 실제로 구현한 정확한 계약 3종

| 자연어 주장(정확히 일치해야 함) | 컴파일된 검증 의무 |
|---|---|
| 두 정수 입력의 순서를 바꿔도 반환값은 같다 | `f(x,y) == f(y,x)` |
| 첫 번째 정수 입력을 1 증가시키면 반환값도 1 증가한다 | `f(x,y) == f(x-1,y)+1` |
| 첫 번째 정수 입력을 1 증가시키면 반환값이 감소하지 않는다 | `f(x,y) >= f(x-1,y)` |

영어로 된 3개의 정확한 동의 문장도 지원한다. 문구를 조금이라도 다르게 쓴 모호한 주장은 `UNSUPPORTED_CLAIM`을 내고 종료한다. **기계적으로 확정한 계약만 테스트**한다. 자연어를 멋대로 해석해 과도한 신뢰를 만드는 것을 피하기 위한 의도적인 제약이다.

가정: 순수·결정적 함수, 정수 인자 2개, 정수 반환형, 입력 범위 기본 `-25..25`. 예외·지원 밖 반환형·반복 실행 불일치는 결함 확증으로 판정하지 않는다. 동일한 첫 입력을 한 번 더 실행해 결정성의 일부를 확인하지만 **전체 순수성을 증명한 것은 아니다**.

## 증거 계약

`tomolab-claim-evidence-v1`의 결과 상태:

- `CLAIM_REFUTED`: 실제 관측값이 컴파일한 **정확한 관계**를 위반하는 재현 가능한 입력쌍 발견.
- `NOT_REFUTED_WITHIN_BUDGET`: 제한된 실행 안에서 반례 발견 못함. **PASS 또는 VERIFIED가 아님.**
- `INCONCLUSIVE_EXECUTION`: 판단 가능한 결과가 없음. 계약 또는 실행 환경 재검토 필요.
- Replay: `REPRODUCED` / `NOT_REPRODUCED` / `SOURCE_DRIFT` / `CONTRACT_DRIFT` / `NO_FINDINGS`.

증거는 계약 ID와 SHA256, 소스 SHA256, 양쪽 입력과 출력, 3회 실행의 관측 줄, 교차 피드백 이유, 예산, 정보 부족 사항을 담는다. **증거 SHA256은 원본 동일성을 확인할 뿐 디지털 서명이나 의도 검증은 아니다.** 외부 의존성과 런타임 환경의 변경까지 암호학적으로 보호하지 않는다.

## 합성 벤치마크 관측값 (프로토타입 기능 시험)

Python 3.13, 기본 seed 0~29, 결함 3종 × 30 seed = 90회, 정상 대조군 4종 관계 설정 × 30 seed = 120회/모드, 대상 함수 호출 최대 12회/시행.

| 탐색 방식 | 주장 위반 반례 발견 | 정상 계약에 대한 허위 반증 |
|---|---:|---:|
| CAST 단독 | 3/90 | 0/120 |
| MRI 단독 | 0/90 | 0/120 |
| 단순 병렬 | 0/90 | 0/120 |
| MRI ↔ CAST | **90/90** | 0/120 |

교차 탐사는 모든 결함에서 **6회 대상 함수 호출(3회/계약 검사 × 2검사)**. 이번 fixture는 **엔진이 쉽게 성공하도록 지원하는 동일한 중첩 if 문법으로 작성한 비블라인드 데이터**다. 시드 30개는 30개의 서로 다른 결함이 아니며, 결과를 현실 코드나 CrossHair보다 우수하다는 증거로 써서는 안 된다.

정상 대조 `symmetric_not_sum.py`는 `x*x+y*y`를 반환하지만 두 입력을 바꾸어도 결과가 같아 **swap 검사를 통과**한다. 이 사례가 중요하다. `f(x,y)=f(y,x)`를 검증했다는 사실이 `f(x,y)=x+y`를 검증했다는 뜻은 아니다. 검증 의무가 **너무 약하면 결함을 놓친다**.

## CrossHair와의 정면 비교 (PC 실행)

CrossHair 공식 문서에서 `--analysis_kind=asserts`는 함수 첫 `assert`를 사전조건, 다음 `assert`를 검증조건으로 사용한다. 이번 baseline은 **실행 가능한 참조 함수가 전혀 없고**, Structural Lab과 **같은 관계식**을 검사한다.

```powershell
python -m crosshair check --analysis_kind=asserts baselines/crosshair_claim_contracts.py
```

이 스크립트에는 합성 결함 주장 3종 및 정상 대조 주장 3종이 들어 있다. CrossHair가 반례를 찾는다면 이번 신기능도 **CrossHair가 이미 할 수 있는 것의 제한적인 재구현**이 된다. 우위가 입증되지 않으면 CrossHair를 재사용하는 것이 합리적이다. **이 환경에서는 CrossHair가 설치되어 있지 않아 공식 baseline은 아직 실행하지 않았다.** 사용자의 Windows PC에는 이전 대화에서 CrossHair 0.0.112가 설치됨.

공정한 비교를 위해 총 벽시계 시간과 결함 탐지 여부를 기록한다. CrossHair의 솔버 반복 횟수와 Phase C의 대상 함수 호출 수는 동등한 비용 단위가 아니므로 직접 비교하지 않는다.

## 진짜 후속 연구: 의미의 검증

**Phase C0(이번)**: 화이트리스트 주장 → 관계식 → 실행 반례, 재현 가능성.

**Phase C1**: 다른 프로젝트의 *공식 문서만*으로 AI가 검증 의무를 제안. 소스코드나 숨겨둔 결함을 본 다음 계약을 선택하는 정보 누출을 막는다.

**Phase C2**: 전문가가 작성한 계약과 제안 계약의 의미적 일치도, 오탐과 거짓 계약에 의한 허위 반증, 반례를 찾지 못한 경우의 UNKNOWN 분리.

**Phase C3**: PBT-Bench(2026, https://pbtbench.com/)처럼 40개 Python 라이브러리 / 365개 주입 결함을 사용하는 독립 benchmark, CrossHair 및 Hypothesis + 전문가 계약 등 강력한 baseline과 대조. 단, 벤치마크의 독립 버전·라이선스·평가 환경을 실제로 확인한 뒤 수행.

**중단 조건:** 단순 계약 컴파일과 기존 CrossHair/Hypothesis에 작은 접착 코드만 붙인 것과 비교해 의미 충실도나 결함 발견 효율이 개선되지 않으면 별도 제품화 금지.

## 보안 및 비공개 정책

`claim-compile`은 파일을 실행하지 않는다. `claim-run`, `claim-replay`, `claim-bench`는 **Python 코드를 실제 실행한다. OS 샌드박스·타임아웃 없음. 외부에서 받은 소스나 악성 코드를 실행하지 말 것.**

API 키·개인 연구·비공개 전략 내용은 포함하지 않았다. 이전 v0.1.1은 별도 ZIP으로 보존하고 본 버전과 혼동하지 않는다. Google Drive 연구 폴더에는 별도 추가 체크포인트로 보관한다.

기술 근거:
- https://crosshair.readthedocs.io/en/stable/kinds_of_contracts.html
- https://crosshair.readthedocs.io/en/stable/contracts.html
- https://doi.org/10.1109/TSE.2013.46
- https://pbtbench.com/
