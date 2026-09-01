---
layout: post
title: "ZFS 소스 학습 (5/5): zresmon - 관찰 포인트를 도구로"
categories: [Storage, OpenZFS, Rust]
description: "ZFS resilver와 scrub 진행을 실시간으로 지켜보는 TUI를 만들었습니다. 빌드 무관 3단 폴백과 45케이스 실측까지 소개합니다."
keywords: [ZFS, OpenZFS, zresmon, resilver, scrub, TUI, Rust, 모니터링]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (5/5, 마지막 편). zresmon은 공개 저장소입니다: [github.com/lhjnano/zresmon](https://github.com/lhjnano/zresmon)

이 글의 실측 수치는 Rocky 8 + OpenZFS 2.2.9 환경에서 zresmon의 통합 테스트 매트릭스 45케이스를 직접 실행해 확보했습니다. 45/45 통과를 기준으로 삼았고, 도구를 일상 운영에서 직접 사용하고 있습니다.

이전 편 (4/5) ZIL·Resilver·Scrub, 약속 장부와 자가복구의 두 스캔: [ZFS-Study-04-ZIL-Resilver-Scrub](/2026/08/29/ZFS-Study-04-ZIL-Resilver-Scrub/)

이전 편 (3/5) Write & Read Path, 쓰기의 두 막과 읽기의 두 갈래: [ZFS-Study-03-Write-Read-Path](/2026/08/29/ZFS-Study-03-Write-Read-Path/)

## TL;DR

- resilver/scrub 실시간 TUI 모니터. 락 프리, 읽기 전용
- 같은 2.2.9도 빌드마다 관측 인터페이스가 다름 → 3단 폴백
- PID/락 파일 없음. 매 폴링이 독립 관측
- 45케이스 실측으로 판정 함정 3가지 발견·반영
- 시리즈의 관찰 포인트가 요구사항 문서였다

## 왜 만들었나: 같은 버전 문자열, 다른 동작

4편을 쓰면서 상태머신과 관찰 포인트를 정리했습니다. 그리고 실측 환경에서 매트릭스를 돌리자마자 벽에 부딪혔습니다. 업스트림 소스로 예측한 관측 경로가 빌드에 따라 그냥 없는 것입니다.

| 항목 | 업스트림 2.2.9 (소스 확인) | 파생 빌드 2.2.9 (실측) |
|---|---|---|
| scan kstat 파일 | 스캔 실행 시 생성 | **일부 경우 생성 안 됨** |
| dRAID rebuild 완료 문구 | `resilvered (vdev) N in ... with X errors` 출력 | **전혀 출력 안 됨** |
| rebuild 완료 감지 | zpool status의 scan 라인 | 이벤트 기반으로만 가능(resilver_finish 이벤트 + 분산 스페어 소진) |

버전 문자열이 같아도 내부 동작이 다를 수 있다는 뜻입니다. 파생 빌드는 업스트림 2.2 브랜치에 백포트 패치가 얹힌 형태라, 소스만 읽어서는 내 관측 인터페이스가 어떤 모양일지 확신할 수 없었습니다.

교훈은 빌드를 신뢰하지 말고 **기능 탐지**로 접근하라는 것입니다. zresmon의 3단 폴백 체인이 그 구현입니다. 첫 번째 단에서 kstat 파일을 찾고, 없으면 zpool status의 scan 라인을 파싱하고, 그마저도 없으면 rebuild 완료 문구와 이벤트를 직접 탐사합니다. 어떤 단에서 성공하든 같은 상태 모델로 정규화됩니다.

아래 그림이 전체 데이터 흐름입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 380" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="zresmon 아키텍처 데이터 흐름. 왼쪽에 세 개의 데이터 소스( proc 스캔 kstat, zpool status -v, zpool events -fv)가 있고, 가운데 3단 폴백 파서(kstat 1단, scan 라인 2단, rebuild 문구 프로브 3단)가 이 소스들을 같은 상태 모델로 정규화하며, 오른쪽 TUI가 진행 게이지, vdev 트리, 에러 서페이스 맵, 멀티풀 탭바 네 패널로 출력한다. 모든 화살표는 읽기 방향뿐이고 풀에 대한 쓰기 경로는 없다.">
  <defs>
    <marker id="zs8-arr-gray" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="zs8-arr-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">zresmon: 읽기 전용 데이터 흐름과 3단 폴백</text>

  <text x="140" y="58" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">데이터 소스</text>
  <rect x="40" y="70" width="200" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="140" y="97" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">/proc/spl/kstat/zfs/&lt;pool&gt;/scan</text>
  <text x="140" y="118" text-anchor="middle" font-size="10" fill="#8b949e">권한 불필요 · 스캔 종료 시 사라짐</text>
  <rect x="40" y="152" width="200" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="140" y="179" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">zpool status -v</text>
  <text x="140" y="200" text-anchor="middle" font-size="10" fill="#8b949e">vdev 트리 · 에러 카운터 (root/ZFS 그룹)</text>
  <rect x="40" y="234" width="200" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="140" y="261" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">zpool events -fv</text>
  <text x="140" y="282" text-anchor="middle" font-size="10" fill="#8b949e">ereport 스트림 · 오프셋 버킷</text>

  <rect x="330" y="110" width="240" height="150" rx="10" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.7"/>
  <text x="450" y="136" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">3단 폴백 파서</text>
  <text x="450" y="158" text-anchor="middle" font-size="10" fill="#92400e">1단: scan kstat</text>
  <text x="450" y="176" text-anchor="middle" font-size="10" fill="#92400e">2단: status의 scan 라인</text>
  <text x="450" y="194" text-anchor="middle" font-size="10" fill="#92400e">3단: rebuild 문구 · 이벤트 프로브</text>
  <text x="450" y="222" text-anchor="middle" font-size="10" font-weight="600" fill="#92400e">어느 단이든 같은 상태 모델로 정규화</text>

  <text x="700" y="58" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">TUI 패널</text>
  <rect x="600" y="70" width="240" height="52" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="720" y="92" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">진행 게이지 + examined/examine</text>
  <text x="720" y="110" text-anchor="middle" font-size="10" fill="#16a34a">RESILVER / SCRUB / ERROR SCRUB 상태</text>
  <rect x="600" y="134" width="240" height="52" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="720" y="156" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">vdev 트리</text>
  <text x="720" y="174" text-anchor="middle" font-size="10" fill="#16a34a">ONLINE/DEGRADED/FAULTED 색 · R/W/C 카운터</text>
  <rect x="600" y="198" width="240" height="52" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="720" y="220" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">에러 서페이스 맵</text>
  <text x="720" y="238" text-anchor="middle" font-size="10" fill="#16a34a">디바이스별 히트스트립 · 120초 슬라이딩 윈도우</text>
  <rect x="600" y="262" width="240" height="52" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="720" y="284" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">멀티풀 탭바 + 배지</text>
  <text x="720" y="302" text-anchor="middle" font-size="10" fill="#16a34a">⟳ RETRY vs ✚ REPLACE · 풀별 건강 마커</text>

  <line x1="240" y1="103" x2="330" y2="160" stroke="#666666" stroke-width="1.4" stroke-dasharray="4,3" opacity="0.6" marker-end="url(#zs8-arr-gray)"/>
  <line x1="240" y1="185" x2="330" y2="185" stroke="#666666" stroke-width="1.4" stroke-dasharray="4,3" opacity="0.6" marker-end="url(#zs8-arr-gray)"/>
  <line x1="240" y1="267" x2="330" y2="220" stroke="#666666" stroke-width="1.4" stroke-dasharray="4,3" opacity="0.6" marker-end="url(#zs8-arr-gray)"/>
  <line x1="570" y1="150" x2="600" y2="115" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs8-arr-green)"/>
  <line x1="570" y1="185" x2="600" y2="165" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs8-arr-green)"/>
  <line x1="570" y1="230" x2="600" y2="225" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs8-arr-green)"/>

  <text x="440" y="356" text-anchor="middle" font-size="10" fill="#8b949e">화살표는 전부 읽기 방향입니다. 풀을 향한 쓰기 경로는 없습니다.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - 읽기 전용 데이터 흐름. 세 소스를 3단 폴백 파서가 같은 상태 모델로 정규화하고 TUI 네 패널로 출력. 풀을 향한 쓰기 경로는 없습니다</figcaption>
