---
layout: post
title: LVM Segments 의 구조
categories: [LVM, Segment]
description: LVM 오픈 소스에서 설명하고 있는 LVM Segments 구조에 대해서 설명합니다.
keywords: LVM, Segment
toc: true
toc_sticky: true
---

#### Segment Type

```bash
63|<                >|48
  0000 0000 0000 0000
  ^
  +------------------- SEG_UNKNOWN            (63)

47|<                >|32
  0000 0000 0000 0000
          ^ ^   [
          | +--------- SEG_STRIPED_TARGET     (39)
          +----------- SEG_LINEAR_TARGET      (40)

31|<                >|16
  0000 0000 0000 0000
   SEG_RAID     ]  ^^
                   |+- SEG_ONLY_EXCLUSIVE1ULL (16)
                   +-- SEG_CAN_ERROR_WHEN_FULL(17)

15|<               >|0
  0000 0000 0000 0000
  ^^^^ ^^   ^^^^ ^^^^
  |||| ||   |||| |||+- SEG_CAN_SPLIT           (0)
  |||| ||   |||| ||+-- SEG_AREAS_STRIPED       (1)
  |||| ||   |||| |+--- SEG_AREAS_MIRRORED      (2)
  |||| ||   |||| +---- SEG_SNAPSHOT            (3)
  |||| ||   |||+------ SEG_FORMAT1_SUPPORT     (4)
  |||| ||   ||+------- SEG_VIRTUAL             (5)
  |||| ||   |+-------- SEG_CANNOT_BE_ZEROED    (6)
  |||| ||   +--------- SEG_MONITORED           (7)
  |||| |+------------- SEG_RAID               (10)
  |||| +-------------- SEG_THIN_POOL          (11)
  |||+---------------- SEG_THIN_VOLUME        (12)
  ||+----------------- SEG_CACHE              (13)
  |+------------------ SEG_CACHE_POOL         (14)
  +------------------- SEG_MIRROR             (15)

※(Number) : shift point
```

##### Examples

- `thick_vol` : seg->segtype = 0x8000000013 = `SEG_CAN_SPLIT & SEG_AREAS_STRIPED & SEG_FORMAT1_SUPPORT & SEG_STRIPED_TARGET`
- `thick_snap` : seg->segtype = 0x8000000013
- `snapshot0` : seg->segtype = 0x100c8 = `SEG_SNAPSHOT & SEG_CANNOT_BE_ZEROED & SEG_MONITORED & SEG_ONLY_EXCLUSIVE1ULL`

#### Usages

- `check_lv_segments` : `segtype` 으로 validate 검증, segment->le 연속성 확인
- `_check_lv_segment` : `segtype` 중 `mirror`, `cache`, `raid`, `thin_pool`, `thin` 의 경우 validate 검증
- `read_segment` : `settype` 으로 `lv->status` 적용

---

#### 기타 참고사항

##### seg->areas 중 type 이 AREA_PV 인 경우

- `_read_segment` => `_stripted_text_import` => `text_import_areas` 에서 pv 의 정보와 같은 이름의 항목이 있다면 `AREA_PV` 로 지정

##### seg->area_count

- `segment` 의 `type = "striped"` 이면 `stripe_count` 를 `area_count` 로 지정

```
8       breakpoint     keep y   0x000055555562f240 in check_lv_segments at metadata/merge.c:551
	breakpoint already hit 10 times
9       breakpoint     keep y   0x0000555555647d50 in check_pv_segments at metadata/pv_manip.c:394
	breakpoint already hit 1 time
10      breakpoint     keep y   0x000055555561c170 in set_lv_segment_area_pv
                                                   at metadata/lv_manip.c:1172
	breakpoint already hit 1 time
11      breakpoint     keep y   0x0000555555609de0 in text_import_areas
                                                   at format_text/import_vsn1.c:458

```

### Thin lv status and segments

```bash
Read thinpool LV segment
        lv->status =  0x2000000340
        segments->areas[0]->type = AREA_LV
        segments->areas[0]->u->lv->lv = pool_data_lv
        segments->areas[0]->u->lv->status = 0x4000000300
        segments->areas[0]->u->lv->le = 0
        segments->metadata_lv = metadata_lv
        segments->metadata_lv->status = 0x8000000300
        segments->chuck_size (thick 와 동일)
        segments->zero_new_blocks (thick 와 동일)
        segments->discards  (thick 과 동일)
        segments->transaction_id
        segments->size = 2097152 = 256(le_count) * 8192(extent_size)

thinvol lv segment
        lv->status = 0x1000010340
        lv->segments->areas[0]->type = AREA_UNASSIGNED

thinsnap lv segment
        lv->status = 0x41000010340
        lv->segments->areas[0]->type = AREA_UNASSIGNED

lvol0_pmspare
        lv->status = 0x10000000300
        lv->segments->areas[0]->type = AREA_PV
        lv->segments->areas[0]->u->pv->pvseg->pv = pv0

thinpool_tmeta
        lv->status = 0x8000000300
        lv->segments->areas[0]->type = AREA_PV
        lv->segments->areas[0]->u->pv->pvseg->pv = pv0

thinpool_tdata
        lv->status = 0x4000000300
        lv->segments->areas[0]->type = AREA_PV
        lv->segments->areas[0]->u->pv->pvseg->pv = pv0

VISIBLE_LV          UINT64_C(0x0000000000000040)
LVM_READ            UINT64_C(0x0000000000000100)    /* LV, VG */
LVM_WRITE           UINT64_C(0x0000000000000200)
VIRTUAL             UINT64_C(0x0000000000010000)
THIN_VOLUME         UINT64_C(0x0000001000000000)
THIN_POOL           UINT64_C(0x0000002000000000)    /* LV - Internal use only */
THIN_POOL_DATA      UINT64_C(0x0000004000000000)    /* LV - Internal use only */
THIN_POOL_METADATA  UINT64_C(0x0000008000000000)    /* LV - Internal use only */
LV_ACTIVATION_SKIP  UINT64_C(0x0000040000000000)

```
