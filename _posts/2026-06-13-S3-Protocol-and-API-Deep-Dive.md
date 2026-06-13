---
layout: post
title: "S3 프로토콜과 API — 개요부터 실전 활용까지"
categories: [AWS, S3]
description: Amazon S3의 핵심 아키텍처부터 REST API, CLI/SDK 실전 활용, Pre-signed URL, 멀티파트 업로드, 이벤트 알림까지 정리합니다.
keywords: [S3, AWS, API, CLI, SDK, 멀티파트]
toc: true
toc_sticky: true
---

## Hook

S3는 단순한 파일 저장소가 아닙니다. 2006년 출시 이후 진화해 온 객체 스토리지 프로토콜이자, 클라우드 데이터 공유의 사실상 표준(de facto standard)입니다.

이 글에서는 S3의 핵심 데이터 모델부터 REST API, AWS CLI/SDK 실전, Pre-signed URL, 멀티파트 업로드, 이벤트 알림까지 한 번에 정리합니다.

![S3 프로토콜과 호환 생태계 전체 개요도](/assets/images/posts/s3-protocol-api/01-01-11-개요.svg)

---

## TL;DR

- **S3는 버킷/객체/키 3가지로 구성** — 폴더가 아닌 평면(flat) 구조, prefix로 논리적 분류
- **REST API + AWS CLI + SDK(Python/Java/Go)로 접근** — 모든 HTTP 도구와 호환
- **Pre-signed URL로 임시 접근 권한 위임** — IAM 없이도 타인에게 업로드/다운로드 허용
- **멀티파트 업로드로 5TB 파일 처리** — 3단계 프로세스로 병렬 업로드, 실패한 파트만 재시도
- **이벤트 알림으로 데이터 파이프라인 자동화** — S3 → SQS/SNS/Lambda/EventBridge

---

## S3란? — 프로토콜 관점

Amazon S3(Simple Storage Service)는 **HTTP 기반 RESTful API**로 동작하는 객체 스토리지입니다. 모든 조작은 표준 HTTP 메서드(PUT, GET, DELETE, HEAD, POST)로 이루어지며, 이 단순함이 S3 API를 업계 표준으로 만들었습니다.

### 핵심 구성 요소

![S3 핵심 구성 요소 — 버킷/객체/키 계층 구조](/assets/images/posts/s3-protocol-api/01-02-21-핵심-구성-요소.svg)

| 구성 요소 | 설명 | 제약사항 |
|-----------|------|----------|
| **Bucket (버킷)** | 객체의 컨테이너. 전역 고유 이름 필요 | 계정당 최대 100개(증가 요청 가능), 이름 3~63자 |
| **Object (객체)** | 데이터의 기본 단위. Key + Value + Metadata | 크기 0Byte~5TB, 단일 PUT 최대 5GB |
| **Key (키)** | 버킷 내 객체의 고유 식별자. 경로+파일명 형태 | 최대 1,024바이트 UTF-8 |
| **Version ID** | 버전 관리 활성화 시 특정 버전 식별자 | null 또는 자동 생성 ID |
| **Metadata** | 시스템 메타데이터 + 사용자 정의 메타데이터 | 사용자 메타데이터는 `x-amz-meta-` 접두사 |

> S3의 "폴더"는 실제로 존재하지 않습니다. Key의 **prefix(접두사)**와 **delimiter(`/`)**를 조합하여 폴더처럼 보이게 할 뿐입니다.

### S3 API가 표준이 된 이유

| 특징 | 설명 |
|------|------|
| **단순성** | 6개의 HTTP 메서드로 모든 조작 표현 |
| **무상태성** | RESTful 설계로 세션 상태 미유지, 수평 확장 용이 |
| **범용성** | HTTP를 지원하는 모든 환경에서 사용 가능 |
| **확장성** | 단일 객체 0Byte~5TB, 버킷 내 객체 수 무제한 |
| **내구성** | 99.999999999%(11 nine) 객체 내구성 보장 |

### 데이터 일관성 모델

S3는 모든 리전에서 **강력한 쓰기 후 읽기(read-after-write) 일관성**을 제공합니다. 객체 업로드 직후 GET 요청을 보내면 최신 데이터가 반환됩니다.

### 스토리지 클래스 비교

