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

안녕하세요, 저는 시스템 엔지니어로 활동하고 있는 `이헌제` 입니다. 

저는 온프레미스 시스템의 확장 및 효율적인 운영을 위해 다양한 기술을 활용하여 시스템의 안정성을 높이고, 자동화된 CI/CD 파이프라인을 구축하고 있습니다. 현재 주요 업무로는 Gitlab, Jenkins, Redmine, VMWare 등을 활용한 CI/CD 구성과 온프레미스 시스템 관리를 위한 소프트웨어를 개발하고 있습니다. 최근에는 LVM 기능을 쉽게 이용할 수 있도록 개선하는 작업을 맡고 있습니다. 

모든 시스템이 안정적으로 운영될 수 있는 인프라를 구축하기 위해서 지속적으로 기술을 학습하고, 기록하고 있습니다 :)

Let's make our on-premise history!


## Contact

<ul>
{% for website in site.data.social %}
<li>{{website.sitename }}：<a href="{{ website.url }}" target="_blank">@{{ website.name }}</a></li>
{% endfor %}
</ul>

## History

* On-premese 확장 및 유지보수
* 고가용성 운영 및 유지보수
* 합의 알고리즘 Paxos 도입 시도
* Gitlab, Jenkins, Redmine CI/CD 파이프라인 구축 및 관리 
* VMware 를 이용한 가상화 환경 관리 
* LVM 기능 개선 및 웹 프론트 개발


## Skill Keywords

{% for skill in site.data.skills %}
### {{ skill.name }}
<div class="btn-inline">
{% for keyword in skill.keywords %}
<button class="btn btn-outline" type="button">{{ keyword }}</button>
{% endfor %}
</div>
{% endfor %}