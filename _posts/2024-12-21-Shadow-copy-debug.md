---
layout: post
title: Shadow copy 소스 파일 분석 (1)
categories: [Shardow Copy, SMB, Snapshot]
description: SMB 에서 vfs 를 사용하여 snapshot 을 shadow copy 로 어떻게 제공하고 있는지 알아봅니다.
keywords: SMB, vfs, ShadowCopy, Snapshot
toc: true
toc_sticky: true
---

Shadow copy 를 어떤 식으로 제공하는지 알아봅니다.

### 테스트 기본 구성

```bash
# {share}.conf
vfs objects = shadow_copy2
shadow:snapdir = /export/{VG}/{LV}/snapshots
shadow:localtime = yes # 또는 format 지정 "@GMT-%Y.%m.%d-%H.%M.%S"
```

### vfs_shadow_copy2 내용 분석

##### Defines

- shadow_copy2_config

  - ...
  - use_localtime
  - snapdir 여기에서 스냅샷 리스트를 얻어 갈 듯
  - ...

- shadow_copy2_snapentry

  - snapname
  - time_fmt
  - next
  - prev

- shadow_copy2_snaplist_info

  - shadow_copy2_snapentry list
  - regex (filter)
  - fetch_time (snap update time)

- shadow_copy2_private

  - config
  - snaps
  - cwd (absolute path)
  - shadow_connectpath (absolute connectpath)
  - smb_filename \*shadow_realpath

- shadow_copy_data

  - num_volumes unit32_t
  - labels char[25]

- file_struct

  - struct smb_filename `*fsp_name` : 파일 이름 정보

- smb_filename
  - char `*base_name`
  - char `*stream_name`
  - uint32_t `flags`
  - SMB_STRUCT_STAT `st`
  - NTTIME `twrp`
  - struct files_struct `*fsp` # read only root
  - struct fsp_smb_fname_link `*fsp_link` # link

##### Methods

- `discard_const_p(type, ptr)` : ((type `*`)((intptr_t)(ptr)))
- SMB_VFS_HANDLE_GET_DATA `private` 에 데이터 갱신

  - Params: `handle`, `datap`, `type`, `ret`
  - Returns: void
  - datap = (type `*`)(handle)->data

- shadow_copy2_get_shadow_copy_data

  - Params : `vfs_handle_struct`, `files_struct`, `shadow_copy_data`, `is_labels`
  - Returns: `int`
  - 1.  shadow_copy2_find_snapdir 로 fsp 의 경로를 읽음. (smb connect_path + base_name + config->snapdir)
  - 2.  snapdir 을 열어 내부 파일 포인터 생성
  - 3.  file handle 의 접근 권한 확인
  - 4.  private 데이터 가져오기
  - 5.  스냅샷에 대한 `regex` 가 있고, `shadow_copy2_data` 가 NULL 이면 모든 스냅샷 리스트 초기화, fetch_time 갱신
  - 6.  스냅샷 디렉터리 하위의 디렉터리를 읽어와서 GMT format 의 스냅샷만 이름 추가
  - 7.  entry 넣을때마다 shadow_copy2_data 의 num_volume 증가 및 라벨 적용
  - 8.  열려있는 객체 정리

- shadow_copy2_saved_snapname : timestamp 기반 스냅샷을 찾고, 스냅샷 이름 반환

  - Params : `shadow_copy2_private`, `timestamp`,`snap_str`, `len`
  - Returns: `ssize_t`
  - 1.  `GMT_FORMAT`으로 timestamp 를 snap_str 에 기입한다.
  - 2.  `private` 에 제공된 `snaplist` 로 `snap_str` 과 이름을 비교한다.
    - 2.1. 같으면 `entry->snapname` 를 `snap_str` 에 기입하고, 그 길이를 반환한다.
    - 2.2 없으면 0을 반환한다.

- shadow_copy2_update_snaplist : 스냅샷이 업데이트 되었는지 검사, 스냅샷이 업데이트 되면 그 시간도 기록

  - Params : `vfs_handle_struct`, `snap_time`
  - Returns : `is_updated`
  - 1.  데이터 private 에 갱신
  - 2.  snap_time 과 private 의 fetch_time 비교
  - 3.  패치 시간이 새로 늘어났거나, 갱신할 스냅샷 리스트가 비었다면
    - 3.1. smb_fname.base_name 에 "." 을 넣고 fsp.fsp_name 에 적용
    - 3.2. shadow_copy2_get_shadow_copy_data 로 fsp 읽음

