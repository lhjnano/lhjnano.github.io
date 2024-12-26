---
layout: post
title: ISO 생성 절차
categories: [ISO]
description: 프로젝트를 진행하면서 ISO 를 생성하기 위한 기록입니다.
keywords: ISO
toc: true
toc_sticky: true
---

### Kerberos 설치 및 인증

```bash
yum install vim krb5-workstation epel-release -y
```

설정 정보 변경

```bash
[root@localhost ~]# vim /etc/krb5.conf
//아래 내용 수정
default_realm = {주소}
[realms]
 GLUESYS.COM = {
  kdc = kdc.{주소}:88
  admin_server = kdc.{주소}:749
  default_domain = {주소}
}

[domain_realm]
 .gluesys.com = {주소}
 gluesys.com = {주소}
```

### Koji 설치 및 설정

Koji-Packages 설치

```bash
# 시스템 업데이트
sudo yum update -y

# Koji 설치
sudo yum install -y koji

# Apache와 데이터베이스 설치
sudo yum install -y httpd mod_wsgi postgresql-server postgresql-contrib

# PostgreSQL 초기화
sudo postgresql-setup initdb

# PostgreSQL 활성화 및 시작
sudo systemctl enable postgresql
sudo systemctl start postgresql
```

koji 설정 정보 변경

```
[root@localhost ~]# mkdir ~/.koji
[root@localhost ~]# cp /etc/koji.conf ~/.koji/config
[root@localhost ~]# vim ~/.koji/config
// 아래 내용으로 수정
[koji]

;configuration for koji cli tool

;url of XMLRPC server
server = http://{주소}/kojihub  // 여기

;url of web interface
weburl = http://{주소}/koji     // 여기

;url of package download site
pkgurl = http://{주소}/packages // 여기

;path to the koji top directory
topdir = /mnt/koji              // 여기

;configuration for Kerberos authentication
authtype = kerberos
krb_rdns = false

;the service name of the principal being used by the hub
;krbservice = host

;the principal to auth as for automated clients
principal = lhjnano@{주소}  // 여기, 앞서 커베로스 인증 받은 계정으로 수행

;the keytab to auth as for automated clients
;keytab = /etc/krb5.keytab

;enable to lookup dns canonical hostname for krb auth
;krb_canon_host = no

;The realm of server principal. Using client's realm if not set
;krb_server_realm = EXAMPLE.COM

;configuration for SSL authentication

;client certificate
;cert = ~/.koji/client.crt

;certificate of the CA that issued the HTTP server certificate
;serverca = ~/.koji/serverca.crt

;plugin paths, separated by ':' as the same as the shell's PATH
;koji_cli_plugins module and ~/.koji/plugins are always loaded in advance,
;and then be overridden by this option
;plugin_paths = ~/.koji/plugins

;[not_implemented_yet]
;enabled plugins for CLI, runroot and save_failed_tree are available
;plugins =
; runroot plugin is enabled by default in fedora
plugins = runroot

;timeout of XMLRPC requests by seconds, default: 60 * 60 * 12 = 43200
;timeout = 43200

;timeout of GSSAPI/SSL authentication by seconds, default: 60
;auth_timeout = 60

; use the fast upload feature of koji by default
use_fast_upload = yes
```

- 기타 의존성 설치

```bash
yum install git rpm-build -y
```

### kbr 패스워드 변경

```
[root@localhost package]# kinit lhj4125@{주소}
Password for lhj4125@{주소}:


[root@localhost package]# kpasswd
Password for lhj4125@{주소}:
Enter new password:
Enter it again:
Password changed.
```

### 시작 전 변경

- Mac을 지원하려고 HFS 부트를 미디어에 추가하는 과정이 기본 활성화되어 있는데 이를 비활성화하는 옵션이 없음

```bash
/usr/lib/python2.7/site-packages/pypungi/__init__.py
   1402         # Only supported mac hardware is x86 make sure we only enable mac support on arches that need it
  1403         if self.tree_arch in ['x86_64']:
  1404             if self.config.getboolean('pungi', 'nomacboot'):
  1405                 domacboot = False
  1406             else:
  1407                 domacboot = True
  1408         else:
  1409             domacboot = False
/usr/lib/python2.7/site-packages/pypungi/config.py
   55         self.set('pungi', 'nomacboot', "False")
/usr/bin/pungi
   109     if opts.no_dvd:
  110         config.set('pungi', 'no_dvd', "True")
  111     if opts.nomacboot:
  112         config.set('pungi', 'nomacboot', "True")

  ...

  284         parser.add_option(
  285           "--nomacboot", action="store_true", dest="nomacboot",
  286           help='disable setting up macboot as no hfs support')
```

- pungi 실행 시 --nomacboot 옵션 추가

```bash
pungi \
...
--nomacboot \
...
```

### 기본 생성

```bash
pungi \
    --destdir=/root/temp \
    --config=ks/my.ks \
    --name=MyProject \
    --ver=1.0 \
    --force \
    --nomacboot \
    --nosource \
    --nodebuginfo \
    --bugurl={주소} \
    --nohash \
    --greedy=build \
    --multilib=devel \
    --isfinal
```

### 커스텀 생성 (별도 repo 생성)

1. 커스텀 repo directory 생성

```bash
mkdir tmp
cd tmp
```

2. 넣을 패키지를 다운로드 또는 생성

```bash
wget https://{주소}/kojifiles/work/tasks/3870/43870/perl-GMS-Plugin-Scheduler-1.1-1.el7.src.rpm
```

3. repo 생성

```bash
createrepo .
```

4. pungi kickstart (anystor-e.ks 등) 에 다음 라인 추가

```bash
repo --name=tmp       --baseurl=file:///root/tmp
...

%packages
perl-GMS-Plugin-Scheduler
@base
@core
@perl-pkgs
@infiniband
@ha
@virtualization-hypervisor
@anaconda-tools
#anaconda
#anaconda-runtime
open-vm-tools
open-vm-tools-desktop
%end
...

```

5. pungi 로 iso 생성

```bash
pungi \
    --destdir=/root/temp \
    --config=ks/my.ks \
    --name=MyProject \
    --ver=1.0 \
    --force \
    --nomacboot \
    --nosource \
    --nodebuginfo \
    --nohash \
    --greedy=build \
    --multilib=devel \
    --isfinal
```

### 에러 리포트

- 대부분 destdir 을 다 삭제하지 않아서 발생

```bash
에러 1) `olddata` => 기존 빌드가 실패로 끊난 경우 olddata 디렉토리가 남아있으면 빌드가 실패
에러 2) `no anaconda package in the repository` => 기본 빌드 내용이 남아있어 package 를 제대로 적용 못하는 문제
에러 3) `subprocess.CalledProcessError: Command '['depmod', '-a', '-F', '/root/temp/work/x86_64/yumroot/boot/System.map-module-info', '-b', '/root/temp/work/x86_64/yumroot', 'module-info']' returned non-zero exit status
```
