---
layout: post
title: "서버리스 — Lambda & API Gateway"
categories: [AWS, Serverless]
description: AWS 서버리스의 핵심인 Lambda(함수/트리거/제한)와 API Gateway(REST/HTTP/WebSocket)를 정리합니다.
keywords: [Lambda, APIGateway, Serverless, AWS, 서버리스]
toc: true
toc_sticky: true
---

## Hook

> 서버를 켜두면 잠자는 시간에도 돈이 나갑니다. 트래픽이 100배로 늘어도 서버 한 대를 추가하지 못하고, 반대로 새벽에 트래픽이 0이 되어도 인스턴스 요금은 그대로입니다. 서버리스는 이 문제를 "코드가 실행된 시간만큼만" 과금하는 구조로 해결합니다.

AWS Lambda는 서버 프로비저닝 없이 코드를 실행하는 서버리스 컴퓨팅 서비스이고, API Gateway는 HTTP/WebSocket 엔드포인트를 생성·관리하는 프런트 도어입니다. 둘을 조합하면 서버 한 대 없이 수백만 요청을 처리하는 API를 만들 수 있습니다. 이 글에서는 Lambda의 함수 구성·트리거·호출 방식·제한·콜드스타트부터 API Gateway의 REST/HTTP/WebSocket 비교·인증·카나리 배포까지 정리하고, 실전 서버리스 아키텍처 패턴까지 다룹니다.

---

## TL;DR

- **Lambda 핵심** — 서버 없이 이벤트 기반으로 실행, ms 단위 과금, 최대 15분·10GB 메모리, 60개 이상 이벤트 소스 트리거
- **호출 3종** — 동기(결과 대기)/비동기(이벤트 위임)/스트림(폴링 배치), 용도에 따라 선택
- **콜드스타트 대응** — Provisioned Concurrency로 예열, SnapStart(Java)로 최대 90% 단축, Graviton2로 성능·비용 동시 개선
- **API Gateway 3종** — REST(풀기능), HTTP(저비용·고성능), WebSocket(양방향), 단순 Lambda 백엔드면 HTTP API가 권장
- **서버리스 3종 패턴** — API Gateway + Lambda + DynamoDB(동기 API), EventBridge + Lambda(이벤트 드리븐), Step Functions(오케스트레이션)

---

## Part 1. Lambda — 서버리스 컴퓨팅

AWS Lambda는 서버를 프로비저닝하거나 관리하지 않고 코드를 실행하는 서버리스 컴퓨팅 서비스입니다. 코드가 실행된 시간에만 비용을 지불하며, 이벤트가 발생하면 자동으로 실행되고 유휴 상태가 되면 스케일 인됩니다.

### Lambda 제한 (Limits)

| 항목 | 제한 | 비고 |
|------|------|------|
| **실행 시간** | 최대 15분 (900초) | 초과 시 타임아웃 |
| **메모리** | 128MB ~ 10GB | CPU·네트워크에 비례 할당 |
| **CPU** | 메모리에 비례 (최대 6 vCPU) | 6GB 이상부터 6 vCPU |
| **임시 스토리지** | /tmp 최대 10GB | EFS로 확장 가능 |
| **동시 실행** | 기본 1,000 (증가 요청 가능) | 계정·리전 단위 |
| **배포 패키지** | 50MB(직접) / 250MB(S3) | 컨테이너 이미지: 10GB |
| **비용** | 요청당 + 실행 시간(GB-초) | Graviton2 시 최대 20% 절감 |

### 함수 구성 요소

Lambda 함수는 코드·런타임·권한·환경으로 구성됩니다. 각 요소의 역할을 이해하면 함수 설계가 명확해집니다.

