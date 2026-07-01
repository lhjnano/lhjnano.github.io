---
layout: post
title: "[S3 2/7] AWS 데이터 공유 서비스 3종: Registry, Data Exchange, Access Points"
categories: [AWS, S3]
description: AWS에서 데이터를 공유하는 세 가지 핵심 서비스를 정리합니다. Registry of Open Data, AWS Data Exchange, S3 Access Points의 차이와 사용 시나리오를 다룹니다.
keywords: [S3, AWS, DataExchange, AccessPoints, OpenData]
toc: true
toc_sticky: true
---

## Hook

> 수백 개의 데이터셋을 외부 조직과 공유해야 한다면? AWS는 세 가지 방법을 제공합니다. 바로 공개 데이터 레지스트리, 마켓플레이스, 그리고 세밀한 접근 제어.

데이터를 공유하는 일은 기술적으로 간단해 보이지만, 규모가 컨질수록 인증·과금·권한 관리가 폭발적으로 복잡해집니다. AWS는 이 문제를 해결하기 위해 목적이 전혀 다른 세 가지 서비스를 제공합니다. 이 글에서는 **Registry of Open Data**, **AWS Data Exchange**, **S3 Access Points**를 비교하고, 각각 언제 써야 하는지 정리합니다.

---

## TL;DR

- **Registry of Open Data**: 공개 데이터셋을 무료로 호스팅. 누구나 접근 가능
- **AWS Data Exchange**: 유료/무료 데이터를 구독 모델로 거래. 결제 연동
- **S3 Access Points**: 버킷 하나에 여러 접근 정책을 분리. 대규모 공유 관리
- 핵심 차이: **공개(Registry)** vs **상업(Data Exchange)** vs **내부 통제(Access Points)**

---

## 어떤 문제를 해결하나요?

데이터를 외부에 공유하려면 다음과 같은 질문에 직면합니다.

- "공개 데이터인가, 상업 데이터인가?"
- "누가 접근할 수 있어야 하는가?"
- "결제와 라이선스는 어떻게 관리하는가?"
- "버킷 정책이 수백 줄이 되면 어떡하지?"

AWS는 이 네 가지 질문에 대해 각각 다른 서비스로 대답합니다.

### 한눈에 보는 비교표

| 구분 | Registry of Open Data | AWS Data Exchange | S3 Access Points |
|------|-----------------------|-------------------|-------------------|
| **목적** | 공개 데이터셋 배포 | 상업적 데이터 거래 | 내부 접근 제어 분산 |
| **비용** | 무료 (다운로드만 과금) | 구독료 + Data Exchange 수수료 | S3 요금만 |
| **접근 방식** | `--no-sign-request` | 구독 후 S3 API 직접 호출 | Access Point ARN |
| **인증** | 불필요 (익명) | AWS 계정 + 구독 승인 | IAM + AP 정책 |
| **적합한 시나리오** | 연구·공공 데이터 | 금융·날씨·ML 데이터 판매 | 다수 팀/파트너 접근 관리 |

---

## 1. Registry of Open Data (공개 데이터)

### 무엇인가요?

AWS가 호스팅하는 공개 데이터셋 컬렉션입니다. 2026년 기준 **400개 이상**의 데이터셋이 등록되어 있으며, 누구나 무료로 접근할 수 있습니다. GitHub(`awslabs/open-data-registry`)에서 커뮤니티 기반으로 관리됩니다.

### 아키텍처

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-01-registry-architecture.svg" alt="Registry of Open Data: 데이터 제공자가 S3 공개 버킷에 데이터를 올리고, 연구자/기업/개발자가 인증 없이 접근하는 흐름" loading="lazy" />

### 대표 데이터셋

| 카테고리 | 대표 데이터셋 | 활용 예시 |
|----------|--------------|----------|
| 지구 관측 | Landsat, Sentinel-2, MODIS | 위성 영상, 지표면 변화 감지 |
| 생명 과학 | 1000 Genomes, TCGA, gnomAD | 유전체, 암 연구 |
| 기상/환경 | NOAA GOES, NEXRAD | 기상 관측, 기후 예측 |
| 자연어 처리 | Common Crawl, Wikipedia | LLM 사전 학습 |
| 공간 정보 | Terrain Tiles, OpenStreetMap | 지형, 지도 데이터 |

### AWS CLI로 접근하기

```bash
# 인증 없이 버킷 목록 확인
aws s3 ls s3://sentinel-s2-l1c/ --no-sign-request

# 데이터 다운로드
aws s3 cp s3://sentinel-s2-l1c/tiles/54/S/WE/2024/ ./data/ \
  --recursive --no-sign-request
```

핵심은 `--no-sign-request` 옵션입니다. AWS 계정 없이도 공개 데이터셋에 바로 접근할 수 있습니다.

---

