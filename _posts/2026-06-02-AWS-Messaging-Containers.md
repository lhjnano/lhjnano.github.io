---
layout: post
title: "[AWS 12/16] 메시징 & 컨테이너: SQS/SNS/Kinesis와 ECS/EKS"
categories: [AWS, Architecture]
description: 비동기 메시징(SQS/SNS/Kinesis/EventBridge/MSK)과 컨테이너 오케스트레이션(ECS/EKS/Fargate)을 정리합니다.
keywords: [SQS, SNS, Kinesis, ECS, EKS, Fargate, AWS]
toc: true
toc_sticky: true
---

## Hook

> 주문이 들어오면 결제, 재고, 배송, 알림이 차례로 기다려야 합니다. 하나라도 실패하면 전체가 멈춥니다. 이 강결합을 끊어주는 것이 메시징이고, 늘어난 마이크로서비스를 가볍게 띄워주는 것이 컨테이너입니다.

분산 시스템에서 서비스 간 통신은 동기식과 비동기식으로 나뉩니다. SQS/SNS/Kinesis/EventBridge는 통신을 비동기화하여 시스템을 디커플링하고, ECS/EKS/Fargate는 컨테이너 단위로 애플리케이션을 가볍고 빠르게 배포합니다. 이 글에서는 Part 1에서 SQS의 큐 유형과 가시성 제한, SNS의 Pub/Sub, Fan-out 패턴, Kinesis의 Streams/Firehose/Analytics, EventBridge와 MSK까지 정리하고, Part 2에서 VM과 컨테이너의 차이, Docker 기초, ECS의 Fargate/EC2 시작 유형, ECR, Kubernetes 핵심 개념, EKS, Fargate 비교까지 다룹니다.

---

## TL;DR

- **동기 vs 비동기**: 동기는 강결합·장애 전파, 비동기 메시징은 느슨한 결합·메시지 보존으로 복구 후 처리
- **SQS는 Pull, SNS는 Push**: SQS는 작업 큐(최소 1회), SNS는 Pub/Sub 브로드캐스트, 둘을 묶으면 Fan-out
- **Kinesis 3종**: Streams(실시간 샤드), Firehose(준실시간 자동 적재), Analytics(SQL/Flink 실시간 분석)
- **EventBridge는 2026 핵심**: 콘텐츠 기반 필터링·스키마 레지스트리·아카이브/재생 지원, 단순 브로드캐스트 SNS와 역할 분담
- **컨테이너는 VM보다 가볍다**: OS 커널 공유, MB 단위, 초 단위 시작, 높은 밀도
- **ECS는 단순, EKS는 표준**: ECS+Fargate로 서버리스 컨테이너, EKS로 K8s 네이티브 생태계 활용

---

## Part 1. 메시징 서비스

### 동기식 vs 비동기식 통신

분산 시스템에서 메시징 서비스는 서비스 간 결합도를 낮춰 독립성과 확장성을 확보합니다.

| 구분 | 동기식 | 비동기식 |
|------|--------|----------|
| 통신 방식 | 요청-응답 (직접 호출) | 메시지 큐 / 이벤트 |
| 결합도 | 강결합 (Tight Coupling) | 느슨한 결합 (Loose Coupling) |
| 장애 전파 | 수신자 장애 시 호출 실패 | 메시지 보존, 복구 후 처리 |
| 확장성 | 제한적 | 우수 |
| AWS 서비스 | API Gateway, 직접 호출 | SQS, SNS, Kinesis, EventBridge |

### SQS (Simple Queue Service)

완전관리형 메시지 큐 서비스입니다. **Pull 기반**으로 소비자가 큐에서 메시지를 가져옵니다.

**Standard vs FIFO Queue:**

