# E9-R1 실제 과거 결함 비교

**C·D의 fallback 교란은 제거했다. 실제 구현 전이에서 D의 추가 가치는 관측되지 않았으며, 적격 LOMO에서는 학습 규칙을 실제 사용한 D의 음의 전이가 관측됐다.** 연구 결과에 맞춘 코드·규칙·예산 조정과 배치 재실행은 0회다. C뿐 아니라 A/B도 함께 비교해야 한다. 작은 역사 corpus에서 얻은 결과이며 보편적 우월성·현재 배포판의 신규 결함·블라인드 일반화 증거가 아니다.

| 상태 | 확인 결과 |
|---|---|
| CONTROL_PARITY | 빈 Mold·타입 불일치·전제조건 불충족·UNKNOWN·거절·중복·실행 불가 제안에서 C와 D의 공통 경로 동치 검사 통과 |
| FALLBACK_RNG_AND_BUDGET_PARITY | 동일 후보·피드백·공통 RNG 상태·Target/Oracle 호출·확인·축소 예산. 손상 Mold는 오류이며 fallback으로 숨기지 않음 |
| REAL_PROJECT_CORPUS | 실제 프로젝트 3개, Source 결함 2개, 평가 결함 6개, 수정본 대조 6개 |
| HISTORICAL_DEFECT_PROVENANCE | 평가 함수 계보 6개·메커니즘군 5개·입력 타입 3개. 고정 원문·수정 이력·독립 계약 Oracle·라이선스 연결 |
| ORACLE_AND_ADAPTER_VALIDATION | 실제 OCI에서 14사례 적격성 통과: Source/Target 실패 8개·수정본 PASS 6개, 원본과 adapter 의미 일치 |
| IMPLEMENTATION_TRANSFER | 288 run. 모든 방법이 각 예산 15/18 탐지, 고유 과거 결함 5/6개. bytes2human은 전 방법 미검출 |
| LOMO_APPLICABILITY | EMPTY Source를 실제 제외하고 정수열 타입 접점이 남는 96 run만 실행. text/float는 routing 대조 |
| LOMO_RULE_USE | D가 학습 제안으로 공통 후보를 바꿔 실제 실행: 예산24에서 28회, 48에서 84회. 규칙 부재로 설명할 수 없음 |
| ADDED_VALUE_OVER_C | 구현 전이의 탐지·최초 확인 호출 이득 없음. LOMO에서 D의 추가 가치 없음 |
| NEGATIVE_TRANSFER | LOMO의 C-only 탐지: 예산24에서 4 run, 예산48에서 6 run. D-only 0 |
| END_TO_END_COST | Source 준비 2.289초, 비교 254.729초, 컨테이너 전체 경계 258.511초. 시간은 기술통계이며 종합 효율 성공을 선언하지 않음 |
| PACKAGE_AND_CLI | 로컬 전체989 검사, 6개 OS/Python CI 조합과 정상 index 설치·online wheel18검사·실제 역사 사례 wheel 경로 통과 |
| PR_AND_PUBLICATION_STATUS | PR #10 draft, allow_release=false. main·PR #8·태그·PyPI·Drive 보존. 새 배포 없음 |

## 동결과 실행