- shadow_copy2_find_snapdir : smb_fname 으로 스냅샷 폴더 검색

  - Params : `mem_ctx`, `vfs_handle_struct`, `smb_fname`
  - Returns: `char\*
  - 1.  설정값을 읽어들임
  - 2.  설정값 중 `snapdirseverywhere` 가 0 이면, `snapshot_basepath` 반환
  - 3.  path 에 `vfs_handle_struct` 의 connectpath 와 base_name 을 합쳐 반환
  - 4.  snapdir 이 있으면 상위 폴더 반환

- have_snapdir : stat 으로 return 의 경로에 디렉토리가 있으면 이름 반환

  - Params : `vfs_handle_struct`, `mem_ctx`, `path`
  - Returns: `snapshot-subdir` = path + config->snapdir

- shadow_copy2_find_slashes : `str` 에서 `/` 를 찾아 개수와 offset 를 반환

  - Params: `mem_ctx`, `str`, `poffsets`, `pnum_offsets`
  - Returns : `bool`

- shadow_copy2_posix_gmt_string

  - Params: `vfs_handle_struct`, `snapshot_time`, `snaptime_string`, `len`
  - Returns: `ssize_t`
  - config 에 use_sscanf 가 있을 경우 config->gms_format 에 맞춰 snapshot_time 을 string 으로 변환
  - use_sscanf 를 사용하지 않고, use_localtime 를 사용하는 경우 localtime_r 로 snapshot_time 을 string 으로 변환
  - use_sscanf 를 사용하지 않고, use_localtime 도 사용하지 않는다면 gmtime_r 로 snapshot_time 을 string 으로 변환
  - use_sscanf 를 사용하지 않는경우 regex 가 있으면 `shadow_copy2_saved_snapname` 를 사용하여 반환
    - timestamp 기반 스냅샷이 없으면 `shadow_copy2_update_snaplist` 로 스냅샷 업데이트하고, 재 검색

- shadow_copy2_insert_string

  - Params: `mem_ctx`, `vfs_handle_struct`, `snapshot_time`
  - Return: `str`
  - `shadow_copy2_posix_gmt_string` 에서 얻은 스냅샷 이름에 `config` 의 `snapdir` 를 추가하여 반환

- shadow_copy2_snapshot_path

  - Params : `mem_ctx`, `vfs_handle_struct`, `snapshot_time`
  - Return : `str`
  - `shadow_copy2_posix_gmt_string` 에서 얻은 스냅샷 이름에 `config` 의 `snapshot_basepath` 를 추가하여 반환

- make_path_absolute

  - Params: `mem_ctx`, `shadow_copy2_private`, `name`
  - Return : `str`
  - `name` 에 `config`의 `shadow_cwd` 를 추가하여 `canonicalize_absolute_path` 경로로 반환

- make_relative_path

  - Params : `cwd`, `abs_path`
  - Return : `bool`
  - `abs_path` 를 `cwd` 를 사용하여 상대 경로로 변환

- check_for_converted_path : `ppath_already_converted` 로 반환값 식별

  - Params: `mem_ctx`, `vfs_handle_struct`, `shadow_copy2_private`, `abs_path`, `ppath_already_converted`, `pconnectpath`
  - Return: success = 0, or errorcode
  - `abs_path` 가 `config` 의 `snapdir` 의 경로를 포함하는 절대경로 인지 확인
  - `config` 의 `snapdir` 의 유효성을 확인하고, `abs_path` 의 유효성을 확인

- \_shadow_copy2_strip_snapshot_internal

  - Params : `mem_ctx`, `vfs_handle_strcut`, `smf_fname`, `ptimestamp`, `pstripped`, `psnappath`, `_already_converted`, `function`
  - Returns: `bool`
  - `smb_fname` 이 이미 path 형식으로 변환되어 있는지 검사
  - 이름을 기반으로 `ptimestamp`, `pstripped`, `psnappath` 등을 없으면 채움

- `_shadow_copy2_strip_snapshot`

  - Params: `mem_ctx`, `vfs_handle_struct`, `orig_name`, `ptimestamp`, `pstripped`, `function`
  - Return : `bool`
  - `_shadow_copy2_strip_snapshot_internal` 을 활용, `psnappath` 와 `_already_converted`는 NULL 로 적용
  - = `shadow_copy2_strip_snapshot`

- `_shadow_copy2_strip_snapshot_converted`

  - Params : `mem_ctx`, `vfs_handle_struct`, `ptimestamp`, `orig_name`, `ptimestamp`, `is_conveted`, `function`
  - Returns: `bool`
  - `_shadow_copy2_strip_snapshot_internal` 에서 `psnappath` 만 NULL 로 적용
  - = `shadow_copy2_strip_snapshot_converted`

- shadow_copy2_find_mount_point

  - Params: `mem_ctx`, `vfs_handle_struct`
  - Returns: `string`
  - `connectpath` 로 뒤에서부터 하나씩 패스 제거해가면서 마운트 패스 확인
  - TODO sample

- shadow_copy2_do_convert

  - Params: `mem_ctx`, `vfs_handle_struct`, `name`, `timestamp`, `snaproot_len`
  - Returns : `str`
  - `SMB 계층`과 `타임스탬프`를 통해 입력한 이름에서 제공된 파일의 `스냅샷의 로컬 경로`로 변환한다. 또한 `파일의 공유 루트에 해당하는 스냅샷의 경로`를 반환한다.
  - 1.  smb 계층 정보 가져오기
  - 2.  `config` 의 `snapdireveryshare` 옵션이 없다면
    - 2.1 스냅샷 path 지정
    - 2.2 `config` 에 `rel_connectpath` 에 따라서 converted 패스 지정
    - 2.3 stat 정보 확인으로 정상인지 확인하고 종료
  - 3.  path 를 `connectpath` 로 지정
  - 4.  `/` 개수가 없으면 fail
  - 5.  `tiemstamp` 붙여서 insert 지정
  - 6.  converted = `path` + `insert` 반환

- shadow_copy2_co nvert

  - Params: `mem_ctx`, `vfs_handle_struct`, `name`, `timestamp`
  - Return : shadow_copy2_do_convnert 와 동일
  - `shadow_copy2_do_convert` 에서 `snaproot_len` 만 제외하고 동일

- convert_sbuf
  - Params : `vfs_handle_struct`, `fname`, `sbuf`
  - Return : `void`
  - check inode by sbuf
  - 주의 : GPFS 같은 경우 스냅샷과 원본 볼륨이 동일한 inode 를 반환한다. 그럴 경우 shadow 를 통해서 복원을 시도할 경우 깨진다. (처리 방법은 잘 이해가 안됌.)
- shadow_copy2_renameat

  - Params : `vfs_handle_struct`, `scrfsp`, `smb_fname_src`, `dstfsp`, `smb_fname_dst`
  - Returns : `int`
  - `shadow_copy2_strip_snapshot_internal` 로 src, dst 의 파일 형식 변환
  - 정상이면 `SMB_VFS_NEXT_RENAMEAT` 호출

- shadow_copy2_symlinkat, shadow_copy2_linkat

  - Parmas: `vfs_handle_struct`, `link_contents`, `dirfsp`, `new_smb_fname`
  - Returns : `int`
  - `shadow_copy2_strip_snapshot_internal` 로 link_contents 와 new_smb_fname 의 파일 형식 변환
  - 정상이면 `SMB_VFS_NEXT_SYMLINKAT`, `SMB_VFS_NEXT_LINKAT` 호출

- shadow_copy2_stat, shadow_copy2_lstat, shadow_copy2_fstat, shadow_copy2_fstatat

  - Params: `vfs_handle_struct`, `smb_filename`, `smb_fname`
  - Returns : `int`
  - `shadow_copy_strip_snapshot_converted` `smb_filename` 에 대한 `convert` 변환 확인
  - 절대 경로 생성하고 stat,lstat, fstat, fstatat 확인

- shadow_copy2_openat_name
  - Params: `mem_ctx`, `dirfsp`, `fsp`, `smb_fname_in`
  - Returns: `smb_filename`
  - 이름으로 full path 검색
- shadow_copy2_openat
  - Params: `vfs_handle_struct`, `dirfsp`, `smb_fname_in`, `fsp`, `_how`
  - Returns: `int`
  - `OPENAT` 확인

##### 객체 메모리 관리

- shadow_copy2_create_snapentry : 스냅샷 엔트리 리스트를 할당하고 반환
  - Params: `shadow_copy2_private`
  - Returns: `shadow_copy2_snapentry`
- shadow_copy2_delete_snaplist : 스냅샷 엔트리를 반환
  - Params: `shadow_copy2_private`
  - Returns : void

```
bool
_shadow_copy2_strip_snapshot_internal(
	MEM_CTX,           # 메모리 할당용
	vfs_handle_struct, # shadow_copy2_connect 를 통해서 정의된 handle
	smb_fname,         # 파일 정보
	ptimestamp,        # 타임스탬프 포인터
	pstripped,         # 파일 부가 설명 포인터
	psnappath,         # 스냅샷 경로 포인터
	_already_converted,# 컨버팅 여부 timestamp <-> time_format
	function,          # 함수명
)

