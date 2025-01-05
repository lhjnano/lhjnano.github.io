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
        <div class="pastel1">목표 0-0</div>
        <div class="pastel2">목표 0-1</div>
        <div class="pastel3">목표 0-2</div>
        <div class="pastel4">목표 0-3</div>
        <div class="pastel5">목표 0-4</div>
        <div class="pastel6">목표 0-5</div>
        <div class="pastel7">목표 0-6</div>
        <div class="pastel8">목표 0-7</div>
        <div class="pastel1">목표 0-8</div>

        <div class="pastel2">목표 1-0</div>
        <div class="pastel3">목표 1-1</div>
        <div class="pastel4">목표 1-2</div>
        <div class="pastel5">목표 1-3</div>
        <div class="pastel6">목표 1-4</div>
        <div class="pastel7">목표 1-5</div>
        <div class="pastel8">목표 1-6</div>
        <div class="pastel1">목표 1-7</div>
        <div class="pastel2">목표 1-8</div>

        <div class="pastel3">목표 2-0</div>
        <div class="pastel4">목표 2-1</div>
        <div class="pastel5">목표 2-2</div>
        <div class="pastel6">목표 2-3</div>
        <div class="pastel7">목표 2-4</div>
        <div class="pastel8">목표 2-5</div>
        <div class="pastel1">목표 2-6</div>
        <div class="pastel2">목표 2-7</div>
        <div class="pastel3">목표 2-8</div>

        <div class="pastel4">목표 3-0</div>
        <div class="pastel5">목표 3-1</div>
        <div class="pastel6">목표 3-2</div>
        <div class="pastel7">목표 3-3</div>
        <div class="pastel8">목표 3-4</div>
        <div class="pastel1">목표 3-5</div>
        <div class="pastel2">목표 3-6</div>
        <div class="pastel3">목표 3-7</div>
        <div class="pastel4">목표 3-8</div>

        <div class="pastel5">목표 4-0</div>
        <div class="pastel6">목표 4-1</div>
        <div class="pastel7">목표 4-2</div>
        <div class="pastel8">목표 4-3</div>
        <div class="center">2025 목표<br><strong>기록하며 성장하는 나</strong></div>
        <div class="pastel1">목표 4-5</div>
        <div class="pastel2">목표 4-6</div>
        <div class="pastel3">목표 4-7</div>
        <div class="pastel4">목표 4-8</div>

        <div class="pastel6">목표 5-0</div>
        <div class="pastel7">목표 5-1</div>
        <div class="pastel8">목표 5-2</div>
        <div class="pastel1">목표 5-3</div>
        <div class="pastel2">목표 5-4</div>
        <div class="pastel3">목표 5-5</div>
        <div class="pastel4">목표 5-6</div>
        <div class="pastel5">목표 5-7</div>
        <div class="pastel6">목표 5-8</div>

        <div class="pastel7">목표 6-0</div>
        <div class="pastel8">목표 6-1</div>
        <div class="pastel1">목표 6-2</div>
        <div class="pastel2">목표 6-3</div>
        <div class="pastel3">목표 6-4</div>
        <div class="pastel4">목표 6-5</div>
        <div class="pastel5">목표 6-6</div>
        <div class="pastel6">목표 6-7</div>
        <div class="pastel7">목표 6-8</div>

        <div class="pastel8">목표 7-0</div>
        <div class="pastel1">목표 7-1</div>
        <div class="pastel2">목표 7-2</div>
        <div class="pastel3">목표 7-3</div>
        <div class="pastel4">목표 7-4</div>
        <div class="pastel5">목표 7-5</div>
        <div class="pastel6">목표 7-6</div>
        <div class="pastel7">목표 7-7</div>
        <div class="pastel8">목표 7-8</div>

        <div class="pastel1">목표 8-0</div>
        <div class="pastel2">목표 8-1</div>
        <div class="pastel3">목표 8-2</div>
        <div class="pastel4">목표 8-3</div>
        <div class="pastel5">목표 8-4</div>
        <div class="pastel6">목표 8-5</div>
        <div class="pastel7">목표 8-6</div>
        <div class="pastel8">목표 8-7</div>
        <div class="pastel1">목표 8-8</div>
    </div>

</section>

<ul class="listing">
{% for item in site.bullet %}
<li class="listing-item" tags="{% for tag in item.tags %}{{ tag }} {% endfor %}">
  <a href="{{ site.url }}{{ item.url }}">{{ item.title }}</a>
</li>
{% endfor %}
</ul>
