---
layout: post
title: Redmine, Mattermost 연동 방법
categories: [Redmine, Mattermost]
description: Redmine, Mattermost 연동 방법을 설명합니다. 
keywords: CI/CD, Redmine, Mattermost
toc: true
toc_sticky: true
---

### Redmine, Mattermost 간 연동

1. Redmine 에서 프로젝트에 접속
2. `설정` > `메신저` 클릭
3. 웹훅 발신에서 다음 값 입력
    - 메신저 URL : 기본값 또는 `Mattermost url` 입력
    - 메신저 채널 : `channel 이름` 입력 (보통 url 의 channels 뒤의 값 입력)
    - 메신저 사용자 이름 : `redmine` 또는 봇 이름 지정
4. `저장` 클릭

Redmine 과 Mattermost 는 이렇게 간단히 연동됩니다. 

이제 Redmine 의 프로젝트에서 이슈를 생성하거나, 수정, 삭제가 있을 때, Mattermost 로 알림이 가는 것을 확인할 수 있습니다! :smile: