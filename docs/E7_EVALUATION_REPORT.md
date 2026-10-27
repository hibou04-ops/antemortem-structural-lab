# E7 실제 프로젝트 독립 평가

최종 판정: **INCONCLUSIVE**. 외적 일반화: **INCONCLUSIVE**.

현재 수치는 명시적으로 재등록한 generation-v2다. v1은 INVALID_ORACLE / INCONCLUSIVE로 원본·127개 개발 파일·해시를 보존했다. 원래 역사적 계약 SHA-256은 `22abade2c41fbcccd02ce898a2591f67dcefaa1f23700c72284688c423eacfe5`이며 현재 v2 계약의 해시와 구분한다.

v1의 원시 불일치6개 실행 중 실제 생산 코드 불일치는2개 실행(15rows·한 함수 메커니즘), Oracle 오판은4개 실행(42rows·한 Oracle 메커니즘)이었다. 사전 정적·수식 감사가 유한 정밀도 zero 판정 구현 오류를 놓쳤으며, 결과 후 개발 로그 정적 감사에서 발견했다. 정확한 Fraction 산술로만 고쳤고 문제·domain·seed·예산·E6-only 수집 정책·제품 runtime54개는 바꾸지 않았다. 앞선3/3 실제 제품 결함 해석은 철회한다. novelty·운영 영향은 UNKNOWN이다.

합성 mutation을 추가하지 않고 사용자 소유5개 저장소에서 실제 함수9개를 HEAD Git blob으로 고정했다. 개발3개와 최종6개는 동일 함수가 아니며, 정적 검토한 함수·필요 class의 AST를 원본 그대로 추출했다. 프로젝트 전체나 provider/네트워크를 실행하지 않았다. 원본 저장소·태그는 수정하지 않았다.

평가자가 코드를 읽고 대상을 선정했으므로 무작위 프로젝트 표본이 아니다. 일부 프로젝트·작성자·표준 알고리즘 계보가 겹친다. 이 한계를 독립 프로젝트 수 또는 일반적 버그 발견률로 확대하지 않는다.

## 사전 계약과 Oracle

v2 계약 SHA-256: `32b77dfca5abdd465f32f664460d94677da4c276dd7b3a4a64ae09afb09b6c35`. v2 비교 전, 최종 관측0 상태에서 재등록했다. float의 Fraction 표현으로 centered variance/covariance와 zero·epsilon 판정을 정확히 계산하고 마지막 제곱근만 기존100-digit Decimal로 변환한다. float tolerance(rel1e-8/abs1e-10)·정상 대조군4개·seeds11/37/73·예산은 그대로다. 개발 자료는 v1에서도 소비된 DEVELOPMENT이며 새로운 blind source라고 주장하지 않는다. 바깥 영역은 대상/Oracle 호출 전에 거절한다.

Oracle 수정 정확성 진단은 기존 개발57rows와 독립 작성5개 수학 fixture에 대해 Oracle-only62calls, production target0이었다. 이 단위를 생산 함수+Oracle 평가 pair와 혼동하지 않는다. 독립 감사와 정상 승인 경로로 연동을 검토했고 suite와 공개 수학 helper의 hash를 함께 동결했다.

## 개발 결과

| 방법 | COMPLETE/전체 | 실제 불일치 run | 함수별 메커니즘 | 실제 target/Oracle 호출 | 전체 wall(s) |
|---|---:|---:|---:|---:|---:|
| NativeHypothesis | 9/9 | 1 | 1 | 1897/1897 | 9.618 |
| NativeStateful | 0/9 | 0 | 0 | 0/0 | 1.705 |
| E6 | 9/9 | 0 | 0 | 486/486 | 19.166 |
| E7 | 9/9 | 1 | 1 | 1415/1415 | 9.674 |

상태 없는 실제 함수만 선택했으므로 Native Stateful은 NOT_COMPARABLE이다. CrossHair는 source-aware 별도 tier이며 실제 내부 symbolic 호출 수는 UNKNOWN이다. source-level 필요조건으로 제안한 후보는 유효 범위에서 별도 Oracle로 재검증하며, 미분석·timeout을 correctness proof로 해석하지 않는다.

## 구조적 지식 신뢰성과 비용

