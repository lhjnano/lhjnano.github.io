---
layout: post
title: "ZFS 소스 학습 (1/5): 라벨·GUID·uberblock - 디스크 바이트 지도부터"
categories: [OpenZFS, Filesystem]
description: "ZFS 라벨 4개는 디스크 어디에 있을까요? 256KiB 라벨 내부와 pool GUID 0x40B8 계산법을 그림으로 정리했습니다."
keywords: [ZFS, OpenZFS, vdev label, uberblock, nvlist, XDR, zdb]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (1/5). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

디스크의 첫 512바이트부터 ZFS가 시작됩니다. 파티션 테이블을 기대하고 덤프하면 나오는 건 0의 연속인데, 이 0조차 ZFS가 예약해 둔 라벨(label)의 첫 영역 pad1입니다.

이 글의 모든 숫자는 hexdump와 zdb로 실제 디스크 바이트를 직접 확인한 실측 기반입니다. 시리즈 1편을 바이트 지도로 시작하는 이유는 하나입니다. **바닥의 바이트를 읽으면 위의 추상화가 전부 이해된다**. 풀, txg, MOS 같은 상위 개념이 전부 라벨 안 몇백 바이트 위에 서 있습니다.

## TL;DR

- **라벨은 디스크마다 4개 × 256KiB.** 시작에 2개, 끝에 2개. 한쪽 끝이 깎여도 살아남는 배치입니다.
- **라벨 내부는 4층.** pad1 8KiB + bootenv 8KiB + 설정 nvlist 112KiB + uberblock 링 128KiB.
- **설정은 XDR(big-endian) nvlist.** hexdump에서 풀 이름 "tank"가 ASCII 그대로 보입니다.
- **pool GUID 위치는 상수가 아니라 공식.** 풀 이름이 tank(4글자)면 L0의 0x40B8.
- **uberblock 링은 txg마다 순환 기록.** txg가 가장 큰 유효 슬롯이 현재 커밋입니다.

## 라벨 4개의 위치: 양 끝에 2개씩

기준은 소스의 `vdev_label_offset()`입니다. 라벨 번호가 0, 1이면 디스크 앞에서, 2, 3이면 `psize - 1MiB`를 기준으로 계산합니다.

| 라벨 | 절대 주소 | 1GiB vdev에서 |
|------|-----------|---------------|
| L0 | 0x00000000 | 0x00000000 |
| L1 | 0x00040000 (256KiB) | 0x00040000 |
| L2 | psize - 0x80000 | 0x3FF80000 |
| L3 | psize - 0x40000 | 0x3FFC0000 |

