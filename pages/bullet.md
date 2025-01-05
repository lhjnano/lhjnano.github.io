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
        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel1"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel2"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>
        <div class="pastel3"></div>

        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel1">System</div>
        <div class="pastel2">클라우드 서비스</div>
        <div class="pastel3">Network</div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>

        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel4">건강 성장</div>
        <div class="center"><strong>기록하며 성장하는 나</strong></div>
        <div class="pastel5">내면 성장</div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>

        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel4"></div>
        <div class="pastel6">IaC</div>
        <div class="pastel7">컨테이너</div>
        <div class="pastel8">CI/CD</div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>
        <div class="pastel5"></div>

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