| 항목 | Standard Queue | FIFO Queue |
|------|----------------|------------|
| 순서 보장 | 최선 노력 (Best Effort) | 엄격한 순서 보장 (First-In-First-Out) |
| 중복 가능성 | 최소 1회 전달 (at-least-once) | 정확히 1회 전달 (exactly-once) |
| 처리량 | 거의 무제한 | 초당 300개 (배치 없음), 3000개 (배치) |
| 이름 접미사 | 없음 | `.fifo` 필수 |
| 사용 사례 | 작업 큐, 로그 처리 | 주문 처리, 금융 거래 |

**주요 속성:**

| 속성 | 값 | 설명 |
|------|----|------|
| 메시지 크기 | 최대 256KB | 초과 시 S3 참조 사용 |
| 보존 기간 | 4일 ~ 14일 | 기본 4일 |
| 가시성 시간 제한 | 기본 30초 | 처리 중 메시지를 다른 소비자에게 숨김 |
| Long Polling | 최대 20초 | 빈 응답 감소, API 호출 비용 절감 |
| 지연 큐 | 최대 15분 | 메시지 전달 지연 |

> 가시성 시간 제한(Visibility Timeout)은 한 소비자가 메시지를 처리하는 동안 다른 소비자가 같은 메시지를 꺼내지 못하게 숨깁니다. 처리가 끝나면 삭제하고, 시간 초과 시 다시 노출되어 재시도됩니다.

**보안:**
- 전송 중 암호화: HTTPS (TLS)
- 저장 시 암호화: SSE-SQS (AWS 관리 키) 또는 SSE-KMS
- 액세스 제어: IAM 정책, 큐 정책

### SNS (Simple Notification Service)

**Publish/Subscribe 모델**의 완전관리형 알림 서비스입니다. **Push 방식**으로 구독자에게 메시지를 전달합니다.

| 구독 대상 | 용도 |
|-----------|------|
| HTTP(s) | 웹훅 엔드포인트 |
| 이메일 | 알림 이메일 |
| SQS | 큐 기반 비동기 처리 |
| Lambda | 서버리스 함수 실행 |
| Kinesis Firehose | 데이터 스트리밍 전송 |
| 모바일 Push | APNs, FCM |

**FIFO Topic:**
- 순서 보장 + 중복 제거
- SQS FIFO Queue와만 호환
- 초당 300개 메시지 (배치 시 3000개)
- 메시지 그룹 ID 기반 파티셔닝

### SNS + SQS Fan-out 패턴

하나의 이벤트를 **여러 소비자에게 병렬로 전달**하는 아키텍처 패턴입니다.

<details markdown="1">
<summary>SNS + SQS Fan-out 패턴</summary>

```
┌───────────────────────────┐
│        Producer           │
│    (S3 Event, Lambda 등)  │
└────────────┬──────────────┘
             │ Publish
┌────────────▼──────────────┐
│       SNS Topic           │
└─┬──────────┬──────────┬───┘
  │          │          │
  ▼          ▼          ▼
┌─────┐  ┌─────┐  ┌─────┐
│ SQS │  │ SQS │  │ SQS │
│Queue│  │Queue│  │Queue│
│ #1  │  │ #2  │  │ #3  │
└──┬──┘  └──┬──┘  └──┬──┘
   │        │        │
   ▼        ▼        ▼
┌─────┐  ┌─────┐  ┌─────┐
│Lambda│ │EC2  │ │Email│
│처리  │ │배치 │ │알림 │
└─────┘  └─────┘  └─────┘
```
</details>

- 각 소비자는 독립적으로 메시지를 처리합니다
- 한 소비자의 장애가 다른 소비자에게 영향을 주지 않습니다
- SQS의 재시도 및 DLQ(Dead Letter Queue)를 활용할 수 있습니다

### Kinesis Data Streams

대규모 **실시간 데이터 스트리밍** 서비스입니다. 데이터를 수집, 저장, 처리할 수 있습니다.