## 2. AWS Data Exchange (데이터 마켓플레이스)

### 무엇인가요?

서드파티 데이터를 구독/판매하는 마켓플레이스입니다. 데이터 제공자는 자신의 S3 버킷에 데이터를 그대로 둔 채(**In-place 접근**) 구독자에게 직접 접근 권한을 부여합니다. 결제, 라이선스, 구독 관리를 AWS가 자동으로 처리합니다.

### 전통적 방식 vs Data Exchange

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-02-copy-vs-inplace.svg" alt="전통적 복사 방식(제공자 S3에서 구독자 S3로 복사 후 분석)과 Data Exchange 직접 접근 방식(제공자 S3에서 구독자 분석 환경으로 복사 없이 접근) 비교" loading="lazy" />

### 작동 흐름

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-03-data-exchange-flow.svg" alt="AWS Data Exchange 작동 흐름: 데이터 제공자 S3 버킷, 중앙의 Data Exchange(구독/라이선스/결제 관리), 구독자 분석 환경, 하단 AWS Marketplace 카탈로그" loading="lazy" />

### 3단계 프로세스

1. **구독**: AWS Marketplace에서 데이터셋 검색 후 구독 신청 (유료/무료)
2. **전송**: 승인되면 S3 API로 제공자 버킷에 직접 접근 (복사 불필요)
3. **사용**: Athena, EMR, SageMaker 등에서 바로 분석

### 구독 라이프사이클

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-04-subscription-lifecycle.svg" alt="구독 라이프사이클: 검색, 구독 신청, 승인 대기, 접근 활성, 갱신/만료의 5단계 흐름" loading="lazy" />

<details>
<summary><b>Data Exchange 데이터셋 생성 (전체 코드)</b></summary>

```bash
# 제공자: 데이터셋 등록
aws dataexchange create-data-set \
  --name "Weather Analytics Data" \
  --asset-type S3_DATA_ACCESS \
  --description "Daily weather data"

# 구독자: 데이터셋 검색
aws dataexchange list-data-sets

# 구독자: S3 데이터 직접 접근 (In-place)
aws s3 ls s3://dataprovider-bucket/dataset/ \
  --request-payer requester
```

</details>

### Data Exchange vs 직접 버킷 공유

| 특징 | AWS Data Exchange | 직접 버킷 정책 공유 |
|------|-------------------|---------------------|
| 데이터 복사 | 불필요 (In-place) | 불필요 |
| 결제/청구 | AWS가 자동 처리 | 직접 구현 필요 |
| 라이선스 관리 | 서비스 내장 | 직접 관리 |
| 구독 관리 | 자동 (시작/종료/갱신) | 수동 정책 업데이트 |
| 데이터 카탈로그 | AWS Marketplace 노출 | 별도 홍보 필요 |
| 권한 회수 | 구독 만료시 자동 | 수동 정책 제거 |
| 적합한 시나리오 | 상업적 데이터 판매 | 파트너 간 무료 공유 |

---

## 3. S3 Access Points (세밀한 접근 제어)

### 무엇인가요?

하나의 버킷에 여러 접근 지점(Access Point)을 생성하여, 각 애플리케이션이나 팀에 맞춤형 정책을 적용하는 기능입니다. 버킷 정책이 수백 줄로 비대해지는 문제를 해결합니다.

### 왜 필요한가?

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-05-why-access-points.svg" alt="기존 단일 버킷 정책(수백 줄 규칙, 관리 어려움)을 Access Points로 정책 분산(팀별 깔끔한 AP 정책)으로 개선" loading="lazy" />

### 아키텍처

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-06-access-points-architecture.svg" alt="S3 Access Points 아키텍처: shared-data 버킷의 /team-a/, /team-b/, /public/ prefix가 각각 Access Point로 연결되고, 각 팀과 사용자가 별도 정책으로 접근" loading="lazy" />

### 이중 정책 평가

Access Point를 통한 요청은 **Access Point 정책**과 **버킷 정책**이 모두 평가됩니다. 두 정책이 모두 허용해야 최종적으로 접근이 허용됩니다.

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-07-dual-policy-evaluation.svg" alt="이중 정책 평가 흐름: 요청 수신 후 Access Point 정책 평가, 버킷 정책 평가를 차례로 통과하면 허용, 어느 하나라도 Deny면 거부" loading="lazy" />

<details>
<summary><b>Access Point 생성 + 정책 설정 (전체 코드)</b></summary>

```bash
# Access Point 생성
aws s3control create-access-point \
  --name "team-a-ap" \
  --bucket "shared-data" \
  --account-id "123456789012"

# Access Point 전용 정책 설정
aws s3control put-access-point-policy \
  --name "team-a-ap" \
  --account-id "123456789012" \
  --policy '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": [
        "arn:aws:s3:ap-northeast-2:123456789012:accesspoint/team-a-ap/object/*"
      ]
    }]
  }'

# Access Point를 통해 객체 접근
aws s3 cp data.csv \
  s3://arn:aws:s3:ap-northeast-2:123456789012:accesspoint/team-a-ap/data.csv
```

