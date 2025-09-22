---
layout: post
title: OpenStack 살펴보기
categories: [OpenStack, DevStack, 클라우드, 인프라]
description: OpenStack 의 기본 구성에 대해서 간략히 설명하고 devstack 을 설치해봅니다.
keywords: OpenStack, 기초, 개념, 설명, 클라우드, 인프라
toc: true
toc_sticky: true
---


본 포스트는 다음의 환경에서 작성되었습니다.

- Win11 Pro / Hyper-V / Ubuntu 24.04


### 1. OpenStack 이해하기

#### 1.1. OpenStack

- 오픈소스 클라우드 인프라 관리 플랫폼
- 데이터센터의 서버, 스토리지, 네트워크 자원을 가상화하여 클라우드처럼 사용 가능하게 해줌
- IaaS(Infra as a Service) 제공하는 목적으로 사용됨.
- 필요할 경우 VM 을 생성하고 스토리지 연결, 네트워크 구성 가능

#### 1.2. OpenStack 구성 요소

| 서비스      | 역할                               |
| -------- | -------------------------------- |
| nova     | 컴퓨팅 관리 (VM 생성, 삭제, 스케줄링)         |
| Neutron  | 네트워크 관리 (가상 네트워크, 라우터, 서브넷, 방화벽) |
| Cinder   | 블록 스토리지 관리 (VM 에 연결할 볼륨)         |
| Glance   | 이미지 관리 (OS 이미지 저장, 배포)           |
| keystone | 인증, 권한 관리 (사용자, 프로젝트, 역할)        |
| Horizon  | 웹 GUI 대시보드 제공                    |
| Swift    | 오브젝트 스토리지                        |
| Heat     | 오케스트레이션 (리소스 자동 배포)              |

#### 1.3. OpenStack 구조

```c
+-----------------+
| Horizon         |
+-----------------+

         v
+-------------------------------------------------+
| Keystone                                        |
+-------------------------------------------------+
| Nova | Neutron | Cinder | Glance | Swift | Heat |
+-------------------------------------------------+
```

- 사용자는 Horizon 또는 CLI/API 를 통해 OpenStack 과 통신
- Keystone 을 통해 인증 후 각 서비스 (Nova 등) 에 접근
- 실제 물리 서버나 가상 서버 위에서 위 리소스가 관리됨


#### 1.4. OpenStack 특징


- 오픈소스
- 모듈형 구조
- 표준 API
- 대규모 확장 가능


### 2. OpenStack 설치 및 환경 구성


#### 2.1. Win11 에서 VM 환경 구성

#### 2.2. Hyper-V 를 활용하여 VM 구성

##### 2.2.1. Hyper-V 활성화

2. **시작의 Windows 기능 켜기/끄기**를 검색해서 실행.
3. **Hyper-V**, **Hyper-V 관리 도구**, **Hyper-V 플랫폼** 체크.
4. 확인 후 PC 재부팅.

##### 2.2.2. 가상 스위치 만들기 (네트워크 연결용)

1. 시작에서 `Hyper-V 관리자` 를 검색하여 실행.
2. 오른쪽의 작업 패널에서 `가상 스위치 관리자` 클릭.
3. **외부** 선택하고 만들기를 선택하면 가상 스위치 속성 패널이 나옴
4. 네트워크 카드 선택하고 확인.

### 2.3. Ubntu 22.04 VM 생성

1. Hyper-V 관리자에서 오른쪽 패널의 **새로 만들기/가상 컴퓨터** 클릭.    
2. 이름 입력을 입력하고 여유공간이 충분한 저장소를 지정합니다.
3. 세대를 지정합니다:
    - **세대 2**: UEFI, 보안 부팅 지원, 최신 Linux 추천.
4. 메모리 설정: 8192 MB (디폴트 4096 MB 이상)
5. 네트워크 설정: 2단계에서 만든 가상 스위치 연결
6. 가상 하드 디스크 생성: 50GB (디폴트 20 GB)
7. 설치 옵션:  **부팅 가능한 ISO 파일 사용**(Ubuntu 22.04 ISO 선택)
	- https://ubuntu.co1m/download/server
8. 생성 완료
9. 설정에서 보안모드 끄기
10. VM 시작
11. Ubuntu 설치 진행

### 2.4. DevStack 설치 (학습용)

1. Ubuntu 20.04 이상 VM 준비 (메모리 8G 이상)
2. devstack clone 및 설치

```bash
# sudo apt update
# sudo apt install git -y
# git clone https://opendev.org/openstack/devstack.git
# cd devstack
# cat local.conf
[[local|localrc]]

ADMIN_PASSWORD=devstack
DATABASE_PASSWORD=$ADMIN_PASSWORD
RABBIT_PASSWORD=$ADMIN_PASSWORD
SERVICE_PASSWORD=$ADMIN_PASSWORD

HOST_IP=192.168.0.100   # server IP

enable_service n-cpu
enable_service q-dhcp
enable_service q-l3
enable_service q-meta
enable_service neutron
enable_service cinder
enable_service c-api
enable_service c-vol
enable_service c-sch
enable_service heat h-api h-api-cfn h-api-cw h-eng
enable_service s-proxy s-object s-container s-account

# ./stack.sh
```

3. 접속 테스트: 웹 브라우저에서 `127.0.0.1/dashboard`

- 사용자: `admin`
- 암호: `devstack`


![devstack_dashboard](/images/posts/openstack/dashboard.png)