왜 앞 2개, 뒤 2개로 갈라 놓았을까요? 헤드 크래시로 앞이 깎이거나 파티션 테이블이 손상돼도 **한쪽 끝만 살아있으면 라벨이 남는** 배치이기 때문입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 190" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="ZFS 디스크 배치도(1GiB 예시): 디스크 시작에 라벨 0과 라벨 1이 각 256KiB씩 붙고, 3.5MiB boot 예약 영역이 이어지며, 디스크의 대부분은 데이터와 메타데이터가 차지합니다. 디스크 끝 512KiB에는 라벨 2와 라벨 3이 붙습니다. 양 끝에 라벨을 배치해 한쪽 끝이 손상돼도 라벨이 살아남는 구조입니다.">
  <rect x="40" y="50" width="80" height="60" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.4"/>
  <text x="80" y="77" text-anchor="middle" font-size="13" font-weight="700" fill="#92400e">라벨 0</text>
  <text x="80" y="96" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>
  <rect x="136" y="50" width="80" height="60" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.4"/>
  <text x="176" y="77" text-anchor="middle" font-size="13" font-weight="700" fill="#92400e">라벨 1</text>
  <text x="176" y="96" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>
  <rect x="232" y="50" width="110" height="60" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.2"/>
  <text x="287" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">boot 예약</text>
  <text x="287" y="96" text-anchor="middle" font-size="10" fill="#666666">3.5MiB</text>
  <rect x="358" y="50" width="330" height="60" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.2"/>
  <text x="523" y="77" text-anchor="middle" font-size="12" fill="#666666">데이터 / 메타데이터</text>
  <text x="523" y="96" text-anchor="middle" font-size="10" fill="#16a34a">풀의 99.9% (MOS · 블록)</text>
  <rect x="704" y="50" width="50" height="60" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.4"/>
  <text x="729" y="77" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">라벨 2</text>
  <rect x="770" y="50" width="50" height="60" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.4"/>
  <text x="795" y="77" text-anchor="middle" font-size="11" font-weight="700" fill="#92400e">라벨 3</text>
  <text x="40" y="132" font-size="10" fill="#666666">0x00000000</text>
  <text x="820" y="132" text-anchor="end" font-size="10" fill="#666666">psize (1GiB = 0x40000000)</text>
  <text x="430" y="170" text-anchor="middle" font-size="11" fill="#8b949e">라벨 4개 합계 1MiB는 1GiB의 0.1%도 안 됩니다 (축척 왜곡)</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 1 - 라벨 4개는 디스크 양 끝에 2개씩. 한쪽 끝이 깎여도 라벨이 살아남는 배치</figcaption>
</figure>

위치를 알았으니, 이제 라벨 하나를 열어 봅니다.

## 라벨 내부는 4층

라벨 하나는 `vdev_label_t` 구조체를 디스크에 그대로 눕힌 정확히 256KiB입니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 190" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="라벨 하나의 내부 256KiB가 4층 구조인 그림. pad1 8KiB(0 채움), bootenv 8KiB(GRUB 부트 환경), 설정 nvlist 112KiB(XDR 인코딩, pool GUID 포함, 초록 강조), uberblock 링 128KiB(슬롯 배열, 노랑 강조) 순서로 이어집니다. 오프셋은 +0x0000, +0x2000, +0x4000, +0x20000, +0x40000입니다.">
  <rect x="40" y="46" width="120" height="64" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="100" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">pad1</text>
  <text x="100" y="92" text-anchor="middle" font-size="10" fill="#666666">8KiB · 0 채움</text>
  <rect x="180" y="46" width="130" height="64" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="245" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">bootenv</text>
  <text x="245" y="92" text-anchor="middle" font-size="10" fill="#666666">8KiB · GRUB 환경</text>
  <rect x="330" y="46" width="220" height="64" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.5"/>
  <text x="440" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">설정 nvlist</text>
  <text x="440" y="92" text-anchor="middle" font-size="10" fill="#16a34a">112KiB · XDR · pool GUID ★</text>
  <rect x="570" y="46" width="250" height="64" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.5"/>
  <text x="695" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">uberblock 링</text>
  <text x="695" y="92" text-anchor="middle" font-size="10" fill="#92400e">128KiB · 슬롯 배열</text>
  <text x="40" y="132" font-size="10" fill="#666666">+0x0000</text>
  <text x="180" y="132" font-size="10" fill="#666666">+0x2000</text>
  <text x="330" y="132" font-size="10" fill="#666666">+0x4000</text>
  <text x="570" y="132" font-size="10" fill="#666666">+0x20000</text>
  <text x="820" y="132" text-anchor="end" font-size="10" fill="#666666">+0x40000 (라벨 끝)</text>
  <text x="430" y="168" text-anchor="middle" font-size="11" fill="#8b949e">색 규약: 초록 = 이 글의 주인공 설정 nvlist · 노랑 = uberblock 링</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 2 - 라벨 256KiB의 4층. 실질 내용물은 3층 설정 nvlist와 4층 uberblock 링</figcaption>
</figure>

