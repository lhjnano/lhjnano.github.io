---
layout: post
title: 로컬에서 ExtJS 실행하기
categories: [ExtJS, Sencha]
description: 로컬에서 ExtJS 를 실행하는 방법을 설명합니다.
keywords: ExtJS
toc: true
toc_sticky: true
---

본 포스트는 Ubuntu 24.04 를 기준으로 작성되었습니다.

<br>

### Sencha 설치

1. 의존성 패키지를 다운로드 합니다.

```bash
sudo apt update
sudo apt -y install default-jre unzip

# sencha zip 파일 다운로드
wget https://trials.sencha.com/cmd/7.8.0/SenchaCmd-7.8.0.59-linux-amd64.sh.zip

# 압축 해제
unzip SenchaCmd-7.8.0.59-linux-amd64.sh.zip

# 설치 스크립트 실행 (설치한 위치는 기억)
./SenchaCmd-7.8.0.59-linux-amd64.sh

...
Where should Sencha Cmd be installed?
[/home/lhj/bin/Sencha/Cmd/7.8.0.59]
```

2. reboot 후 `sencha` 커멘드가 활성화 되는지 확인합니다.

```bash
sencha
Sencha Cmd v7.8.0.59
Sencha Cmd provides several categories of commands and some global switches. In
most cases, the first step is to generate an application based on a Sencha SDK
such as Ext JS or Sencha Touch:

    sencha -sdk /path/to/sdk generate app MyApp /path/to/myapp

Sencha Cmd supports Ext JS 4.1.1a and higher and Sencha Touch 2.1 and higher.

To get help on commands use the help command:

    sencha help generate app

For more information on using Sencha Cmd, consult the guides found here:

http://docs.sencha.com/cmd/
```

<br>

### 테스트 앱 생성

`ext-app` 폴더에 테스트 앱을 생성해봅니다.

```bash
$ sencha generate app --ext MyApp ./ext-app
Sencha Cmd v7.8.0.59
[INF] Loading framework from /home/lhj/bin/Sencha/Cmd/repo/extract/ext/7.8.0.33
[INF] Package is already local: ext/7.8.0.33
[INF] Extracting  : ....................
[INF] Processing Build Descriptor : classic (development environment)
[INF] Loading compiler context
[INF] Loading app json manifest...
[INF] Appending content to /home/lhj/bootstrap.js
[INF] Writing content to /home/lhj/classic.json
[INF] merging 265 input resources into /home/lhj/build/development/MyApp/classic/resources
[INF] merged 265 resources into /home/lhj/build/development
```

<br>

### 테스트 코드 작성

`ext-app` 폴더에서 `app/Application.js` 를 작성하고 다음과 같이 작성합니다.

```bash
cd ext-app
cat app/Application.js   # 다음과 같이 코드를 변경
Ext.define('MyApp.Application', {
        extend: 'Ext.app.Application',
        name: 'MyApp',

        launch: function() {
                Ext.create('Ext.container.Viewport', {
                        layout: 'fit',
                        items: [
                                { title: 'Hello World!', html : 'Hello! Welcome to ExtJS.' }
                        ]
                });
        }
});

```

<br>

### 테스트 실행

이제 로컬에서 작성한 테스트 코드로 실행해봅니다.

```bash
sencha web start
Sencha Cmd v7.5.1.20
WARNING: An illegal reflective access operation has occurred
WARNING: Illegal reflective access by com.google.gson.internal.bind.ReflectiveTypeAdapterFactory (file:/home/lhj/bin/Sencha/Cmd/7.5.1.20/lib/closure-compiler-v20180610.jar) to field java.io.File.path
WARNING: Please consider reporting this to the maintainers of com.google.gson.internal.bind.ReflectiveTypeAdapterFactory
WARNING: Use --illegal-access=warn to enable warnings of further illegal reflective access operations
WARNING: All illegal access operations will be denied in a future release
[INF] Starting server on port : 1841
[INF] Mapping http://localhost:1841/ to /Study/my-app...
[INF] Server started at port : 1841
```

<br>

### 참고

- [install sencha](https://www.radiusdesk.com/docuwiki/user_guide/extjs/sencha)
