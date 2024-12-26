---
layout: post
title: Jenkins 빌드 오류 "Failed to fetch from"
categories: [Jenkins]
description: Jenkins 에서 빌드 시 오류를 설명합니다.
keywords: CI/CD, Jenkins
toc: true
toc_sticky: true
---

### Jenkins 이슈 로그

Jenkins 에서 빌드 시 다음과 같은 오류가 발생하였다.

```bash
**15:00:00**  ERROR: Error fetching remote repo 'lhj4125'
**15:00:00**  hudson.plugins.git.GitException: Failed to fetch from git@gitlab.com:lhj4125/myProject.git
**15:00:00**  	at hudson.plugins.git.GitSCM.fetchFrom(GitSCM.java:999)
**15:00:00**  	at hudson.plugins.git.GitSCM.retrieveChanges(GitSCM.java:1241)
**15:00:00**  	at hudson.plugins.git.GitSCM.checkout(GitSCM.java:1305)
**15:00:00**  	at org.jenkinsci.plugins.workflow.steps.scm.SCMStep.checkout(SCMStep.java:136)
**15:00:00**  	at org.jenkinsci.plugins.workflow.steps.scm.SCMStep$StepExecutionImpl.run(SCMStep.java:101)
**15:00:00**  	at org.jenkinsci.plugins.workflow.steps.scm.SCMStep$StepExecutionImpl.run(SCMStep.java:88)
**15:00:00**  	at org.jenkinsci.plugins.workflow.steps.SynchronousNonBlockingStepExecution.lambda$start$0(SynchronousNonBlockingStepExecution.java:47)
```

### 해결

권한이 없다는 메시지이고, 다음의 절차를 통해서 해결 할 수 있다.

1. GitLab Project 접속
2. `Setting` -> `Repository` -> `Deploy keys` -> `Enabled deploy keys` 에서 `Jenkins` key 가 있는지 확인
3. 없다면 `Publicly accessible deploy keys` 에서 `Enable` 시켜줘야 한다.
