---
layout: post
title: Active Directory(AD) 개념과 동작 구조 
categories: [AD, Active Directory]
description: Active Directory 를 사용하여 centos 에서 Window Server(ADS) 에 연결하는 방법을 설명합니다. 
keywords: LVM
toc: true
toc_sticky: true
---


### Active Directory 

간략하게 설명하자면 **AD (Active Directory)**는 주로 Windows 기반의 네트워크 환경에서 사용되며, 사용자, 컴퓨터, 그룹 등의 리소스를 중앙에서 관리하는 역할을 하는 계층형 데이터베이스입니다. 

각각의 리소스는 소수의 사용자만 볼 수 있도록, 접근 권한을 부여할 수도 있습니다. 

<br>

### Active Directory 의 구조

**AD** 에는 크게 도메인(Domain), 트리(Tree), 포리스트(Forest) 의 세 가지 계층이 있습니다. 

* 객체 : 도메인에서 관리되는 정보(사용자, 컴퓨터, 어플리케이션, 프린터, 공유)
* 도메인 : 관리 경계
* 트리   : 도메인 결합
* 포리스트 : 트리 그룹화 (보안을 다룹니다)

ADS(Active Directory Server) 의 `서버 관리자` > `도구` > `Active Directory 사용자 및 컴퓨터` 에서 관리하고 있는 객체에 대해서 확인할 수 있습니다. 

<img src="/assets/images/ad-user-computer.png" width="80%" alt="Active Directory 사용자 및 컴퓨터"/>

각 객체는 조직 단위(Organizational units, OU) 로 구성해서 사용자를 그룹으로 묶을 수도 있습니다. 
그 외에도 객체는 특성(Attrobutes), 식별자(Gobally Unique Identifier; GUID) 와 보안 식별자(Security Identify; SID) 등의 특성도 포함하고 있습니다. 


<br>

### NAS 에서 AD 로 공유 폴더 연결

아래에서는 간략하게 ADS 를 구성하였을때, 어떻게 NAS 가 연결하는지를 나타냅니다. 

```
[ NAS ]                                 [    AD    ] 도메인 기반
+-----+-----------------+               +----------+ Realm: 도메인/작업 그룹(NetBIOS)
| NAS | Samba [winbind] |     < --- >   | LDAP     |
+-----+-----------------+               | Kerberos |
                                        | DNS      |
                                        | NTP      |
                                        +----------+
| UID: Integer          |               | GUID     | 사용자 계정 ID
               <----------    baserid    -------------- 
```



1. AD 는 도메인 기반이기 때문에  NAS 에서 DNS 정보를 등록해줘야 합니다.
2. NAS는 Samba 의 winbind 를 통해서 AD 에 인증 정보를 보낼 수 있습니다..
3. 인증은 AD 서버에서 사용하는 NTP 와 시간 동기화가 되어야 Kerberos 에서 정상적으로 인증 절차를 거칠 수 있습니다.
4. 인증을 거치게 되면 AD 로 부터 Realm(작업 그룹) 에 대한 계층형 데이터베이스 정보를 받아올 수 있습니다.
5. 그 중 사용자 계정은 Windows 에서는 SID 를 사용하기 때문에, 리눅스 기반의 사용자 계정에서는 UID 를 사용하여 정보를 매핑시킬 필요가 있는데, 그 중 한가지 방법은 다음의 절차와 같습니다. 
6. 그 중 한 가지 방법은 SID 의 맨 뒤 번호와 NAS 에서 지정할 `baserid` 를 더하여 계정 정보를 가져올 수 있습니다.
7. 사용자 계정에 대한 매핑은 samba 의 winbind 를 통해서 이루어집니다.


이렇게 간략하게 AD 의 설명부터 NAS 에서 ADS 에 어떻게 연결하는 건지 에 대해서 설명했는데, 다음 포스트에서는 실제로 어떤 명령과 설정을 통해서 연결할 수 있는지 살펴보겠습니다 :smile:

<br>

---

### 참고

* [NAS 에서 ADS 연결 시 작업](https://www.baeldung.com/linux/netbios-resolve-names)
* [AD 설명](https://blog.naver.com/quest_kor/221487945625)