> **매직 넘버 2종을 혼동하지 마세요.** uberblock의 매직은 `0x00bab10c`("bloc"를 읊는 소리)이고, 라벨 체섬의 매직은 `0x210da7ab10c7a11`입니다. hexdump에서 둘 다 등장하므로 감별 포인트로 씁니다.

4층 중 디스크가 서로를 알아보는 방식이 들어 있는 곳이 설정 nvlist입니다.

## 설정 nvlist: 풀 이름과 GUID가 사는 곳

라벨의 설정은 `nvlist_pack(..., NV_ENCODE_XDR)`로 팩됩니다. XDR은 big-endian이라 x86 덤프에 익숙한 눈에는 순서가 반대지만, **GUID가 사람이 읽는 순서 그대로 저장된다**는 반전의 편리함이 있습니다.

키 순서는 `config_generate()`가 정합니다. 라벨 안에서는 version → name → state → txg → **pool_guid** → errata → hostid → hostname → vdev_tree 순입니다. GUID가 두 번 나오는 이유도 여기에 있습니다. 최상위 pool_guid는 풀의 신분증, vdev_tree 안의 각 guid는 디스크(vdev)의 신분증입니다.

풀 이름이 tank(4글자)면 엔트리 크기를 하나씩 더해 pool GUID의 자리를 정확히 계산할 수 있습니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 200" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="nvlist 바이트 산책 그림. 라벨 내 오프셋 0x4000에서 시작해 nvlist 헤더 8바이트, version 엔트리, name 엔트리(문자열 tank 포함), state 엔트리, txg 엔트리를 차례로 지나 pool_guid 엔트리의 값에 도달합니다. 각 단계 아래 누적 오프셋(0x4000, 0x4008, 0x402C, 0x4054, 0x4078, 0x4098)이 표시되고 pool_guid의 값은 8바이트 뒤인 절대 주소 0x40B8에 있음이 초록 박스로 강조됩니다.">
  <defs>
    <marker id="zs1-a" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#999999"/>
    </marker>
  </defs>
  <rect x="40" y="50" width="100" height="58" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="90" y="75" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">nvlist 헤더</text>
  <text x="90" y="93" text-anchor="middle" font-size="10" fill="#666666">8B</text>
  <rect x="160" y="50" width="100" height="58" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="210" y="75" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">version</text>
  <text x="210" y="93" text-anchor="middle" font-size="10" fill="#666666">UINT64</text>
  <rect x="280" y="50" width="120" height="58" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.4"/>
  <text x="340" y="75" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">name</text>
  <text x="340" y="93" text-anchor="middle" font-size="10" fill="#16a34a">"tank" ← 눈에 보임</text>
  <rect x="420" y="50" width="100" height="58" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="470" y="75" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">state</text>
  <text x="470" y="93" text-anchor="middle" font-size="10" fill="#666666">UINT64</text>
  <rect x="540" y="50" width="100" height="58" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="590" y="75" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">txg</text>
  <text x="590" y="93" text-anchor="middle" font-size="10" fill="#666666">UINT64</text>
  <rect x="660" y="50" width="160" height="58" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.7"/>
  <text x="740" y="72" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">pool_guid ★</text>
  <text x="740" y="92" text-anchor="middle" font-size="10" fill="#16a34a">값 8B → 0x40B8</text>
  <line x1="140" y1="79" x2="156" y2="79" stroke="#999999" stroke-width="1.3" marker-end="url(#zs1-a)"/>
  <line x1="260" y1="79" x2="276" y2="79" stroke="#999999" stroke-width="1.3" marker-end="url(#zs1-a)"/>
  <line x1="400" y1="79" x2="416" y2="79" stroke="#999999" stroke-width="1.3" marker-end="url(#zs1-a)"/>
  <line x1="520" y1="79" x2="536" y2="79" stroke="#999999" stroke-width="1.3" marker-end="url(#zs1-a)"/>
  <line x1="640" y1="79" x2="656" y2="79" stroke="#999999" stroke-width="1.3" marker-end="url(#zs1-a)"/>
  <text x="90" y="130" text-anchor="middle" font-size="10" fill="#666666">0x4000</text>
  <text x="210" y="130" text-anchor="middle" font-size="10" fill="#666666">0x4008</text>
  <text x="340" y="130" text-anchor="middle" font-size="10" fill="#666666">0x402C</text>
  <text x="470" y="130" text-anchor="middle" font-size="10" fill="#666666">0x4054</text>
  <text x="590" y="130" text-anchor="middle" font-size="10" fill="#666666">0x4078</text>
  <text x="740" y="130" text-anchor="middle" font-size="10" fill="#16a34a" font-weight="700">0x4098 + 8B = 0x40B8</text>
  <text x="430" y="170" text-anchor="middle" font-size="11" fill="#8b949e">엔트리를 하나씩 더하면 GUID의 자리가 나옵니다. 이 값 자체는 "tank일 때"의 답입니다</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 3 - nvlist 산책: 0x4000에서 엔트리를 지나면 pool GUID는 0x40B8에</figcaption>
