---
layout: post
title: "[AWS 16/16] 아키텍처 설계 패턴 & Well-Architected Framework"
categories: [AWS, Architecture]
description: AWS Well-Architected Framework 6원칙과 실전 아키텍처 패턴, 재해 복구 전략, 비용 최적화까지 정리합니다.
keywords: [WellArchitected, 아키텍처, AWS, DR, 비용최적화]
toc: true
toc_sticky: true
---

## Hook

"서버 한 대가 죽었을 때 사용자는 몇 초나 기다릴까?" 이 질문에 답하려면 아키텍처를 설계할 수 있어야 합니다. Auto Scaling으로 교체하는 데 1~2분, Route 53 페일오버는 수십 초, Multi-AZ RDS 장애조치는 60초. 어느 전략을 선택하느냐에 따라 다운타임이 100배 달라집니다.

AWS에서 서비스를 고르는 것은 시작일 뿐입니다. 그 서비스들을 어떻게 조합하고, 장애를 어떻게 격리하며, 재해 시 얼마나 빨리 복구할 것인지가 아키텍처 설계의 본질입니다. 이 글에서는 Well-Architected Framework 6원칙부터 핵심 설계 패턴, DR 전략, 비용 최적화까지 실무에서 반드시 알아야 할 내용을 압축해서 정리합니다.

---

## TL;DR

- **Well-Architected 6원칙**: 운영 우수성, 보안, 안정성, 성능 효율성, 비용 최적화, 지속 가능성. 모든 설계 결정의 체크리스트
- **4대 아키텍처 패턴**: 3계층 웹, 마이크로서비스, 서버리스, 이벤트 기반. CQRS와 Outbox는 분산 시스템의 데이터 일관성 문제를 해결합니다
- **설계 원칙**: 느슨한 결합, 무상태, 멱등성, 장애 격리. 이 네 가지가 탄력적이고 복원력 있는 시스템의 기반
- **DR 전략 4단계**: Backup & Restore부터 Multi-Region Active-Active까지, RPO/RTO 요구사항에 따라 선택
- **비용 최적화**: Right Sizing, 예약/스팟 활용, 스토리지 계층화, FinOps 실천

---

## 1. Well-Architected Framework 6대 원칙

AWS Well-Architected Framework는 안전하고 고성능이며 탄력적이고 효율적인 인프라를 구축하기 위한 지침입니다. 2026년 기준 6개 원칙(Pillar)으로 구성됩니다.

```
┌─────────────────────────────────┐
│   Well-Architected Framework     │
│          6대 원칙                 │
└───────────────┬─────────────────┘
                │
    ┌───┬───┬───┼───┬───┐
    │   │   │   │   │   │
    ▼   ▼   ▼   ▼   ▼   ▼
 ┌────┐┌──┐┌──┐┌──┐┌──┐┌────┐
 │운영 ││보 ││안 ││성 ││비 ││지속 │
 │우수 ││안 ││정 ││능 ││용 ││가능 │
 │성   ││  ││성 ││효 ││최 ││성   │
 │    ││  ││  ││율 ││적 ││(新) │
 │    ││  ││  ││성 ││화 ││     │
 └────┘└──┘└──┘└──┘└──┘└────┘
```

### 1.1 운영 우수성 (Operational Excellence)

시스템을 실행 및 모니터링하고, 운영 절차를 지속적으로 개선합니다.

- **코드로 운영 수행**: 모든 운영 절차를 코드로 문서화 (Runbook 자동화)
- **빈번한 작은 변경**: 작고 점진적인 변경으로 위험 최소화
- **실패 예상**: 장애 시나리오 사전 정의, Game Day 실습
- **사후 분석**: Incident Review, 개선 사항 추적

핵심 도구로는 CloudWatch/X-Ray(모니터링), CloudFormation/CDK/Terraform(IaC), Systems Manager/Step Functions(자동화)가 있습니다.

### 1.2 보안 (Security)

데이터, 시스템, 자산을 보호하는 동시에 비즈니스 가치를 제공합니다.

- **최소 권한 원칙**: 필요한 최소한의 권한만 부여 (IAM)
- **모든 계층 보안**: 네트워크, 애플리케이션, 데이터 모든 계층에 보안 적용
- **보안 자동화**: Config, Security Hub, GuardDuty로 보안 메커니즘 자동화
- **암호화**: KMS, ACM, TLS를 통한 전송 중/저장 시 데이터 보호

