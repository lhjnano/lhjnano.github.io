---
layout: post
title: Redmine, GitLab 연동
categories: [GitLab, Redmine]
description: Redmine, GitLab 저장소 연동 방법과 이슈 링크 연결을 설명합니다. 
keywords: CI/CD, Redmine, GitLab
toc: true
toc_sticky: true
---

Redmine 과 GitLab 을 연동 시에 필요한 정보를 작성합니다. 
우선 `저장소`를 연동 전에 필요한 정보가 어떤 것이 있나 조회하고 넘어가 봅시다.

### 저장소 연결 시 필요 정보

* 연결할 GitLab 프로젝트 : `https://gitlab.lhjnano.com/myproject/myrepo.git`
    * 필요 권한 : GitlLab repository maintainer
* Redmine 서버 : redmine-ip / redmine-port
    * 접근 계정 : redmine-id / redmine-pw



### Redmine 서버 GitLab Repository mirroring

Redmine 서버에서 GitLab 의 최신 소스를 유지할 수 있도록 구성합니다.  그러기 위해서 gitlab repository 를 주기적으로 fetch 할 예정입니다. 

우선 저장할 경로를 생성합니다.

```bash
mkdir git_repos/myproject/myrepo.git
```

그런 다음 git 명령을 통해서 미러링합니다.

> :bulb: **NOTE** <br>
> Git mirror는 기본적으로 원격 저장소의 복제본을 만드는 데 사용됩니다. 이는 특히 원격 저장소가 손상되거나 유실될 경우 해당 코드의 백업을 보장하는 데 유용합니다. git clone --mirror 명령을 통해 원격 저장소를 미러링할 수 있습니다. 이 명령은 모든 참조(heads, notes, tags, and others)와 함께 원격 저장소를 복제합니다.


```bash
git clone --mirror https://gitlab.lhjnano.com/myproject/myrepo.git git_repos/myproject/myrepo.git
```

Cron 으로 주기적으로 미러링을 할 수 있게 합니다. 
`default_path` 에는 git_repos 를 생성한 경로를 지정합니다.

```
$ cat /etc/cron.minutely/git_mirror.sh < EOT
#!/bin/bash

for repo in $(find {default_path}/git_repos -type d -name '*.git');
do
	pushd $repo;
	git fetch --all --prune;
	popd;
done;
EOT
```

### Redmine 저장소 추가

Redmine 의 프로젝트와 GitLab 의 저장소를 이제 연동해봅시다. 

1. {Redmine 프로젝트} 접속
2. `설정` > `저장소` > `저장소 추가` 클릭 
     - 설정 정보는 권한에 따라서 접근이 불가능할 수도 있습니다. 관리자에게 권한을 요청하세요.
3. 다음 정보를 설정하여 저장합니다. 
    - 형상관리 시스템 : git
    - 주 저장소 : [v]
    - 식별자 : myrepo
    - 저장소 경로 : {default_path}/git_repos/myproject/myrepo.git
    - 경로 인코딩 : UTF-8
    - 파일이나 폴더의 마지막 커밋을 보고 : [v]
    - `만들기` 클릭


이제 저장소 연결이 완료되었습니다 :smile:

---

Redmine 의 이슈번호도 GitLab 에서 연결될 수 있도록 해보겠습니다. 
이번에는 간단한 설정만으로도 연결이 가능합니다. 

### GitLab 에 Redmine Issue 링크

GitLab 에서 프로젝트에 들어가서 다음의 과정을 진행합니다. 

1. `Settings` > `Integrations` > `Redmine` 을 설정하여 다음을 입력
    - Project URL : https://{redmine-url}/projects/{project}
    - Issue URL : https://{redmine-url}/issues/:id
    - New Issue URL : https://{redmine-url}/issues/:id
2. GitLab 에서 제공하는 `issue` 를 사용하면 연동이 되지 않으므로 `off`
    - `Settings` > `General` > `Visibility, Project features, Permissions` > `Issues` [off]

> :bulb: **NOTE** <br>
> GitLab 에서 제공하는 Issue 를 사용하지 않게 되면 Plan 의 Issue 가 비활성화 됩니다. 이미 제공하는 이슈 목록이 있다면, Redmine 에서 다시 작성하세요!