</figure>

핵심을 한 줄로 정리하면 이렇습니다.

```text
nvlist 내 pool_guid 값 오프셋 = 0x98 + 0x20(프레이밍) = 0xB8
L0 절대 오프셋              = 0x4000 + 0xB8 = 0x40B8
```

<details>
<summary>📖 엔트리 크기 계산과 실제 hexdump 보기</summary>

XDR nvlist 문법과 각 엔트리의 크기 계산, 그리고 실제 덤프에서 GUID가 보이는 모습입니다.

**XDR nvlist 문법**

```text
[nvlist 헤더]  int32 nvl_version = 0
               int32 nvl_nvflag = 1 (NV_UNIQUE_NAME)
[엔트리 반복]   int32 encode_size
               int32 decode_size
               int32 name_len              (strlen + 1, NUL 포함)
               char  name[name_len]        (4바이트 배수 패딩)
               int32 data_type             (UINT64=8, STRING=9, NVLIST=19)
               int32 nelem
               byte  value[...]
[종료]          00 00 00 00                (encode_size=0)
```

**tank 풀의 엔트리 크기 누적**

| # | 키 | 이름(패딩) | 타입 | 엔트리 크기 | 시작(nvlist 내) |
|---|-----|-----------|------|------------|----------------|
| - | nvlist 헤더 | - | - | 8 | 0x00 |
| 1 | version | 7→8 | UINT64 | 36 | 0x08 |
| 2 | name | 4→8 | STRING("tank") | 40 | 0x2C |
| 3 | state | 5→8 | UINT64 | 36 | 0x54 |
| 4 | txg | 3→4 | UINT64 | 32 | 0x78 |
| 5 | pool_guid | 9→12 | UINT64 | 40 | 0x98 |

엔트리 5의 값은 프레이밍 32바이트(4+4+4+12+4+4) 뒤에 옵니다. 그래서 0x98 + 0x20 = 0xB8.

**실제 덤프 (L0의 핵심 구간)**

```text
00004030  00 00 00 28 00 00 00 05  6e 61 6d 65 00 00 00 00   name_len=5 | "name"
00004040  00 00 00 09 00 00 00 01  00 00 00 05 74 61 6e 6b   type=9(STRING) | len=5 | "tank"
000040b0  00 00 00 08 00 00 00 01  12 34 56 78 9a bc de f0   type=8 | pool GUID @ 0x40B8 ★
0001ffd8  21 0d a7 ab 10 c7 a1 11  ...                       vp_zbt: ZEC_MAGIC + 체섬
00020000  00 ba b1 0c ...                                    uberblock 링 시작
```

크기 워드의 정확한 값은 구현 디테일이므로, 덤프를 읽을 때는 문자열과 타입 코드, GUID를 앵커로 삼는 것이 안전합니다.

