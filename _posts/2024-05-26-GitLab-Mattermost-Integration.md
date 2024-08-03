---
layout: post
title: GitLab, Mattermost 웹 훅 설정과 subscription 설정
categories: [GitLab, Mattermost]
description: GitLab, Mattermost 연동 방법을 설명합니다. 
keywords: CI/CD, GitLab, Mattermost
toc: true
toc_sticky: true
---

### Mattermost 에서 GitLab 의 웹 훅 설정

1. 연결할 채팅창에 접속

<br>

2. gitlab 연결

```bash
/gitlab connect
```

<br>

3. subscription 설정

```bash
/gitlab subscriptions add myrepo/myproject issues,merges,pushes,issue_comments,merge_request_comments,pipeline,tag,pull_reviews

Successfully subscribed to myrepo/myproject
```

<br>

4. 웹 훅 설정

```bash
/gitlab webhook add myrepo/myproject

Webhook Created:

`https://chat.lhjnano.com/plugins/com.github.manland.mattermost-plugin-gitlab/webhook`
```

<br>

5. 테스트

GitLab 의 프로젝트에서 `Settings` > `Webhook` 에서 등록된 프로젝트 홈으로 테스트로 확인할 수 있습니다 :smile:

<br>


---

### 참고 

* [Mattermost 에서 웹훅 설정](https://github.com/mattermost/mattermost-plugin-gitlab)