| 개념 | 설명 |
|------|------|
| Shard | 데이터 처리 단위 (초당 1MB 입력 / 2MB 출력, 1000 records/s) |
| Partition Key | 데이터를 특정 Shard에 라우팅하기 위한 키 |
| Sequence Number | 각 레코드의 고유 식별자 |
| 보존 기간 | 24시간 ~ 365일 (기본 24시간) |
| 레코드 크기 | 최대 1MB |

> 💡 **Kinesis vs SQS:** Kinesis는 실시간 스트리밍과 데이터 재생이 필요한 경우, SQS는 작업 큐와 비동기 메시징에 적합합니다.

### Kinesis Data Firehose

스트리밍 데이터를 **변환 및 전송**하는 완전관리형 서비스입니다. 실시간보다는 **준실시간(Near Real-time)** 처리에 적합합니다.

```
┌──────────┐     ┌─────────────────────┐     ┌─────────────┐
│  Data     │────▶│  Kinesis Firehose   │────▶│  S3         │
│  Source   │     │  (변환 Lambda 포함) │     │  Redshift   │
└──────────┘     └─────────────────────┘     │  OpenSearch  │
                                              │  Snowflake   │
                                              └─────────────┘
```

- 버퍼링: 크기(1~128MB) 또는 시간(60~900초) 기반 자동 적재
- 변환: Lambda 함수로 데이터 변환 가능
- 전송 대상: S3, Redshift, OpenSearch, Splunk, Snowflake 등
- 샤드 관리 불필요, 자동 확장

### Kinesis Data Analytics

스트리밍 데이터를 **SQL 또는 Python(Apache Flink)**로 실시간 분석합니다.

- SQL 기반 실시간 쿼리
- Apache Flink 기반 Python 애플리케이션
- 창 함수(Window Functions): Tumbling, Sliding, Session
- 입력: Kinesis Data Streams, Firehose
- 출력: S3, Firehose, Lambda

### Amazon EventBridge: 2026 핵심

서버리스 **이벤트 버스** 서비스로, 이벤트 기반 아키텍처의 핵심입니다.

| 구분 | EventBridge | SNS |
|------|-------------|-----|
| 모델 | 이벤트 버스 (Router) | Pub/Sub (Broadcast) |
| 필터링 | 고급 콘텐츠 기반 필터링 | 제한적 |
| 스키마 | 레지스트리 / 검색 | 없음 |
| AWS 서비스 연동 | 90+ 서비스 이벤트 자동 수신 | 수동 구성 |
| 아카이브/재생 | 지원 | 미지원 |

- 기본 버스: AWS 계정의 기본 이벤트 버스
- 커스텀 버스: 애플리케이션 전용 이벤트 버스
- 파트너 버스: SaaS 파트너 이벤트 수신
- 규칙(Rule): 이벤트 패턴 매칭으로 타겟 라우팅

**이벤트 기반 아키텍처 패턴:**

```
┌────────┐  ┌────────┐  ┌────────┐
│ S3     │  │DynamoDB│  │EC2     │
│ 이벤트 │  │Streams │  │앱 이벤트│
└───┬────┘  └───┬────┘  └───┬────┘
    │           │           │
    └───────────┼───────────┘
                ▼
┌───────────────────────────┐
│    EventBridge 이벤트 버스  │
│    ┌─────────────────┐    │
│    │ Rule (필터링)    │    │
│    └──┬──────┬───────┘    │
└───────┼──────┼────────────┘
        │      │
   ┌────▼──┐ ┌─▼─────┐
   │Lambda │ │Step   │
   │함수   │ │Function│
   └───────┘ └───────┘
```

**스트리밍 파이프라인 패턴:**

```
┌──────────┐   ┌─────────────┐   ┌──────────────┐   ┌──────────┐
│ IoT /    │──▶│   Kinesis   │──▶│   Kinesis    │──▶│   S3     │
│ Click    │   │   Data      │   │   Data       │   │  (Data   │
│ Stream   │   │   Streams   │   │   Firehose   │   │   Lake)  │
└──────────┘   └──────┬──────┘   └──────────────┘   └──────────┘
                      │
                      ▼
               ┌──────────────┐
               │   Kinesis    │
               │   Analytics  │
               │   (실시간    │
               │    분석)     │
               └──────────────┘
```