### 1.3 안정성 (Reliability)

시스템이 장애를 예방하고 복구하는 능력입니다. 장애 복구 자동화(Auto Healing), 수평 확장(Scale Out), 용량 추측 중단(Auto Scaling), 장애 주입 테스트(FIS, Chaos Engineering)가 핵심 설계 원칙입니다.

### 1.4 성능 효율성 (Performance Efficiency)

컴퓨팅 리소스를 효율적으로 사용하고 요구사항 변화에 맞게 조정합니다. 관리형 서비스를 활용한 고급 기술 민주화, CloudFront/Global Accelerator로 글로벌 배포, 서버리스 아키텍처 선호가 핵심입니다.

### 1.5 비용 최적화 (Cost Optimization)

불필요한 비용을 제거하고 비즈니스 가치를 극대화합니다. FinOps 실천, 비용 효율적 리소스 선택, 예약 인스턴스/Savings Plans로 공급과 수요를 매칭하고, Cost Explorer/Budgets로 지출을 분석합니다.

### 1.6 지속 가능성 (Sustainability): NEW

2021년 추가된 6번째 원칙입니다. 환경 영향을 최소화하면서 클라우드 워크로드를 운영합니다. 탄소 발자국 측정(Customer Carbon Footprint Tool), 리소스 효율성 향상(Graviton 인스턴스), 관리형 서비스로 공유 인프라 활용, 재생 에너지 비율이 높은 리전 선택이 핵심입니다.

> **실전 팁:** Well-Architected Tool로 정기적으로 워크로드를 검사하면 각 원칙별 위험도를 시각적으로 파악할 수 있습니다. 설계 시 이 6원칙을 체크리스트로 사용하세요.

---

## 2. 핵심 아키텍처 패턴

### 2.1 3계층 웹 애플리케이션 (Web-App-DB)

가장 기본이 되는 패턴입니다. 프레젠테이션(Web), 비즈니스 로직(App), 데이터(DB) 계층을 분리합니다.

<details markdown="1">
<summary>2.1 3계층 웹 애플리케이션 (Web-App-DB)</summary>

```
[사용자]
    │
    ▼
┌──────────┐    ┌──────────┐
│ Route 53 │    │ S3       │
│ (DNS)    │    │ (정적)    │
└────┬─────┘    └──────────┘
     │
┌────▼─────┐
│CloudFront│  CDN (정적 캐싱)
└────┬─────┘
     │ /api/*
┌────▼─────────┐
│     ALB      │  로드밸런서
└────┬─────────┘
     │
─────┼── [Web Tier] ──────────
┌────▼──────────────────┐
│  EC2 / ECS (Auto Scal) │  ← 3개 이상 인스턴스
└────┬──────────────────┘
─────┼── [App Tier] ──────────
┌────▼──────────────────┐
│ ECS Fargate / Lambda  │  비즈니스 로직
└────┬──────────────────┘
─────┼── [DB Tier] ───────────
┌────▼────┐ ┌────────┐ ┌──────────┐
│RDS      │ │DynamoDB│ │ElastiCache│
│(Multi-AZ│ │(NoSQL) │ │(Redis)   │
└─────────┘ └────────┘ └──────────┘
```
</details>

각 계층이 독립적으로 확장 가능하고, Multi-AZ 배포로 단일 AZ 장애에 대응합니다.

### 2.2 마이크로서비스 아키텍처

애플리케이션을 작고 독립적인 서비스 단위로 분해합니다. API Gateway가 요청을 라우팅하고, 각 서비스는 자체 데이터 저장소를 소유합니다. 서비스 간 통신은 동기(ALB + REST/gRPC), 비동기(SQS + SNS), 이벤트(EventBridge) 방식으로 구분합니다.

핵심은 **데이터베이스 공유 금지**입니다. 각 마이크로서비스가 자체 DB를 가져야 결합도를 낮출 수 있습니다. 서비스 메시(App Mesh/Istio)로 서비스 디스커버리, 트래픽 관리, mTLS 보안을 처리합니다.