고정된 E6 source 실행의 실제 유효 영역 실패·반증 로그를 중복 제거해 지식을 만들고 새 개발 입력으로 반증했다. 실행하지 않은 precondition 위반 입력을 clean REFUTATION으로 학습하지 않는다. 실제 같은 구현의 새 입력은 독립 구현 지지로 꾸미지 않았다. 합산 archive 상태는 `{}`이다. 반증된 가설은 삭제하지 않고 자동 전이에서 배제한다. 미확인 가설이나 전부 fallback인 경로를 연구 우위로 인정하지 않는다.

v2 주평가 source archive 후보는 0개다. 사전 고정한 E6 수집의 불일치 실행은 0개이며 Native Hypothesis 1개, E7 native 1개와 구분한다. v1 E6 경로는 seed11의 실제 불일치도 놓쳤다. 결과를 보고 다른 방법의 로그를 주평가로 대체하지 않았다. 후보0개라면 반증 정확도·qualified knowledge 발견 기여를 검증할 수 없다.

결과 관측 전부터 공통 robust Pearson 수학 도메인에 한정한 호환 가능한 cross-project 계약 쌍은1개, 독립 구현의 양성·음성 DEVELOPMENT 지지 계보는0개였다. 따라서 아무 후보도 승격되지 않는다면 이 설계는 qualified knowledge의 발견 유틸리티를 검증할 수 없다는 사전 근거 부족을 명시했다. 같은 함수의 이름을 바꾸거나 final을 개발 검증에 쓰지 않았다.

관측한 source 실행·검사·지식 축적 비용은 55.283초다. capture 실행1.073초와 개발/별도 symbolic/반증/ablation을 포함한 보수적 합계다. 분석자·LLM 추론 비용은 측정하지 않아 UNKNOWN이다. 위 비용과 target-only 비용을 구분한다.

별도 비용 장부: 퇴역 v1 주개발·source 준비 55.885초, 사후 비비교 API ingestion 109.450초, Oracle-only 수정 진단 0.027265초다. v2만 소비한 것처럼 이전 비용을 숨기지 않으며 사후 보충 archive는 주평가·최종 계획에서 제외한다.

duplicate_evaluation_rate는 shrink와 필수 독립 replay를 포함한 전체 실제 평가의 중복이다. 순수 생성 중복률이나 낭비 탐색률로 해석하지 않는다.

E7 archive enabled/empty ablation은 개발3개 문제에서만 시행했고 결과에 따라 정책·문제·seed·가설을 고치지 않았다. 가이드가 실제 사용됐다는 사실과 독립적인 발견 기여는 별도다.

## 별도 비비교 API 기능 QA

Oracle가 교정된 v2에서 이미 기록된 유효 source 실패 로그 두 집합만으로 공개 `KnowledgeArchive.from_failure_log` API를 별도 검증했다. 새 production/Oracle 호출은0이고 실제 생산 모듈·최종 자료를 로드하지 않았다. 각 집합의 기존 관측32개를 ingest하고 같은 구현에서 이미 기록된 반증45개를 적용했다.

| 기존 로그 집합 | 후보 | 기존 모순 상태 | 남은 가설 | 추가 기록 반증 적용 뒤 상태 변화 | qualified |
|---|---:|---:|---:|---|---:|
| Native Hypothesis | 265 | 260 | 5 | 수량 동일 | 0 |
| E7 native | 271 | 268 | 3 | 수량 동일 | 0 |

모순 상태 중 다수는 최초 관측32개에 포함된 clean 기록으로 이미 반증됐으므로 뒤의45개가 새로 전부 반증했다고 주장하지 않는다. 독립 구현의 양성·음성 지지가 아닌 동일 구현의 관측이다. API가 실제 개발 로그에서 후보·모순·미확인 가설을 처리한다는 기능 증거이며, 지식 전이·발견 기여·성능 우위 근거가 아니다. 보충 snapshot은 별도 폴더에 두고 고정된 E6-only 주평가 archive와 최종 retrieval에 넣지 않았다. 주평가 archive SHA-256은 처리 전후 `261bf69237872216fea5387b909555fd67d9ba4211167eb98dd9b3aa3db9e564`로 같다. 보충 offline 처리38.034초는 주 비교 비용에서 제외하고 별도 비용 장부에 남겼다.