### Amazon MSK (Managed Streaming for Apache Kafka)

Apache Kafka 클러스터를 완전관리형으로 제공합니다. Kafka 네이티브 API를 그대로 사용할 수 있습니다.

| 비교 항목 | Kinesis | MSK |
|-----------|---------|-----|
| 프로토콜 | AWS 전용 | Kafka 프로토콜 |
| 보존 기간 | 최대 365일 | 무제한 (스토리지 기반) |
| 파티션 | Shard | Partition |
| 관리 | 완전 서버리스 | 관리형 (브로커 관리 포함) |
| 마이그레이션 | AWS 전용 | 온프레미스 Kafka 마이그레이션 용이 |

---

## Part 2. 컨테이너 서비스

### VM vs Container

컨테이너는 OS 레벨 가상화로 호스트 커널을 공유하여 가볍고 빠릅니다.

| 구분 | 가상 머신 (VM) | 컨테이너 (Container) |
|------|----------------|----------------------|
| 가상화 방식 | 하드웨어 가상화 (Hypervisor) | OS 레벨 가상화 |
| 격리 수준 | 완전 격리 (별도 커널) | 프로세스 격리 (호스트 커널 공유) |
| 크기 | GB 단위 (OS 포함) | MB 단위 (앱 + 종속성만) |
| 시작 시간 | 분 단위 | 초 단위 |
| 오버헤드 | 높음 (Guest OS) | 낮음 (호스트 OS 공유) |
| 밀도 | 낮음 | 높음 (동일 호스트에 다수 배포) |

```
┌─── VM ───────────────────┐  ┌─── Container ──────────────────┐
│  ┌─────────┐ ┌─────────┐ │  │ ┌───────┐ ┌───────┐ ┌───────┐ │
│  │  App A  │ │  App B  │ │  │ │ App A │ │ App B │ │ App C │ │
│  ├─────────┤ ├─────────┤ │  │ ├───────┤ ├───────┤ ├───────┤ │
│  │Guest OS │ │Guest OS │ │  │ │Bins/  │ │Bins/  │ │Bins/  │ │
│  │         │ │         │ │  │ │Libs   │ │Libs   │ │Libs   │ │
│  ├─────────┴─┴─────────┤ │  │ ├───────┴─┴───────┴─┴───────┤ │
│  │     Hypervisor       │ │  │ │   Container Runtime       │ │
│  ├──────────────────────┤ │  │ ├───────────────────────────┤ │
│  │     Host OS          │ │  │ │       Host OS             │ │
│  ├──────────────────────┤ │  │ ├───────────────────────────┤ │
│  │    Infrastructure    │ │  │ │     Infrastructure        │ │
│  └──────────────────────┘ │  │ └───────────────────────────┘ │
└──────────────────────────┘  └───────────────────────────────┘
```

### Docker

컨테이너를 **생성, 관리, 실행**하는 오픈소스 플랫폼입니다.

| 개념 | 설명 |
|------|------|
| Dockerfile | 컨테이너 이미지 빌드 지시서 |
| Image | 컨테이너 실행용 읽기 전용 템플릿 |
| Container | 이미지의 실행 인스턴스 |
| Registry | 이미지 저장소 (Docker Hub, ECR) |

```dockerfile
# Dockerfile 예시
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
EXPOSE 3000
CMD ["node", "server.js"]
```

### ECS (Elastic Container Service)

AWS의 **관리형 컨테이너 오케스트레이션** 서비스입니다. Kubernetes 없이 간단하게 컨테이너를 실행할 수 있습니다.

**핵심 구성 요소:**