### 2.3 서버리스 아키텍처

서버 프로비저닝, 패치, 스케일링을 AWS에 위임하는 패턴입니다.

```
┌───────────┐    ┌──────────────┐
│  Client   │───▶│ CloudFront   │
└───────────┘    │ + S3 (정적)   │
                 └──────┬───────┘
                        │ /api/*
                 ┌──────▼───────┐
                 │  API Gateway │
                 └──┬───┬───┬───┘
                    │   │   │
             ┌──────┘   │   └──────┐
             ▼          ▼          ▼
        ┌────────┐ ┌────────┐ ┌────────┐
        │Lambda  │ │Lambda  │ │Lambda  │
        │(인증)  │ │(CRUD)  │ │(이벤트) │
        └────┬───┘ └────┬───┘ └────┬───┘
             │          │          │
        ┌────▼──┐  ┌───▼────┐  ┌──▼───┐
        │Cognito│  │DynamoDB│  │SQS/  │
        │       │  │       │  │SNS   │
        └───────┘  └───────┘  └──────┘
```

서버 관리 부담이 없고, 사용한 만큼만 과금되며, 자동 확장과 고가용성이 내장되어 있습니다. 트래픽이 예측 불가능하거나 간헐적인 워크로드에 특히 효과적입니다.

### 2.4 이벤트 기반 아키텍처 (Event-Driven)

컴포넌트가 이벤트를 발행하고, 이벤트 버스가 규칙에 따라 타겟으로 라우팅하는 구조입니다. S3 업로드, DynamoDB 변경, API 호출, 스케줄(Cron) 등이 이벤트 소스가 되며, EventBridge가 중앙 이벤트 버스 역할을 합니다. 이벤트는 SQS(큐), SNS(알림), Lambda(처리), Step Functions(복합 워크플로)로 전달됩니다.

이벤트 기반 구조는 **느슨한 결합의 극단적 형태**입니다. 이벤트 생산자와 소비자가 서로를 알 필요 없이, 이벤트 버스만 바라봅니다.

### 2.5 CQRS & Outbox 패턴

마이크로서비스에서 자주 발생하는 두 가지 문제를 해결하는 패턴입니다.

- **CQRS (Command Query Responsibility Segregation)**: 쓰기(Command)와 읽기(Query) 모델을 분리합니다. 쓰기는 정규화된 RDS로, 읽기는 DynamoDB/ElasticSearch로 분리하면 읽기 부하가 많은 시스템에서 성능을 극대화할 수 있습니다. 최종 일관성(Eventual Consistency)을 허용하는 것이 전제입니다.

- **Outbox 패턴**: 데이터베이스 트랜잭션과 이벤트 발행의 원자성을 보장합니다. DB 변경과 이벤트를 같은 트랜잭션에 저장하고(Outbox 테이블), 별도 프로세스가 Outbox를 읽어 EventBridge/SNS로 발행합니다. 이렇게 하면 DB는 커밋됐는데 이벤트가 유실되는 문제를 방지할 수 있습니다.

---

## 3. 아키텍처 설계 원칙

### 느슨한 결합 (Loose Coupling)

컴포넌트 간 의존성을 최소화하여 하나의 변경이 다른 컴포넌트에 미치는 영향을 줄입니다. SQS(비동기 메시징), EventBridge(이벤트 기반 통신), API Gateway(REST/gRPC 인터페이스), Cloud Map(서비스 디스커버리)로 결합도를 낮춥니다.

### 무상태 (Stateless)

각 요청이 독립적으로 처리되도록 상태를 외부(ElastiCache, DynamoDB)에 저장합니다. 무상태 서버는 언제든 교체/확장 가능하며, 세션 문제 없이 Auto Scaling이 동작합니다.

### 멱등성 (Idempotency)

같은 요청을 여러 번 실행해도 결과가 동일하도록 설계합니다. Lambda 재시도, SQS 중복 메시지, Step Functions 재실행 시 데이터 손상을 방지합니다. 요청 ID로 중복을 감지하고 건너뛰는 패턴을 사용합니다.

### 장애 격리 (Failure Isolation)

하나의 컴포넌트 장애가 전체 시스템으로 전파되지 않도록 격리합니다.

