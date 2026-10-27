# E5 공개 평가 기록

최종 판정은 **NO_IMPROVEMENT**다. 제품 기능 통합과 외적 일반화 성능은 별도로 판단한다. 외부 실제 프로젝트 평가는 **NOT_EXECUTED**다.

## 고정 조건과 증거

- 기준 릴리스: `v0.4.0a1`, commit `514a7ac6a10995b5ec1f8b706e4afe0bb8570fb2`.
- [사전 계약](E5_EVALUATION_CONTRACT.json) SHA-256: `290391f054213f7205c1121ceb4a6771d0c28b075d6b182ee0ff7738cc4368a1`.
- 제품 40개 파일·source mold 27개·계약·public fixture·새 private final suite 동결 SHA-256: `3e143df698f7fcb2fde5dedfbce9622ba7fea6970c1364e38d18601059e71d8b`.
- 최종 5개 mutation family와 기존 프로젝트 정상 control 2개, 3 seeds, 3 methods의 전체 63 runs. 실제 지원 불가인 E4 typed domains는 `NOT_COMPARABLE`이다.
- 최종 결과의 Generator feedback은 0이다. 독점 생성한 ledger로 한 차례만 실행했고, 최종 source와 입력·정답·raw logs·molds는 저장소 밖에 보존했다.

## 공개 개발용 비교

| 방법 | 완료/비교가능 | 독립 결함 계열 | control 오탐 | 실제 Oracle 호출 | 총 wall(s) |
|---|---:|---:|---:|---:|---:|
| CrossHair | 7 | 5 | 0 | UNKNOWN (concrete replay 7) | 5.755 |
| E4 | 6 | 1 | 0 | 275 | 10.583 |
| E5 | 21 | 5 | 0 | 1524 | 42.607 |
| Hypothesis | 21 | 5 | 0 | 919 | 18.376 |

개발용 판정은 `NO_IMPROVEMENT`다. native Hypothesis와 E5 모두 5개 독립 결함 계열을 찾았다. 다수의 실패 입력을 독립 결함 증가로 해석하지 않는다. CrossHair는 실제 CLI로 실행했으며 source-aware tier다. 내부 symbolic 호출 수는 UNKNOWN이고, 별도의 concrete replay만 계측했다.

## 한 차례의 frozen final 비교

| 방법 | 완료/비교가능 | 독립 결함 계열 | control 오탐 | 실제 Oracle 호출 | 총 wall(s) |
|---|---:|---:|---:|---:|---:|
| E4-frozen | 6 | 1 | 0 | 384 | 5.281 |
| E5-frozen | 21 | 5 | 0 | 1344 | 30.815 |
| Hypothesis-strategy-plan | 21 | 5 | 0 | 1312 | 19.876 |

- Hypothesis-strategy-plan: 15 paired runs, 5 shared families, wall 중앙값 비율 1.540, 첫 발견 Oracle 호출 비율 1.000.
- E4-frozen: 3 paired runs, 1 shared families, wall 중앙값 비율 3.636, 첫 발견 Oracle 호출 비율 5.000.

비율은 E5/각 baseline이다. 총 wall에는 시작·import·공개 IR 분석·후보 생성·solver·Oracle 평가를 포함한다. E4는 지원하는 두 정수 입력 영역만 비교한다. 최종 비교는 feedback과 shrinking 없이 고정 계획을 평가했으므로, native Hypothesis의 개발용 적응 탐색과 별도 track이다.

## 독립 개발 감사

- 별도의 440개 평가 입력에서 source 후보 가설 5개 중 2개가 반증됐다. 이는 bounded membership 가설이며 원인 법칙이나 높은 정밀도 입증이 아니다. 후보가 없는 계열도 그대로 포함했다.
- 정적 전이 선언 검사 28/28 통과: 허용 기대 2개, 거절 기대 26개다. 실제 clean 개발 입력의 반증 5건에서 해당 constraint 제거가 모두 일치했다. 반복 결함의 실제 발생 여부는 `UNKNOWN`으로 유지했다.
- 축소 기능의 별도 공개 개발 확인에서 `dev-add-order` seed 17의 정수 L1 크기는 E5 13→1, native Hypothesis 1→1, E4 반환 반례는 12→3이었다. E4의 별도 native search 축소 status는 `NOT_REDUCED_WITHIN_SEARCH_BUDGET`였다. 전역 최소성은 주장하지 않는다. 이 추가 확인은 성능 비교에 합치지 않았다.
- CPU는 process identity마다 마지막 표본을 합한 하한이다. RSS는 10ms 간격의 살아 있는 process tree 표본 최댓값이며 실제 OS peak가 아니다. 수치 집계는 [공개 JSON](E5_RESULTS.json)에 있다.

## 해석 범위

이 suite는 새로 작성한 작은 mutation 5계열과 사용자 소유 프로젝트의 정상 함수 2개에 한정된다. 기존 비공개 E1~E4 holdout은 읽거나 새 blind 평가로 재사용하지 않았다. 최종 source는 Generator에서 숨겼지만, 외부 실제 프로젝트에 대한 독립 일반화 실험은 아니다.

로컬 Generator 분리는 `LOGICAL_ONLY`다. 실제 Docker 접근제어 CI 증거는 별도로 보고한다. 제품의 callback 시간 제한은 협조적 검사이며 임의 함수 강제 종료의 보장이 아니다. 평가기는 전체 worker wall cap을 별도로 적용한다.

최종 실행 전 evaluator의 JSON 동치·CPU 중복 방지·counterevidence 해석·전체 suite 실행 강제를 정정했다. 원본 개발 보고와 정정 이유를 private provenance에 보존했으며 성능 손실은 제거하지 않았다. 최종 결과를 본 뒤 제품·계약·대상·몰드·기준을 조정하거나 같은 final suite를 다시 실행하지 않았다.
