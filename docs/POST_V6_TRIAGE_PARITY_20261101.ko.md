# v6 이후: 전수 사전선별·동일 호출 상한·트랙 분리

이 문서는 PR #15의 증분 개발 계약이다. 공개 제품은 v0.8.0a1이며 미병합 개발 기능, 자료 자격, 실제 탐색 효용은 서로 다른 상태다. push 이후 최종 HEAD·CI·OCI 실행·동기화 결과는 PR 본문의 post-commit 원문 검증을 따른다. 합성 기능 검증으로 실제 성능이나 일반화를 승격하지 않는다.

## 기존 46건의 전수 정적 사전선별

원래 50 metadata/10 상세/4 심층 예약/8 저장소의 raw bytes·registry·최초 결과를 보존한다. 이미 심층 검토한4건을 제외한 정확46개 후보 ID에 새 읽기 계약을 먼저 고정했다. revision이 원래 없던40건은 같은 PR의 실제 merge commit/first parent를 새 sidecar에 기록하고 원래 envelope에 소급해서 넣지 않는다.

별도 공식 정적 GET200회(상한552), 원래 cache hit12회로46건의 전체 changed-file 목록을 확보했다. 사전 선택된 runtime Python 경로는 후보당 최대4개이며 추가 경로·누락/파싱 실패를 성공으로 채우지 않는다. 소스는 bytes/hash/AST로만 처리하고 import/exec/pytest/OCI/Target/Oracle 호출은0이다.

최초 선별 결과는 문서·비코드 제외11, 계약·상태 보류31, 정적 근거 부족 보류4, 자동 typed sequence_int 후보0·text 후보0이다. 이는 이 제한된 자동 규칙에서 후보를 확인하지 못했다는 뜻이며 실제 결함0이나 주석 없는 Python이 지원 불가라는 뜻이 아니다. 네 근거 부족 건을 UNKNOWN0을 맞추기 위해 제거하지 않았다. 추가 GET0인 offline-r2에서는 이미 보존한 pinned-ref Contents/Git blob 원문으로4개 source를 복구했다. PR changed-file row SHA와 merge-ref Contents SHA가 달랐던 이유는 UNKNOWN이며, 원문과 각 SHA를 따로 보존했다. 최초 결과는 불변이고 현재 결과는 제외11·계약/상태 보류34·근거 부족 보류1·두 트랙 자동 후보0이다. 변경된 docstring을 getattr/vars/inspect.getdoc 등으로 읽는 명시적 runtime introspection도 HOLD한다.

`harvest-triage`는 완전한 파일 목록·정확한 revision/source/Git blob 해시가 담긴 data-only manifest를 읽는다. docstring/comment 제거 AST와 annotation 제거 AST를 따로 기록한다. annotation 지우기만으로 eager evaluation·decorator·introspection의 runtime 영향이 없다고 단정하지 않는다. self/cls, I/O, global/closure, async/generator, 미해결 dependency/입력형은 보수적으로 HOLD한다. CANDIDATE는 Oracle·reset·라이선스·재현을 검토하기 전의 가능성이며 실행 권한이 아니다.

```bash
python -m tomolab harvest-triage --manifest static-records.json --output new-triage-result.json
```

## 동일 호출 상한의 의미

같은 Hard Call Meter 구현을 arm별 독립 인스턴스로 사용한다. A/B/C/D 또는 고정 G0/G1/G2의 예산을 서로 빼앗는 한 개 누적 counter로 비교하지 않는다. Target/Oracle 진입 직전에 각24/48회 같은 상한을 적용하고 native·confirm·shrink·추가 paired 평가를 모두 해당 arm의 ledger에 포함한다. fresh reset의 시도·성공·실패와 phase별 실제 사용량·unused를 따로 기록한다. Source 수집/학습/모델 선택 준비 비용은 평가 비용과 별도로 명시하며0으로 숨기지 않는다.

조기 실패 발견이나 예산 부족 시 실제 unused를 남긴다. 의미 없는 호출로 used 수치를 같게 만들지 않는다. 동일 상한, 동일 seed, prefix 보존이나 carryover는 무회귀·동일 탐색 경로·동일 성능을 보장하지 않는다. Oracle/reset 오류와 비결정적 결과는 UNKNOWN/HOLD이며 미실행 budget exhaustion과 구분한다.

```bash
python -m tomolab structural-probe --workspace new-equal-cost-probe --budget 24 --equal-cost --allow-local-execution
```

이 probe는 노출된 작성 fixture의 기능 검증이다. 새 equal-cost 기준선은 실제 C 엔진이며 M1~M4는 별도의 COMMON_PRIOR_RELATIONAL arm으로, 학습된 D라고 이름을 바꾸지 않는다. 실제 Hypothesis `@given` 탐색을 사용한다. 기존 기본 probe의 A/22 대 relational24 결과는 역사로 보존한다. 국소 anchor 쌍과 C 전체 탐색의 인과 비교도 구분한다. 이전185UNKNOWN은 새 표본이 아니다.

## TRACK_SEQ_INT / TRACK_TEXT

| 필드 | TRACK_SEQ_INT | TRACK_TEXT |
|---|---|---|
| 역할 | 기존 M0의 주 입력 트랙 | 별도 대안 트랙 |
| 기존 자격 | 원래46의 자동 후보0, 재현 적격0 | v6의 keon/algorithms#2772 한 계보 |
| 기존 재현 | 미실행 | 공개 a#a의 buggy aa / Oracle·fixed a#a, 각각3회 |
| v6 실제 비용 |0| Target6·Oracle6·fresh reset12·UNKNOWN0 |
| 이번 text 재실행 | 해당 없음 |0, 기존 영수증 참조 |
| 실제 전이 효용·OOS | NOT_ESTABLISHED | NOT_ESTABLISHED |

