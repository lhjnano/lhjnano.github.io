---
layout: post
title: "[AWS 11/16] 운영 & IaC — CloudWatch, CloudTrail, CloudFormation"
categories: [AWS, DevOps, Monitoring]
description: 모니터링(CloudWatch), 감사(CloudTrail/Config), 인프라 코드(CloudFormation/CDK)로 AWS 운영 자동화를 정리합니다.
keywords: [CloudWatch, CloudTrail, CloudFormation, CDK, AWS, IaC]
toc: true
toc_sticky: true
---

## Hook

AWS 인프라가 커지면 세 가지 질문이 늘 따라옵니다. **지금 시스템이 정상인가?**(모니터링), **누가 무엇을 바꿨는가?**(감사), **이 인프라를 재현 가능하게 관리하는가?**(IaC). 이 세 질문에 답하는 서비스가 각각 **CloudWatch**, **CloudTrail + Config**, **CloudFormation + CDK**입니다.

이 글은 운영 자동화의 세 축을 하나로 묶어 정리합니다. 각 서비스의 핵심 메커니즘과 연결 지점을 짚고, 다중 계정·다중 리전 환경에서 어떻게 조합하는지 다룹니다.

---

## TL;DR

- **CloudWatch** — 지표·로그·경보·대시보드로 관측 가능성(Observability)을 제공하고, EventBridge로 이벤트 기반 자동화를 연결합니다
- **CloudTrail + Config** — CloudTrail은 "누가" API를 호출했는지, Config는 "무엇"이 어떻게 변경됐는지 추적합니다. Organization Trail과 Config Aggregator로 다중 계정을 중앙 집중합니다
- **CloudFormation + CDK** — 선언적 템플릿(YAML) 또는 프로그래밍 언어(TS/Python)로 인프라를 코드로 관리합니다. Change Set으로 안전하게 변경하고, StackSets로 조직 전체에 배포합니다
- **조합의 핵심** — CloudWatch 경보 → EventBridge → Lambda/SSM 자동 복구, CloudTrail 로그 → Athena/Lake 분석, IaC로 모든 것을 재현 가능하게 버전 관리합니다

---

## 1. CloudWatch — 관측 가능성의 중심

Amazon CloudWatch는 지표(Metrics), 로그(Logs), 경보(Alarms), 대시보드(Dashboards)를 통합한 관측 가능성 서비스입니다. 모든 AWS 리소스의 상태를 실시간으로 추적하고, 임계값 기반 자동 액션을 수행합니다.

### 지표(Metrics)와 로그(Logs)

- **기본 지표** — AWS 서비스가 자동 수집합니다 (EC2 `CPUUtilization`, Lambda `Invocations/Errors`, ELB `HTTPCode_Target_5XX` 등)
- **사용자 지정 지표** — `PutMetricData` API 또는 **EMF(Embedded Metric Format)**로 비즈니스 지표를 전송합니다. 고해상도(1초) 지표도 가능합니다
- **로그 그룹/스트림** — 출처별로 로그를 분리하고, 그룹 단위로 보존 기간(1일~10년)과 KMS 암호화를 설정합니다. CloudWatch Agent, Lambda, VPC Flow Logs, API Gateway 등이 소스입니다

**Logs Insights**로 구조화된 쿼리로 로그를 검색·집계합니다:

```text
# Lambda 에러 로그 검색 + HTTP 상태 코드별 집계
fields @timestamp, @message
| filter @message like /ERROR/
| sort @timestamp desc | limit 50

fields @timestamp, statusCode
| stats count() by statusCode
```

> **팁**: 2026년에는 **Contributor Insights for VPC Flow Logs**로 Top Talkers를 자동 식별해 네트워크 이상을 잡을 수 있습니다.

### 경보(Alarms)와 자동 액션

경보는 지표가 임계값을 N회 연속 초과하면 `OK → ALARM`으로 전환되며 액션을 트리거합니다. **복합 경보**(Composite)로 AND/OR 조건을 조합하면 노이즈를 줄일 수 있습니다.