</figure>

파서가 흡수해야 할 변종도 만만치 않았습니다. ereport 포맷 하나만 봐도 클래스 경로 표기, 키=값 구분(공백 vs 등호), 오프셋 필드명(zio_ 접두 유무), 따옴표 유무가 빌드마다 갈렸습니다. zresmon의 파서는 양쪽을 모두 지원합니다. 접미사 매칭, 등호 제거, zio_ 접두 스트립, 따옴표 제거의 조합입니다.

## 무엇을 보여주나

화면은 네 패널로 구성됩니다.

| 패널 | 내용 |
|---|---|
| 진행 게이지 | RPM 설치형 게이지(`##########------[ 45%]`)와 examined/to-examine 바이트. RESILVER/SCRUB/ERROR SCRUB에 IDLE/SCANNING/FINISHED/CANCELED 상태 병기 |
| vdev 트리 | ONLINE/DEGRADED/FAULTED 색과 읽기/쓰기/체크섬 에러 카운터 |
| 에러 서페이스 맵 | 디바이스별 히트스트립. ereport의 io_offset을 버킷팅해 최악 우선 정렬, 밀도 범례, 120초 슬라이딩 윈도우 |
| 멀티풀 탭바 | 풀별 건강 마커(빨강 ✚ = faulted/unavail vdev 있음, 노랑 ! = degraded, ⟳ = 스캔 중) |