</details>

설정을 봤으니, 이제 라벨의 마지막 층인 uberblock 링의 산수를 합니다.

## uberblock 링: txg마다 다음 슬롯로

링은 라벨 내 0x20000부터 128KiB입니다. 슬롯 크기와 개수는 **ashift가 결정**합니다.

<figure>
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 860 210" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="uberblock 링의 순환 그림. 슬롯 0부터 127까지 배열에서 쓰기는 매 트랜잭션 그룹(txg)마다 다음 슬롯으로 이동합니다. 슬롯 55는 txg 2999(과거, 초록), 슬롯 56은 txg 3000(현재 커밋, 노랑 강조), 슬롯 57은 txg 3001(다음, 점선)이고, 슬롯 127 다음에는 다시 슬롯 0으로 순환하는 화살표가 그려져 있습니다. 모든 유효 슬롯은 매직 넘버 00 ba b1 0c로 시작합니다.">
  <defs>
    <marker id="zs1-b" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
  </defs>
  <rect x="40" y="50" width="90" height="60" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="85" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 0</text>
  <text x="85" y="96" text-anchor="middle" font-size="10" fill="#666666">링의 시작</text>
  <text x="160" y="85" text-anchor="middle" font-size="14" fill="#666666">…</text>
  <rect x="190" y="50" width="110" height="60" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="245" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">슬롯 55</text>
  <text x="245" y="96" text-anchor="middle" font-size="10" fill="#16a34a">txg 2999 · 과거</text>
  <rect x="320" y="50" width="110" height="60" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.7"/>
  <text x="375" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">슬롯 56 ★</text>
  <text x="375" y="96" text-anchor="middle" font-size="10" fill="#92400e">txg 3000 · 현재</text>
  <rect x="450" y="50" width="110" height="60" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.2" stroke-dasharray="5,3"/>
  <text x="505" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 57</text>
  <text x="505" y="96" text-anchor="middle" font-size="10" fill="#666666">txg 3001 · 다음</text>
  <text x="580" y="85" text-anchor="middle" font-size="14" fill="#666666">…</text>
  <rect x="600" y="50" width="110" height="60" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="655" y="77" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 127</text>
  <text x="655" y="96" text-anchor="middle" font-size="10" fill="#666666">다음은 슬롯 0</text>
  <path d="M 655 118 C 655 152, 85 152, 85 116" fill="none" stroke="#666666" stroke-width="1.4" marker-end="url(#zs1-b)"/>
  <text x="370" y="172" text-anchor="middle" font-size="11" fill="#666666">쓰기는 매 txg마다 다음 슬롯으로. 127을 넘으면 다시 0으로 순환</text>
  <text x="430" y="198" text-anchor="middle" font-size="11" fill="#8b949e">모든 유효 슬롯은 매직 00 ba b1 0c로 시작 → 덤프에서 바로 감별됩니다</text>
</svg>
<figcaption style="font-size:13px;color:#8b949e;text-align:center;margin-top:8px">그림 4 - 링 순환. txg가 가장 큰 유효 슬롯이 현재 커밋, 그 안의 ub_rootbp가 풀 전체로 뻗는 유일한 실</figcaption>
</figure>

산수는 세 단계입니다.

- **슬롯 크기**: `shift = MIN(MAX(ashift, 10), 13)`. ashift 9~10이면 1KiB, 12면 4KiB, 13 이상은 8KiB로 상한.
- **슬롯 수**: `count = 128KiB >> shift`. 1KiB면 128개, 4KiB면 32개.
- **슬롯 번호**: `slot = txg % (count - m)`. m은 mmp=on이면 1(MMP 심박용 마지막 슬롯 예약).

| ashift | 슬롯 크기 | 슬롯 수 | 비고 |
|--------|----------|---------|------|
| 9, 10 | 1KiB | 128 | 하한 UBERBLOCK_SHIFT=10 |
| 11 | 2KiB | 64 | |
| 12 | 4KiB | 32 | 현대 SSD 일반적 |
| 13+ | 8KiB | 16 | 상한 MAX_UBERBLOCK_SHIFT=13 |

