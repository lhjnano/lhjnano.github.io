---
layout: post
title: "[AWS 10/16] 인증 & 방화벽 — Cognito, ACM, Shield/WAF"
categories: [AWS, Security]
description: 사용자 인증(Cognito), SSL/TLS 인증서(ACM), DDoS 방어(Shield), 웹 방화벽(WAF), 네트워크 방화벽까지 AWS 보안 서비스를 정리합니다.
keywords: [Cognito, ACM, WAF, Shield, AWS, 보안, SSL]
toc: true
toc_sticky: true
---

## Hook

사용자가 로그인하고, 데이터가 암호화되어 전송되고, 공격 트래픽이 차단되는 과정은 하나의 보안 파이프라인입니다. AWS는 이 파이프라인을 **인증 → 암호화 → 방어** 세 계층으로 분담합니다. **Cognito**가 사용자 신원을 증명하고, **ACM**이 통신을 암호화하며, **Shield·WAF·Network Firewall**이 악의적 트래픽을 걸러냅니다.

세 영역은 독립적이지만 함께 동작해야 완전한 보안이 완성됩니다. 이 글에서는 각 서비스의 핵심 메커니즘과 **어떻게 연결되는지**를 정리합니다.

---

## TL;DR

- **Cognito** — User Pool이 사용자 디렉터리·JWT 발급을 담당하고, Identity Pool이 AWS 임시 자격 증명을 발급합니다. 소셜 로그인·SAML·MFA까지 지원합니다
- **ACM** — 무료 SSL/TLS 인증서를 자동 발급·갱신·배포합니다. ELB·CloudFront·API Gateway에 원클릭으로 적용합니다
- **Shield/WAF/Network Firewall** — Shield는 L3/L4 DDoS 방어(Standard 무료), WAF는 L7 웹 공격 차단, Network Firewall은 VPC 내 상태 저장 방화벽을 제공합니다
- **Defense in Depth** — Edge(Shield+WAF) → Network(Network Firewall) → Application(IAM/KMS) → Monitoring(GuardDuty/Security Hub) 4계층으로 다중 방어합니다

---

## 1. Cognito — 사용자 인증

Amazon Cognito는 웹·모바일 애플리케이션에 가입, 로그인, 액세스 제어 기능을 제공하는 완전관리형 서비스입니다. 백엔드 인프라 없이 수백만 사용자를 처리하며, **User Pool**과 **Identity Pool** 두 축으로 구성됩니다.

### 1.1 전체 아키텍처

![Cognito 아키텍처]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-01-핵심-기능.svg)

웹·모바일·타사 서비스가 User Pool에서 인증을 받아 JWT를 발급받고, Identity Pool이 이를 기반으로 AWS 임시 자격 증명을 발급하여 S3·DynamoDB·Lambda에 접근합니다.

### 1.2 외부 IdP 연동

Cognito는 SAML 2.0(엔터프라이즈 SSO), OIDC(표준 인증), 소셜 자격 증명(Google, Facebook, Apple, Amazon)을 모두 지원합니다. 기존 인증 시스템을 그대로 활용하면서 AWS 관리 편의성을 누릴 수 있습니다.

![외부 IdP 연동]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-02-지원-프로토콜.svg)

| 프로토콜 | 용도 | 지원 제공자 |
|----------|------|------------|
| SAML 2.0 | 엔터프라이즈 SSO | Okta, Azure AD, OneLogin, ADFS |
| OpenID Connect | 표준 인증 | Auth0, Keycloak, Google |
| 소셜 자격 증명 | 소셜 로그인 | Google, Facebook, Apple, Amazon |

### 1.3 User Pool — 디렉터리 & JWT

User Pool은 사용자 계정 정보를 저장하는 **디렉터리** 역할을 합니다. 이메일/비밀번호, SRP 프로토콜 기반 인증, 비밀번호 정책, MFA(SMS/TOTP), 계정 복구를 처리합니다. 성공적인 인증 후 세 종류의 **JWT**를 발급합니다.

![JWT 토큰 구조]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-03-jwt-토큰-구조.svg)

| 토큰 | 유효기간 | 용도 |
|------|---------|------|
| Access Token | 1시간 | API 접근, 권한 부여 |
| ID Token | 1시간 | 사용자 정보 포함 |
| Refresh Token | 30일 | 토큰 갱신 |

User Pool은 인증 이벤트마다 **Lambda 트리거**를 실행할 수 있습니다. Pre Sign-up(가입 검증), Post Authentication(로그인 로깅), Pre Token Generation(클레임 커스터마이징), User Migration(투명 마이그레이션) 등이 대표적입니다.

