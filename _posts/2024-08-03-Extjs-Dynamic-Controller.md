---
layout: post
title: Extjs 에서 동적으로 Controller 를 추가하는 방법
categories: [Extjs, MVC]
description: Redmine, GitLab 저장소 연동 방법과 이슈 링크 연결을 설명합니다. 
keywords: Extjs, MVC, Dynamic, Controller, Application, getApplicationm, 동적, 로드, load, 컨트롤러, 어플리케이션, 여러
toc: true
toc_sticky: true
---


> 본 포스트는 Ext 4.1.0 을 기준으로 작성되었습니다. 

대규모 웹 애플리케이션을 개발할 때, MVC 아키텍처를 활용하여 웹 애플리케이션을 구축하게 됩니다. 이 과정에서 수많은 동료와 팀이 협력하게 되는데, 이로 인해 프로젝트의 복잡성이 증가합니다. 또한, 많은 기능이 동시에 로드되는 상황에서는 성능과 자원 사용의 효율화가 중요해집니다. 따라서, 이러한 문제를 해결하기 위해 동적으로 기능을 로드할 수 있는 방법이 필요하게 됩니다.


<br>

### 들어가기 전에

ExtJS MVC는 Sencha의 ExtJS 프레임워크를 기반으로 한 MVC (Model-View-Controller) 아키텍처를 제공합니다. 이 아키텍처는 웹 애플리케이션의 구조를 명확하게 구분하여 유지보수성과 확장성을 향상시키는 데 도움을 줍니다.

우선 어플리케이션에서는 다음과 같이 Controller 를 등록할 수 있습니다. 

* Application

```javascript
Ext.application({
    extend: 'Ext.app.Application',
    name: 'MyApp',
    appFolder: '/app',
    autoCreateViewport: true,
    controllers: [
        'manage.User',
    ],
});
```

* Controller

```javascript
Ext.define('MyApp.controller.manage.User', {
    extned: 'Ext.app.Controller',
    views: [
        'manage.User',
    ],
    stores: [
        'manage.User',
    ],
    init: function (app) {
        this.control({
            '#AddUserButton' : {
                ...
            }
        });
    }
});
```

Application 을 통해서 Controller 를 등록하고 Controller 에 등록되어 생성된 view 과 store 를 통해서 사용자는 로드된 컴포넌트를 제어할 수 있게 됩니다. 

<br>

### 동적 Controller

본론으로 들어가서 동적으로 컨트롤러를 추가하려면 어떻게 해야 할까요.
현재로써는 Application 에서 모든 관리자가 controller 를 정의해주는 수 밖에 없습니다. Extjs 에서는 어떻게 Controller 를 로드하고 있는지 알아봅시다. 

```javascript
initControllers: function() {
    var me = this,
        controllers = Ext.Array.from(me.controllers);

    me.controllers = new Ext.util.MixedCollection();

    for (var i = 0, ln = controllers.length; i < ln; i++) {
        me.getController(controllers[i]);
    }
},
```

Application 의 controllers 에 등록된 정보를 가져와서 `getController` 를 합니다. 

```javascript
    getController: function(name) {
        var me          = this,
            controllers = me.controllers,
            className, controller;

        controller = controllers.get(name);

        if (!controller) {
            className  = me.getModuleClassName(name, 'controller');

            controller = Ext.create(className, {
                application: me,
                id:          name
            });

            controllers.add(controller);

            if (me._initialized) {
                controller.doInit(me);
            }
        }
```

그리고 `getController` 에서는 해당 이름을 생성하여 Application 에 추가하고 초기화를 시행합니다. 생각보다 간단한 원리로 Controller 가 로드되고 있었네요!

<br>

이제 동적으로 Controller 를 로드해볼까요? 우선 다음과 같이 어플리케이션에서 동적으로 컨트롤러를 추가할 수 있도록 해봅시다. 

```javascript
Ext.require('Ext.app.Application', function () {
    // Ext.app.Application 가 로드된 후에 실행되는 코드
    Ext.app.Application.addMemebers({
        hasController: function (name) {
            return !!this.controllers.get(name);
        },
        addController: function (name) {
            return this.getController(name);
        }
    }) ;  
};
```

그리고 실제로 추가했을 때, `getCotroller` 에서 초기화까지 수행하므로 별도로 해줘야 할 것은 없습니다. 이제 실제로 추가해볼까요?

동적으로 추가할 경우는 어떤 메뉴트리 또는 버튼을 눌렀을 경우, 컨트롤러를 동적으로 추가해줄 수 있도록 합니다.

```bash
function(button) {
    let app = MyApp.getApplication();

    if (!app.hasController('manage.User')) {
        app.addController('manage.User');
    }

    ...
}
```

간단하죠? 여러분도 이제 동적으로 컨트롤러를 추가할 수 있게 되었습니다 :smile:
