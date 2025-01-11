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
        <div class="pastel1">테스트 커널 모듈 작성 및 로드</div>
        <div class="pastel2">애플리케이션 성능 모니터링(APM) 개념 포스팅 1회</div>
        <div class="pastel2">컨테이너화된 환경(Kubernetes 포함)에서 모니터링 구축 1회</div>
        <div class="pastel2">SLO, SLA, SLI 개념 정리</div>
        <div class="pastel3">AWS 관련 포스팅 2회</div>
        <div class="pastel3">cgroups 와 namesspaces 의 동작 방식 이해</div>
        <div class="pastel3">Docker의 동작 원리 이해</div>
        <!-- next -->
        <div class="pastel1">리눅스 네트워크 스택 구조 및 <strong>netfilter</strong>, <strong>iptables</strong> 내부 동작 이해</div>
        <!-- 심화 학습: LVM 소스 분석 > LVM 어플 > LVM 어플에 기여 > LVM 에 기여 -->
        <div class="pastel1">LVM thin send/receive 구성해서 테스트 및 Contribute 혹은 포스팅 1회</div>
        <div class="pastel1">관심 있는 리눅스 관련 오픈소스 프로젝트 Contribute 혹은 포스팅 1회</div>
        <!-- Prometheus, Grafana, Datadog -->
        <div class="pastel2">매트릭 기반 모니터링으로 시스템 병목 현상 분석 1회</div>
        <!-- (Elasticsearch, Logstash, Kibana), Splunk, Loki -->
        <div class="pastel2">로그 기반 모니터링 시스템 구축</div>
        <div class="pastel2">로그 기반 모니터링으로 세부적인 원인 분석 3회</div>
        <div class="pastel3">고가용성 네트워크 원리 및 이해</div>
        <div class="pastel3">공유 프로토콜 오픈 소스 블로그 2회</div>
        <div class="pastel3">Kubernetes의 기본 개념 학습</div>
        <!-- next -->
        <div class="pastel1">고성능 네트워크 및 디스크 I/O 분석</div>
        <div class="pastel1">tmux 사용 늘리기</div>
        <div class="pastel1">리눅스 시스템 관련 블로그 포스트</div>
        <div class="pastel2">모니터링 종류 포스팅 1회</div>
        <div class="pastel2">Pull, Push 모델 동작 방식 및 원리 이해</div>
        <div class="pastel2">Prometheus와 Grafana를 설치하고 기본적인 메트릭 수집</div>
        <div class="pastel3">Pod, Deployment, Service 개념 이해</div>
        <div class="pastel3">컨테이너와 가상 머신의 차이점 학습</div>
        <div class="pastel3">Kubernetes Helm Chart 작성</div>
        <!-- next -->
        <div class="pastel4">치실 하기</div>
        <div class="pastel4">물 1L 마시기</div>
        <div class="pastel4">음주 관리</div>
        <div class="pastel1">System</div>
        <div class="pastel2">모니터링</div>
        <div class="pastel3">Network</div>
        <div class="pastel5">국내 여행 2회</div>
        <div class="pastel5">명상</div>
        <div class="pastel5">흑백요리사 식당 2회 방문</div>
        <!-- next -->
        <div class="pastel4">주 2회 헬스장</div>
        <div class="pastel4">주 1회 공원 산책</div>
        <div class="pastel4">영양제 챙기기</div>
        <div class="pastel4">건강 성장</div>
        <div class="center"><strong>기록하며 성장하는 나</strong></div>
        <div class="pastel5">내면 성장</div>
        <div class="pastel5">친구 혹은 동료에게 구체적인 내용으로 칭찬하기</div>
        <div class="pastel5">지인 생일에 소소한 선물하기</div>
        <div class="pastel5">자기 개발 관련 서적 5권 이상 읽기</div>
        <!-- next -->
        <div class="pastel4">월 1회 간헐적 단식</div>
        <div class="pastel4">등산 1회</div>
        <div class="pastel4">건강 검진 2회</div>
        <div class="pastel6"></div>
        <div class="pastel7"></div>
        <div class="pastel8"></div>
        <div class="pastel5">예술 분야 서적 5권</div>
        <div class="pastel5">미술관/전시회 3회</div>
        <div class="pastel5">출퇴근시 영어 앱</div>
    </div>

</section>

<br>

# 미래 로그

<ul class="listing">
    {% assign filtered_items = site.bullet | where: "category", "2025.future_log" %}
    {% for item in filtered_items %}
    <li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
        <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
    </li>
    {% endfor %}
</ul>

<br>

# 월간 로그

<ul class="listing">
    {% assign filtered_items = site.bullet | where: "category", "2025.monthy_log" %}
    {% for item in filtered_items %}
    <li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
        <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
    </li>
    {% endfor %}
</ul>

<br>

---

# 학습 로그

<ul class="listing">
    {% assign filtered_items = site.bullet | where: "category", "2025.study_log" %}
    {% for item in filtered_items %}
    <li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
        <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
    </li>
    {% endfor %}
</ul>

<br>

# 기술 트래커

<ul class="listing">
    {% assign filtered_items = site.bullet | where: "category", "2025.skill_tracker" %}
    {% for item in filtered_items %}
    <li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
        <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
    </li>
    {% endfor %}
</ul>

<br>

# 이벤트 로그

<ul class="listing">
    {% assign filtered_items = site.bullet | where: "category", "2025.skill_tracker" %}
    {% for item in filtered_items %}
    <li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
    <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
    </li>
    {% endfor %}
</ul>

<br>

# 습관 트래커

<style>
    .habit-tracker table {
        width: 100%;
        border-collapse: collapse;
        margin-top: 20px;
    }
    .habit-tracker th, .habit-tracker td {
        border: 1px solid #ddd;
        padding: 10px;
        text-align: left;
    }
    .habit-tracker th {
        background-color: #f4f4f4;
    }
</style>

<table class="habit-tracker" id="habit-tracker">
    <thead>
        <tr>
            <th>습관</th>
            <th>기록</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td colspan="2">Loading...</td>
        </tr>
    </tbody>
</table>

<!-- ref:https://lourcode.kr/posts/Jekyll-%EA%B8%B0%EB%B0%98-Github-Pages%EC%99%80-Notion-Page-%EC%97%B0%EB%8F%99/#github-%ED%99%98%EA%B2%BD-%EC%84%A4%EC%A0%95 -->

<script>
    async function fetchHabitData() {
        const response = await fetch('2025/notion_data.json');
        const data = await response.json();
        const habits = {};

        data.results.forEach(item => {
            const habit = item.properties['습관'].title[0]?.plain_text;
            const date = item.properties['날짜'].date.start;

            if (!habits[habit]) {
                habits[habit] = [];
            }

            habits[habit].push(date);
        });

        renderHabitTracker(habits);
    }

    function renderHabitTracker(habitData) {
        const trackerTable = document.getElementById('habit-tracker').querySelector('tbody');
        trackerTable.innerHTML = '';

        for (const [habit, dates] of Object.entries(habitData)) {
            const row = document.createElement('tr');

            const habitCell = document.createElement('td');
            habitCell.textContent = habit;
            row.appendChild(habitCell);

            const recordCell = document.createElement('td');
            const starCount = dates.length;
            recordCell.textContent = '★'.repeat(starCount);
            row.appendChild(recordCell);

            trackerTable.appendChild(row);
        }
    }

    fetchHabitData();
</script>