| 구성 요소 | 설명 |
|-----------|------|
| Cluster | ECS 리소스의 논리적 그룹 |
| Task Definition | 컨테이너 실행 설정 (이미지, CPU, 메모리, 포트 등) |
| Task | Task Definition의 실행 인스턴스 |
| Service | 지정된 수의 Task를 유지 관리 (Auto Scaling, ELB 연동) |

**시작 유형. EC2 vs Fargate:**

| 항목 | EC2 시작 유형 | Fargate 시작 유형 |
|------|---------------|-------------------|
| 인프라 관리 | 직접 EC2 인스턴스 관리 | AWS가 관리 (서버리스) |
| 비용 | EC2 인스턴스 요금 | Task 기반 요금 (vCPU/메모리/시간) |
| 제어 | 높음 (OS 레벨 접근) | 낮음 (컨테이너 레벨만) |
| 네트워크 모드 | bridge, host, awsvpc | awsvpc만 지원 |
| 적합한 경우 | 대규모 워크로드, OS 커스터마이징 | 간편 실행, 소규모 워크로드 |

**IAM Role 3종:**

- EC2 인스턴스 Role: EC2 호스트가 ECR에서 이미지를 Pull, CloudWatch에 로그 전송
- Task Role: 컨테이너 내 애플리케이션이 AWS 서비스에 접근 (S3, DynamoDB 등)
- Task Execution Role: ECS Agent가 ECR 이미지 Pull, 로그 전송, Secrets 가져오기

**ELB & EFS 연동:**
- ALB/NLB 연동: Service별 대상 그룹 자동 등록, 동적 포트 매핑
- EFS 연동: 여러 Task 간 공유 파일 시스템, 영구 스토리지

### ECR (Elastic Container Registry)

완전관리형 **Docker 컨테이너 이미지 저장소**입니다.

- 이미지 저장, 버전 관리, 취약점 스캔
- 프라이빗 / 퍼블릭 레지스트리 지원
- Lifecycle Policy로 오래된 이미지 자동 정리
- 교차 리전 / 교차 계정 복제 지원
- IAM 기반 액세스 제어

### Kubernetes 개념

컨테이너 오케스트레이션의 사실상 표준(De Facto Standard)입니다.

| 개념 | 설명 |
|------|------|
| Cluster | Kubernetes 전체 시스템 |
| Control Plane | 클러스터 관리 (API Server, etcd, Scheduler, Controller) |
| Node (Worker) | 컨테이너가 실행되는 워커 머신 |
| Pod | Kubernetes 최소 배포 단위 (1개 이상의 컨테이너) |
| Namespace | 클러스터 내 논리적 격리 |
| Deployment | Pod의 선언적 업데이트 및 스케일링 |
| Service | Pod 집합에 대한 네트워크 엔드포인트 |
| Ingress | 외부 HTTP(S) 트래픽 라우팅 |

### EKS (Elastic Kubernetes Service)

AWS의 **관리형 Kubernetes** 서비스입니다. Control Plane을 AWS가 완전 관리합니다.

**관리형 컨트롤 플레인:**
- 고가용성: 여러 AZ에 걸쳐 배포
- 자동 업데이트 및 패치
- etcd 백업 자동 관리
- API Server 엔드포인트: 퍼블릭 / 프라이빗 / 하이브리드

**노드 유형:**

| 노드 유형 | 설명 |
|-----------|------|
| 관리형 노드 그룹 | AWS가 노드 프로비저닝 및 업데이트 관리 |
| 자체 관리형 노드 | 사용자가 직접 EC2 인스턴스 관리 |
| Fargate | 서버리스, 노드 관리 불필요 |

**AutoScaling:**

| 도구 | 설명 |
|------|------|
| Cluster Autoscaler | Pod 스케줄링 실패 시 노드 자동 추가/제거 |
| Karpenter (2026 권장) | 빠른 프로비저닝, 다양한 인스턴스 유형, GPU 지원 |

> 💡 **2026 권장:** Karpenter는 Cluster Autoscaler 대비 빠른 스케일링, 유연한 인스턴스 선택, GPU/ARM 지원 등의 장점이 있습니다.