| 구성 요소 | 설명 |
|-----------|------|
| **Handler** | 런타임이 호출하는 진입점 함수 (event, context 수신) |
| **Runtime** | Python, Node.js, Java, .NET, Go, Ruby, Custom Runtime |
| **IAM Role (실행 역할)** | 함수가 접근할 AWS 서비스 권한 |
| **VPC 구성** | 프라이빗 리소스(RDS, ElastiCache) 접근 시 Subnet + SG |
| **환경 변수** | 설정값, KMS 암호화 지원 |
| **Layer** | 공통 종속성 패키징, 여러 함수에서 재사용 |
| **Extensions** | 코드 수정 없이 모니터링·보안·관측성 도구 통합 |

### 트리거 — 60개 이상 이벤트 소스

Lambda는 AWS 서비스 60개 이상의 이벤트를 트리거로 받을 수 있습니다. 트리거 방식은 크게 세 가지로 나뉩니다.

| 트리거 | 방식 | 설명 |
|--------|------|------|
| **API Gateway** | 동기 (Request) | HTTP 요청 기반 함수 실행 |
| **S3** | 비동기 (Event) | 객체 생성/삭제 이벤트 |
| **SNS** | 비동기 (Event) | SNS Topic 메시지 수신 |
| **EventBridge** | 비동기 (Event) | 이벤트 버스, 예약 일정(Cron) |
| **SQS** | 폴링 (Stream) | 큐 메시지 배치 처리 |
| **DynamoDB Streams** | 폴링 (Stream) | 테이블 변경 사항 처리 |
| **Kinesis** | 폴링 (Stream) | 스트림 레코드 배치 처리 |
| **CloudWatch Alarm** | 비동기 (Event) | 알람 상태 변경 시 실행 |

### 호출 방식 (Invocation)

Lambda는 호출 방식에 따라 동작과 비용 구조가 다릅니다. 용도에 맞게 선택해야 합니다.

| 호출 방식 | 동작 | 대표 사례 |
|-----------|------|-----------|
| **동기 (Sync)** | 호출자가 결과 대기, 응답 반환 | API Gateway, ALB, CLI |
| **비동기 (Async)** | 이벤트 큐에 적재 후 즉시 반환 | S3, SNS, EventBridge |
| **스트림 (Stream)** | 폴링 기반 배치 처리 | SQS, DynamoDB Streams, Kinesis |

```
[동기]  Client → Lambda → (실행) → 결과 반환 (Client 대기)
[비동기] Event Source → Event Queue → Lambda → (실행) → Destination
[스트림] Lambda ← Polling ← (SQS/DDB Streams/Kinesis) → 배치 처리
```

### Destinations — 성공/실패 전달

비동기 호출 시 함수 실행 결과(성공/실패)를 다른 서비스로 전달할 수 있습니다. DLQ(Dead Letter Queue)를 대체하는 더 강력한 메커니즘입니다.

| 전달 대상 | 성공 시 | 실패 시 |
|-----------|---------|---------|
| **SNS** | 알림 전송 | 에러 알림 |
| **SQS** | 후속 처리 큐잉 | 실패 메시지 큐잉 |
| **Lambda** | 체인 실행 | 에러 핸들러 |
| **EventBridge** | 이벤트 버스 전송 | 에러 이벤트 |

### 콜드스타트와 해결책

콜드스타트는 유휴 상태였던 실행 환경을 처음 초기화할 때 발생하는 지연입니다. 첫 호출에서 수백 ms ~ 수 초가 걸릴 수 있습니다.

```
[콜드스타트 발생]                          [워ARM 상태]
다운로드 → 초기화(Init) → 핸들러 실행    →   핸들러 실행 (빠름)
   ↑__________________________________________|
                 웜(Warm) 환경 재사용
```

| 해결책 | 효과 | 대상 |
|--------|------|------|
| **Provisioned Concurrency** | 실행 환경을 미리 예열, 지연 제거 | 모든 런타임 |
| **SnapStart** | 초기화된 스냅샷 복원, 최대 90% 단축 | Java 11/17 (Corretto) |
| **Graviton2 (ARM)** | 최대 19% 성능 향상 + 20% 비용 절감 | Python/Node/Java/.NET/Ruby/Go |

> 콜드스타트에 민감한 API 백엔드는 **Provisioned Concurrency**를 적용하고, Java 함수는 반드시 **SnapStart**를 활성화합니다.

