---
layout: post
title: "ZFS 소스 학습 (1/8): 라벨·GUID·uberblock - 디스크 바이트 지도부터"
categories: [OpenZFS, Filesystem]
description: "ZFS 라벨 4개는 디스크 어디에 있을까요? 256KiB 라벨 내부 지도와 pool GUID 0x40B8 계산법을 정리했습니다."
keywords: [ZFS, OpenZFS, vdev label, uberblock, nvlist, XDR, zdb]
toc: true
toc_sticky: true
---

> ZFS 소스 학습 시리즈 (1/8). 소스: OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스 기준.

디스크의 첫 512바이트부터 ZFS가 시작됩니다. 파티션 테이블을 기대하고 덤프하면 나오는 건 0의 연속인데, 이 0조차 ZFS가 예약해 둔 라벨(label)의 첫 영역 pad1입니다. ZFS는 풀 이름, GUID, 최신 커밋 위치를 디스크 맨 앞과 맨 뒤에 각각 두 장씩, 총 4장의 라벨로 새겨 둡니다.

이 글의 모든 숫자는 OpenZFS master(2.4.99-917-ge939b2d7e) 실제 소스에서 뽑았고, hexdump와 zdb로 실제 디스크 바이트를 직접 확인하며 검증한 실측 기반입니다.

이 내용을 시리즈 1편으로 두는 이유는 하나입니다. **바닥의 바이트부터 읽으면 위의 추상화가 전부 이해된다**는 것입니다. 풀, txg, MOS 같은 상위 개념이 전부 라벨 안 몇백 바이트 위에 서 있습니다. 이 바닥을 먼저 밟아 두면 이후 편들이 거꾸로 읽힙니다.

## TL;DR

- 라벨은 디스크마다 **4개 × 256KiB**입니다. 시작에 2개(L0 @ 0x0, L1 @ 0x40000), 끝에 2개(L2 @ psize-0x80000, L3 @ psize-0x40000).
- 라벨 내부는 **pad1 8KiB + bootenv 8KiB + 설정 nvlist 112KiB + uberblock 링 128KiB**의 4층 구조입니다.
- 설정 nvlist는 **XDR(big-endian)**로 인코딩되어 hexdump에서 풀 이름 "tank"가 ASCII 그대로 보입니다.
- pool GUID의 위치는 상수가 아니라 **공식**입니다. 풀 이름이 tank(4글자)면 L0의 **0x40B8**.
- uberblock 링은 128KiB이고 슬롯 수는 ashift가 결정합니다. **ashift≤10이면 1KiB×128슬롯**이고 txg 3000은 라벨+0x2E000에 기록됩니다.
- 검증은 `zdb -l -u /dev/sdX` 한 줄이면 충분하고, hexdump 직독 레시피도 함께 담았습니다.

## 라벨 4개의 절대 주소

기준은 OpenZFS master 소스의 `vdev_label_offset()`입니다. 함수가 사실상 한 줄이라 그대로 옮깁니다.

```c
return (offset + l * sizeof (vdev_label_t) +
    (l < VDEV_LABELS / 2 ? 0 : psize - VDEV_LABELS * sizeof (vdev_label_t)));
```

라벨 번호 l이 0, 1이면 디스크 앞에서, 2, 3이면 `psize - 1MiB`를 기준으로 계산합니다. 여기에 psize가 256KiB의 배수라는 조건이 더해져 절대 주소 4개가 나옵니다.

| 라벨 | 절대 주소 | 1GiB vdev에서 (psize=0x40000000) |
|------|-----------|----------------------------------|
| L0 | 0x00000000 (시작) | 0x00000000 |
| L1 | 0x00040000 (256KiB) | 0x00040000 |
| L2 | psize - 0x80000 (끝-512KiB) | 0x3FF80000 |
| L3 | psize - 0x40000 (끝-256KiB) | 0x3FFC0000 |

왜 앞 2개, 뒤 2개로 갈라 놓았을까요? 헤드 크래시로 앞이 깎이거나 파티션 테이블이 손상돼도 **한쪽 끝만 살아있으면 라벨이 남는** 배치이기 때문입니다. 주소를 알았으니 이제 디스크 전체에서 이 네 점이 어디쯤인지 한 장으로 봅니다.

## 디스크 hex 지도 전체