</details>

### VPC Access Point (프라이빗 네트워크)

VPC 제한 Access Point를 생성하면, 지정된 VPC에서만 접근할 수 있습니다. 외부 인터넷이나 다른 VPC의 요청은 자동으로 차단됩니다.

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-08-vpc-access-point.svg" alt="VPC 제한 Access Point: 사내 VPC에서는 접근 허용, 외부 인터넷에서는 접근 거부" loading="lazy" />

<details>
<summary><b>VPC 제한 Access Point 생성</b></summary>

```bash
aws s3control create-access-point \
  --name "internal-ap" \
  --bucket "shared-data" \
  --account-id "123456789012" \
  --vpc-configuration VpcId=vpc-0abc123def456
```

</details>

### Best Practices

| 실천 항목 | 설명 |
|-----------|------|
| 정책 분산 | 팀/앱마다 별도 Access Point 사용, 버킷 정책은 최소화 |
| VPC 제한 | 민감 데이터는 VPC 전용 AP로 인터넷 차단 |
| Prefix 격리 | 각 AP에 다른 prefix 매핑 (`/team-a/`, `/team-b/`) |
| 버킷 정책 위임 | 버킷 정책에서 AP 통과를 명시적 허용 |
| Multi-Region AP | 글로벌 서비스시 자동 장애조치 + 지연시간 최적화 |

---

## 언제 무엇을 쓸까?

| 상황 | 추천 서비스 | 이유 |
|------|------------|------|
| 공개 연구·공공 데이터를 무료로 배포 | **Registry of Open Data** | 인증·결제 불필요, 커뮤니티 카탈로그 노출 |
| 상업 데이터를 유료로 판매 | **AWS Data Exchange** | 결제·라이선스·구독을 AWS가 자동 처리 |
| 다수 내부 팀의 버킷 접근을 관리 | **S3 Access Points** | 버킷 정책 분산으로 관리 복잡도 해결 |
| 파트너사와 VPC 내에서 안전하게 공유 | **Access Points + VPC** | 네트워크 수준 접근 제어 |
| 글로벌 다중 리전 데이터 공유 | **Multi-Region Access Points** | 단일 글로벌 엔드포인트 + 자동 장애조치 |

<img src="{{ site.baseurl }}/assets/images/posts/s3-data-sharing-services/03-09-decision-tree.svg" alt="데이터 공유 방식 선택 가이드: 상업적 판매 여부, 다수 구독자 여부, 공개 데이터 여부, 내부 다수 팀 여부에 따라 Data Exchange, Registry, Access Points 중 선택하는 의사결정 흐름" loading="lazy" />

---

## 마치며

데이터를 공유한다는 것이 "버킷 권한 좀 열어주면 되는 거 아닌가?"라고 생각했던 시절이 있습니다. 하지만 규모가 커지면서 공개 여부, 결제, 라이선스, 접근 제어가 각각 완전히 다른 문제라는 것을 깨달았습니다. AWS가 이 세 가지를 Registry of Open Data, Data Exchange, Access Points라는 전혀 다른 서비스로 분리해 놓은 것은, 데이터 공유라는 행위 자체가 하나의 기술적 과제가 아니라 비즈니스 맥락에 따라 완전히 다른 해법을 요구한다는 뜻이었습니다.

특히 Data Exchange의 In-place 접근 방식은 제 선입견을 깨뜨렸습니다. "데이터를 공유하려면 복사해야 한다"는 당연한 듯한 가정이, 실제로는 스토리지 비용과 동기화 문제라는 거대한 부채를 만들어낸다는 것을 알게 되었습니다. 복사 없이 원본 위치에서 직접 접근하면서도 결제와 라이선스를 자동 처리한다는 것은, 클라우드가 제공하는 가장 큰 가치가 인프라 자동화가 아니라 **비즈니스 로직의 자동화**라는 사실을 일깨워줍니다.

데이터 공유를 설계하실 때는 "기술적으로 어떻게?"보다 먼저 "누구에게, 왜, 어떤 조건으로?"를 물어보시길 권합니다. 그 답이 곧 세 서비스 중 하나를 자연스럽게 가리켜 줄 것입니다.

---

> **S3 시리즈 2/7**
>
> | | |
> |---|---|
> | ← [S3 프로토콜과 API. 개요부터 실전 활용까지]({% post_url 2026-05-15-S3-Protocol-and-API-Deep-Dive %}) | |
> | | [S3 Access Grants와 복제로 대규모 데이터 공유하기]({% post_url 2026-05-17-S3-Access-Grants-and-Replication %}) → |
