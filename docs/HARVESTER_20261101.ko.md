# Evidence Harvester 구현·실행 — 2026-11-01

**상태: `HARVESTER_FUNCTIONAL` / 합성 `RECURSIVE_UPDATE_FUNCTIONAL` / 실제 M0·학습·동일 비용 비교 `NOT_EXECUTED` / 외적 효용 `NOT_ESTABLISHED`.** 실제 GitHub 후보를 수집·등록했지만, 발견한 후보를 검증된 신규 결함이나 적격 학습자료로 세지 않는다.

## 계보와 현재 범위

| 계보 | 정체성 | 의미 |
|---|---|---|
| 기존 공개 제품 | `v0.8.0a1`, 기준 커밋 `3ece4df3bd01abe6aae58ef8a01bf4b01515f689` | 기존 제품의 공개 상태 |
| 제품 수정 | [PR #12](https://github.com/hibou04-ops/antemortem-structural-lab/pull/12), `525ca8b262497f5491c390580238de8949b241ef` | 모듈 로딩·별칭 재현·CP1252 수정 개발 |
| 재귀 기능 | [PR #13](https://github.com/hibou04-ops/antemortem-structural-lab/pull/13), `a8ffd07f7c0419e196513df6802a588473976aaa` | paired 관측·selector·세대 저장·새 탐색 재사용 |
| 이번 Harvester | `feat/evidence-harvester-20261101`, 기반은 위 PR #13 HEAD | 외부 후보 공급망 개발; 이 문서를 포함한 draft PR의 HEAD가 개발 정체성이며 CI readback은 PR에 기록 |

기존 연구 실행·동결 보고서와 공개 제품, 이후 개발 PR은 각각 다른 상태다. 이번 작업은 기존 역사 연구 배치를 재실행하거나 공개 제품을 새로 발행하지 않는다. 과거의 `DESIGN_ONLY` 기록과 부정적 결과도 소급 수정하지 않는다.

## 실행 가능한 경로

```text
GitHub 공개 API → 고정된 수집 상한·원본 bytes/ETag 기록
→ 후보 registry·출처/중복 검사 → 검토 대기열
→ 명시적 계약·Oracle·reset·라이선스 검토
→ 실제 OCI 경계의 buggy/fixed 재현 → DEVELOPMENT_ELIGIBLE
→ 동결 개발 계약의 M0 → paired 영수증 → 기존 selector 업데이트
→ append-only 세대 저장 → 재시작 후 다음 새 탐색
```

후보 registry와 정책 학습 journal은 분리한다. 기본 `harvest-run`은 첫 세 단계의 수집·정적 검사·대기열 생성까지만 수행한다. 후보의 제목, PR 병합, 서로 다른 SHA, AST 검사 통과는 독립 Oracle·재현·학습 자격을 대신하지 않는다.

```bash
python -m pip install -e ".[qa,solver]"
python -m tomolab harvest-run --workspace work/harvest
```

기존 GitHub CLI의 정상 인증을 재사용하며 토큰을 출력·저장하지 않는다. `--repositories`로 명시한 공개 저장소 목록을 줄일 수 있지만 최대 8개다. `--max-candidates`, `--max-details`, `--max-qualifications`의 상한은 각각 50·10·4다. `--output`을 지정한다면 기존 결과를 보존하도록 새 파일명을 사용한다.

같은 workspace에서 다시 실행하면 registry의 기존 candidate ID를 읽어 불필요한 상세 조사를 생략한다. 새로운 관측·실패는 이전 기록을 덮어쓰지 않고 추가한다. 이 기능은 무제한 백그라운드 수집이나 자동 학습 스케줄러를 켜지 않는다.

## 수집·출처·검토 계약

- `harvester_github.py`: GitHub 공식 GET endpoint만 사용한다. 요청은 직렬로 수행하며 원본 응답 bytes를 content-addressed cache에 보존한다. ETag·304 재사용에는 endpoint/API version/cache bytes digest 검증이 필요하다. 오류 원문은 보존하되 정상 응답의 cache index를 오류 응답으로 교체하지 않는다. rate limit·인증 실패·대형/잘못된 응답·잘못된 Link는 명시적으로 중단·보류한다.
- 8개 저장소에는 metadata 예산을 먼저 균등 배분한다. metadata 관측 뒤 저장소 순서의 round-robin으로 상세 10개와 그중 심사 대상 4개를 사전 예약한다. 실패한 예약도 소비하며, 원하는 결과를 채우려고 다른 후보를 계속 추가하지 않는다. API로 받은 candidate 행 수를 분모에 남긴다.
- merged PR의 현재 `base.sha`를 수정 전 코드로 단정하지 않는다. 실제 merge commit의 첫 부모를 **제안된 이전 revision**으로 기록한다. buggy 실패·fixed PASS는 실제 재현 단계가 따로 필요하다. 고정 revision의 license/source bytes와 Git blob SHA·SHA256도 검증한다.
- `harvester_registry.py`: canonical JSONL 해시 체인, 협조 writer lock, flush/fsync, 후보 ID 중복 방지, 부분 기록·변조 거절을 제공한다. 원자적 분산 CAS나 적대적 호스트 보호라고 주장하지 않는다.
- `harvester_review.py`: 단계별로 `DISCOVERED → PROVENANCE_VERIFIED → CONTRACT_REVIEWED → ORACLE_REVIEWED → REPRODUCED → DEVELOPMENT_ELIGIBLE`을 구분한다. 부족한 자료는 `HOLD_REVIEW`, `HOLD_EXECUTION`, `UNKNOWN`, 또는 근거가 있는 `REJECTED`로 남긴다. 검토 ID와 해시는 검토 대상·기록의 정체성을 묶으며 의미적 독립성 자체를 증명하지 않는다.

소비 차단에는 공개 E8/R4 CORR/ONLINE/HISTORICAL 기록과 역사 source capsule에서 도출한 **146개 fingerprint token**을 사용한다. 공개 snapshot의 registry digest는 `6ad4c924aa0c0142cf09d49b4e71b026d495080237a6ff4614bf2632ce1a47e5`다. 범위는 `KNOWN_PUBLIC_REGISTRIES_ONLY_NOT_A_GLOBAL_E1_E9_CENSUS`이며 비공개 final 입력을 읽지 않는다. 알려진 registry와 불일치는 전역 미소비·독립성이 확인됐다는 뜻이 아니다.

## 실제 GitHub batch에서 관측한 결과

관측 전에 수집 계약과 코드 정체성을 고정한 첫 batch는 공개 저장소 8개에서 **후보 metadata 50개**, 상세 예약 10개, 심층 검토 대상 4개를 처리했다. 실제 GitHub API 요청은 56회였고 수집 실행 wall time은 약 32.37초였다. 이 숫자는 엔지니어링 자원과 처리량이며 통계적 검정력이나 고유 결함 발견 수가 아니다.

| 판정 시점 | HOLD_REVIEW | UNKNOWN | REJECTED | DEVELOPMENT_ELIGIBLE |
|---|---:|---:|---:|---:|
| 최초 실행 원문 | 46 | 4 | 0 | 0 |
| 동일 원자료의 수정 후 정적 재평가 | 50 | 0 | 0 | 0 |

최초 검토기에는 first-parent bool 플래그와 부모 SHA의 역할을 혼동한 통합 오류가 있었다. 두 필드를 분리해 수정한 뒤 **동일한 4후보**를 offline으로 다시 평가했다. 최초 결과·원시 API bytes·실패 이력은 보존했다. 재평가는 API 호출 0회·새 후보 0개이며, 새로운 네 개의 독립 사례를 얻은 것으로 세지 않는다. 심사 대상은 4개이고 정적 판정은 최초 4회와 재계산 4회를 구분해 기록한다.

현재 50개 모두 대기열에 있다. 그중 46개는 심층 검토 예산 대상으로 예약되지 않았고, 4개는 출처를 확인했지만 계약·독립 Oracle·reset·라이선스의 책임 있는 검토가 필요하다. `HOLD_REVIEW`는 결함이 없다는 음의 실험 결과가 아니다.

별도 append로 보완한 50후보 profile은 이미 받은 원자료만 사용했다. 실제 `.py` source blob으로 언어를 확인한 후보는 Python 3개이고 나머지 47개는 `UNKNOWN`이다. 입력 타입·기전·Oracle는 검토 전 `UNKNOWN`으로 남겼다. 이 profile 보완은 새 API 호출·새 심층 심사 대상 각각 0개다.

**실제 개발 적격 사례 0개, 실제 연구 Target/Oracle 호출 각각 0회다.** 현재 Docker daemon을 사용할 수 없어 실제 OCI 실행 경계도 검증하지 못했다. 따라서 실제 buggy/fixed 재현, M0, 실제 경험의 selector 갱신, 동일 총비용 A/C/F/L 비교와 미관측 평가는 실행하지 않았다.

## 외부 코드 실행 경계와 후속 명령

`harvester_execution.py`는 기존 검토된 OCI launcher를 재사용하고, 호스트에서는 외부 source bytes를 준비·정적 검사하고 결과 JSON을 검증한다. upstream 코드를 호스트에서 import·실행하는 fallback은 없다. 구현은 네트워크 차단, 비특권 UID, 읽기 전용 code/input, 지정 출력 mount, capability·시간·CPU·메모리·프로세스 제한과 실행 후 정리를 요구한다. 실제 daemon·image·runtime inspection이 충족되지 않으면 `HOLD_EXECUTION`이다. 단위 fixture의 flags 검증을 실제 컨테이너 격리 성공으로 세지 않는다.

다음은 **검토된 자료 파일을 미리 확보한 경우의 연결 지점**이다. 현재 수집한 50후보의 검토·재현이 완료됐다는 명령 예제가 아니다.

```bash
python -m tomolab harvest-review --workspace work/harvest --candidate-id CANDIDATE_ID --review reviewed-development.json --execution-receipt reviewed-reproduction.json --allow-reviewed-development
python -m tomolab harvest-m0 --workspace work/harvest --execution-contract frozen-m0-contract.json --allow-external-execution
python -m tomolab harvest-learn --workspace work/harvest --candidate-ids ID1 ID2 ID3 ID4 --manifest development-manifest.json --receipts paired-receipts.json --generation-store work/harvest/generations.jsonl --generation-id G1 --allow-reviewed-development
```

실제 M0는 새 독립 개발 4계보·2프로젝트·2기전군, 검토된 Oracle/reset, 동결 ALL Mold 적용 범위, 정확한 입력 계약과 source identity가 필요하다. 첫 M0의 Target·Oracle 각각 최대 1,152회와 고정된 seed·호출·시간·미검출·재시도 계약을 결과 관측 전에 묶는다. 양의 국소 신호와 계측 완결성 기준을 충족하지 않으면 실제 후속 학습을 보류한다.

실제 학습 경로는 완전한 기존 M0 영수증·manifest·적격 candidate identity를 대조한 후 기존 `recursive_api.update_generation`을 사용한다. evaluator·Oracle·input contract·비교 허용오차를 업데이트하지 않는다. final split을 이름만 development로 바꾸어 사용할 수 없으며, 선택에 사용한 검증 자료도 미관측 평가 자료로 다시 세지 않는다.

## 합성 공급망 종단 검증

```bash
python -m tomolab harvest-demo --workspace work/harvest-authored --allow-local-execution
```

workspace는 새 디렉터리여야 한다. 이 명령의 HTTP 응답은 작성된 in-process fixture이며 실제 GitHub 후보가 아니다. 출처·cache·registry·대기열은 실제 제품 경로를 사용한다. 이어서 **별도 fixture authority**가 기존 `recursive_demo`의 정확한 module/function 및 source SHA whitelist를 검사한 뒤에만 직접 작성한 함수를 실행한다. 외부에서 가져온 source text는 호스트에서 실행하지 않는다. 이 authority는 실제 적격성 판정을 약화하지 않는다.

실행 영수증 기준 결과:

- 작성된 저장소 2개·후보 4개 등록 및 대기열 4개. 재실행은 신규 0·중복 4개이며 검증된 304 재사용 4회다.
- 작성 transport 요청 32회, 실제 네트워크 요청 0회다.
- candidate metadata digest → 구현 source SHA → source lineage → 실제 paired receipt digest → 기존 공유 `_append_update` → 세대 journal이 연결된다.
- 개발 paired/운반의 실제 비용은 Target 28회·Oracle 28회·reset 24회다. 세대의 누적 개발 Target/Oracle 비용은 G0 0/0, G1 14/14, G2 28/28이다. 새 탐색과 고정 슬롯 재실행 비용은 별도 영수증으로 보존한다.
- 별도 새 프로세스 3개에서 실제 실행 후보가 G0 `[-1,-2]`, G1 `[1,1]`, G2 `[-1,-2]`로 바뀌고, 저장된 정책을 적용한 fresh Hypothesis 탐색의 learned 변경 실행은 0/1/0이다.
- 이 workspace의 실제자료 적격 수는 계속 0이다. synthetic 경험을 실제 `learn_from_harvest`로 보내는 시도는 거부한다.

G2의 common 복귀는 반증에 따른 기권 기능을 확인한 것이며 양의 성능 향상이 아니다. 가장 강한 반론은 작성 fixture가 행동 전환을 유도하도록 구성됐다는 점이다. 따라서 위 결과로 실제 새 결함의 탐지 이득·무회귀·일반화·지속적 자기개선을 주장하지 않는다.

## 검증 상태·미해결 판단

새 source client·review/execution·registry·learning·공급망 통합 검사는 `tests/test_harvester_*.py`에 있다. GitHub client의 로컬 fixture 20개와 공급망 통합 6개가 개별 실행에서 통과했고, **최종 로컬 Windows/Python 3.12.10 한정 통합 회귀는 308 PASS·symlink 검사 1 SKIP(수집 309개)**다. wheel/sdist 새 설치 2개에서 제품 검사 36개가 통과했고, 설치된 Harvester에서도 작성 후보 4개·재실행 중복 4개·새 프로세스 3개·새 탐색 변경 0/1/0·실제 적격 수 0을 확인했다. 역사 226파일·60회귀 보존도 통과했다. 이 버전 관리 문서는 push 전 로컬 검증을 기록한다. 원격 CI와 최종 HEAD·draft PR 및 비공개 SYNC 완료 판정은 같은 PR 본문의 후속 readback 기록을 따른다. 2026-11-01 05:32 KST 공개 readback에서도 기존 제품 버전은 `0.8.0a1`로 확인했으며 이번 개발을 새로 발행하지 않았다. [검증 집계](HARVESTER_VERIFICATION_20261101.json)는 공개 가능한 숫자와 상태만 포함한다.

확인된 사실은 실제 후보 발견·중복 방지·대기열 등록과 작성 fixture의 재귀 업데이트다. 책임 있는 Oracle/reset 검토, 실제 컨테이너 경계, 적격 개발자료와 독립 평가자료가 부족하다. 지금 가장 큰 병목은 이 검토·실행 자격이며, 표현력·selector·추가 비용 중 무엇이 실제 성능을 제한하는지는 아직 `UNKNOWN`이다. 같은 총비용의 정책 우월성은 별도 실험 전 `NOT_ESTABLISHED`로 유지한다.

공개 GitHub에는 코드·작성 fixture·검토 가능한 집계만 남긴다. 원시 수집 cache·실행 영수증·개인 경로·비공개 Drive 정본 및 ID는 로컬/비공개 증거 패킷에 보존한다. Drive의 최종 증분 COMMITTED 여부는 manifest 최후 게시와 원본 bytes·detached receipt readback을 마친 뒤 별도로 확정한다. 이번 변경의 main 병합·태그·Release·PyPI 게시 권한은 없다.