- **Bulkhead**: 리소스 풀 분리 (별도 SQS 큐, 별도 DB)
- **Circuit Breaker**: 장애 서비스 호출 중단, 대체 응답(fallback) 반환
- **Timeout**: 모든 API 호출에 타임아웃 설정
- **Rate Limiting**: API Gateway Throttling으로 과부하 방지
- **Multi-AZ**: AZ 단위 장애 격리

### 관측 가능성 (Observability)

시스템 상태를 이해하기 위한 세 가지 핵심 요소입니다. Logs(CloudWatch Logs), Metrics(CloudWatch Metrics), Traces(X-Ray)를 수집하고, Managed Grafana/Prometheus, OpenTelemetry로 통합 대시보드를 구성합니다.

---

## 4. 재해 복구(DR) 전략

비즈니스 연속성을 위해 **RPO(Recovery Point Objective)** 와 **RTO(Recovery Time Objective)** 를 기준으로 DR 전략을 선택합니다. RPO는 "얼마나 많은 데이터 손실을 감당할 수 있는가", RTO는 "얼마나 빨리 복구해야 하는가"를 의미합니다.

| 전략 | RPO | RTO | 비용 | 구성 |
|------|-----|-----|------|------|
| **Backup & Restore** | 시간~일 | 시간~일 | 낮음 | DR 리전은 백업만 보관. 재해 시 스냅샷에서 복원 |
| **Pilot Light** | 분~시간 | 분~시간 | 중간 | DR 리전에 최소 규모(중지된 EC2, Read Replica) 유지. 재해 시 Scale Up |
| **Warm Standby** | 초~분 | 분 | 높음 | DR 리전에 축소 규모로 운영 중. 재해 시 Scale Up to Full |
| **Multi-Region Active-Active** | 실시간 (0) | 실시간 (0) | 매우 높음 | 양쪽 리전 모두 활성. Route 53이 트래픽 분산 |

### 전략 선택 기준

- **비용이 최우선이면** Backup & Restore. 규정 준수 보관, 개발/테스트 환경에 적합
- **몇 시간 복구가 가능하면** Pilot Light. 핵심 데이터만 동기화(RDS Read Replica, DynamoDB Global Table)
- **몇 분 내 복구가 필요하면** Warm Standby. DR 리전에서 축소 규모로 상시 운영
- **다운타임이 허용되지 않으면** Multi-Region Active-Active. Aurora Global Database, DynamoDB Global Table, Route 53 Latency/Weighted 라우팅

> **실전 팁:** 모든 워크로드가 Active-Active일 필요는 없습니다. 핵심 서비스만 Active-Active로, 일반 서비스는 Pilot Light나 Warm Standby로 구성하는 하이브리드 DR이 비용 효율적입니다. Resilience Hub로 복원력을 정량적으로 검증할 수 있습니다.

---

## 5. 비용 최적화 전략

### Right Sizing

워크로드에 맞는 최적의 인스턴스 타입과 크기를 선택합니다. Compute Optimizer가 CloudWatch 메트릭을 분석해 권장 사항을 제시합니다. 과소 프로비저닝(성능 저하)과 과대 프로비저닝(비용 낭비) 둘 다 피해야 합니다.

### 예약 및 스팟 활용

| 옵션 | 약정 기간 | 할인율 | 적합한 워크로드 |
|------|----------|--------|----------------|
| **On-Demand** | 없음 | 0% | 유연, 단기, 예측 불가 |
| **Compute Savings Plans** | 1년/3년 | 최대 72% | EC2, Fargate, Lambda 혼합 |
| **EC2 Instance Savings Plans** | 1년/3년 | 최대 72% | 특정 인스턴스 패밀리 |
| **Reserved Instances** | 1년/3년 | 최대 72% | 특정 인스턴스 타입 |
| **Spot** | 없음 | 최대 90% | 배치, CI/CD, 중단 허용 워크로드 |

안정적으로 상시 실행되는 워크로드는 Savings Plans/RI로, 중단 헹용 워크로드는 Spot으로 비용을 극적으로 줄일 수 있습니다. Spot은 종료 2분 전 알림을 제공하므로 체크포인트 저장이 가능합니다.

### 스토리지 계층화

