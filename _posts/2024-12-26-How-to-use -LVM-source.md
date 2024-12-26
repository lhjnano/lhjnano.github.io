---
layout: post
title: LVM 오픈 소스를 활용하여 커스텀 실습
categories: [LVM]
description: LVM 을 활용하여 LV list 를 출력하는 예제를 설명합니다.
keywords: LVM
toc: true
toc_sticky: true
---

### LVM 소스 라이브러리 설치

lvm2 devel 설치

```bash
yum -y install lvm2-devel.x86_64
```

### LVM 소스를 활용한 소스 파일 작성

간단하게 LV 리스트를 출력하는 `test.c` 파일 작성

```c
#include <lvm2app.h>

int main() {
    lvm_t lvm;
    vg_t vg;
    struct dm_list *lvs;
    struct lvm_lv_list *lvl;

    lvm = lvm_init(NULL);
    printf("complete: lvm_init\n");

    if (!lvm) {
        printf("fail: lvm_init\n");
        return -1;
    }

    vg = lvm_vg_open(lvm, "VGPA", "r", 0);
    printf("complete: lvm_vg_open\n");

    lvs = lvm_vg_list_lvs(vg);
    printf("complete: lvm_vg_list_lvs\n");

    lvm_vg_close(vg);
    printf("complete: lvm_vg_close\n");

    if (!lvs) {
        printf("no lvs are defined\n");
        return -1;
    }

    dm_list_iterate_items(lvl, lvs) {
        const char *name = lvm_lv_get_name(lvl->lv);

        printf("name: %s\n", name);
    }

    printf("Done\n");
    return 0;
}
```

### 컴파일

```bash
[lhj@LVMTest ~]# gcc test.c -llvm2app -ldevmapper  -o test
In file included from test.c:1:0:
/usr/include/lvm2app.h:22:2: warning: #warning "liblvm2app is deprecated, use D-Bus API instead." [-Wcpp]
 #warning "liblvm2app is deprecated, use D-Bus API instead."
  ^
```

### 실행 및 확인

```
[lhj@LVMTest ~]# ./test
complete: lvm_init
complete: lvm_vg_open
complete: lvm_vg_list_lvs
complete: lvm_vg_close
name: tp_VGPA
name: thinvol
name: thinsnap
name: thinsnap2
name: mysnapshot
name: mymysnap
name: lvol0_pmspare
name: tp_VGPA_tmeta
name: tp_VGPA_tdata
Done
```

---

### 참고

#### LVM 코드에서 LV 의 구조

- [lvm 커스텀 참조](https://github.com/collectd/collectd/blob/4e8dab9bf35517dfc16a665baaff9e57be617015/src/lvm.c)

```c
#defined ID_LEN 32

struct id {
	int8_t uuid[ID_LEN];
};

union lvid {
	struct id id[2];
	char s[2* sizeof(struct id) + 1 + 7];
};

struct lvm_lv_t {
	int8_t uuid[64];
	char   s[136];
	const char* name;
	struct volume_group *vg;
	unit64_t status;
	alloc_policy_t alloc;

	struct profile *profile;
	uint32_t read_ahead;
	int32_t major;
	int32_t minor;
	uint64_t size;>->---/* Sectors visible */
	uint32_t le_count;>-/* Logical extents visible */
	uint32_t origin_count;
	uint32_t external_count;
	struct dm_list snapshot_segs;
	struct lv_segment *snapshot;
	struct dm_list segments;
	struct dm_list tags;
	struct dm_list segs_using_this_lv;
	struct dm_list indirect_glvs;
}
```
