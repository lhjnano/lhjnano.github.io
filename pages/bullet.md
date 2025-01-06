---
layout: page
title: Bullet Skill
description: Bullet
keywords: Bullet
comments: false
mermaid: false
menu: bullet
permalink: /bullet/
---

<style>
    .mandalart {
        display: grid;
        grid-template-columns: repeat(9, 1fr);
        gap: 1px;
        background-color: #ccc;
    }
    .mandalart div {
        background-color: #fff;
        padding: 10px;
        text-align: center;
        border: 1px solid #ddd;
        font-size: 10px;
    }
    .mandalart div.center {
        background-color: #fce4ec;
        font-weight: bold;
    }
    .mandalart div.pastel1 { background-color: #f8bbd0; }
    .mandalart div.pastel2 { background-color: #e1bee7; }
    .mandalart div.pastel3 { background-color: #d1c4e9; }
    .mandalart div.pastel4 { background-color: #c5cae9; }
    .mandalart div.pastel5 { background-color: #bbdefb; }
    .mandalart div.pastel6 { background-color: #b3e5fc; }
    .mandalart div.pastel7 { background-color: #b2ebf2; }
    .mandalart div.pastel8 { background-color: #b2dfdb; }
</style>

# 2025 목표

<section>
    <div class="mandalart">
        <div class="pastel1">파일 시스템 관련 논문 2부</div>
        <div class="pastel1">리눅스 관리 관련 서적 1권</div>
        <div class="pastel1">커널 모듈 작성 및 로드</div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel1">리눅스 네트워크 스택 구조 및 `netfilter`, `iptables` 내부 동작 이해</div>
        <div class="pastel1">LSM(Linux Security Modules) SELinux 내부 구조 및 정책 작성 학습</div>
        <div class="pastel1">관심 있는 리눅스 관련 오픈소스 프로젝트 코드 기여</div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel1">고성능 네트워크 및 디스크 I/O 분석</div>
        <div class="pastel1">tmux 사용 늘리기</div>
        <div class="pastel1"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel4">치실 하기</div>
        <div class="pastel4">물 1L 마시기</div>
        <div class="pastel4">음주 관리</div>
        <div class="pastel1">System</div>
        <div class="pastel2">클라우드 서비스</div>
        <div class="pastel3">Network</div>
        <div class="pastel5">국내 여행 2회</div>
        <div class="pastel5">명상</div>
        <div class="pastel5">흑백요리사 식당 2회 방문</div>

        <div class="pastel4">주 2회 헬스장</div>
        <div class="pastel4">주 1회 공원 산책</div>
        <div class="pastel4">아침에 영양제 챙기기</div>
        <div class="pastel4">건강 성장</div>
        <div class="center"><strong>기록하며 성장하는 나</strong></div>
        <div class="pastel5">내면 성장</div>
        <div class="pastel5">친구 혹은 동료에게 구체적인 내용으로 칭찬하기</div>
        <div class="pastel5">지인 생일에 소소한 선물하기</div>
        <div class="pastel5">자기 개발 관련 서적 5권 이상 읽기</div>

        <div class="pastel4">월 1회 간헐적 단식</div>
        <div class="pastel4">등산 1회</div>
        <div class="pastel4">건강 검진 2회</div>
        <div class="pastel6">IaC</div>
        <div class="pastel7">컨테이너</div>
        <div class="pastel8">CI/CD</div>
        <div class="pastel5">예술 분야 서적 5권</div>
        <div class="pastel5">미술관/전시회 3회</div>
        <div class="pastel5">출퇴근시 영어 앱</div>

        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel7">컨테이너 네이티브 기술(LXC, CRI-O)과 Kubernetes 오픈소스 학습</div>
        <div class="pastel7">cgroups 와 namesspaces 의 동작 방식 이해</div>
        <div class="pastel7">리눅스 시스템 관련 블로그 포스트</div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>

        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel7"></div>
        <div class="pastel7"></div>
        <div class="pastel7"></div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>

        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel6"></div>
        <div class="pastel7"></div>
        <div class="pastel7"></div>
        <div class="pastel7"></div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>
        <div class="pastel8"></div>
    </div>

</section>

<br>

<ul class="listing">
{% for item in site.bullet %}
<li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
  <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
</li>
{% endfor %}
</ul>