배지 설계에 판단이 들어 있습니다. `⟳ RETRY`는 재시도 의미가 있는 상태에만 붙이고, FAULTED 디스크에는 `✚ REPLACE`를 붙입니다. 죽은 장치를 재시도하는 건 무의미하니 교체가 먼저라는 뜻입니다. 이 구분의 근거는 다음 절의 실측 발견입니다.

## 설계: 락 프리, resource-agent 스타일

모니터링 도구가 장애의 원인이 되면 안 됩니다. 그래서 원칙을 세웠습니다.

- **락 파일과 PID 파일이 없습니다.** 인스턴스를 몇 개를 띄워도 서로 방해하지 않습니다.
- **매 폴링이 독립된 읽기 관측입니다.** kstat, status, events를 읽고 상태를 조립합니다. 풀에 대한 변경은 없습니다.
- **`--once [--json]`**로 단일 스냅샷을 뱉습니다. OCF 모니터 액션 스타일이라 스크립트나 대시보드에 붙이기 쉽습니다.
- **한국어 IME 폴백**. IME가 켜진 상태에서 q가 ㅂ로 들어와도 핫키가 동작합니다. 두벌식 QWERTY 위치 투영으로 처리합니다. 이전 TUI 프로젝트에서 배운 교훈의 재적용입니다.

## 상태 판정의 함정: 매트릭스가 가르쳐준 것

45케이스 매트릭스는 단순 통과 확인이 아니라 판정 로직의 교정기였습니다. 발견 세 가지가 도구에 그대로 박혀 있습니다.

**첫째, UNAVAIL 인테리어와 FAULTED 리프는 다릅니다.** 복제본 부족으로 인테리어(풀, 레이드 그룹)가 UNAVAIL인 경우 리프가 전부 FAULTED여도 복구 가능합니다. 충분한 리프를 교체하고 resilver하면 됩니다. 반대로 리프만 FAULTED인 경우는 교체 대상으로 구분해야 합니다.

**둘째, retry의 규칙은 좁습니다.** FAULTED 리프는 retry를 유발하지 않습니다(교체가 먼저). DEGRADED/UNAVAIL 리프만 retry 대상입니다. 단, 인테리어 UNAVAIL은 리프가 전부 FAULTED여도 retry 대상입니다. 이 구분이 없으면 죽은 풀을 정상으로 오판합니다.

**셋째, `zpool clear`는 카운터만 리셋합니다.** R/W/C 에러 카운터는 clear 즉시 0이 됩니다(vdev.c:4752의 vdev_clear). 에러가 사라진 게 아니라 카운터만 초기화된 것입니다. 그래서 zresmon은 카운터와 에러 맵(ereport 윈도우)을 별도로 관리합니다.