| 액션 | 용도 |
|------|------|
| SNS | 이메일/SMS/HTTP 알림 |
| Lambda | 경보 상태 변경 시 함수 실행 |
| Auto Scaling | 스케일 인/아웃 트리거 |
| EC2 | 인스턴스 중지/종료/복구 |
| Systems Manager | SSM Automation/Incident Manager 연동 |

경보 → Auto Scaling 연동으로 지표 기반 자동 스케일링을 구성합니다.

![CloudWatch 기반 자동 스케일링 아키텍처 — Application 지표 수집 → CloudWatch 경보(ALARM) → Auto Scaling 그룹 → EC2 인스턴스 스케일 아웃(추가)](/assets/images/posts/aws-ops-iac/18-02-경보-기반-auto-scaling-연동.svg)

- **Target Tracking** — 목표 지표 값(예: CPU 50%)을 유지
- **Step Scaling** — 단계별로 스케일 조정
- **예약 스케일링** — 예측 가능한 트래픽 패턴에 대응

### 대시보드와 분산 트레이싱

대시보드는 프로젝트·환경·팀별 맞춤 뷰를 만듭니다. **크로스 리전 대시보드**로 글로벌 인프라를 단일 화면에서 확인하고, IAM 없이 퍼블릭 링크로 공유할 수 있습니다.

관측 가능성 3대 축은 **지표·로그·트레이스**입니다. **AWS X-Ray**가 분산 트레이싱을 담당하며, 마이크로서비스 요청 흐름을 종단 간 추적해 병목을 식별합니다. CloudWatch ServiceLens가 지표+트레이스를 통합 뷰로 제공합니다.

![요청 흐름 추적 (Distributed Tracing) — Client → API Gateway → Lambda → DynamoDB, SNS → SQS → Lambda → RDS 경로를 X-Ray가 각 구간 지연 시간·에러율·응답 시간 추적](/assets/images/posts/aws-ops-iac/18-01-aws-x-ray-통합-분산-트레이싱.svg)

### EventBridge — 이벤트 기반 자동화

CloudWatch Events는 **Amazon EventBridge**로 발전했습니다. AWS 서비스의 상태 변경 이벤트를 패턴 매칭으로 타겟에 라우팅합니다.

```json
// EC2 인스턴스가 running 상태가 된 이벤트만 매칭
{
  "source": ["aws.ec2"],
  "detail-type": ["EC2 Instance State-change Notification"],
  "detail": { "state": ["running"] }
}
```

- **예약 규칙(Cron)** — `cron(0 9 * * ? *)` (매일 9시), `rate(30 minutes)`
- **EventBridge Pipes** — DynamoDB Streams/Kinesis/SQS 소스를 Lambda/Step Functions 타겟에 저코드로 연결 (필터링·변환 단계 지원)
- **EventBridge Scheduler** — 전용 스케줄링 서비스. 최대 1년 후까지 예약, 유연한 재시도·DLQ 지원. 대규모 스케줄에 최적화됩니다

---

## 2. CloudTrail & Config — 감사와 규정 준수

**CloudTrail**은 "누가" 무엇을 했는지(API 호출), **Config**는 "무엇"이 어떻게 변경됐는지(리소스 구성)를 기록합니다. 둘을 함께 쓰면 포괄적인 감사 체계가 완성됩니다.

### CloudTrail — API 호출 로깅

CloudTrail은 계정 내 모든 API 호출(CLI, SDK, Console, 서비스 간)을 기록합니다. **기본 활성화**되며 최근 90일 관리 이벤트를 무료로 제공합니다. 장기 보관·고급 분석에는 **Trail** 생성이 필수입니다.

![CloudTrail 아키텍처 — 서울·도쿄·버지니아 리전의 이벤트를 다중 리전 Trail이 수집해 중앙 S3 버킷에 저장, Athena로 SQL 쿼리 분석, CloudWatch로 실시간 경고, SSE-KMS 암호화·버전 관리·MFA Delete·수명 주기(7년 보존) 적용](/assets/images/posts/aws-ops-iac/19-01-cloudtrail-아키텍처.svg)