### Lambda vs EC2

| 항목 | Lambda | EC2 |
|------|--------|-----|
| 서버 관리 | 불필요 | 필요 (OS, 패치) |
| 확장 | 자동 (이벤트 기반) | 수동 또는 Auto Scaling |
| 비용 | 실행 시간만큼 (ms 단위) | 인스턴스 실행 시간 (시간 단위) |
| 실행 시간 | 최대 15분 | 무제한 |
| 상태 | Stateless | 상태 유지 가능 |
| 콜드스타트 | 있음 | 없음 |
| 적합 | 짧은 작업, 이벤트 처리 | 장시간 실행, 상태 유지 |

---

## Part 2. API Gateway — 서버리스 API 프런트 도어

Amazon API Gateway는 REST API, HTTP API, WebSocket API를 생성·게시·유지·관리하는 완전관리형 서비스입니다. Lambda, HTTP 백엔드, AWS 서비스, Mock 등 다양한 통합을 지원합니다.

### REST API vs HTTP API vs WebSocket API

| 항목 | REST API | HTTP API | WebSocket API |
|------|----------|----------|---------------|
| **통신** | HTTP 요청/응답 | HTTP 요청/응답 | 양방향 실시간 |
| **비용** | $3.50/백만 요청 | $1.00/밀만 요청 | $1.00/백만 요청 |
| **지연** | 표준 | 최대 60% 낮음 | 실시간 |
| **캐싱** | 지원 | 미지원 | 미지원 |
| **요청 변환** | 매핑 템플릿 | 미지원 | N/A |
| **Usage Plans** | 지원 | 미지원 | N/A |
| **권장** | 복잡한 API, 풀 기능 | 단순 Lambda 백엔드 | 채팅, 실시간 알림 |

> 단순한 Lambda 백엔드라면 **HTTP API**를 선택하세요. REST API 대비 비용 1/3.5, 지연 최대 60% 감소, CORS 원클릭, 네이티브 JWT 인증을 지원합니다.

### Resource, Method, Stage, Integration

API Gateway는 리소스 경로와 메서드를 정의하고 백엔드(Lambda 등)와 통합한 뒤 Stage에 배포합니다.

```
API Gateway
├── Resource: /users
│   ├── GET  → Lambda: GetUsers
│   └── POST → Lambda: CreateUser
│       └── /{id}
│           ├── GET    → Lambda: GetUser
│           ├── PUT    → Lambda: UpdateUser
│           └── DELETE → Lambda: DeleteUser
├── Stage: dev   (v1)
├── Stage: prod  (v2)
└── Authorizer: Lambda / JWT / IAM / Cognito
```

| 개념 | 설명 |
|------|------|
| **Resource** | URL 경로 (`/users`, `/orders/{id}`) |
| **Method** | HTTP 메서드 (GET, POST, PUT, DELETE) |
| **Integration** | 백엔드 연결 (Lambda, HTTP, Mock, AWS Service) |
| **Stage** | 배포 환경 (dev, staging, prod) |
| **Deployment** | API 설정 변경 사항을 Stage에 배포 |
| **Authorizer** | 인증/인가 처리 |

### Canary Release 배포

새 버전을 일부 트래픽에만 점진적으로 노출하는 배포 전략입니다. 트래픽 비율을 10% → 25% → 50% → 100%로 점진적 승격하거나, 문제 발생 시 즉시 롤백합니다.

```
┌──────────────────────┐
│      API Gateway     │
│      (Stage: prod)   │
└──────────┬───────────┘
           │
     ┌─────┴──────┐
     │   Canary   │
     │   10%/90%  │
     ├────┬───────┤
     │    │       │
  10%│    │    90%│
     ▼    │       ▼
┌────────┐│  ┌──────────┐
│ Canary ││  │  Stable  │
│  v2    ││  │   v1     │
└────────┘│  └──────────┘
          │
    검증 후 승격/롤백
```