덤으로 dRAID의 sequential rebuild는 2GB 파일 vdev 풀에서 1~3초 만에 끝났습니다. 진행 중 인터럽트 케이스는 대부분 "너무 빨라서 못 interrupt"로 스킵될 정도였습니다. 그만큼 관측 창이 짧다는 뜻이고, 그래서 폴백 체인의 3단(문구 프로브)이 실제로 필요해지는 지점이기도 합니다.

## 설치와 사용

Rust 표준 배포를 따릅니다.

```bash
# 저장소에서 설치 (~/.cargo/bin)
cargo install --path .

# 구형 배포판(Rocky 8 등)용 musl 정적 빌드 - 어디서든 실행됨
rustup target add x86_64-unknown-linux-musl
cargo build --release --target x86_64-unknown-linux-musl
sudo cp target/x86_64-unknown-linux-musl/release/zresmon /usr/local/bin/
```

사용법은 화면 하나로 충분합니다.

```bash
zresmon                  # 스캔 kstat이 있는 모든 풀 실시간
zresmon --pool tank      # 단일 풀
zresmon --demo errors    # 데모 시나리오: scanning|done|errors|fault
zresmon --once --json    # 한 번 찍고 종료 (머신 리더블)
```

핵키는 q/Esc 종료, 방향키와 Tab로 풀 이동, h/l로 vdev 트리와 에러 맵 포커스 전환입니다.

CI는 9개 Linux distro(almalinux8~10, centos-stream9/10, debian12/13, fedora43/44, ubuntu22/24)에서 QEMU VM을 띄워 OpenZFS 2.4.1을 소스빌드하고 랩 매트릭스 17케이스를 실제 풀 대상으로 실행합니다. 이 구축 과정은 [후속 편](/2026/09/02/zresmon-QEMU-CI-Build/)에서 다룹니다. 테스트벤치도 함께 제공합니다. `scripts/lab.sh`가 RAID 타입별 풀을 만들고 데이터를 채우고 vdev를 fail/replace로 몰아서 resilver를 유발하면, 다른 터미널의 zresmon으로 지켜보는 2터미널 워크플로우입니다. 통합 매트릭스 `scripts/run-matrix.sh`는 이 시나리오를 45케이스로 자동화해 jq로 단언합니다.

## 시리즈를 닫으며

1편에서 디스크의 첫 512바이트부터 시작한 이유는, 바닥의 바이트가 위의 모든 추상화의 답보였기 때문입니다. 라벨과 uberblock의 바이트 지도가 2편의 온디스크 체인으로 자라고, 체인이 3편의 쓰기와 4편의 읽기 경로를 지탱했고, 그 경로 위에서 4편의 DTL 장부와 ZIL 약속이 움직였고, scrub이 그 전부를 검증했습니다.

그리고 zresmon은 그 시리즈의 관찰 포인트들을 요구사항 문서 삼아 만든 도구입니다. 상태머신을 소스로 읽고, 읽은 모델을 코드로 구현하고, 구현한 도구로 다시 소스의 예측을 실측으로 확인하는 사이클. 학습의 끝에서 도구가 나온 게 아니라, 학습의 각 단계가 도구의 한 조각이었던 셈입니다.

- (1/5) 라벨·GUID·uberblock 바이트 지도: [ZFS-Study-01-Byte-Map](/2026/08/29/ZFS-Study-01-Byte-Map/)
- (2/5) 아키텍처: [ZFS-Study-02-Architecture](/2026/08/29/ZFS-Study-02-Architecture/)
- (3/5) Write & Read Path: [ZFS-Study-03-Write-Read-Path](/2026/08/29/ZFS-Study-03-Write-Read-Path/)
- (4/5) ZIL·Resilver·Scrub: [ZFS-Study-04-ZIL-Resilver-Scrub](/2026/08/29/ZFS-Study-04-ZIL-Resilver-Scrub/)

다음 장애가 왔을 때, 이 도구로 DTL과 errlog를 눈으로 따라가겠다는 것이 시리즈를 닫는 말입니다.