1. handle 을 통해서 shadow_copy2_connect 에서 정의했던 priv 불러오기
2. _already_converted false 로 초기화
3. make_path_absolute 호출
	1. 절대 경로로 시작하는 것이 아니면 priv->shadow_cwd + '/' + smb_fname 반환
	2. 절대 경로로 시작하는 것이면 smb_fname 반환
4. check_for_converted_path 호출
	1. _already_converted 를 false 로 초기화
	2. 절대 경로에서 config->snapdir 를 검색
	3. 검색 결과가 없으면 0(convert 되지 않음) 반환
	4. 검색 결과가 '/' 로 시작하고 절대경로와 같지 않으면 0 반환
	5. snapdir 이 '/' 로 끝나지 않으면 0 반환
	7. config->snapdir 가 '/' 로 끝나지 않으면 정상 반환
	8. 검색결과가 절대 경로보다 길고 검색결과 이전에 '/' 가 있다면 0 반환
	9. 검색결과를 제외한 나머지 정보에서
	10. '/' 를 검색하는데, 아무것도 없으면 connect_path 는 절대 경로
	11. 아니면 connect_path 는 abs 에서 첫번째 경로까지
	12. connect_path 가 없으면 에러 반환
	13. shadow_copy2_snapshot_to_gmt 를 호출
		1. handle 을 통해서 shadow_copy2_connect 에서 정의했던 priv 불러오기
		2. config->snapprefix 가 있으면
			1. config->delimeter 로 name 구분
			2. 정규표현식대로 써있으면 false 반환