| 스토리지 클래스 | 용도 | 비용 | 검색 지연 |
|----------------|------|------|----------|
| **Standard** | 자주 접근하는 데이터 | 표준 | 즉시 |
| **Standard-IA** | 드물게 접근하지만 빠른 검색 필요 | 저렴 | 즉시 |
| **One Zone-IA** | 단일 AZ, 재생성 가능 데이터 | 더 저렴 | 즉시 |
| **Glacier Instant** | 아카이브, 즉시 검색 | 매우 저렴 | 즉시 |
| **Glacier Flexible** | 장기 아카이브 | 극히 저렴 | 1~5분~12시간 |
| **Glacier Deep Archive** | 최장기 아카이브 | 최저가 | 12~48시간 |

---

## S3 인증과 엔드포인트

### 자격 증명 유형

S3 API 호출 시 모든 요청은 **AWS Signature V4(SigV4)**로 서명되어야 합니다. 목적에 따라 4가지 자격 증명 유형을 선택할 수 있습니다.

![S3 자격 증명 유형 비교](/assets/images/posts/s3-protocol-api/01-03-42-자격-증명-유형.svg)

| 유형 | 구성 | 수명 | 용도 |
|------|------|------|------|
| **장기 자격 증명** | Access Key ID + Secret Access Key | 영구 (수동 삭제 시) | IAM 사용자, 서비스 계정 |
| **임시 자격 증명 (STS)** | Access Key + Secret Key + Session Token | 15분 ~ 12시간 | 임시 접근, 교차 계정 |
| **IAM 역할 (Role)** | EC2/Lambda에 자동 부여 | 자동 갱신 | 서비스 간 접근 |
| **Pre-signed URL** | 서명이 포함된 URL | 최대 7일 (SigV4) | 임시 공유, 브라우저 접근 |

### 엔드포인트 유형

![S3 엔드포인트 유형 비교](/assets/images/posts/s3-protocol-api/01-04-54-엔드포인트-유형-비교.svg)

| 유형 | 형식 | 용도 | 비고 |
|------|------|------|------|
| **Virtual-hosted** | `bucket.s3.region.amazonaws.com` | 일반 접근 (권장) | DNS 기반 라우팅, 성능 최적 |
| **Path-style** | `s3.region.amazonaws.com/bucket` | 하위 호환 | 레거시, 신규 버킷은 지원 중단 |
| **S3 Access Point** | `ap-account.s3-accesspoint.region.amazonaws.com` | 공유/접근 관리 | 별칭 지원 |
| **VPC Endpoint** | `vpce-xxx.s3.region.vpce.amazonaws.com` | 프라이빗 접근 | 인터넷 없이 VPC 내부 접근 |
| **Express One Zone** | `bucket.s3express-az.region.amazonaws.com` | 고성능 | ms 단위 일관된 지연 |

### AWS CLI 설정 예시

```bash
# 자격 증명 설정
aws configure
# Access Key ID, Secret Key, Region(ap-northeast-2), Output(json) 입력

# 또는 환경 변수로 설정
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/...
export AWS_DEFAULT_REGION=ap-northeast-2
```

---

## S3 API 실전

### 기본 조작 (CRUD)

AWS CLI는 `aws s3`(고수준)와 `aws s3api`(저수준) 두 가지 인터페이스를 제공합니다.

![AWS CLI S3 조작 흐름 — 업로드/다운로드/삭제/관리](/assets/images/posts/s3-protocol-api/02-01-15-삭제-및-관리.svg)

```bash
# 버킷 생성 및 목록
aws s3 mb s3://my-data-bucket --region ap-northeast-2
aws s3 ls

# 업로드 / 다운로드 / 동기화
aws s3 cp data.csv s3://my-data-bucket/data/
aws s3 cp s3://my-data-bucket/data/data.csv ./
aws s3 sync ./local-data s3://my-data-bucket/data/

# 삭제 및 버킷 제거
aws s3 rm s3://my-data-bucket/temp/ --recursive
aws s3 rb s3://my-data-bucket --force
```

Python Boto3로 동일한 작업을 수행할 수 있습니다.

```python
import boto3

s3 = boto3.client('s3', region_name='ap-northeast-2')

# 업로드
s3.put_object(
    Bucket='my-data-bucket',
    Key='data/hello.txt',
    Body=b'Hello, S3!',
    ContentType='text/plain',
    Metadata={'author': 'data-team'}
)

# 다운로드
resp = s3.get_object(Bucket='my-data-bucket', Key='data/hello.txt')
print(resp['Body'].read().decode('utf-8'))
```

