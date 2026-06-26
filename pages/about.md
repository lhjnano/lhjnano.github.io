---
layout: page
title: 소개
description: 운영자 소개
keywords: HeonJe Lee, 이헌제
comments: true
menu: 소개
permalink: /about/
---

## 안녕하세요

**이헌제**입니다.

"이거 가능해?"보다 **"이거 결국 안 되는 거네?"**를 먼저 찾는 성격입니다. 기능이 어떻게 동작하는지보다, 어디서 부서지는지가 궁하고, 그 제약이 운영 환경에서 어떤 영향을 주는지가 중요합니다. 클러스터링, 고가용성, 스토리지 같은 분야에서 일하다 보니 자연스럽게 그렇게 됐습니다.

모바일 앱과 CCTV 펌웨어를 거쳐, 리눅스 기반 스토리지 관리 OS를 만들었습니다. LVM 스냅샷이 어떤 조건에서 I/O 병목을 일으키는지 소스 코드까지 파고들어 분석하고, Paxos 기반으로 클러스터의 Split Brain을 어떻게 막을지 설계했습니다. "이 기능 가능해?"가 아니라 "장애 났을 때 어떻게 되는가?"를 먼저 따지는 일이었는데, 이 습관은 팀을 옮긴 지금도 변하지 않았습니다.

최근에 ZFS/Lustre 기반 듀얼컨트롤러 스케일 아웃 스토리지의 백엔드 팀으로 자리를 옮겼습니다. LVM 중심이던 환경에서 ZFS와 Lustre로 무대가 바뀌었고, API 백엔드와 클러스터 관리를 개발하고 있습니다.

최근에는 볼륨 생성 중 간헐적으로 `EBUSY`가 뜨는 문제를 추적하다가, OpenZFS 커널 내부의 잠금 레이스까지 파고들어갔습니다. 결국 업스트림에 [패치를 기여](https://github.com/openzfs/zfs/pull/18611)하게 됐는데, 버그 증상부터 잠금 계층 분석, 패치 작성, 리뷰 통과까지 꽤 긴 여정이었습니다.

![Career Evolution](/assets/images/about/career-timeline.svg)

## 왜 블로그를 쓰는가

제 약점 중 하나가 **"머릿속은 명확한데 설명이 짧아진다"**는 겁니다. 구조는 보이는데, "그래서?"에서 끝나버리죠. 분석과 비교는 많이 하는데, 그걸 밖으로 꺼내는 건 적었습니다.

이 블로그는 그걸 고치는 연습입니다. 읽고 분석한 걸 글로 풀어내면서, "안다"와 "설명할 수 있다" 사이의 간격을 줄이고 있습니다. AWS 클라우드, IAM과 보안 프로토콜, AI 개발 프로세스를 배우며 기록하고 있고, 틀린 부분이 있으면 지적해 주세요.

![기술 생태계](/assets/images/about/skill-ecosystem.svg)

## 만든 것들

- **[LVM-MCP](https://github.com/lhjnano/lvm-mcp)**: LVM 자동화를 위한 MCP 서버. 씬 프로비저닝, 스냅샷 자동화, 볼륨 관리 기능을 제공합니다.
- **[thin-send-recv-grpc](https://github.com/lhjnano/thin-send-recv-grpc)**: gRPC 멀티채널로 최대 300MB/s 속도를 내는 LVM thin snapshot 복제 도구입니다.

## Contact

<ul>
{% for website in site.data.social %}
<li>{{website.sitename }}：<a href="{{ website.url }}" target="_blank">@{{ website.name }}</a></li>
{% endfor %}
</ul>

## Skill Keywords

{% for skill in site.data.skills %}

### {{ skill.title }}

<div class="btn-inline">
{% for keyword in skill.keywords %}
<button class="btn btn-outline" type="button">{{ keyword }}</button>
{% endfor %}
</div>
{% endfor %}