```

### 디버그

#### samba debuginfo 설치

```bash
$ yum-config-manager --enable anystor-debuginfo
$ debuginfo-install samba.x86_64

# 의존성 패키지 설치
$ debuginfo-install audit-libs-2.8.5-4.el7.x86_64 bzip2-libs-1.0.6-13.el7.x86_64 cyrus-sasl-lib-2.1.26-23.el7.x86_64 elfutils-libelf-0.176-5.el7.x86_64 elfutils-libs-0.176-5.el7.x86_64 gmp-6.0.0-15.el7.x86_64 keyutils-libs-1.5.8-3.el7.x86_64 krb5-libs-1.15.1-51.el7_9.x86_64 libattr-2.4.46-13.el7.x86_64 libcap-ng-0.7.5-4.el7.x86_64 libcom_err-1.42.9-19.el7.x86_64 libffi-3.0.13-19.el7.x86_64 libgcc-4.8.5-44.el7.x86_64 libgcrypt-1.5.3-14.el7.x86_64 libgpg-error-1.12-3.el7.x86_64 libidn-1.28-4.el7.x86_64 libselinux-2.5-15.el7.x86_64 libtasn1-4.10-1.el7.x86_64 lz4-1.8.3-1.el7.x86_64 nettle-3.1.1-1.ase3.x86_64 nspr-4.21.0-1.el7.x86_64 nss-3.44.0-7.el7_7.x86_64 nss-softokn-freebl-3.44.0-8.el7_7.x86_64 nss-util-3.44.0-4.el7_7.x86_64 p11-kit-0.23.5-3.el7.x86_64 pcre-8.32-17.el7.x86_64 sssd-client-1.16.5-10.el7_9.5.x86_64 xz-libs-5.2.2-1.el7.x86_64
$ wget http://linuxsoft.cern.ch/centos-debuginfo/7/x86_64/nss-util-debuginfo-3.44.0-4.el7_7.x86_64.rpm
$ wget http://linuxsoft.cern.ch/centos-debuginfo/7/x86_64/nss-debuginfo-3.44.0-7.el7_7.x86_64.rpm
$ yum -y localinstall ./nss*.rpm