- **다중 리전 Trail** — 단일 Trail로 모든 리전 이벤트를 단일 S3 버킷에 통합 (권장)
- **S3 보안** — gzip 압축, SSE-S3/SSE-KMS 암호화, SHA-256 무결성 검증, MFA Delete, 7년 보존 권장
- **조직 전체 추적** — 관리 계정에서 단일 Trail로 모든 멤버 계정 추적

![Organization 추적 — 관리 계정이 Organization Trail을 생성해 멤버 계정 A/B/C 전체 로그를 중앙 S3 버킷으로 집중, 멤버 계정은 Trail 비활성화/수정 불가](/assets/images/posts/aws-ops-iac/19-02-4-organization-추적.svg)

> Organization Trail은 신규 생성되는 멤버 계정도 자동 포함되며, 멤버 계정에서 비활성화할 수 없어 일관된 로깅을 보장합니다.

### CloudTrail Lake — SQL 기반 이벤트 쿼리

CloudTrail Lake는 ETL이나 Athena 없이 **표준 SQL**로 이벤트 로그를 직접 쿼리하는 관리형 데이터 레이크입니다. 이벤트 데이터 스토어에 최대 7년 보존하며, Config 변경 데이터와 통합 분석도 지원합니다.

<details>
<summary>CloudTrail Lake SQL 쿼리 예시 — 전체 보기</summary>

```sql
-- 특정 IAM 사용자의 모든 S3 액세스 이벤트 조회
SELECT eventTime, eventName, requestParameters,
       sourceIpAddress, errorCode
FROM eda1a2b3-c4d5-e6f7-g8h9-i0j1k2l3m4n5
WHERE userIdentity.arn LIKE '%alice%'
  AND eventSource = 's3.amazonaws.com'
  AND eventTime >= '2026-01-01'
ORDER BY eventTime DESC;
```

</details>

### CloudTrail Insights — 이상 탐지

기계학습으로 평소와 다른 **Write API** 호출 패턴을 자동 탐지합니다. 비정상적 EC2 대량 생성, 예기치 않은 IAM 정책 변경, 대량 S3 삭제 작업 등을 감지해 EventBridge로 알림을 보냅니다. Trail 설정에서 활성화해야 합니다.

### AWS Config — 구성 변경 추적과 규칙 평가

Config는 리소스 구성 상태를 지속적으로 기록하고, **규칙**으로 규정 준수 여부를 자동 평가합니다.

- **AWS 관리형 규칙** — `encrypted-volumes`, `s3-bucket-server-side-encryption-enabled`, `required-tags`, `cloudtrail-enabled` 등 즉시 사용 가능
- **사용자 지정 규칙** — Lambda 함수 또는 **Guard DSL**로 정의. 구성 변경 시 또는 주기적(1~24시간)으로 트리거

<details>
<summary>Config Guard 규칙 예시 — 전체 보기</summary>

```text
rule check_required_tags {
  resource_type == "AWS::EC2::Instance" {
    configuration.tags.Project !empty
    configuration.tags.Environment !empty
    configuration.tags.CostCenter !empty
  }
}
```

</details>

**Config Aggregator**로 여러 계정·리전의 규정 준수 데이터를 단일 위치에서 집계합니다. Organization 연동 시 모든 계정의 상태를 중앙 대시보드에서 한눈에 파악합니다.

![Config Aggregator 다중 계정/리전 집계 — 계정 A/B/C의 서울·도쿄·버지니아 리전 Config 데이터를 중앙 계정의 Aggregator가 수집해 통합 규정 준수 대시보드(전체 준수율·계정별 상태·위반 리소스 목록) 제공](/assets/images/posts/aws-ops-iac/19-03-92-config-aggregator-다중-계정리전-집계.svg)

### Conformance Pack과 자동 수정(Remediation)

**Conformance Pack**은 관련 Config 규칙과 수정 액션을 단일 패키지로 관리합니다. AWS 제공 표준 팩(CIS, NIST 800-53, PCI DSS, HIPAA, AWS Foundational Security Best Practices)을 CloudFormation 템플릿으로 조직 전체에 배포합니다.

