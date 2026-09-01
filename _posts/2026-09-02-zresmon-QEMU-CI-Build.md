---
layout: post
title: "zresmon CI 구축기 - QEMU 멀티 Distro 풀테스트"
categories: [DevOps, Rust, OpenZFS]
description: "커널 모듈 CI는 왜 호스티드 러너에서 안 될까요? QEMU로 9개 distro를 띄워 ZFS 소스빌드 후 17케이스 풀테스트를 돌린 여정을 정리했습니다."
keywords: [zresmon, QEMU, CI, GitHub Actions, OpenZFS, kernel module, 멀티 distro]
toc: true
toc_sticky: true
---

> [zresmon](https://github.com/lhjnano/zresmon) 후속 이야기. 2026-09-01 완료, 최종 결과 14 jobs / 0 failures.

> 시리즈: [ZFS 소스 학습 (5/5) zresmon](/2026/08/29/ZFS-Study-05-Zresmon/)에서 도구를 만들었다면, 이 글은 그 도구를 9개 distro에서 검증한 CI 구축기입니다.

## TL;DR

- 호스티드 러너 커널은 통제 불가 → ZFS kmod 빌드 실패
- QEMU로 각 distro VM을 띄워 자체 커널에서 소스빌드
- 9 distro × 17 랩케이스 실제 풀 대상 실행
- 디버깅 6건: KVM 권한, 패키지명, PATH, rustup HOME
- 최종: 14 jobs / 0 failures

## 문제: 호스티드 러너로는 안 됐다

zresmon은 ZFS 커널 모듈 위에서 동작하는 TUI입니다. 테스트하려면 실제 ZFS 모듈이 로드된 환경이 필요합니다. GitHub Actions 호스티드 러너에서 시도한 결과:

| 시도 | 결과 | 이유 |
|-----|------|------|
| ubuntu-22.04 + zfs-dkms 2.1 | ❌ 빌드 실패 | 2.1 dkms는 6.x 커널과 미호환 |
| ubuntu-24.04 + zfs-dkms 2.2 | ❌ 빌드 실패 | kernel 6.17-azure와 불일치 |
| ubuntu-26.04 + ZFS 소스빌드 2.4.1 | ❌ configure 실패 | kernel 7.0 > ZFS 2.4.1 max 6.19 |

결론: 러너 커널이 아니라 **자체 커널을 가진 VM**에서 테스트해야 합니다. QEMU로 각 distro의 클라우드 이미지를 부팅합니다.

## 해결: QEMU VM 매트릭스

아래 그림이 전체 아키텍처입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 880 480" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="zresmon CI 아키텍처. GitHub Actions ubuntu-latest 러너에서 qemu-boot.sh가 distro 클라우드 이미지를 다운로드하고 QEMU VM을 부팅한 뒤, vm-payload.sh를 VM에 전송하여 실행한다. VM 내부에서는 빌드 의존성 설치, OpenZFS 2.4.1 소스빌드, Rust 툴체인 설치, zresmon 클론, 유닛 테스트, 랩 매트릭스 17케이스 실행이 순서대로 진행된다.">
  <defs>
    <marker id="ci-arr" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="ci-arr-green" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="440" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">zresmon CI: QEMU VM 매트릭스 아키텍처</text>

  <rect x="40" y="46" width="180" height="66" rx="8" fill="#dbeafe" stroke="#2563eb" stroke-width="1.5"/>
  <text x="130" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#2563eb">GitHub Actions</text>
  <text x="130" y="92" text-anchor="middle" font-size="10" fill="#2563eb">ubuntu-latest 러너</text>

  <rect x="280" y="46" width="200" height="66" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="380" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">qemu-boot.sh</text>
  <text x="380" y="92" text-anchor="middle" font-size="10" fill="#92400e">이미지 다운로드 · resize · cloud-init · 부팅</text>

  <rect x="540" y="46" width="180" height="66" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.5"/>
  <text x="630" y="72" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">SSH 대기 (최대 15분)</text>
  <text x="630" y="92" text-anchor="middle" font-size="10" fill="#8b949e">hostfwd tcp::2222 → :22</text>

  <line x1="220" y1="79" x2="276" y2="79" stroke="#666666" stroke-width="1.4" marker-end="url(#ci-arr)"/>
  <line x1="480" y1="79" x2="536" y2="79" stroke="#666666" stroke-width="1.4" marker-end="url(#ci-arr)"/>

  <rect x="280" y="140" width="500" height="56" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.7"/>
  <text x="530" y="163" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">QEMU VM (KVM, 4 vCPU, 8G RAM)</text>
  <text x="530" y="183" text-anchor="middle" font-size="10" fill="#16a34a">almalinux8~10 · centos-stream9/10 · debian12/13 · fedora43/44 · ubuntu22/24</text>

  <line x1="630" y1="112" x2="630" y2="136" stroke="#666666" stroke-width="1.4" marker-end="url(#ci-arr)"/>

  <rect x="280" y="220" width="230" height="200" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="395" y="243" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">vm-payload.sh (VM 내부)</text>
  <text x="295" y="265" font-size="9.5" fill="#8b949e">① 빌드 의존성 설치 (apt/dnf)</text>
  <text x="295" y="281" font-size="9.5" fill="#8b949e">② OpenZFS 2.4.1 소스빌드</text>
  <text x="295" y="297" font-size="9.5" fill="#8b949e">③ make install · modprobe zfs</text>
  <text x="295" y="313" font-size="9.5" fill="#8b949e">④ rustup + zresmon 클론</text>
  <text x="295" y="329" font-size="9.5" fill="#8b949e">⑤ cargo test --all (유닛)</text>
  <text x="295" y="345" font-size="9.5" fill="#8b949e">⑥ 랩 매트릭스 17케이스</text>
  <text x="295" y="361" font-size="9.5" fill="#8b949e">　 (sudo cargo test -- --ignored)</text>

  <rect x="550" y="220" width="230" height="200" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="665" y="246" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">소요 시간 (VM당)</text>
  <text x="565" y="270" font-size="9.5" fill="#8b949e">이미지 다운로드</text><text x="780" y="270" text-anchor="end" font-size="9.5" fill="#666666">~30초</text>
  <text x="565" y="290" font-size="9.5" fill="#8b949e">부팅 + SSH 대기</text><text x="780" y="290" text-anchor="end" font-size="9.5" fill="#666666">~2분</text>
  <text x="565" y="310" font-size="9.5" fill="#8b949e">ZFS 소스빌드</text><text x="780" y="310" text-anchor="end" font-size="9.5" fill="#666666">~5분</text>
  <text x="565" y="330" font-size="9.5" fill="#8b949e">유닛 테스트</text><text x="780" y="330" text-anchor="end" font-size="9.5" fill="#666666">~30초</text>
  <text x="565" y="350" font-size="9.5" fill="#8b949e">랩 매트릭스 17케이스</text><text x="780" y="350" text-anchor="end" font-size="9.5" fill="#666666">~15분</text>
  <rect x="565" y="368" width="200" height="1" fill="#e2e8f0"/>
  <text x="565" y="390" font-size="10" font-weight="700" fill="#666666">합계</text><text x="780" y="390" text-anchor="end" font-size="10" font-weight="700" fill="#666666">~12-25분</text>

  <line x1="530" y1="196" x2="395" y2="216" stroke="#666666" stroke-width="1.4" marker-end="url(#ci-arr)"/>
  <line x1="530" y1="196" x2="665" y2="216" stroke="#666666" stroke-width="1.4" marker-end="url(#ci-arr)"/>

  <text x="440" y="456" text-anchor="middle" font-size="10" fill="#8b949e">9개 distro가 병렬 실행됩니다. 전체 파이프라인은 가장 느린 VM 기준 ~25분.</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - QEMU VM 매트릭스. 러너에서 qemu-boot.sh로 VM을 띄우고 vm-payload.sh를 전송해 ZFS 소스빌드부터 풀테스트까지 실행</figcaption>
</figure>

## 디버깅 여정

### KVM 권한 (전체 실패)

첫 시도는 전멸이었습니다. `qemu-system-x86_64: failed to initialize kvm: Permission denied`.

**원인**: 러너 유저는 `/dev/kvm`에 접근 불가.

**해결**: `sudo qemu-system-x86_64`로 root 권한 실행. OpenZFS CI는 libvirt로 해결하는데, libvirt도 결국 qemu를 root로 돌립니다. sudo 직접 실행이 더 간단합니다.

### 패키지명 차이

```
Error: Unable to find a match: libelf-devel     # Fedora/EL
Error: Unable to find a match: libtirpc-devel   # EL9 (CRB 필요)
```

**해결**: `elfutils-libelf-devel`로 수정 + CRB/Powertools 저장소 활성화.

### zpool PATH (debian12)

```
/tmp/vm-payload.sh: line 38: zpool: command not found
```

**원인**: 소스빌드가 `/usr/local/sbin`에 설치하지만 비-root 셸 PATH에 없음.

**해결**: payload에 `export PATH="/usr/local/sbin:$PATH"` 추가.

### rustup HOME 불일치 (전체 dnf 계열)

```
error: rustup could not choose a version of cargo to run
```

**원인**: `sudo cargo` 실행 시 rustup이 root의 HOME을 보지만 툴체인은 유저 홈에 설치돼 있음.

**해결**: 환경 변수를 명시적으로 전달.

```bash
sudo -E env \
  "PATH=$PATH" \
  "RUSTUP_HOME=$HOME/.rustup" \
  "CARGO_HOME=$HOME/.cargo" \
  "HOME=$HOME" \
  cargo test --test lab_matrix -- --ignored --nocapture
```

### centos-stream9 미러 실패 (일시적)

`dnf clean all` 후 retry 3회로 해결했습니다.

### debian13 UEFI 부팅

debian13 클라우드 이미지는 UEFI 부팅이 필요해서 QEMU에 OVMF 펌웨어를 지정했습니다.

## 최종 결과

```
✓ check          (ubuntu-latest: fmt/clippy/unit/build)
✓ scripts        (bash -n)
✓ musl           (static binary artifact)
✓ qemu-full ×9   (각 distro에서 ZFS 2.4.1 소스빌드 → 랩 17케이스)
```

| Distro | 커널 | 결과 |
|--------|------|------|
| almalinux8 | 4.18 | ✓ |
| almalinux9 | 5.14 | ✓ |
| almalinux10 | 6.12 | ✓ |
| centos-stream9 | 5.14 | ✓ |
| centos-stream10 | 6.12 | ✓ |
| debian12 | 6.1 | ✓ |
| debian13 | 6.12 | ✓ |
| fedora43 | 6.17 | ✓ |
| fedora44 | 6.17 | ✓ |
| ubuntu22 | 5.15 | ✓ |
| ubuntu24 | 6.8 | ✓ |

**14 jobs / 0 failures.**

## 교훈

- **커널 모듈 테스트는 VM에서.** 호스티드 러너 커널은 통제 불가. QEMU VM으로 자체 커널을 제공하면 어떤 ZFS 버전이든 빌드 가능
- **소스빌드가 제일 확실.** distro 패키지는 커널 버전에 종속되지만 소스빌드는 그 자리에서 컴파일하므로 항상 일치
- **sudo + rustup은 HOME 명시.** `RUSTUP_HOME`/`CARGO_HOME`/`HOME`을 전부 env로 전달해야 rustup이 툴체인을 찾음
- **cloud-init SSH 유저는 distro마다 다름.** almalinux/almalinux, centos/cloud-user, debian/debian, fedora/fedora, ubuntu/ubuntu

이 CI가 없었다면 zresmon의 3단 폴백 체인이 실제로 필요하다는 것을 9개 distro에서 확인할 수 없었을 것입니다. 특히 빌드 변종 차이(scan kstat 생성 안 됨, rebuild 문구 없음)가 distro별로도 재현되어 폴백 설계의 정당성이 입증됐습니다.