새 sequence_int 배치는 첫46의 자격 부족 확인 후 별도 사전등록한다. query·분모·detail 순서·정적 source 범위·부분계약 근거와 repo별 first2 예약 규칙을 Oracle/runtime 결과 전에 고정한다. Python annotation이 없어도 원래 명세·구체적 source line·signature·dependency·반환·precondition이 실제 bounded list[int] 부분영역을 지지하면 별도 static support를 검토할 수 있다. 다중 인자를 몰래 list에 넣거나 text를 encoding하거나 None-return을 wrapper로 바꾸지 않는다. 모든 정적 탈락·미예약·중복·UNKNOWN을 보존하고 예약 후 유리한 결과로 교체하지 않는다.

실제 공개 sequence_int 재현은 정확 source·독립 명세 Oracle·reset·라이선스 검토, 같은 frozen HEAD/image의 실제 OCI control PASS 후 이번 지시에서 승인된 정확 두 예약 함수의 PR CI 또는 명시 dispatch에서 수행한다. 후보별 buggy3+fixed3, 각각 별도 Oracle와 fresh container를 사용하며 이번 정확2후보 Target12·Oracle12·reset24의 별도 qualification 상한이다. 이는 full M0의 호출 예산이 아니다. 첫 미해결 호출/정리 실패에서 중단하고 실제 시도·진입·UNKNOWN·비용을 남긴다. fixed patch 복사나 회귀 정답 상수 표를 Oracle로 삼지 않는다.

현재 real M0는 HOLD다. 같은 동결 ALL Mold/입력 계약에 적합한 새 독립 sequence_int4계보·2프로젝트·2기전군, 독립 Oracle/reset·실제 실행 자격과 기존 사전등록이 필요하다. 기존 first M0 Target/Oracle 각1152 상한을 완화하지 않는다. 실제 M0·동일 총비용 추가 발견/최초 확인 절감이 확인되기 전 utility/OOS/누적 세대 성능은 NOT_ESTABLISHED다.

## 실행·증거 경계

Windows 로컬 daemon이 없으면 계속 HOLD이며 외부 코드를 호스트에서 실행하는 fallback은 없다. Linux CI에서는 network none, UID/GID65534, CapEff0/no-new-privileges, read-only root/app, 실제 cgroup512MiB/64PID/1CPU, 정확한 container ID의 inspection과 종료 후 정리를 검증한다. controller/CLI의 협조적 상한을 전역 OS 강제 종료 보장으로 부르지 않는다.

새 네 환경 CI는 기존439회귀와 신규 선별/등가 상한 검사를 포함한다. mock/합성·설치 검증·실제 OCI를 각각 보고한다. main merge·태그·Release·PyPI·유료 Jev 호출은 금지하며 기본 Jev off·과거 Mold/Oracle/최종 평가 경계를 보존한다. 비공개 정본·Drive 식별자·원시 cache·개인 경로는 공개하지 않는다. v6와 과거 snapshot 보존, 같은13문서ID의 증분·manifest-last·원본 readback·양쪽 detached receipt를 따르며 Drive CAS/배타 잠금은 주장하지 않는다.


## Post-v6 R2 재개 경계

신규 배치는 metadata18·상세10·심층예약2(radix sort / decimal plus-one), GET58/92에서 마감됐다. 미충족 슬롯 보충·재시도·사후 교체는 없다. 두 예약은 모두 keon/algorithms 소속이며 radix는 원소0..99, decimal은 자리수0..9의 서로 다른 비어 있지 않은 길이1..8 계약이다. 재현 성공으로 기존 M0의 공통 계약·4독립계보·2프로젝트 요건을 충족했다고 판정하지 않는다.

radix 독립 명세는 완전한 정수값의 빈도를 세어 오름차순 열거하며 자리수별 정렬·종료 조건을 복사하지 않는다. decimal 명세는 전체 십진값에1을 더한 뒤 원래 최소 자릿수 폭을 유지한다. 선행0은 제외하지 않으며 이 폭 보존은 원래 함수 분기와 형제 구현이 지지하는 bounded source-inferred 계약이다. 전체 자연어 의미 충실성의 증명은 아니다.

재진입 방어는 reset·Target·Oracle에서 같은 활성 계량기를 다시 호출하기 전에 거부한다. callback이 예외를 삼켜도 미해결 사건을 남겨 PASS로 복구하지 않으며 외부 pair는 EXECUTION_ERROR 또는 reset 실패로 남는다. 실제 진입 전 counter 증가·중복 observer 진입 거부·finally guard 해제를 검증한다.

추가 GitHub GET 금지에 따라 이번 sequence CI는 이미 보존한 MIT 공개 source·license·test patch를 docs/sequence-v7-source의 content-addressed .txt 데이터로만 읽는다. 원래 revision·Git blob·SHA256·review digest를 재검증하고 캐시 누락/변조 시 네트워크 대체 없이 HOLD한다. 호스트에서 원문을 import/exec/pytest하지 않는다. 실제 함수 실행은 검사된 새 Linux OCI에서만 수행한다. CI summary 검증과 원본 artifact 다운로드 검증은 구분하며, 이번 외부 readback 방식은 웹 UI다.