1GiB 단일 디스크 vdev 기준으로 절대 오프셋을 쭉 편 표입니다. ZFS가 예약하는 영역은 양 끝뿐이고 가운데는 풀의 99.9%를 차지하는 데이터와 메타데이터가 씁니다.

| 절대 오프셋 | 내용 |
|------------|------|
| 0x00000000 | 라벨 0 (256KiB) |
| 0x00040000 | 라벨 1 (256KiB) |
| 0x00080000 | boot 예약 영역 3.5MiB |
| 0x00400000 | 데이터 · 메타데이터 시작 (풀의 99.9%) |
| 0x3FF80000 | 라벨 2 (psize - 0x80000) |
| 0x3FFC0000 | 라벨 3 (psize - 0x40000) |
| 0x40000000 | psize (디스크 끝) |

아래 지도가 위 표의 그림 버전입니다. 라벨 내부까지 확대해 uberblock 링 위치까지 담았고, L2/L3도 같은 구조가 같은 순서로 기록됩니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 360" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="ZFS 디스크 바이트 지도(1GiB 예시): 디스크 시작에 라벨 0과 라벨 1(각 256KiB)이 붙고, 3.5MiB boot 예약 영역이 이어지며, 디스크의 99.9%는 데이터와 메타데이터가 차지합니다. 디스크 끝 512KiB에는 라벨 2(끝-512KiB)와 라벨 3(끝-256KiB)이 붙습니다. 아래 확대도는 라벨 256KiB 내부가 pad1 8KiB, bootenv 8KiB, 설정 nvlist 112KiB, uberblock 링 128KiB의 4층이며 링이 라벨 베이스+0x20000부터 시작함을 보여줍니다.">
  <defs>
    <marker id="zs1-arr" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
  </defs>
  <text x="480" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">디스크 바이트 지도: 라벨 4개와 uberblock 위치 (1GiB 예시)</text>

  <rect x="60" y="48" width="72" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="96" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">라벨 0</text>
  <text x="96" y="98" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>
  <rect x="152" y="48" width="72" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="188" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">라벨 1</text>
  <text x="188" y="98" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>
  <rect x="244" y="48" width="96" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="292" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">boot 예약</text>
  <text x="292" y="98" text-anchor="middle" font-size="10" fill="#666666">3.5MiB</text>
  <rect x="360" y="48" width="370" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="545" y="78" text-anchor="middle" font-size="12" fill="#666666">데이터 / 메타데이터</text>
  <text x="545" y="98" text-anchor="middle" font-size="10" fill="#16a34a">풀의 99.9% (MOS · 블록)</text>
  <rect x="750" y="48" width="72" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="786" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">라벨 2</text>
  <text x="786" y="98" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>
  <rect x="842" y="48" width="72" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="878" y="78" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">라벨 3</text>
  <text x="878" y="98" text-anchor="middle" font-size="10" fill="#92400e">256KiB</text>

  <text x="60" y="133" font-size="10" fill="#666666">0x00000000</text>
  <text x="152" y="133" font-size="10" fill="#666666">0x00040000</text>
  <text x="244" y="133" font-size="10" fill="#666666">0x00080000</text>
  <text x="360" y="133" font-size="10" fill="#666666">0x00400000</text>
  <text x="750" y="133" font-size="10" fill="#666666">0x3FF80000</text>
  <text x="842" y="133" font-size="10" fill="#666666">0x3FFC0000</text>
  <text x="914" y="149" text-anchor="end" font-size="10" fill="#666666">psize=0x40000000</text>

  <line x1="96" y1="118" x2="96" y2="178" stroke="#666666" stroke-width="1.2" stroke-dasharray="4,3" marker-end="url(#zs1-arr)"/>
  <text x="60" y="200" font-size="13" font-weight="700" fill="#2c3e50">라벨 1개 내부 (256KiB 확대)</text>

  <rect x="60" y="216" width="74" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="97" y="246" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">vl_pad1</text>
  <text x="97" y="264" text-anchor="middle" font-size="10" fill="#666666">8KiB · 0 채움</text>
  <rect x="154" y="216" width="90" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="199" y="246" text-anchor="middle" font-size="11" font-weight="700" fill="#666666">vl_be</text>
  <text x="199" y="264" text-anchor="middle" font-size="10" fill="#666666">bootenv 8KiB</text>
  <rect x="264" y="216" width="210" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="369" y="246" text-anchor="middle" font-size="11" font-weight="700" fill="#16a34a">vl_vdev_phys 112KiB</text>
  <text x="369" y="264" text-anchor="middle" font-size="10" fill="#16a34a">설정 nvlist(XDR) · pool GUID ★</text>
  <rect x="494" y="216" width="240" height="65" rx="6" fill="#fef2f2" stroke="#dc2626" stroke-width="1.3"/>
  <text x="614" y="246" text-anchor="middle" font-size="11" font-weight="700" fill="#dc2626">vl_uberblock 128KiB</text>
  <text x="614" y="264" text-anchor="middle" font-size="10" fill="#dc2626">uberblock 링 (슬롯 배열)</text>

  <text x="60" y="296" font-size="10" fill="#666666">+0x0000</text>
  <text x="154" y="296" font-size="10" fill="#666666">+0x2000</text>
  <text x="264" y="296" font-size="10" fill="#666666">+0x4000</text>
  <text x="494" y="296" font-size="10" fill="#666666">+0x20000</text>
  <text x="734" y="296" text-anchor="end" font-size="10" fill="#666666">+0x40000</text>

  <rect x="414" y="312" width="320" height="34" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.2"/>
  <text x="574" y="334" text-anchor="middle" font-size="11" font-weight="600" fill="#92400e">uberblock 링 = 라벨 베이스 + 0x20000부터 128KiB</text>
  <text x="480" y="354" text-anchor="middle" font-size="10" fill="#666666">축척 왜곡: 라벨 4개 합계 1MiB는 1GiB의 0.1%도 안 됩니다</text>