### 1.4 Identity Pool — AWS 임시 자격 증명

Identity Pool은 인증된 사용자와 미인증(Guest) 사용자에게 **STS를 통해 AWS 임시 자격 증명**(최대 1시간)을 발급합니다. 역할 매핑 규칙으로 사용자 속성·그룹에 따라 IAM 역할을 동적 할당합니다.

![Identity Pool 자격 증명 흐름]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-04-주요-특징.svg)

### 1.5 User Pool vs Identity Pool

| 항목 | User Pool | Identity Pool |
|------|-----------|---------------|
| 주요 목적 | 사용자 인증 및 디렉터리 | AWS 리소스 액세스 권한 |
| 발급 토큰 | JWT (Access, ID, Refresh) | AWS 임시 자격 증명 (STS) |
| 사용자 저장 | 자체 디렉터리에 저장 | 저장하지 않음 |
| 미인증 지원 | 불가 | 가능 (Guest 액세스) |
| AWS 서비스 접근 | 직접 불가 | IAM 역할을 통해 직접 가능 |

> **결합 패턴**: User Pool에서 인증받은 JWT를 Identity Pool에 전달하여 AWS 임시 자격 증명을 획득하는 것이 표준 흐름입니다.

### 1.6 아키텍처 패턴

**모바일 앱 인증** — AWS Amplify SDK로 User Pool에서 인증받고, Lambda 트리거로 비즈니스 로직을 수행하며, Identity Pool 자격 증명으로 S3·DynamoDB·Lambda에 직접 접근합니다.

![모바일 앱 인증]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-05-패턴-1-모바일-앱-인증.svg)

**API Gateway 인증** — SPA 클라이언트가 User Pool JWT를 API Gateway에 전달하면, Cognito Authorizer가 JWT를 검증하고 Lambda 백엔드로 라우팅합니다.

![API Gateway 인증]({{ site.url }}/assets/images/posts/aws-auth-firewall/15-06-패턴-2-api-gateway-인증.svg)

> 프로덕션에서는 항상 **MFA 활성화**를 권장합니다. Cognito Advanced Security Features는 위협 방어, 컴프라미즈드 자격 증명 탐지, 적응형 인증(위험 점수 기반 MFA)을 추가로 제공합니다.

---

## 2. ACM — SSL/TLS 인증서

AWS Certificate Manager(ACM)는 **무료 SSL/TLS 인증서**를 프로비저닝, 관리, 배포하는 서비스입니다. 발급·갱신·배포를 자동화하여 운영 부담을 최소화합니다.

### 2.1 TLS 1.3 Handshake

SSL/TLS 인증서는 서버 인증, 패킷 암호화, 데이터 무결성 보장의 세 역할을 합니다. TLS 1.3은 **1-RTT Handshake**로 지연을 줄이고 향상된 암호화 스위트(ChaCha20-Poly1305 등)를 사용합니다.

![TLS 1.3 Handshake]({{ site.url }}/assets/images/posts/aws-auth-firewall/16-01-ssltls-handshake-과정.svg)

### 2.2 ACM 핵심 이점

- **무료** — ACM에서 발급한 공인 인증서는 추가 비용이 없습니다
- **자동 갱신** — 만료 60일 전 자동 갱신, 무중단 교체
- **AWS 서비스 통합** — ELB, CloudFront, API Gateway에 원클릭 배포
- **안전한 보관** — 인증서 개인 키는 AWS 관리 하드웨어에 보관

### 2.3 인증서 검증

인증서 발급 전 도메인 소유권을 증명해야 합니다. 두 가지 검증 방법을 지원합니다.

| 검증 방식 | 동작 | 자동 갱신 |
|-----------|------|-----------|
| **DNS 검증 (권장)** | 도메인 DNS에 CNAME 레코드 추가. Route 53 연동 시 자동 생성 | 원활 |
| 이메일 검증 | WHOIS 등록 관리자 이메일로 링크 발송 | 어려움 |

![인증서 검증 프로세스]({{ site.url }}/assets/images/posts/aws-auth-firewall/16-03-이메일-검증.svg)

### 2.4 적용 서비스

![ACM 인증서 적용 아키텍처]({{ site.url }}/assets/images/posts/aws-auth-firewall/16-02-3-acm-적용-서비스.svg)

| 서비스 | 적용 방식 | 용도 |
|--------|-----------|------|
| ELB (ALB/NLB) | HTTPS 리스너에 바인딩 | 로드 밸런서 TLS 종료 |
| CloudFront | 배포 설정에 연결 | CDN 엣지 HTTPS |
| API Gateway | 커스텀 도메인에 연결 | REST/WebSocket HTTPS |
| Cognito | User Pool 도메인에 연결 | 호스팅된 UI HTTPS |