### Fargate: Serverless 컨테이너

서버를 관리하지 않고 **컨테이너를 직접 실행**할 수 있습니다.

| 항목 | 설명 |
|------|------|
| 인프라 관리 | 불필요 (AWS가 관리) |
| 비용 | 사용한 vCPU/메모리/시간 단위 |
| 지원 | ECS, EKS 모두 지원 |
| 네트워크 | ENI 기반 (awsvpc) |
| 스토리지 | 임시 (20GB 기본), EFS 연동 가능 |

### 컨테이너 아키텍처 패턴

**마이크로서비스 아키텍처:**

```
┌──────────────────────────────────────────────────────┐
│                    ALB / NLB                          │
│  /api/users    /api/orders    /api/products          │
└──────┬─────────────┬──────────────┬──────────────────┘
       │             │              │
  ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐
  │  ECS    │  │   ECS     │  │  ECS    │
  │ Service │  │  Service  │  │ Service │
  │ (Users) │  │ (Orders)  │  │(Products│
  │ ┌─────┐ │  │ ┌───────┐ │  │┌──────┐│
  │ │Task1│ │  │ │Task1  │ │  ││Task1 ││
  │ │Task2│ │  │ │Task2  │ │  ││Task2 ││
  │ └─────┘ │  │ └───────┘ │  │└──────┘│
  └────┬────┘  └─────┬─────┘  └────┬────┘
       │             │              │
  ┌────▼────┐  ┌─────▼─────┐  ┌────▼────┐
  │  RDS    │  │ DynamoDB  │  │ElastiC. │
  │(Users)  │  │ (Orders)  │  │(Cache)  │
  └─────────┘  └───────────┘  └─────────┘
```

**CI/CD 파이프라인:**

```
┌────────┐  ┌─────────┐  ┌─────┐  ┌─────┐  ┌──────────┐
│ GitHub │─▶│CodeBuild│─▶│ ECR │─▶│ ECS │  │ECS       │
│ Push   │  │(이미지   │  │(저장)│  │Deploy│ │Blue/Green│
│        │  │ 빌드)    │  │     │  │     │  │배포      │
└────────┘  └─────────┘  └─────┘  └──┬──┘  └──────────┘
                                     │
                              ┌──────▼──────┐
                              │ CodeDeploy  │
                              │ (Blue/Green)│
                              └─────────────┘
```

---

## Best Practices

**메시징 서비스 선택 가이드:**

| 시나리오 | 권장 서비스 | 이유 |
|----------|------------|------|
| 작업 큐 / 비동기 처리 | SQS Standard | Pull 기반, 무제한 처리량 |
| 순서가 중요한 거래 | SQS FIFO | 엄격한 순서, exactly-once |
| 이벤트를 여러 시스템에 전달 | SNS + SQS (Fan-out) | 병렬 독립 처리 |
| 대규모 실시간 스트림 | Kinesis Data Streams | 샤드 기반, 재생 가능 |
| S3 적재 / 준실시간 ETL | Kinesis Firehose | 관리형 버퍼링, 변환 Lambda |
| 애플리케이션 이벤트 라우팅 | EventBridge | 콘텐츠 필터링, 스키마, 아카이브 |
| 온프레미스 Kafka 마이그레이션 | MSK | Kafka 네이티브 API |

**컨테이너 런타임 선택 가이드:**

| 시나리오 | 권장 | 이유 |
|----------|------|------|
| 단순 컨테이너, 서버 관리 불필요 | ECS + Fargate | 서버리스, 과금 유연 |
| OS 커스터마이징, 대규모 워크로드 | ECS + EC2 | 제어권, 비용 효율 |
| K8s 생태계 / 멀티클라우드 | EKS | 표준 호환, 이식성 |
| EKS에서 노드 관리 부담 제거 | EKS + Fargate | 서버리스 Pod |
| 빠른 프로토타입 | App Runner | 소스/이미지 → 자동 배포 |