비용 해석: source 비용의 capture1.073초는 최초 측정값을 같은 검토 source 준비에 charge한 공유 항이다. v1 장부와 v2 source 비용을 단순 합산할 때 다시 더하지 않는다. 서로 겹치는 phase와 human·LLM UNKNOWN 비용도 구분한다.

## 최종 동결 평가

전체72 records: 실제 비교54개와 Native Stateful18 NOT_COMPARABLE. 비교 가능한54개 중45개는 생산 결함 판정 범위5함수,9개는 사전 계약에서 production-defect-eligible가 아닌 것으로 선언한 population-equivalence 호환성 대조군1함수다. 이 대조군의 불일치는 결함 발견 분자·분모에 넣지 않고 전체 개선 판정을 보류시킨다. 각 방법의64개 이하 계획을 대상 실행 전에 동결하고 최종 피드백0으로 실행했다. 원래 pinned final project/revision/path/function-AST identity에 대한 canonical exclusive claim과 manifest 인접 ledger의 START/COMPLETE 각1회로 재소비를 차단했다. Oracle·suite·case alias·출력 경로를 바꿔도 같은 최종 대상은 재사용할 수 없다.

| 방법 | COMPLETE/전체 | 불일치 run | 함수별 메커니즘 | target/Oracle 호출 | 전체 wall(s) |
|---|---:|---:|---:|---:|---:|
| NativeHypothesis | 18/18 | 0 | 0 | 929/929 | 17.786 |
| NativeStateful | 0/18 | 0 | 0 | 0/0 | 3.197 |
| E6 | 18/18 | 0 | 0 | 939/939 | 35.052 |
| E7 | 18/18 | 0 | 0 | 933/933 | 33.467 |

실제 qualified guidance 후보 0개. 판정 `INCONCLUSIVE`. 비용 감소가 보이더라도 가이드의 실제 재생된 발견 기여·source 포함 비용 기준을 충족하지 못하면 개선이라고 하지 않는다. 발견이 없는 문제에서 최초 발견 시간을 만들어내지 않는다.

동결 manifest SHA-256: `0222c42c605e3b8cf77615b1cc49aec13e5844292a933d8a1e87d804b0990df4`. 최종 입력·출력·구현·원시 기록·archive·ledger는 저장소 밖에 보존한다. Generator에는 predeclared spec·역할·검토된 provenance·개발 archive만 전달했고, 비공개 target IR/정답/구현/최종 labels는 전달하지 않았다.

## 해석 한계

모든 비교 방법에서 최종 불일치0이므로 판정은 INCONCLUSIVE다. 발견 민감도·재현율·최초 발견 시간 우위를 계산하거나 정확성을 증명했다고 하지 않는다. E7의 최종 실행 비용33.467초와 v2 source 비용을 합친 charge는 88.750초이며, 앞의 퇴역 v1·보충 비용은 별도 장부로 남긴다.

최종 비교의 범위는 모든 방법의 최대64개 public-spec 동결 계획에 사전 지식이 주는 추가 가치다. Native Hypothesis도 최종 feedback으로 적응하거나 shrink하지 않는다. 개발 단계의 native find/shrink는 별도 실험이며, native Hypothesis 전체 적응형 PBT 능력에 대한 우월성은 검증하지 않는다. qualified0이라는 사전 증거 부족과 함께 해석한다.

실제 프로젝트 함수의 제한된 수학/문자열 계약 검증이다. 동일 결함의 입력·seed를 별개 메커니즘으로 세지 않는다. E1~E6 소비된 final 자료를 읽거나 재사용하지 않았다. 기본 subprocess는 LOGICAL_ISOLATION_ONLY이고 Docker 검사는 별도 CI의 실제 범위만 인정한다. 대상·Oracle은 신뢰된 host code다.

CPU는10ms process-tree 표본 하한, 메모리는 live-tree 표본 최대이며 true peak가 아니다. timing phase 일부는 겹친다. 원시 자료를 독립 재산출하지 않은 metadata 감사와 실행 자체의 검증도 구별한다. 공개 수치는 [E7_RESULTS.json](E7_RESULTS.json), 선행 계약은 [E7_EVALUATION_CONTRACT.json](E7_EVALUATION_CONTRACT.json)에 있다.
