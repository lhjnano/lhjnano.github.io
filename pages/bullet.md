---
layout: page
title: Goals
description: Goals
keywords: Goals
comments: false
mermaid: false
menu: bullet
permalink: /bullet/
---

# 2025 목표

- 부족한 스킬 업데이트 및 자격 증명
  - RocKy 리녹스 신규 업데이트 기능 정리
  - 네트워크 관리자 자격증 도전
  - AWS certified solutions architect 자격증 도전
- 기술 서적 탐독 예정 리스트
  - ~~윌 라슨의 엔지니어링 리더십~~
  - 가상 면접 사례로 배우는 대규모 시스템 설계 기초 : 재밌는 구축 방법이 많아 보인다.
  - Splunk 를 활용한 시큐리티 모니터링 : 요즘 보안 문제가 많은 것 같아 눈독 중.
  - 금융 보안 프로세스 A to Z : 법적이 용어가 많던데, 읽을지...
  - 러스트로 배우는 리눅스 커널 프로그래밍 : 러스트도 커널도 성장해야할 분야
- 세미나도 종종 참석했는데, 본 걸 리뷰해보자.

<br>

<!-- 노션 DB 가져오는 건데 나중에 사용할 일이 있으려나...  ------------------------------------------------

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

-->
<!-- ref:https://lourcode.kr/posts/Jekyll-%EA%B8%B0%EB%B0%98-Github-Pages%EC%99%80-Notion-Page-%EC%97%B0%EB%8F%99/#github-%ED%99%98%EA%B2%BD-%EC%84%A4%EC%A0%95 -->

<!--
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
---------------------------------------------------------------------------------------------------
-->