> CloudFront용 인증서는 반드시 **us-east-1** 리전에서 발급해야 합니다.

### 2.5 아키텍처 패턴

**HTTPS 종료 (TLS Termination)** — ALB에서 ACM 인증서로 TLS를 종료하고, VPC 내부는 HTTP로 통신합니다. 인스턴스의 암호화 부담을 줄입니다.

![HTTPS 종료 아키텍처]({{ site.url }}/assets/images/posts/aws-auth-firewall/16-04-패턴-1-https-종료-tls-termination.svg)

**글로벌 인증서 자동화** — Route 53이 DNS 검증을 자동 처리하고, ACM이 와일드카드 인증서(`*.example.com`)를 발급하여 CloudFront 전체 엣지 로케이션에 자동 배포·갱신합니다.

![글로벌 인증서 자동화]({{ site.url }}/assets/images/posts/aws-auth-firewall/16-05-패턴-2-인증서-자동화-cloudfront-acm.svg)

> **와일드카드 한계**: `*.example.com`은 `sub.sub.example.com`(2단계 하위)을 커버하지 않습니다. SAN 인증서로 최대 100개 도메인을 하나의 인증서에 포함할 수 있습니다.

---

## 3. Shield / WAF / Network Firewall — 방어 계층

AWS는 **DDoS 방어(Shield)**, **웹 방화벽(WAF)**, **VPC 네트워크 방화벽(Network Firewall)**으로 다층 보안 아키텍처를 제공합니다.

### 3.1 AWS Shield — DDoS 보호

![AWS Shield 방어 계층]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-01-shield-advanced-유료.svg)

| 항목 | Shield Standard | Shield Advanced |
|------|----------------|-----------------|
| 비용 | 무료 (모든 고객 자동 적용) | 월 $3,000 + 데이터 전송료 |
| 보호 계층 | L3, L4 | L3, L4, **L7** |
| 자동 완화 | 네트워크 레벨 | 애플리케이션 레벨 자동 완화 |
| 지원 | AWS Support 플랜 | 전담 DDoS 대응 팀 (DRT) 24/7 |
| 비용 보호 | 없음 | ELB/CloudFront/Route 53 비용 보호 |

Standard는 SYN Flood, UDP 리플렉션, DNS 쿼리 플러드 등을 자동 차단합니다. Advanced는 HTTP 플러드, Slowloris 등 L7 공격까지 완화하며 WAF 규칙을 자동 생성합니다.

### 3.2 WAF — 웹 애플리케이션 방화벽

AWS WAF는 **L7(애플리케이션 계층)**에서 웹 요청을 검사하여 악성 트래픽을 차단합니다. CloudFront, ALB, API Gateway, AppSync, Cognito와 연동합니다.

![WAF 요청 처리 흐름]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-02-waf-동작-흐름.svg)

요청은 Web ACL의 규칙 순서대로 검사되어 **Allow**, **Block**(403), **Count**(모니터링)로 분기됩니다.

| 규칙 유형 | 검사 대상 | 활용 사례 |
|-----------|-----------|-----------|
| IP 기반 | 소스 IP, IP 세트 | 특정 국가/IP 차단 또는 허용 |
| SQL Injection | 쿼리 스트링, 바디 | SQL 인젝션 공격 차단 |
| XSS | 스크립트 태그 | 크로스 사이트 스크립팅 방지 |
| Rate-based | 5분당 요청 수 | 브루트포스, API 남용 방지 |

### 3.3 WAF 관리형 규칙 & 로깅

**관리형 규칙 그룹** — AWS가 사전 구성한 규칙 세트를 즉시 적용할 수 있습니다.

- **AWSManagedRulesCommonRuleSet** — OWASP Top 10 방어
- **AWSManagedRulesSQLiRuleSet** — SQL 인젝션 방어
- **AWSManagedRulesAnonymousIpList** — VPN/프록시 차단
- 서드파티 — Fortinet, Imperva, F5 등 보안 벤더 규칙
- **Bot Control** — 자동화 봇 탐지, 악성 봇 차단
- **Fraud Control** — 크리덴셜 스터핑, 계정 탈취 방지

WAF 로그는 **Kinesis Data Firehose**를 통해 S3(장기 보관), CloudWatch Logs(실시간), Redshift(분석)로 전송되며, Athena로 쿼리 분석합니다.