### Pre-signed URL

Pre-signed URL은 S3 객체에 대한 **임시 접근 권한을 URL 자체에 인코딩**하는 메커니즘입니다. URL에 서명이 포함되어 있어, 자격 증명 없이도 지정된 작업만 지정된 시간 동안 수행할 수 있습니다.

![Pre-signed URL 흐름 — 파일 공유 시나리오](/assets/images/posts/s3-protocol-api/02-02-31-pre-signed-url-개요.svg)

| 유형 | 용도 | HTTP Method | 만료 범위 |
|------|------|-------------|----------|
| **GET Pre-signed** | 객체 읽기/다운로드 공유 | GET | 최대 7일 |
| **PUT Pre-signed** | 객체 업로드 공유 | PUT | 최대 7일 |
| **POST Pre-signed** | 조건부 업로드 (정책 문서) | POST | 최대 7일 |

```python
# 다운로드용 URL (1시간 유효)
url = s3.generate_presigned_url(
    'get_object',
    Params={'Bucket': 'my-data-bucket', 'Key': 'data/report.csv'},
    ExpiresIn=3600
)

# 업로드용 URL (30분 유효)
upload_url = s3.generate_presigned_url(
    'put_object',
    Params={'Bucket': 'my-data-bucket',
            'Key': 'uploads/user-file.csv',
            'ContentType': 'text/csv'},
    ExpiresIn=1800
)
```

> **보안 팁**: 최소 만료 시간을 설정하고, HTTPS를 필수로 사용하세요. PUT URL은 Content-Type과 Content-Length를 제한하여 악용을 방지할 수 있습니다.

### 멀티파트 업로드

대용량 파일(100MB 이상 권장)을 여러 파트로 분할하여 **병렬로 업로드**하는 메커니즘입니다. 단일 PUT 요청의 5GB 한계를 극복하고, 실패한 파트만 재시도할 수 있습니다.

![멀티파트 업로드 3단계 프로세스](/assets/images/posts/s3-protocol-api/02-03-42-3단계-멀티파트-업로드-프로세스.svg)

| 항목 | 제한 |
|------|------|
| 최대 객체 크기 | **5TB** (멀티파트 사용 시) |
| 파트 크기 | 5MB ~ 5GB (마지막 파트 제외) |
| 최대 파트 수 | 10,000개 |

3단계 프로세스는 다음과 같습니다:

1. **CreateMultipartUpload** — 업로드 세션 시작, `UploadId` 발급
2. **UploadPart** — 각 파트를 병렬 업로드, `ETag` 수신
3. **CompleteMultipartUpload** — 모든 파트 조합하여 객체 완성

AWS CLI는 임계값 이상 파일을 자동으로 멀티파트 처리합니다. Boto3로 수동 제어하려면:

<details>
<summary>📖 Boto3 멀티파트 업로드 전체 코드 보기</summary>

```python
import boto3, os
from concurrent.futures import ThreadPoolExecutor, as_completed

s3 = boto3.client('s3')

def multipart_upload(bucket, key, file_path, part_size=100*1024*1024):
    file_size = os.path.getsize(file_path)

    # Step 1: 멀티파트 업로드 초기화
    mpu = s3.create_multipart_upload(Bucket=bucket, Key=key)
    upload_id = mpu['UploadId']

    # Step 2: 파일을 파트로 분할하여 병렬 업로드
    def upload_part(part_num, start, end):
        with open(file_path, 'rb') as f:
            f.seek(start)
            data = f.read(end - start)
            resp = s3.upload_part(
                Bucket=bucket, Key=key, PartNumber=part_num,
                UploadId=upload_id, Body=data
            )
        return {'PartNumber': part_num, 'ETag': resp['ETag']}

    parts = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures, offset, num = [], 0, 1
        while offset < file_size:
            end = min(offset + part_size, file_size)
            futures.append(executor.submit(upload_part, num, offset, end))
            offset, num = end, num + 1
        for future in as_completed(futures):
            parts.append(future.result())

    # Step 3: 멀티파트 업로드 완료
    parts.sort(key=lambda x: x['PartNumber'])
    s3.complete_multipart_upload(
        Bucket=bucket, Key=key, UploadId=upload_id,
        MultipartUpload={'Parts': parts}
    )
    print(f"업로드 완료: s3://{bucket}/{key}")
```

</details>

---

## S3 호환 API 생태계