구현 HEAD는 `6cbe985e77c482cda6413250a9a270924e648c0d`, tree는 `3cc8caecbaee053045c7e2f8b01432815bcdf718`다. [첫 PR CI](https://github.com/hibou04-ops/antemortem-structural-lab/actions/runs/41214559998)는 14개 job 성공, study·prerelease 2개 skip이다. PR merge ref의 tree도 동일했다.

[단일 수동 연구 실행](https://github.com/hibou04-ops/antemortem-structural-lab/actions/runs/41215382397)의 `historical-study`가 384/384 run을 완료했다. Source-only preflight 후 사전 결정한 예산24·48, seed4201/4211/4229, 확인3회, 축소6회 상한, run당30초를 유지했다. Source는 seed1811·예산48로 수집했다. 알고리즘226파일·의존성·어댑터·Oracle·Source 절차·초기 Mold·routing·성공 기준을 Target 비교 전에 fsync하고, 종료 후 다시 검증했다.

- 등록 digest: `97fea8dde2994cb0e305dfb23038fe318c41c0022d5056824becc895fe175053`
- 알고리즘 inventory digest: `71972209bd2302093a90baa63b0c69addb7c88a458c52166e0954d2a5ddfaa4c`
- 환경: CPython3.12.16 / Hypothesis6.170.11. 일반 matrix CI의 최신 의존성/patch 환경과 동일하다고 주장하지 않는다.
- Source: 실제 Target/Oracle 각88회, ALL 3규칙·3,788바이트, EMPTY 제외 2규칙·2,449바이트. 생략 규칙0. 기존 선택 정책과 10KiB 상한 유지.
- [동결 기록](HISTORICAL_PROFILE.json), [384 run 전체 계측·미검출·비용](HISTORICAL_RESULTS.json). 기존 E9의 ONLINE_PROFILE·ONLINE_RESULTS·360회 결과는 원 revision에 보존한다.

## 실제 발견·미검출과 비용

아래 탐지는 buggy Target의 seed run이다. 수정본 대조 run은 분모에 넣지 않았고 호출·시간에는 포함했다. I는 방법당36 run(18 Target+18 대조), LOMO는 방법당12 run(6 Target+6 대조)이다.

| 평가·예산 | A | B | C | D | C / D 외부 executor wall초 |
|---|---:|---:|---:|---:|---:|
| 구현 전이24 | 15/18 | 15/18 | 15/18 | 15/18 | 21.128 / 21.237 |
| 구현 전이48 | 15/18 | 15/18 | 15/18 | 15/18 | 26.850 / 27.025 |
| EMPTY LOMO24 | 6/6 | 6/6 | 4/6 | 0/6 | 6.688 / 6.584 |
| EMPTY LOMO48 | 6/6 | 6/6 | 6/6 | 0/6 | 8.881 / 8.910 |

구현 전이에서 모든 방법은 windowed·accumulate·split_iter·split_punct_ws·iter_splitlines의 알려진 결함 5개와 메커니즘군4개를 재현했다. bytes2human 반올림 경계는 적격성 재현에 성공했지만 생성된 탐색으로는 전 방법·전 seed·두 예산에서 발견하지 못했다. 알고 있는 재현 입력으로 이 미검출을 채우지 않았다.

C/D 공동 탐지30쌍의 최초 확인 호출 수는 모두 같았다. 더 빠른 최초 확인 시간과 더 느린 시간은 함께 보존하며 통계적 유의성·종합 효율 성공으로 해석하지 않는다. LOMO에서 D는 탐지0이므로 성공 run만의 중앙값이나 절약된 확인 호출로 효율을 주장할 수 없다. Source replay를 쓰는 C도 작은 예산에서 A/B보다 2 run을 놓쳤다.

| 방법 | 전체 run | 실제 Target 호출 | 실제 Oracle 호출 | 외부 executor wall초 |
|---|---:|---:|---:|---:|
| A | 96 | 2,869 | 2,869 | 63.666 |
| B | 96 | 2,870 | 2,870 | 63.474 |
| C | 96 | 2,864 | 2,864 | 63.547 |
| D | 96 | 2,834 | 2,834 | 63.755 |

비교의 실제 Target/Oracle는 각각11,437회다. Source 각88회를 합치면 각11,525회이며, 사전 적격성·예산 probe·설치 기능검사는 별도다. 전 run COMPLETE, Oracle 오류·실행 오류·UNKNOWN·수정본 불일치0이다. 입력 중복·거절·replay·축소·생성·Mold 조회·직렬화·worker 시작/import/IPC/종료 비용은 각 run JSON에 남긴다. D의 전체 적용 wall은 C보다 약0.208초 증가했다. 탐지 손실을 수반한 호출 감소는 개선이 아니다.

Source 자동 수집1.633초, ALL 학습0.609초, LOMO 학습0.014초이며 준비 전체2.289초다. 비교 외부벽시간254.729초에는 run별 합 이외의 결과 flush가 포함된다. 공개 결과 파일을 쓰기 직전 측정은258.061초, phase 완료 stdout은258.133초, Docker host launcher의 startup/종료 포함 경계는258.511초다. 중첩 시간을 더하지 않는다. 이미지 build·암호화·원격 전송은 이 수치 밖이며 CI 단계 로그에 남긴다. 수동 조사·계약 검토 노동시간은 미계측이다.

수정본의 실제 5,376개 관측은 모두 PASS였다. 실패한 고유 입력 중 같은 입력이 수정본에서 실제 PASS인 106개와 수정본에서 같은 입력이 관측되지 않은 21개를 구분했다. 후자는 공개 계약·독립 참조 계산·알려진 수정 기전으로 검토했으며, 기록을 메우기 위한 수정본 추가 실행은 하지 않았다. 확정 입력685건·실패 관측2,517개를 고유 결함685개로 부풀리지 않는다.

## 규칙 사용과 음의 전이

전체 D96 run에서 lookup670, 전제조건 match430, 유효 제안280, 공통 후보와 다른 제안240, 실제 유효 규칙 실행280, 실제 다른 후보 실행240이었다. 적용 불가240·invalid36·duplicate114·unexecutable0을 구별한다. `match=valid+invalid+duplicate`, `lookup=match+not_applicable`를 기록으로 확인한다. 무규칙 fallback 동치와 유효하지만 도움이 되지 않는 규칙은 다른 상태다.

EMPTY LOMO의 windowed/seed4201/예산24에서는 C/D의 동일 공통 상태와 base digest에서 첫 학습 append가 공통 delete 후보를 대체했다. 공통 후보 digest는 실제 C의 실패 입력과 같았다. C는 길이0에서 실패했고 D의 길이2 후보는 정상 관측이었다. 이는 한 슬롯에서 Source 학습 편집이 Target 실패 후보를 정상 후보로 바꾼 실제 경로다. 전체 미검출의 유일한 원인으로 확대하지 않는다. 두 Source 중 남은 falsey-validator Source의 실패 구조를 빈 iterable 기전에 적용하는 경험적 정책이 이 범위에서 유용하지 않았다는 제한된 근거다.

따라서 D는 실험 옵션으로 유지한다. C도 이번 LOMO의 작은 예산에서 A/B보다 손실이 있으므로 C의 보편적 우위를 선언하지 않는다. 데이터·가중치·규칙 수를 사후 조정해 성공 결과를 만들지 않았다.

## 실행 경계·출처·감사 한계

외부 고정 코드 실행은 network=none, UID/GID65534, capability0, no-new-privileges, root/app/boundary 읽기전용, 전용 output 쓰기, noexec/nosuid tmpfs, 512MiB·CPU1·PID64의 실제 Docker inspect와 kernel/file probe를 거쳤다. Source 준비와 Target 비교는 동일 container/image binding이다. 서로 다른 CI job에서 build한 이미지ID는 같다고 주장하지 않는다. Generator의 6파일 data-only 프로세스 경계는 기존 협력적 논리 경계이며 별도의 보안상 독립 평가자라고 하지 않는다.

원격 artifact는 `13047714141`, ZIP SHA256은 `6b527ad87eab7bda3fa8571e6ff7c6c92cd571143caac03a155eebbaf8a7924c`다. 정상 다운로드 후 CMS를 로컬에서 복호화하고 raw ZIP·ciphertext·수신자 인증서 해시를 확인했다. 원시 입력·Oracle 출력·개인키는 저장소에 추가하지 않는다. 공개 결과는 원시 payload 없이 모든 run과 미검출을 보존한다.

고유 upstream blob17개(전체 원문14·license3)를 정확 base64 바이트로 재확인했다. 로컬 전체 텍스트와의 차이는 끝 LF1개 추가와 라이선스 CRLF→LF뿐이다. 실행한16개 캡슐의 선택된 원문 단락·AST, 라이선스 전문과 retained SHA는 일치한다. global manifest의 보수적인 옛 MRI 설명보다 실제 관측 범위는 per-case metadata와 각 run의 MRI에 기록한다. 인자 mapping은 모델링하지 않아 comparison distance는 UNKNOWN이며, bucket 클래스는 명시적 black-box다.

성공 eligibility의 개별 세 관측은 저장하지 않아 동결 코드의 동일 semantic digest 강제 검사·CI exit0·집계 영수증으로 간접 확인한다. Source와 연구 run의 확인 관측은 private outcome 기록으로 직접 대조했다. 역할별 에이전트는 파일·도구를 공유하며 보안상 독립 실험자로 간주하지 않는다. 현재 upstream 배포판 영향·새로운 미관측 프로젝트/기전·독립 C·최종 Target·발행 readiness는 입증하지 않았다.

공개 PyPI0.7.0a1·기존 Release8개와 자산·main·PR #8·Drive 정본은 보존한다. 이번에는 draft PR #10 갱신과 미발행 wheel만 제공한다. main merge·새 tag·GitHub Release·PyPI upload·upstream issue/PR·Drive 쓰기는 모두0회다.