</svg>

그림에서 라벨 하나가 사실 4층짜리 상자라는 게 보입니다. 이제 그 내부로 들어갑니다.

## 라벨 내부는 256KiB 4층 구조

라벨 하나는 `vdev_label_t` 구조체를 디스크에 그대로 눕힌 정확히 256KiB입니다.

| 라벨 내 오프셋 | 크기 | 필드 | 내용 |
|---------------|------|------|------|
| 0x00000 | 8KiB | vl_pad1 | 예약 패딩, 전부 0 |
| 0x02000 | 8KiB | vl_be | bootenv(GRUB 부트 환경) |
| 0x04000 | 112KiB | vl_vdev_phys | **설정 nvlist(XDR)** + 끝에 vp_zbt 체섬 @ 0x1FFD8 |
| 0x20000 | 128KiB | vl_uberblock | **uberblock 링**(슬롯 배열) |
| 0x40000 | 끝 | 256KiB | 라벨 끝 |

vp_zbt는 `zio_eck_t`, 매직 8바이트 + 체섬 32바이트 = 40바이트로 112KiB 전체의 무결성을 검사합니다.

> **매직 넘버 2종을 혼동하지 마세요.** uberblock의 매직은 `UBERBLOCK_MAGIC = 0x00bab10c`("oo-ba-bloc!")이고, 라벨 체섬(vdev_phys/bootenv 끝)의 매직은 `ZEC_MAGIC = 0x210da7ab10c7a11`입니다. hexdump에서 둘 다 등장하므로 감별 포인트로 씁니다.

4층 중 실질적인 내용물은 3층의 설정 nvlist입니다. 디스크가 서로를 알아보는 방식이 여기 들어 있습니다.

## nvlist XDR 인코딩과 tank 실전 계산

라벨의 설정은 `nvlist_pack(..., NV_ENCODE_XDR)`로 팩됩니다. XDR은 **big-endian**이라 x86 덤프에 익숙한 눈에는 순서가 반대지만, GUID가 사람이 읽는 순서 그대로 저장된다는 반전의 편리함이 있습니다. 문법은 다음과 같습니다.