**Remediation Actions**는 규칙 위반 시 SSM Automation으로 자동 수정합니다:

| 규칙 위반 | 자동 수정 액션 |
|----------|---------------|
| 공개 S3 버킷 감지 | 퍼블릭 액세스 차단 활성화 |
| 암호화되지 않은 EBS 볼륨 | 스냅샷 기반 암호화 |
| SSH 포트 개방 | 보안 그룹 규칙 자동 수정 |
| 필수 태그 누락 | 알림 발송 또는 기본 태그 적용 |

### 보안 모니터링 파이프라인

CloudTrail(누가) + Config(무엇)을 결합하면 포괄적인 보안 모니터링 파이프라인이 완성됩니다.

![보안 모니터링 파이프라인 — API 호출은 CloudTrail이 로깅→S3→CloudTrail Lake(SQL 분석)→EventBridge→Lambda/SNS 경고, 리소스 변경은 Config가 추적→규칙 평가→위반 시 Remediation→SSM Automation 자동 수정, CloudWatch로 실시간 경고](/assets/images/posts/aws-ops-iac/19-04-보안-모니터링-파이프라인.svg)

> **핵심**: CloudTrail은 감사 추적(Audit Trail)을, Config는 규칙 평가 + 자동 수정을 담당합니다. 두 서비스를 항상 함께 배포하세요.

### 포렌식 및 다중 계정 감사

보안 사고 발생 시 **CloudTrail Lake**(SQL 타임라인 재구성) + **Config 타임라인**(리소스 변경 이력) + **GuardDuty**(위협 정보) + **Security Hub**(통합 뷰)로 포렌식 분석을 수행합니다.

![포렌식 분석 아키텍처 — 보안 사고 탐지 → CloudTrail Lake(SQL 타임라인) → CloudTrail S3(Athena 상세 분석) → Config 타임라인(변경 이력) → GuardDuty(위협 정보) → Security Hub(통합 뷰) → 포렌식 보고서 생성](/assets/images/posts/aws-ops-iac/19-05-103-포렌식-분석-아키텍처.svg)

다중 계정 환경에서는 **보안 전용 계정(Audit Account)**을 두어 중앙 집중 감사를 수행합니다.

![다중 계정 감사 아키텍처 — 보안 계정(Audit)이 CloudTrail Org Trail, Config Aggregator, CloudTrail Lake, Security Hub, CloudWatch를 중앙 운영, 개발·스테이징·프로덕션 계정의 로그·Config 데이터를 통합 감사·규정 준수·보안 모니터링](/assets/images/posts/aws-ops-iac/19-06-104-다중-계정-감사-아키텍처.svg)

---

## 3. IaC — CloudFormation & CDK

인프라를 코드(Infrastructure as Code)로 관리하면 **반복 가능한 프로비저닝**, **변경 추적**(버전 관리), **종속성 자동 처리**, **오류 시 롤백**이 가능해집니다.

### CloudFormation — 선언적 템플릿

CloudFormation은 YAML/JSON 템플릿으로 인프라를 정의합니다. **Stack**은 템플릿 기반으로 생성·업데이트·삭제되는 리소스 모음 단위입니다.

![CloudFormation Stack 라이프사이클 — 템플릿 작성(YAML/JSON) → CREATE_IN_PROGRESS → CREATE_COMPLETE(성공) 또는 CREATE_ROLLBACK(오류 시 자동 롤백) → UPDATE(수정)/DELETE(삭제)](/assets/images/posts/aws-ops-iac/20-01-스택-라이프사이클.svg)

템플릿의 핵심 섹션은 `Resources`(필수), `Parameters`(런타임 입력), `Conditions`(조건부 생성), `Mappings`, `Outputs`(다른 스택 참조)입니다.

<details>
<summary>CloudFormation 템플릿 구조 — 전체 보기</summary>

