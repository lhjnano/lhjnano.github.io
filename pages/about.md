---
layout: page
title: About
description: 개발 기록기
keywords: HeonJe Lee, 이헌제
comments: true
menu: 소개
permalink: /about/
---

개발을 하면서 다시 사용할 컨텐츠를 정리합니다.

정리는 언제나 저에게도 당신에게도 도움이 될 수 있습니다. 

Let's go to make my search GPT!

## Contact

<ul>
{% for website in site.data.social %}
<li>{{website.sitename }}：<a href="{{ website.url }}" target="_blank">@{{ website.name }}</a></li>
{% endfor %}
</ul>


## Skill Keywords

{% for skill in site.data.skills %}
### {{ skill.name }}
<div class="btn-inline">
{% for keyword in skill.keywords %}
<button class="btn btn-outline" type="button">{{ keyword }}</button>
{% endfor %}
</div>
{% endfor %}