**핵심 모범 사례 6가지:**

1. **DLQ 필수 설정**: SQS/SNS 모두 Dead Letter Queue를 구성하여 반복 실패 메시지를 격리합니다
2. **Long Polling 활성화**: SQS 빈 응답을 줄여 API 호출 비용과 빈 폴링을 감소시킵니다
3. **Visibility Timeout 튜닝**: 처리 시간보다 여유 있게 설정하여 중복 처리를 방지합니다
4. **이미지 취약점 스캔**: ECR 자동 스캔을 켜고 Lifecycle Policy로 오래된 이미지를 정리합니다
5. **최소 권한 Task Role**: 컨테이너별 전용 IAM Role을 부여하고 Execution Role과 분리합니다
6. **Graviton(ARM) 활용**: 다중 아키텍처 이미지로 빌드하여 최대 20% 비용 절감, 40% 성능 향상을 얻습니다

---

## 마치며

메시징 서비스를 처음 공부할 때는 SQS, SNS, Kinesis, EventBridge의 차이를 외우는 데 급급했습니다. 하지만 이 서비스들을 "결합도를 어떻게 낮추는가"라는 하나의 렌즈로 바라보니 전혀 다르게 보이기 시작했습니다. 동기 호출은 수신자가 죽으면 호출자도 죽는 강결합의 연쇄이고, 비동기 메시징은 그 연쇄를 끊어내는 행위입니다. SQS의 가시성 제한, SNS의 Fan-out, EventBridge의 콘텐츠 기반 라우팅은 모두 "장애를 격리하고, 메시지를 보존하여 복구할 기회를 남기는" 서로 다른 전략이었습니다. DLQ 하나 설정하는 것도 "실패를 무시하지 않고 격리하는" 설계 의도의 표현이라는 점이 새로웠습니다.

컨테이너를 접하면서 놀랐던 것은 "OS 커널을 공유한다"는 한 문장이 가져오는 결과의 크기였습니다. GB 단위의 Guest OS를 포함하던 VM이 MB 단위로 줄어들고, 시작 시간이 분에서 초로 단축되며, 동일 호스트에 여러 컨테이너가 올라가는 밀도 효율이 극적으로 향상됩니다. 이는 단순한 기술적 차이가 아니라, 마이크로서비스 아키텍처가 경제적으로 가능해지는 전제 조건이었습니다. ECS+Fargate로 서버 관리 부담을 없애거나, EKS로 Kubernetes 생태계를 활용하거나, Karpenter로 노드 프로비저닝을 자동화하는 선택지는 모두 "어디까지 관리를 위임하고 어디까지 직접 제어할 것인가"에 대한 답이라고 느꼈습니다.

메시징과 컨테이너는 결국 같은 목표를 향해 가는 두 개의 축이라고 생각합니다. 하나는 서비스 간 결합도를 낮춰 독립성을 확보하는 것이고, 다른 하나는 서비스 자체를 가볍고 빠르게 배포하여 확장성을 확보하는 것입니다. Graviton(ARM)으로 비용과 성능을 동시에 개선하고, ECR에서 취약점 스캔을 수행하는 세부 실천까지 포함하면, 분산 시스템의 복잡성을 엔지니어링 원칙으로 다스리는 완성된 그림이 됩니다. 앞으로는 "강결합이 만들어내는 장애 전파"를 항상 경계하며, 비동기와 디커플링을 설계의 기본 전제로 삼고 싶습니다.

---

> **AWS 시리즈 12/16**
>
> | | |
> |---|---|
> | ← [운영 & IaC. CloudWatch, CloudTrail, CloudFormation]({% post_url 2026-06-01-AWS-Ops-IaC %}) | |
> | | [서버리스. Lambda & API Gateway]({% post_url 2026-06-03-AWS-Serverless-Lambda-APIGateway %}) → |