tank 풀 txg 3000을 넣으면 3000 % 128 = 56, 즉 `0x20000 + 56×0x400 = 0x2E000`에 기록돼 있어야 합니다.

<details>
<summary>📖 예상 위치의 실제 덤프 보기</summary>

```text
0002e000  00 ba b1 0c 00 00 00 00  00 00 00 00 00 00 13 88   ub_magic | ub_version=5000
0002e010  00 00 00 00 00 00 0b b8  ab cd ef 98 76 54 32 10   ub_txg=3000 ★ | ub_guid_sum
```

공식대로 슬롯 56(0x2E000)에서 `ub_txg = 0x0BB8 = 3000`이 확인됩니다.

</details>

공식과 덤프가 서로 맞는지는 직접 확인해 볼 차례입니다.

## 검증 레시피: hexdump와 zdb

실 디스크(/dev/sdX)가 있다면 아래 순서로 전부 확인할 수 있습니다.

```bash
# ① 라벨 L0의 nvlist: 풀 이름과 GUID가 눈에 보임
sudo hexdump -C -s 0x4000 -N 320 /dev/sdX
# ② pool GUID 직독 (tank 예: 0x40B8의 8바이트, big-endian)
sudo hexdump -C -s 0x40B8 -N 8 /dev/sdX
# ③ uberblock 링 스캔: 00 ba b1 0c 시그니처 찾기
sudo hexdump -C -s 0x20000 -N 4096 /dev/sdX | grep -i "00 ba b1 0c"
# ④ 끝 라벨 L2/L3은 psize가 필요: L2 = psize-0x80000, L3 = psize-0x40000
sudo blockdev --getsize64 /dev/sdX
# ⑤ 사람이 읽는 디코드 (권장): 라벨 nvlist + uberblock 목록 전체
sudo zdb -l -u /dev/sdX
sudo zdb -C tank
```

체크리스트는 네 가지입니다.

- ① 0x4000에서 풀 이름이 보이는가
- ② 0x40B8(또는 계산 오프셋)의 8바이트가 `zdb -C`의 pool guid와 일치하는가
- ③ L2/L3의 nvlist가 L0/L1보다 최신인가
- ④ 예상 슬롯 수만큼 00bab10c가 보이는가

## 함정 노트 5가지

1. **오프셋은 상수가 아니라 공식입니다.** pool_guid 위치는 풀 이름 길이의 함수입니다. "항상 0x40B8"이 아니라 "tank일 때 0x40B8"이 정확한 표현입니다.
2. **XDR은 big-endian입니다.** little-endian에 익숙한 눈에는 순서가 반대지만 GUID가 `12 34 ...`로 사람 눈에 편하게 저장됩니다.
3. **문자열 길이 워드는 NUL을 포함합니다.** 4글자 "tank"의 길이 워드가 5인 이유입니다.
4. **L0/L1과 L2/L3의 갱신 시점은 다릅니다.** 갱신은 L2/L3에만 쓰입니다. L0/L1이 과거 트리를 담고 있어도 정상이며, import는 전부 읽고 체섬과 txg로 최선을 고릅니다.
5. **슬롯 크기는 디스크마다 다릅니다.** 1KiB 간격으로 훑다가 4KiB 슬롯 디스크를 만나면 4개를 하나로 세는 실수를 합니다. `zdb -l`을 쓰면 이 산수를 건너뛸 수 있습니다.

**다음 편 예고**: [ZFS 소스 학습 (2/5): 아키텍처](/2026/08/29/ZFS-Study-02-Architecture/)에서 uberblock의 ub_rootbp가 가리키던 MOS가 풀 전체를 어떻게 조립하는지 봅니다.