# 프로세스 확인 (이미 공유는 열어놓은 상태)

$ smbstatus

Samba version 4.10.16
PID     Username     Group        Machine                                   Protocol Version  Encryption           Signing
----------------------------------------------------------------------------------------------------------------------------------------
14833   root         root         192.168.24.100 (ipv4:192.168.24.100:46510) SMB3_02           -                    partial(AES-128-CMAC)

Service      pid     Machine       Connected at                     Encryption   Signing
---------------------------------------------------------------------------------------------
IPC$         14833   192.168.24.100 화  3월 12 14시 59분 59초 2024 KST -            AES-128-CMAC
share        14833   192.168.24.100 화  3월 12 14시 59분 59초 2024 KST -            AES-128-CMAC

No locked files


# gdb 실행

$ gdb -p 14833

(gdb) b shadow_copy2_strip_snapshot
Breakpoint 1 at 0x7fab3d5db3a3: shadow_copy2_strip_snapshot. (24 locations)
(gdb) continue
Continuing.

(gdb) n   # 다음라인
(gdb) s   # 현재라인 스택
(gdb) l   # 라인 보기
(gdb) quit # 종료
```

### 원격지 공유 폴더 접근

```bash
$ ls
```

### 바로 확인 가능

```bash
Breakpoint 1, shadow_copy2_stat (handle=0x55a577cfd5c0, smb_fname=0x55a577cfc340)
    at ../../source3/modules/vfs_shadow_copy2.c:1272
1272		if (!shadow_copy2_strip_snapshot(talloc_tos(), handle,
(gdb) p (struct smb_filename)*smb_fname
$2 = {base_name = 0x55a577cee3b0 ".", stream_name = 0x0, original_lcomp = 0x0, flags = 0, st = {
    st_ex_dev = 0, st_ex_ino = 0, st_ex_mode = 0, st_ex_nlink = 0, st_ex_uid = 0, st_ex_gid = 0,
    st_ex_rdev = 0, st_ex_size = 0, st_ex_atime = {tv_sec = 0, tv_nsec = 0}, st_ex_mtime = {tv_sec = 0,
      tv_nsec = 0}, st_ex_ctime = {tv_sec = 0, tv_nsec = 0}, st_ex_btime = {tv_sec = 0, tv_nsec = 0},
    st_ex_calculated_birthtime = false, st_ex_blksize = 0, st_ex_blocks = 0, st_ex_flags = 0,
    st_ex_mask = 0}}
```

아직은 더 살펴봐야할 것 같기는 하다... TO BE Continue...

---

### Reference

- script : [https://wiki.samba.org/index.php/Rotating_LVM_snapshots_for_shadow_copy](https://wiki.samba.org/index.php/Rotating_LVM_snapshots_for_shadow_copy)
- shadow_copy2 : [https://www.samba.org/samba/docs/current/man-html/vfs_shadow_copy2.8.html](https://www.samba.org/samba/docs/current/man-html/vfs_shadow_copy2.8.html)
- vfs_shadow_copy2: https://github.com/samba-team/samba/blob/master/source3/modules/vfs_shadow_copy2.c
- https://github.com/samba-team/samba/blob/master/source3/modules/vfs_shadow_copy2.c
- 디버그 : https://wiki.samba.org/index.php/Writing_a_Samba_VFS_Module#Building,_Installing_and_Debugging_your_VFS_Module