![S3 호환 API 범용 공유 생태계](/assets/images/posts/s3-protocol-api/01-05-63-s3-호환-api-범용-공유-생태계.svg)

S3 API는 클라우드 스토리지의 **사실상 표준**이 되었습니다. AWS 외부에서도 동일한 API로 데이터를 저장하고 공유할 수 있습니다.

| S3 호환 스토리지 | 특징 |
|------------------|------|
| **MinIO** | 오픈소스, 온프레미스 자체 호스팅 |
| **Ceph RGW** | 오픈소스, 분산 스토리지 통합 |
| **VersityGW** | 고성능 온프레미스 S3 게이트웨이 |
| **Cloudflare R2** | egress 요금 없는 S3 호환 스토리지 |
| **Google Cloud Storage** | 호환 모드 지원 |

S3 호환 API를 사용하면 **벤더 종속성(vendor lock-in)을 방지**할 수 있습니다. 동일한 Boto3 코드로 AWS S3와 MinIO를 모두 제어할 수 있습니다.

```python
# MinIO(온프레미스)에 동일한 Boto3 코드 사용
s3 = boto3.client('s3',
    endpoint_url='https://minio.company.com:9000',
    aws_access_key_id='minio-key',
    aws_secret_access_key='minio-secret'
)

# AWS S3와 완전 동일한 API
s3.put_object(Bucket='shared-data', Key='report.csv', Body=data)
```

---

## 이벤트 기반 데이터 파이프라인

![S3 이벤트 알림 아키텍처](/assets/images/posts/s3-protocol-api/02-04-61-이벤트-알림-아키텍처.svg)

S3 이벤트 알림은 객체 업로드/삭제 등의 변화를 **자동으로 다른 서비스에 전달**합니다. 별도의 폴링 없이 데이터 파이프라인을 구축할 수 있습니다.

| 라우팅 대상 | 용도 |
|-------------|------|
| **SNS** | 이메일/SMS/HTTP 알림, 팬아웃 |
| **SQS** | 워커 프로세스 큐잉, 배치 처리 |
| **Lambda** | 데이터 처리/변환/분석 자동 실행 |
| **EventBridge** | 고급 필터링, 다중 타겟 라우팅 |

대표적인 활용 사례는 **파일 업로드 → 자동 처리** 파이프라인입니다. CSV가 버킷에 업로드되면 Lambda가 트리거되어 데이터를 정제하고 분석 결과를 저장합니다.

<details>
<summary>📖 EventBridge 규칙 설정 전체 코드 보기</summary>

```bash
# EventBridge 규칙 생성 — 특정 버킷의 PutObject 이벤트 감지
aws events put-rule \
  --name "S3DataUploadRule" \
  --event-pattern '{
    "source": ["aws.s3"],
    "detail-type": ["AWS API Call via CloudTrail"],
    "detail": {
      "eventSource": ["s3.amazonaws.com"],
      "eventName": ["PutObject", "CompleteMultipartUpload"],
      "requestParameters": {
        "bucketName": ["my-data-bucket"]
      }
    }
  }'

# 규칙에 Lambda 타겟 추가
aws events put-targets \
  --rule "S3DataUploadRule" \
  --targets '[{
    "Id": "ProcessUpload",
    "Arn": "arn:aws:lambda:ap-northeast-2:123456789012:function:process-upload"
  }]'
```

</details>

주요 이벤트 유형은 다음과 같습니다:

| 이벤트 카테고리 | 대표 이벤트 |
|----------------|------------|
| **Object Created** | `s3:ObjectCreated:Put`, `CompleteMultipartUpload` |
| **Object Removed** | `s3:ObjectRemoved:Delete`, `DeleteMarkerCreated` |
| **Object Restore** | `s3:ObjectRestore:Post`, `Completed` |
| **Object Tagging** | `s3:ObjectTagging:Put` |

---

## Takeaway

1. **S3는 파일 시스템이 아니라 객체 스토리지** — Key-Value 구조에 평면 네임스페이스, "폴더"는 prefix의 논리적 표현일 뿐입니다
2. **Pre-signed URL로 IAM 없이 권한 위임** — 임시 서명 URL을 발급하여 외부 사용자에게 업로드/다운로드를 허용할 수 있습니다
3. **멀티파트 업로드로 대용량 파일을 병렬 처리** — 3단계 프로세스(Create → Upload → Complete)로 5TB까지 안정적으로 업로드할 수 있습니다
