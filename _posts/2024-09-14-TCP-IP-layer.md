---
layout: post
title: TCP/IP 4 계층의 정의 및 개념
categories: [TCP/IP, Network]
description: TCP/IP 4 계층의 정의 및 개념에 대해서 설명합니다.
keywords: TCP/IP, 네트워크, 계층
toc: true
toc_sticky: true
---


인터넷과 네트워크의 핵심 기술인 `TCP/IP` 모델은 우리가 일상적으로 사용하는 인터넷의 기초가 되는 중요한 개념입니다. 
이 포스트에서는 `TCP/IP` 모델의 구조와 각 계층의 역할에 대해 상세히 알아보려고 합니다. 


<br>
<br>


### TCP/IP 모델이란

TCP/IP 모델은 네트워크 통신을 관리하기 위해 설계된 프로토콜 스택입니다. 이는 데이터가 네트워크를 통해 전송되는 방식을 정의하며, 네 가지 주요 계층으로 구성되어 있습니다. 각각의 계층은 특정 기능을 담당하여 데이터의 송수신을 효율적으로 처리합니다.

<br>

```sh
+-------------------------+
|       응용 계층         |   (Application Layer)        - HTTP, FTP, SMTP
+-------------------------+
|      전송 계층          |   (Transport Layer)          - TCP, UDP
+-------------------------+
|       인터넷 계층       |   (Internet Layer)           - IP
+-------------------------+
|     네트워크 인터페이스  |   (Network Interface Layer)  - NIC, MAC
+-------------------------+
```


<br>


### L4: 응용 계층 (Application Layer)

응용 계층은 `사용자가 직접 상호작용하는 계층`으로, 우리가 사용하는 다양한 애플리케이션들이 이 계층에서 동작합니다.
웹 브라우저, 이메일 클라이언트, 파일 전송 프로그램 등이 이 계층에 포함됩니다. 주로 `HTTP`, `FTP`, `SMTP`와 같은 프로토콜이 이 계층에서 사용됩니다.


<br>


### L3: 전송 계층 (Transport Layer)

전송 계층은 `데이터의 신뢰성`과 `순서를 보장`하는 역할을 합니다. 이 계층에서는 주로 `TCP(Transmission Control Protocol)`와 `UDP(User Datagram Protocol)`가 사용됩니다. 
TCP는 연결 지향적이며 데이터의 신뢰성 있는 전송을 보장합니다. 반면 UDP는 비연결 지향적이며, 빠른 전송이 필요한 경우에 사용됩니다.


<br>

### L2: 인터넷 계층 (Internet Layer)

인터넷 계층은 `네트워크 간 데이터 전송을 관리`합니다. 이 계층에서 데이터는 패킷 형태로 전송되며, `IP(Internet Protocol)`가 주요 프로토콜로 사용됩니다. 
IP는 `데이터가 올바른 경로를 통해 목적지까지 도달하도록 라우팅`합니다

<br>

### L1: 네트워크 인터페이스 계층 (Network Interface Layer)

네트워크 인터페이스 계층은 `실제 물리적인 네트워크 매체를 통해 데이터가 전송되는 방식을 정의`합니다. 이 계층에서는 Ethernet, Wi-Fi, 그리고 다양한 `네트워크 카드`와 같은 하드웨어와 관련된 프로토콜이 포함됩니다.


<br><br>

TCP/IP 4계층에 대해서 간략하게 알아보았는데, 이제 실전으로 들어가서 L4 응용 어플리케이션인 SMB 를 사용한다면, 각 계층에서 어떻게 설정할 수 있는지 예를 들어 설명해보겠습니다.

<br>

### SMB (L4) 사용시 각 계층별 설정 [CentOS]

<br>

#### L1: 네트워크 계층 (Network Interface Layer), L2: 인터넷 계층 (Internet Layer)

CentOS 에서는 `network-scripts` 를 사용하여 네트워크 인터페이스를 작성할 수 있습니다. 네트워크 인터페이스를 작성하면, 네트워크 장치에 인터넷 계층인 IP 를 지정할 수 있습니다.

<br>

```sh
# /etc/sysconfig/network-scripts/ifcfg-ens192 에서 작성

DEVICE="ens192"
TYPE="Ethernet"
BOOTPROTO="static"
ONBOOT="yes"
MTU="1500"
IPADDR="192.168.26.100"
NETMASK="255.255.192.0"
GATEWAY="192.168.0.1"
```

<br>

`ens192` 인터페이스에 IP `192.168.26.100` 를 할당받도록 설정합니다. 설정을 변경한 후 네트워크 서비스를 재시작합니다. 

<br>

```sh
sudo systemctl restart network
```

<br>

#### L3: 전송 계층 (Transport Layer)

전송 계층에서는 애플리케이션을 식별하기 위해 포트 번호를 사용합니다. `SMB 프로토콜이 사용하는 포트`(기본적으로 TCP 445 포트)가 방화벽에서 열려 있어야 L4 에서 사용이 가능하므로 `firewalld`를 사용하여 포트를 열어줍니다.

<br>

```sh
# TCP 445 포트 열기
sudo firewall-cmd --zone=public --add-port=445/tcp --permanent

# 방화벽 설정 재로드
sudo firewall-cmd --reload
```

<br>

#### L4: 응용 계층 (Application Layer)

응용 계층에서는 SMB 서버 소프트웨어인 Samba를 설정합니다.

1. 설치 

<br>

```sh
sudo yum install samba samba-client samba-common
```

<br>

2. samba 설정 파일 수정

SMB 의 설정파일은 `/etc/samba/smb.conf` 입니다. 이 파일을 수정하여 공유 폴더를 설정합니다.

<br>

```sh
# /etc/samba/smb.conf 에서 작성

[share]                    # 공유 이름
   path = /srv/samba/share # 공유 경로 
   browseable = yes
   writable = yes
   guest ok = yes
   read only = no
```

<br>

3. 사용자 생성

smb 에 접속할 사용자를 생성합니다. 

<br>

```sh
# Samba 사용자 추가
sudo smbpasswd -a user1

# Samba 서비스를 재시작하여 설정 적용
sudo systemctl restart smb
sudo systemctl restart nmb
```

<br>

4. 디렉토리 권한 설정

<br>

```sh
# 공유 디렉토리 생성
sudo mkdir -p /srv/samba/share

# 권한 설정
sudo chown -R nobody:nogroup /srv/samba/share
sudo chmod -R 0775 /srv/samba/share
```

<br>

---

이번 과정을 통해 네트워크 인터페이스 계층에서 IP 주소와 물리적 네트워크를 설정하고, 전송 계층에서 포트를 관리하며, 응용 계층에서 SMB 서버를 설정하는 방법을 배울 수 있었습니다. 이러한 실습은 TCP/IP 모델의 각 계층이 실제 네트워크 통신에서 어떤 역할을 하는지 구체적으로 알아볼 수 있는 계기가 되었네요 :)

여러분도 이 과정을 통해 네트워크 통신의 기본 개념을 실전에서 어떻게 적용하는지 배워 보시기 바랍니다. 궁금한 점이나 추가적인 질문이 있다면 언제든지 댓글로 남겨주세요!