```yaml
AWSTemplateFormatVersion: "2010-09-09"
Description: "인프라 템플릿 설명"

Parameters:
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, staging, prod]

Conditions:
  IsProduction: !Equals [!Ref Environment, prod]

Resources:
  MyVPC:
    Type: AWS::EC2::VPC
    Properties:
      CidrBlock: 10.0.0.0/16

  MySubnet:
    Type: AWS::EC2::Subnet
    Properties:
      VpcId: !Ref MyVPC
      CidrBlock: 10.0.1.0/24

Outputs:
  VPCId:
    Description: "VPC ID"
    Value: !Ref MyVPC
    Export:
      Name: !Sub "${AWS::StackName}-VPCId"
```

</details>

> **과금**: CloudFormation 자체는 **무료**입니다. 생성되는 AWS 리소스 비용만 과금됩니다. StackSets, Change Sets도 추가 비용 없습니다.

### Change Sets — 안전한 변경

Change Set은 스택 업데이트 시 **어떤 변경이 발생할지 미리 확인**하는 기능입니다. 추가·수정·삭제·교체될 리소스를 검토 후 수동 승인합니다.

![Change Set 워크플로우 — 템플릿 수정 → Change Set 생성 → 변경 내용 미리 보기(Add/Modify/Remove/Replace 영향 분석) → 승인/거부(수동 검토) → 승인 시 스택 업데이트](/assets/images/posts/aws-ops-iac/20-02-4-변경-세트-change-sets.svg)

- **미리 보기** — 추가·수정·삭제·교체(Replace)될 리소스 목록 표시
- **리소스 교체 예측** — 변경이 Replacement(재생성)를 유발하는지 사전 감지
- **Stack Policy** — 중요 리소스의 실수로 인한 업데이트/삭제를 방지

### StackSets — 조직 전체 배포

하나의 템플릿으로 **여러 AWS 계정과 리전에 동시 배포**합니다. Organizations 통합으로 OU별 배포, 신규 계정 자동 배포를 지원합니다.

![StackSets 다중 계정/리전 배포 — 관리 계정의 StackSet(마스터 템플릿)이 계정 A/B/C/D의 리전 1·2에 동시 배포, AWS Organizations 기반 자동 배포](/assets/images/posts/aws-ops-iac/20-03-stacksets-다중-계정리전-배포.svg)

**Drift Detection**(구성 드리프트 탐지)은 템플릿과 실제 리소스의 불일치를 자동 감지합니다. 상태는 `IN_SYNC`, `MODIFIED`, `DELETED`, `NOT_CHECKED`로 표시됩니다. **CloudFormation Guard**로 템플릿을 배포 전 보안·규정 준수 정책에 대해 검증합니다.

### AWS CDK — 코드로 인프라 정의

CDK는 **TypeScript, Python, Java, C#, Go**로 인프라를 정의해 CloudFormation 템플릿을 생성하는 프레임워크입니다. 핵심은 재사용 가능한 **Construct**입니다.

| 계층 | 설명 | 예시 |
|------|------|------|
| **L1** | CloudFormation 리소스 1:1 매핑 | `CfnVPC` |
| **L2** | 안전한 기본값 포함 고수준 추상화 | `Vpc` |
| **L3** | 패턴 기반 완전한 아키텍처 | `ApplicationLoadBalancedFargateService` |

<details>
<summary>CDK 예제 (Fargate 서비스) — 전체 보기</summary>

```typescript
import * as cdk from 'aws-cdk-lib';
import { Vpc } from 'aws-cdk-lib/aws-ec2';
import { Cluster } from 'aws-cdk-lib/aws-ecs';
import { ApplicationLoadBalancedFargateService }
  from 'aws-cdk-lib/aws-ecs-patterns';

export class MyAppStack extends cdk.Stack {
  constructor(scope: cdk.App, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const vpc = new Vpc(this, 'MyVpc', {
      maxAzs: 3,
      natGateways: 1,
    });

    const cluster = new Cluster(this, 'MyCluster', {
      vpc,
      containerInsights: true,
    });

    new ApplicationLoadBalancedFargateService(this, 'MyService', {
      cluster,
      memoryLimitMiB: 512,
      cpu: 256,
      desiredCount: 2,
      taskImageOptions: {
        image: ecs.ContainerImage.fromRegistry('nginx:latest'),
      },
    });
  }
}
```

</details>