CloudWatch 지표로 에러율·지연 시간을 검증한 뒤 자동 승격 또는 롤백합니다. Stage 변수로 기능 토글도 가능합니다.

### Throttling & Usage Plans

| 기능 | 설명 |
|------|------|
| **Rate Limiting** | 초당 최대 요청 수 (throttle) |
| **Burst Limit** | 동시 스파이크 허용 요청 수 |
| **Usage Plans** | API 호출 한도 (초당/분당/월간) |
| **API Keys** | 고객별 키 발급, 사용량 추적 |
| **Quota** | 일/주/월간 최대 요청 수 |

### 인증 (Authorizers)

| Authorizer | 설명 | 지원 API |
|------------|------|----------|
| **Lambda Authorizer** | 커스텀 인증 로직 | REST, WebSocket |
| **JWT Authorizer** | OAuth 2.0 / OIDC 토큰 검증 | HTTP API |
| **IAM 인증** | AWS SigV4 서명 기반 | REST, HTTP, WebSocket |
| **Amazon Cognito** | User Pool 토큰 검증 | REST, HTTP |

### 2026년 업데이트

| 기능 | 효과 |
|------|------|
| **Lambda SnapStart** | Java 콜드스타트 최대 90% 감소 |
| **Response Streaming** | 응답 스트리밍, TTFB 단축, LLM 응답에 적합 |
| **10GB 메모리 + 6 vCPU** | 고성능 워크로드 처리 가능 |
| **Lambda Function URLs** | API Gateway 없이 직접 HTTP 엔드포인트 |
| **Graviton2 (ARM)** | 최대 20% 비용 절감, 19% 성능 향상 |
| **HTTP API (네이티브 JWT)** | REST API 대비 저비용·고성능 |
| **Private API (VPC Endpoint)** | 퍼블릭 노출 없는 프라이빗 API |

---

## Part 3. 서버리스 아키텍처 패턴

### 패턴 1. API Gateway + Lambda + DynamoDB (동기 API)

가장 대표적인 서버리스 CRUD API 패턴입니다. API Gateway가 요청을 받아 Lambda를 동기 호출하고, Lambda가 DynamoDB에 접근합니다.

```
┌────────────────────────────────────────────┐
│                 Client                      │
│          (Web / Mobile / IoT)               │
└──────────────────┬─────────────────────────┘
                   │ HTTPS
┌──────────────────▼─────────────────────────┐
│            API Gateway                      │
│     ┌──────────────────────────┐            │
│     │ Authorizer (JWT/Cognito) │            │
│     └──────────────────────────┘            │
│     GET /items  → Lambda:GetItems           │
│     POST /items → Lambda:CreateItem         │
└──────────────────┬─────────────────────────┘
                   │
┌──────────────────▼─────────────────────────┐
│              Lambda Functions               │
│     ┌─────────┐ ┌─────────┐ ┌──────────┐  │
│     │GetItems │ │CreateIt.│ │ GetItem  │  │
│     └────┬────┘ └────┬────┘ └────┬─────┘  │
└──────────┼───────────┼───────────┼─────────┘
           │           │           │
┌──────────▼───────────▼───────────▼─────────┐
│             DynamoDB                        │
│         Table: Items                        │
└────────────────────────────────────────────┘
```

### 패턴 2. EventBridge + Lambda (이벤트 드리븐)

이벤트 버스가 이벤트를 라우팅하고, 각 Lambda가 독립적으로 처리하는 느슨한 결합 아키텍처입니다. S3 업로드 → 썸네일 생성 → SNS 알림 같은 파이프라인에 적합합니다.

```
┌──────────┐   Event    ┌──────────┐   Trigger   ┌──────────┐
│  S3      │───────────▶│ Lambda   │────────────▶│ Lambda   │
│ (Upload) │  (PUT)     │(Thumbnail│             │(Process  │
│          │            │ Generate)│             │ Result)  │
└──────────┘            └────┬─────┘             └────┬─────┘
                             │                        │
                             ▼                        ▼
                        ┌──────────┐            ┌──────────┐
                        │  S3      │            │   SNS    │
                        │(Thumbn.  │            │(Notify   │
                        │ Output)  │            │ Result)  │
                        └──────────┘            └──────────┘
                                                       │
                                               ┌───────┼───────┐
                                               ▼       ▼       ▼
                                            Email   SQS    HTTP
                                                    Queue  Webhook
```

