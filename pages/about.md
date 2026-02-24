---
layout: page
title: 소개
description: 운영자 소개
keywords: HeonJe Lee, 이헌제
comments: true
menu: 소개
permalink: /about/
---

## 인사

안녕하세요, 저는 스토리지 개발자로 활동하고 있는 `이헌제` 입니다.

저는 `온프레미스` 시스템의 확장 및 효율적인 운영을 위해 다양한 기술을 활용하여 시스템의 안정성을 높이고,
자동화된 `CI/CD` 파이프라인을 구축하고 있습니다.
현재 주요 업무로는 온프레미스 시스템 관리를 위한 소프트웨어를 개발과 `Gitlab`, `Jenkins`, `Redmine`, `VMWare` 등을 활용한 CI/CD 구성하고 있습니다.
최근에는 `LVM` 기능을 쉽게 이용할 수 있도록 개선하는 작업을 맡고 있습니다.

스토리지 서비스가 안정적으로 운영될 수 있는 인프라를 구축하기 위해서 지속적으로 기술을 학습하고, 기록하고 있습니다 :)

Let's make our on-premise history!

## Contact

<ul>
{% for website in site.data.social %}
<li>{{website.sitename }}：<a href="{{ website.url }}" target="_blank">@{{ website.name }}</a></li>
{% endfor %}
</ul>

## History

- On-premese 확장 및 유지보수
- 고가용성 운영 및 유지보수
- 합의 알고리즘 Paxos 도입 시도
- Gitlab, Jenkins, Redmine CI/CD 파이프라인 구축 및 관리
- VMware 를 이용한 가상화 환경 관리
- LVM 기능 개선 및 웹 프론트 개발

## Skill Keywords

{% for skill in site.data.skills %}

## Personal Project 

LVM-MCP 는 LVM 자동화를 위한 Model Context Protocol(MCP) 서버입니다.
씬 프로비저닝 및 스냅샷 자동화, 볼륨 관리, LVM 구성 최적화 등이 가능합니다.
구현된 프로젝트는 다음에서 확인할 수 있습니다:

- [LVM-MCP GitHub Repository](https://github.com/lhjnano/lvm-mcp)

THIN-SEND-RECV-GRPC 는 여러 thin-send-recv 의 코드를 참고하여 빠른 전송이 가능하도록 구현했습니다.
grpc 및 멀티채널을 활용하여 최대 300MB/s 의 속도로 데이터를 복제할 수 있습니다.
구현된 프로젝트는 다음에서 확인할 수 있습니다: 

- [THIN-SEND-RECV-GRPC](https://github.com/lhjnano/thin-send-recv-grpc)

### {{ skill.name }}

<div class="btn-inline">
{% for keyword in skill.keywords %}
<button class="btn btn-outline" type="button">{{ keyword }}</button>
{% endfor %}
</div>
{% endfor %}