- **CDK Pipelines** — 셀프 뮤턴트(self-mutating) 자동 배포 파이프라인. 다중 환경(dev/staging/prod) 배포 지원
- **cdk-nag** — 보안 규칙 자동 검사 도구. CI/CD에 통합해 배포 전 검증
- **CloudFormation Registry** — Datadog, MongoDB Atlas 등 서드파티 리소스를 네이티브처럼 관리

### Terraform 비교

| 항목 | CloudFormation | CDK | Terraform |
|------|---------------|-----|-----------|
| 정의 언어 | YAML/JSON | TS, Python 등 | HCL |
| AWS 통합 | 네이티브 (즉시 지원) | CFN 기반 | Provider 업데이트 필요 |
| 다중 클라우드 | AWS 전용 | AWS 전용 | AWS, Azure, GCP |
| 상태 관리 | AWS 자체 관리 | AWS 자체 관리 | S3/DynamoDB 또는 TF Cloud |
| 드리프트 탐지 | 내장 | CFN 기반 | `plan` 명령 |
| 비용 | 무료 | 무료 | 무료 (TF Cloud는 유료) |

### IaC 아키텍처 패턴

**환경 분리** 패턴은 단일 매개변수화 템플릿을 dev/staging/prod에 각각 다른 파라미터로 배포합니다.

![환경 분리 아키텍처 — 공통 템플릿(parameterized)을 Parameter Store/환경별 파라미터 파일로 Dev Stack(t3.small·1AZ), Staging Stack(t3.medium·2AZ), Prod Stack(t3.xlarge·3AZ)으로 분리 배포](/assets/images/posts/aws-ops-iac/20-04-패턴-1-환경-분리.svg)

**재사용 가능한 모듈** 패턴은 VPC, ECS, RDS, Auth, Monitoring, Security 모듈을 조합해 일관된 보안·모니터링과 조직 표준을 준수합니다.

![재사용 가능한 모듈 아키텍처 — Construct Library(VPC/ECS/RDS/Auth/Monitoring/Security 표준 모듈)를 조합해 애플리케이션 스택 구성, 일관된 보안·모니터링·조직 표준 준수](/assets/images/posts/aws-ops-iac/20-05-패턴-2-재사용-가능한-모듈.svg)

> **설계 원칙** — 환경 분리(별도 스택/계정), 모듈화(VPC/컴퓨팅/DB 독립), 매개변수화(환경 차이를 Parameters로), CI/CD 통합(코드 리뷰·테스트·자동 배포), 보안 검증(cfn-guard/cdk-nag), 롤백 전략(`DeletionPolicy: Retain`).

---

## Takeaway

1. **관측·감사·IaC는 운영 자동화의 삼위일체입니다** — CloudWatch로 시스템 상태를 보고, CloudTrail+Config로 변경을 추적하고, CloudFormation/CDK로 인프라를 재현 가능하게 관리합니다. 세 축을 함께 세우면 "보이고, 추적하고, 재현하는" 운영 체계가 완성됩니다
2. **다중 계정은 중앙 집중이 정답입니다** — Organization Trail로 모든 계정의 API를, Config Aggregator로 모든 계정의 규정 준수를, StackSets로 모든 계정에 IaC를 중앙에서 배포합니다. 보안 전용 Audit 계정을 두면 감사 체계가 한층 견고해집니다
3. **자동화의 사각지대를 없애세요** — CloudWatch 경보 → EventBridge → Lambda/SSM으로 자동 복구를, Config 위반 → Remediation → SSM Automation으로 자동 수정을, CDK Pipelines/cdk-nag로 배포 전 검증을 구성하면 사람의 개입 없이도 안정성이 유지됩니다

---

> **AWS 시리즈 11/16**
>
> | | |
> |---|---|
> | ← [인증 & 방화벽 — Cognito, ACM, Shield/WAF]({% post_url 2026-06-14-AWS-Auth-Firewall %}) | |
> | | [메시징 & 컨테이너 — SQS/SNS/Kinesis와 ECS/EKS]({% post_url 2026-06-14-AWS-Messaging-Containers %}) → |