![WAF 로깅 아키텍처]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-03-waf-로깅.svg)

### 3.4 Network Firewall — VPC 상태 저장 방화벽

AWS Network Firewall은 VPC 내에서 동작하는 **상태 저장(stateful) 방화벽** 서비스입니다. 트래픽이 VPC 외부로 나가지 않고 검사되며, 자동 확장·다중 AZ 고가용성을 제공합니다.

![Network Firewall VPC 배포]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-04-주요-특징.svg)

| 구분 | 상태 저장 (Stateful) | 비저장 (Stateless) |
|------|---------------------|-------------------|
| 연결 추적 | TCP 세션 등 연결 상태 추적 | 개별 패킷 독립 검사 |
| 활용 | 세션 기반 규칙, IPS | IP/포트 기반 필터링 |
| 처리 순서 | Stateless 먼저 → Stateful 규칙 | 1차 필터링 |

Network Firewall은 **Suricata 호환 IPS 규칙**을 지원하여 오픈소스 규칙 형식과 Emerging Threats 위협 인텔리전스 피드를 그대로 사용할 수 있습니다.

### 3.5 Firewall Manager — 중앙 관리

AWS Firewall Manager는 **다중 계정·다중 리전**에서 방화벽 규칙을 중앙에서 관리합니다. AWS Organizations 기반으로 새 계정/리소스에 자동으로 WAF, Shield Advanced, Network Firewall, Security Group 정책을 배포합니다.

![Firewall Manager 다중 계정 관리]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-05-주요-기능.svg)

### 3.6 Defense in Depth — 다중 계층 방어

모든 보안 서비스를 계층화하면 **Defense in Depth** 아키텍처가 완성됩니다.

![Defense in Depth 다중 계층 방어]({{ site.url }}/assets/images/posts/aws-auth-firewall/17-06-다중-계층-방어-defense-in-depth.svg)

| 계층 | 구성 요소 | 역할 |
|------|-----------|------|
| **Edge 보안** | Shield + CloudFront/WAF | DDoS 방어, OWASP Top 10, Bot Control, Rate Limiting |
| **네트워크 보안** | Network Firewall + Security Groups | 상태 저장 방화벽, Suricata IPS, 최소 권한 포트 |
| **애플리케이션 보안** | ALB TLS 종료, IAM, KMS | 암호화, 최소 권한, 데이터 보호 |
| **모니터링 & 대응** | GuardDuty, CloudWatch, Security Hub | 위협 탐지, 지표, 보안 통합 |

> 각 계층에 **독립적인 보안 메커니즘**을 적용하고, Firewall Manager로 조직 전체를 통합 관리하며, Lambda + EventBridge로 자동 대응 체계를 구축합니다.

---

## Takeaway

1. **Cognito의 두 축을 구분하세요** — User Pool은 사용자 디렉터리·JWT 발급을 담당하고, Identity Pool은 AWS 임시 자격 증명(STS) 발급을 담당합니다. User Pool에서 인증받은 JWT를 Identity Pool에 전달해 AWS 리소스에 접근하는 결합 패턴이 표준입니다. 소셜 로그인·SAML SSO·MFA까지 지원하므로 백엔드 인증 인프라 없이 엔터프라이즈급 인증을 구축할 수 있습니다
2. **ACM은 무료이되 us-east-1을 기억하세요** — 공인 SSL/TLS 인증서가 추가 비용 없이 자동 발급·갱신·배포됩니다. DNS 검증을 선택하면 Route 53 연동으로 검증부터 갱신까지 완전 자동화됩니다. 단 CloudFront용 인증서는 반드시 us-east-1에서 발급해야 하며, 공인 인증서 개인 키는 내보낼 수 없습니다
3. **Defense in Depth로 4계층을 겹치세요** — Edge(Shield+WAF)에서 DDoS와 웹 공격을 1차 차단하고, Network Firewall로 VPC 내부를 상태 저장 검사하며, IAM/KMS로 애플리케이션·데이터를 보호하고, GuardDuty/Security Hub로 위협을 탐지합니다. Firewall Manager로 다중 계정 정책을 중앙 관리하면 한 계층이 뚫려도 다음 계층이 막아줍니다

---

> **AWS 시리즈 10/16**
>
> | | |
> |---|---|
> | ← [보안 기초 — IAM 사용자 관리와 KMS 암호화]({% post_url 2026-05-30-AWS-IAM-KMS-Security %}) | |
> | | [운영 & IaC — CloudWatch, CloudTrail, CloudFormation]({% post_url 2026-06-01-AWS-Ops-IaC %}) → |
