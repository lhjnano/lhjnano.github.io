---
layout: post
title: GitLab 에서 Badge 연결하는 방법
categories: [GitLab]
description: GitLab 에서 Badge 연결하는 방법을 설명합니다.
keywords: GitLab
toc: true
toc_sticky: true
---

### Gitlab 에서 Badge 설정

1. `Project` => `Settings` => `Genernal` => `Badges` => `Add badge` 클릭 후 다음을 입력
   1. name: `coverage`
   2. link: `https://GitLab주소/%{project_path}/-/commits/%{default_branch}`
   3. Badge image URL: `https://GitLab주소/%{project_path}/badges/%{default_branch}/coverage.svg`
   4. name: `pipeline
   5. link: `https://GitLab주소/%{project_path}/-/commits/%{default_branch}`
   6. Badge image URL: `https://GitLab주소/%{project_path}/badges/%

### Gitlab CI 에서 수치 적용

1. `.gitlab-ci.yml` 에서 `test` 단계에서 `cover` 수행 후 `coverage` 수치 적용
   - 수치 적용은 프로그램에 따라 다를 수 있음.

```yaml
test:
  stage: test
  script:
    - cover -delete
    - >
      TEST_VERBOSE=1 HARNESS_PERL_SWITCHES=-MDevel::Cover
      prove -lvm -I${LIB_DIR} t/unit.t :: --statistics
    - cover -ignore_re '^t/'
  coverage: '/^(?i)Total\s+.*\s+([\d\.]+)$/'
  artifacts:
    when: always
    paths:
      - cover_db
      - unit.log
    expire_in: 1 week
```