```
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

키 순서는 `config_generate()`가 정하는데, 라벨 안에서는 version → name → state → txg → **pool_guid** → errata → hostid → hostname → vdev_tree 순입니다. GUID가 두 번 나오는 이유도 여기에 있습니다. 최상위 pool_guid는 풀의 신분증, vdev_tree 안의 각 guid는 디스크(vdev)의 신분증입니다.

풀 이름이 tank(4글자)면 엔트리 크기를 더해 pool GUID의 자리를 정확히 계산할 수 있습니다.

| # | 키 | 이름(패딩) | 타입 | 엔트리 크기 | 시작(nvlist 내) |
|---|-----|-----------|------|------------|----------------|
| - | nvlist 헤더 | - | - | 8 | 0x00 |
| 1 | version | 7→8 | UINT64 | 36 | 0x08 |
| 2 | name | 4→8 | STRING("tank") | 40 | 0x2C |
| 3 | state | 5→8 | UINT64 | 36 | 0x54 |
| 4 | txg | 3→4 | UINT64 | 32 | 0x78 |
| 5 | pool_guid | 9→12 | UINT64 | 40 | 0x98 |

엔트리 5의 값은 프레이밍 32바이트(4+4+4+12+4+4) 뒤에 옵니다.

```
nvlist 내 pool_guid 값 오프셋 = 0x98 + 0x20 = 0xB8
L0 절대 오프셋              = 0x4000 + 0xB8 = 0x40B8
L2/L3에서도                 = label_base + 0x40B8
```

실제 덤프에서 눈에 보이는 모습입니다.

```
주소(L0 절대)  바이트                                                        읽는 법
00004000  00 00 00 00 00 00 00 01  00 00 00 24 00 00 00 24   헤더(ver=0) | 'version' 엔트리 시작
00004010  00 00 00 08 76 65 72 73  69 6f 6e 00 00 00 00 08   name_len=8 | "version" | type=8(UINT64)
00004020  00 00 00 01 00 00 00 00  00 00 13 88 00 00 00 28   값=5000 | 'name' 엔트리 시작
00004030  00 00 00 28 00 00 00 05  6e 61 6d 65 00 00 00 00   name_len=5 | "name" | pad
00004040  00 00 00 09 00 00 00 01  00 00 00 05 74 61 6e 6b   type=9(STRING) | len=5 | "tank" ← 풀 이름
000040a0  00 00 00 0a 70 6f 6f 6c  5f 67 75 69 64 00 00 00   name_len=10 | "pool_guid"
000040b0  00 00 00 08 00 00 00 01  12 34 56 78 9a bc de f0   type=8 | pool GUID @ 0x40B8 ★
0001ffd8  21 0d a7 ab 10 c7 a1 11  (체섬 32B)               vp_zbt: ZEC_MAGIC + 체섬
00020000  ...                                                   uberblock 링 시작
```

크기 워드의 정확한 값은 구현 디테일이므로, 덤프를 읽을 때는 문자열과 타입 코드, GUID를 앵커로 삼는 것이 안전합니다. 0x20000에서 링이 시작된다고 했으니, 이제 이 링의 산수를 합니다.

## uberblock 링 산수

링은 라벨 내 0x20000부터 128KiB입니다. 슬롯 크기와 개수는 **ashift가 결정**합니다.

```
shift = MIN(MAX(ashift, 10), 13)     // 10 = UBERBLOCK_SHIFT(하한), 13 = 상한
count = 128KiB >> shift              // 슬롯 수
slot  = txg % (count - m)            // m = mmp=on이면 1 (MMP 심박용 마지막 1슬롯 예약)
위치  = label_base + 0x20000 + (slot << shift)
```

| ashift | 슬롯 크기 | 슬롯 수 | 비고 |
|--------|----------|---------|------|
| 9, 10 | 1KiB | 128 | 하한 UBERBLOCK_SHIFT=10 |
| 11 | 2KiB | 64 | |
| 12 | 4KiB | 32 | 현대 SSD 일반적 |
| 13+ | 8KiB | 16 | 상한 MAX_UBERBLOCK_SHIFT=13 |

모든 유효 슬롯은 uberblock 첫 필드인 ub_magic 때문에 정확히 `00 ba b1 0c`로 시작합니다. tank 풀 txg 3000을 넣으면 3000 % 128 = 56, 즉 0x20000 + 56×0x400 = **0x2E000**에 기록돼 있어야 합니다.

```
0002e000  00 ba b1 0c 00 00 00 00  00 00 00 00 00 00 13 88   ub_magic=0x00bab10c | ub_version=5000
0002e010  00 00 00 00 00 00 0b b8  ab cd ef 98 76 54 32 10   ub_txg=3000 ★ | ub_guid_sum
```

커밋은 매 txg마다 다음 슬롯에 순환 기록됩니다. **txg가 가장 큰 유효 슬롯이 현재 커밋**이고, 그 안의 ub_rootbp가 풀 전체로 뻗어 나가는 유일한 실입니다.

<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 960 412" font-family="'Segoe UI','Noto Sans KR',system-ui,sans-serif" role="img" aria-label="uberblock 링의 128슬롯 순환과 위치 산수: 슬롯 0부터 127까지 128개(ashift 10 이하, 슬롯 1KiB 기준)로 구성되고 쓰기는 매 트랜잭션 그룹(txg)마다 다음 슬롯으로 이동해 127 다음 0으로 순환합니다. txg 2999는 슬롯 55, txg 3000은 슬롯 56(현재 커밋), txg 3001은 슬롯 57에 기록됩니다. 산수는 세 단계로, 슬롯 크기 shift는 MIN(MAX(ashift,10),13), 슬롯 수 count는 128KiB를 shift로 나눈 값, 슬롯 번호는 txg를 슬롯 수로 나눈 나머지이며 tank 풀 txg 3000이면 라벨 베이스+0x20000+56 곱하기 0x400, 즉 0x2E000에 위치합니다.">
  <defs>
    <marker id="zs2-arr" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#666666"/>
    </marker>
    <marker id="zs2-arr-g" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth">
      <path d="M0,0 L0,6 L9,3 z" fill="#16a34a"/>
    </marker>
  </defs>
  <text x="480" y="26" text-anchor="middle" font-size="15" font-weight="700" fill="#2c3e50">uberblock 링: 128슬롯 순환과 산수 (ashift≤10 · 슬롯 1KiB)</text>

  <rect x="60" y="60" width="84" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="102" y="88" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 0</text>
  <text x="102" y="108" text-anchor="middle" font-size="10" fill="#666666">링의 시작</text>
  <text x="163" y="98" text-anchor="middle" font-size="14" fill="#666666">…</text>
  <rect x="182" y="60" width="92" height="65" rx="6" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="228" y="88" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">슬롯 55</text>
  <text x="228" y="108" text-anchor="middle" font-size="10" fill="#16a34a">txg 2999 · 과거</text>
  <rect x="294" y="60" width="92" height="65" rx="6" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.6"/>
  <text x="340" y="88" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">슬롯 56 ★</text>
  <text x="340" y="108" text-anchor="middle" font-size="10" fill="#92400e">txg 3000 · 현재</text>
  <rect x="406" y="60" width="92" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3" stroke-dasharray="5,3"/>
  <text x="452" y="88" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 57</text>
  <text x="452" y="108" text-anchor="middle" font-size="10" fill="#666666">txg 3001 · 다음</text>
  <text x="517" y="98" text-anchor="middle" font-size="14" fill="#666666">…</text>
  <rect x="530" y="60" width="92" height="65" rx="6" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="576" y="88" text-anchor="middle" font-size="12" font-weight="700" fill="#666666">슬롯 127</text>
  <text x="576" y="108" text-anchor="middle" font-size="10" fill="#666666">다음은 슬롯 0</text>

  <path d="M 576 130 C 576 172, 102 172, 102 132" fill="none" stroke="#666666" stroke-width="1.4" marker-end="url(#zs2-arr)"/>
  <text x="339" y="196" text-anchor="middle" font-size="11" fill="#666666">쓰기는 매 txg마다 다음 슬롯으로: 127을 넘으면 다시 0으로 순환</text>

  <rect x="60" y="222" width="272" height="65" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="196" y="244" text-anchor="middle" font-size="12" font-weight="700" fill="#2c3e50">① 슬롯 크기</text>
  <text x="196" y="262" text-anchor="middle" font-size="10" fill="#666666">shift = MIN(MAX(ashift, 10), 13)</text>
  <text x="196" y="278" text-anchor="middle" font-size="10" fill="#666666">ashift 9~10이면 1KiB</text>
  <line x1="336" y1="254" x2="356" y2="254" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs2-arr-g)"/>
  <rect x="360" y="222" width="272" height="65" rx="8" fill="#f0f4f8" stroke="#666666" stroke-width="1.3"/>
  <text x="496" y="244" text-anchor="middle" font-size="12" font-weight="700" fill="#2c3e50">② 슬롯 수</text>
  <text x="496" y="262" text-anchor="middle" font-size="10" fill="#666666">count = 128KiB &gt;&gt; shift</text>
  <text x="496" y="278" text-anchor="middle" font-size="10" fill="#666666">1KiB면 128개, 4KiB면 32개</text>
  <line x1="636" y1="254" x2="656" y2="254" stroke="#16a34a" stroke-width="1.5" marker-end="url(#zs2-arr-g)"/>
  <rect x="660" y="222" width="240" height="65" rx="8" fill="#dcfce7" stroke="#16a34a" stroke-width="1.3"/>
  <text x="780" y="244" text-anchor="middle" font-size="12" font-weight="700" fill="#16a34a">③ 슬롯 번호</text>
  <text x="780" y="262" text-anchor="middle" font-size="10" fill="#16a34a">slot = txg % (count - m)</text>
  <text x="780" y="278" text-anchor="middle" font-size="10" fill="#16a34a">3000 % 128 = 56</text>

  <rect x="300" y="312" width="600" height="65" rx="8" fill="#fef3c7" stroke="#fbbf24" stroke-width="1.3"/>
  <text x="600" y="334" text-anchor="middle" font-size="12" font-weight="700" fill="#92400e">tank 풀 · txg 3000의 uberblock 절대 위치</text>
  <text x="600" y="353" text-anchor="middle" font-size="11" fill="#92400e">0x20000 + (56 &lt;&lt; 10) = 0x20000 + 0xE000 = 0x2E000</text>
  <text x="600" y="370" text-anchor="middle" font-size="10" fill="#666666">mmp=on이면 마지막 1슬롯을 MMP 심박으로 예약 (m=1)</text>
</svg>

공식과 덤프가 서로 맞는지는 직접 확인해 볼 차례입니다.

## 검증 레시피: hexdump와 zdb

실 디스크(/dev/sdX)가 있다면 아래 순서로 전부 확인할 수 있습니다.

```
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