### 패턴 3. Step Functions 오케스트레이션

장기 실행·다단계·조건 분기가 필요한 워크플로우는 Step Functions로 오케스트레이션합니다. Lambda 함수를 상태 머신으로 연결하여 재시도·에러 처리·순차/병렬 실행을 선언적으로 관리합니다.

```
[Step Functions 상태 머신]

  Start
    │
    ▼
┌──────────┐     실패      ┌──────────────┐
│ Validate │──────────────▶│ Retry (3회)  │
│  Input   │               └──────┬───────┘
└────┬─────┘                      │
     │ 성공                        ▼
     ▼                        [Catch: DLQ]
┌──────────┐
│ Process  │───병렬───▶ ┌─────────┐ ┌─────────┐
│  Order   │            │ Payment │ │ Notify  │
└────┬─────┘            └─────────┘ └─────────┘
     │
     ▼
  Success
```

> 순차 호출이 2~3개 이상이면 Lambda-to-Lambda 체인 대신 Step Functions를 사용하세요. 재시도·타임아웃·에러 핸들링을 프레임워크가 관리합니다.

### SAM (Serverless Application Model)

서버리스 애플리케이션을 IaC로 정의하는 프레임워크입니다. CloudFormation을 확장하여 Lambda, API Gateway, DynamoDB를 간결하게 선언합니다.

```yaml
# template.yaml (SAM)
Transform: AWS::Serverless-2016-10-31
Resources:
  GetItemsFunction:
    Type: AWS::Serverless::Function
    Properties:
      CodeUri: src/get-items/
      Handler: app.handler
      Runtime: python3.11
      MemorySize: 256
      Timeout: 30
      Events:
        GetItems:
          Type: HttpApi
          Properties:
            Path: /items
            Method: GET
            ApiId: !Ref MyApi
  MyApi:
    Type: AWS::Serverless::HttpApi
    Properties:
      StageName: prod
```

| SAM CLI 명령 | 용도 |
|-------------|------|
| `sam build` | 애플리케이션 빌드 |
| `sam local invoke` | 로컬에서 함수 테스트 |
| `sam local start-api` | 로컬 API 서버 실행 |
| `sam deploy --guided` | 대화형 배포 |

---

## Takeaway

1. **Lambda는 이벤트 기반·ms 과금의 서버리스 컴퓨팅입니다** — 서버 관리 없이 60개 이상 이벤트 소스에 반응하며, 동기·비동기·스트림 세 가지 호출 방식과 성공/실패 Destination으로 유연한 파이프라인을 구성합니다. 콜드스타트는 Provisioned Concurrency(예열)와 SnapStart(Java)·Graviton2(ARM)로 해결합니다.
2. **API Gateway는 용도에 따라 3종으로 선택합니다** — 풀 기능과 캐싱이 필요한 복잡한 API는 REST API, 단순 Lambda 백엔드와 저비용·고성능이 필요하면 HTTP API(비용 1/3.5, 지연 60% 감소), 양방향 실시간 통신은 WebSocket API를 사용합니다. 카나리 배포·쓰로틀링·네 가지 인증(IAM/Cognito/Lambda/JWT)으로 운영 수준의 API를 관리합니다.
3. **서버리스 패턴 3종으로 대부분의 아키텍처를 커버합니다** — 동기 API는 API Gateway + Lambda + DynamoDB, 이벤트 드리븐은 EventBridge + Lambda + SNS/SQS, 다단계 워크플로우는 Step Functions로 오케스트레이션합니다. SAM으로 IaC를 관리하고 `sam local`로 로컬 테스트 후 배포하면 서버 한 대 없이 프로덕션급 시스템을 구축할 수 있습니다.