| 계층 | 사용 사례 | S3 비용(GB당) |
|------|----------|---------------|
| **Hot** (S3 Standard) | 자주 접근 | $0.023 |
| **Warm** (S3 IA) | 월 1~2회 접근 | $0.0125 |
| **Cold** (Glacier Flexible) | 연 1~2회 접근 | $0.0036 |
| **Archive** (Glacier Deep Archive) | 규정 준수 보관 (7~10년) | $0.00099 |

S3 Intelligent-Tiering으로 액세스 패턴을 자동 감지해 계층을 이동시키고, Lifecycle Policy로 수명 주기 규칙을 자동화합니다.

### FinOps 실천

FinOps는 클라우드 비용을 최적화하는 재무 관리 실천입니다. 세 단계로 구성됩니다.

- **Inform (가시화)**: Cost Explorer, Budgets, Cost Allocation Tags로 비용 현황 파악
- **Optimize (최적화)**: Compute Optimizer, Trusted Advisor, Savings Plans로 리소스 최적화
- **Operate (운영)**: Budgets Actions, SCP, Lambda 자동화로 지속적 개선

비용 태깅(프로젝트/팀/환경별), 예산 알림, Cost Anomaly Detection으로 예상치 못한 비용 증가를 감지하고, 유휴 EBS, 미연결 EIP, 오래된 Snapshot을 정기적으로 정리합니다.

---

## 마치며

Well-Architected Framework를 처음 봤을 때는 또 하나의 "준수 체크리스트"라고 생각했습니다. 하지만 여섯 원칙을 실제 아키텍처 결정에 적용해 보니, 이것은 체크리스트가 아니라 "트레이드오프를 식별하는 사고 프레임"이라는 것을 깨달았습니다. 비용을 낮추면 안정성이 흔들리고, 성능을 높이면 비용이 올라가며, 보안을 강화하면 운영 복잡도가 증가합니다. 모든 결정에는 대가가 따르며, Well-Architected는 그 대가를 "보이게" 만드는 도구라는 점이 인상적이었습니다. 지속 가능성까지 포함하면, 기술적 완벽함이 곧 정답이 아니라는 시각도 새롭게 다가왔습니다.

가장 크게 놀란 것은 "느슨한 결합과 장애 격리"가 단순한 모범 사례가 아니라 복원력의 근본 원리라는 사실이었습니다. 무상태 설계, 비동기 메시징, Circuit Breaker, Bulkhead, Multi-AZ 배포. 이 모든 패턴이 추구하는 것은 "부분 장애가 전체 장애로 번지는 것을 막는" 일입니다. 서버 한 대가 죽었을 때 사용자가 몇 초나 기다리는가,라는 질문에서 시작해 Auto Scaling, Route 53 페일오버, Multi-AZ 장애조치로 이어지는 사고 흐름은, 결국 "장애를 얼마나 국소화할 것인가"라는 하나의 질문으로 수렴된다는 것을 체감했습니다. CQRS와 Outbox 패턴이 분산 시스템의 데이터 일관성 문제를 다루는 방식도 같은 맥락에서 이해할 수 있었습니다.

DR 전략을 RPO/RTO와 비용의 트레이드오프로 체계화하는 것을 보면서, "모든 서비스를 Active-Active로 만들 필요는 없다"는 통찰이 마음에 남았습니다. 서비스 중요도에 따라 Backup & Restore부터 Multi-Region Active-Active까지 단계를 나누는 설계는, 엔지니어링이 곧 "제한된 자원으로 최적의 복원력을 설계하는 일"이라는 본질을 잘 보여줍니다. 이 시리즈 16편을 마무리하며 드는 생각은, 클라우드 아키텍처는 서비스를 나열하는 것이 아니라 트레이드오프를 설계하는 일이라는 것입니다. 앞으로는 모든 결정 앞에서 "이 선택이 여섯 원칙 각각에 미치는 영향"을 의식하며, 완벽함이 아니라 균형을 추구하는 설계자로 성장하고 싶습니다.

---

> **AWS 시리즈 16/16**
>
> | | |
> |---|---|
> | ← [AI & ML. Bedrock, SageMaker, Amazon Q]({% post_url 2026-06-05-AWS-AI-ML-Bedrock-SageMaker %}) | |
> | | 마지막 글입니다 |