체크리스트: ① 0x4000에서 풀 이름이 보이는가 ② 0x40B8(또는 계산 오프셋)의 8바이트가 `zdb -C`의 pool guid와 일치하는가 ③ L2/L3의 nvlist가 L0/L1보다 최신인가 ④ 예상 슬롯 수만큼 00bab10c가 보이는가. 마지막으로 실수하기 쉬운 지점 다섯 가지를 남깁니다.

## 함정 노트 5가지

1. **오프셋은 상수가 아니라 공식입니다.** pool_guid 위치는 풀 이름 길이의 함수, leaf vdev의 guid는 hostname 길이까지의 함수입니다. "항상 0x40B8"이 아니라 "tank일 때 0x40B8"이 정확한 표현입니다.
2. **XDR은 big-endian입니다.** little-endian에 익숙한 눈에는 순서가 반대지만 GUID `0x1234...`가 `12 34 ...`로 저장돼 있어 오히려 사람 눈에는 편합니다.
3. **문자열 길이 워드는 NUL을 포함합니다.** XDR 문자열은 strlen+1을 길이로 쓰고 4바이트 배수로 패딩합니다. 4글자 "tank"의 길이 워드가 5인 이유입니다.
4. **L0/L1과 L2/L3의 갱신 시점은 다릅니다.** L0/L1의 vdev_phys는 풀 생성·라벨 복구 시(vdev_label_init) 쓰이고, 갱신은 vdev_label_sync가 L2/L3에만 씁니다. L0/L1이 과거 트리를 담고 있어도 정상이며, import는 전부 읽고 체섬과 txg로 최선을 고릅니다.
5. **슬롯 크기는 디스크마다 다릅니다.** 1KiB 간격으로 훑다가 4KiB 슬롯(ashift 12) 디스크를 만나면 4개를 하나로 세는 실수를 합니다. `zdb -l`을 쓰면 이 산수를 건너뛸 수 있습니다.

**다음 편 예고**: [ZFS 소스 학습 (2/8): 아키텍처](/2026/08/29/ZFS-Study-02-Architecture/)에서 uberblock의 ub_rootbp가 가리키던 MOS가 풀 전체를 어떻게 조립하는지 봅니다.
