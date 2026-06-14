---
layout: post
title: "[S3 7/7] VersityGW로 온프레미스에 S3 API 구축하기"
categories: [S3, Infrastructure, OpenSource]
description: 오픈소스 S3 게이트웨이 VersityGW로 온프레미스에 S3 호환 스토리지를 구축하는 방법을 정리합니다. 설치부터 클러스터 배포, 보안 설정, MinIO 비교까지.
keywords: [VersityGW, S3, 온프레미스, MinIO, Go, FUSE, 하이브리드]
toc: true
toc_sticky: true
---

## Hook

> AWS S3 API가 필요하지만 클라우드 비용이 부담된다면? 오픈소스 VersityGW로 온프레미스에 S3 호환 스토리지를 구축할 수 있습니다.

기존 NFS, GPFS, Lustre 같은 파일 기반 인프라를 그대로 두면서도 S3 생태계의 도구(AWS CLI, Boto3, Spark 등)를 활용하고 싶다면, VersityGW가 그 사이를 잇는 가장 가벼운 다리가 됩니다. 이 글에서는 바이너리 하나로 시작하는 방법부터 클러스터 배포, 보안 설정, MinIO와의 비교까지 실전 중심으로 정리합니다.

## TL;DR

- **VersityGW는 Go 기반 오픈소스 S3 게이트웨이** — POSIX 파일시스템을 S3 API로 노출합니다.
- **바이너리 하나로 시작 가능** — Docker, Kubernetes(Helm), 소스 빌드를 모두 지원합니다.
- **AWS CLI/SDK와 100% 호환** — `--endpoint-url`만 추가하면 기존 코드를 그대로 사용합니다.
- **HAProxy/Nginx로 클러스터 구성** — Stateless 구조이므로 로드밸런서 뒤에 다중 인스턴스로 고가용성을 확보합니다.
- **MinIO 대안** — POSIX 백엔드가 필요하거나 파일과 객체를 동시에 다뤄야 한다면 VersityGW가 유리합니다.

## VersityGW란?

![VersityGW 기본 아키텍처](/assets/images/posts/versitygw-onprem-s3/14-01-1-versitygw-개요.svg)

VersityGW(VERSITY S3 Gateway)는 **POSIX 파일시스템을 S3 API로 번역하는 오픈소스 게이트웨이**입니다. Go 언어로 작성되었고 Apache 2.0 라이선스로 배포됩니다. S3 프로토콜(HTTP REST)을 수신해 POSIX 시스템 콜(write, read, unlink, readdir)로 변환하며, 버킷은 디렉토리로, 객체는 파일로 매핑됩니다.

핵심 특징은 다음과 같습니다.

- **Stateless 아키텍처** — 상태를 저장하지 않아 수평 확장이 쉽습니다.
- **Go + Fiber 웹 프레임워크** 기반으로 가볍고 빠릅니다.
- **POSIX 동시 접근** — S3 API와 일반 파일 접근을 동시에 지원합니다.
- Los Alamos National Laboratory, Pawsey Supercomputing Centre 등 HPC/연구기관에서 실사용 중입니다.

![VersityGW가 해결하는 문제](/assets/images/posts/versitygw-onprem-s3/14-02-2-왜-versitygw가-필요한가.svg)

### 왜 필요한가?

기존 파일 기반 데이터 인프라를 운영 중이라면, 클라우드 마이그레이션 비용과 리스크 없이 S3 호환성을 확보하고 싶은 상황이 자주 발생합니다. VersityGW는 이 간극을 메워줍니다.

| 문제 | VersityGW 해결 |
|------|----------------|
| 기존 NFS/GPFS 데이터를 S3 도구로 접근 불가 | POSIX → S3 API 자동 번역 |
| 클라우드 마이그레이션 비용/리스크 | 온프레미스 유지 + S3 API 제공 |
| 데이터 이동 없이 S3 호환 도구 사용 | 파일原地에서 S3 접근 |
| 연구기관 간 데이터 공유 표준 부재 | S3 프로토콜을 공통 인터페이스로 |
| 에어갭 환경에서 S3 생태계 필요 | 완전 오프라인 S3 API 제공 |

## 지원 백엔드

![지원 백엔드 아키텍처](/assets/images/posts/versitygw-onprem-s3/14-03-3-지원-백엔드.svg)

VersityGW는 플러그형 백엔드 아키텍처를 사용하며, 다양한 스토리지 백엔드를 지원합니다.

| 백엔드 | 설명 | 적합 시나리오 |
|--------|------|---------------|
| **POSIX** | 일반 리눅스 파일시스템 (ext4, XFS 등) | 단일 서버, 소규모 배포, 개발/테스트 |
| **ScoutFS** | Versity의 클러스터 파일시스템 | 대규모 아카이브, PB급 데이터 |
| **Azure Blob** | 마이크로소프트 Azure Blob Storage | Azure 하이브리드 환경 |
| **S3 Proxy** | 다른 S3 서버에 프록시 | 캐시 계층, S3 마이그레이션 |
| **Ceph** | Ceph RADOS / CephFS | 분산 스토리지 환경 |

백엔드는 커스텀 플러그인으로도 확장할 수 있습니다. 기존 파일시스템에 S3 API만 얹고 싶다면 **POSIX** 백엔드가 기본 선택입니다.

## 설치 및 실행

### 바이너리로 빠른 시작

가장 빠른 방법은 GitHub Releases에서 바이너리를 다운로드하는 것입니다.

```bash
# 바이너리 다운로드
wget https://github.com/versity/versitygw/releases/latest/download/versitygw-linux-amd64
chmod +x versitygw-linux-amd64
mv versitygw-linux-amd64 versitygw

# 데이터/IAM/버전 관리 디렉토리 생성
mkdir -p /tmp/vgw /tmp/vers

# 루트 자격 증명 설정 후 실행
export ROOT_ACCESS_KEY="testuser"
export ROOT_SECRET_KEY="secret"
./versitygw --port :10000 \
  --iam-dir /tmp/vgw \
  posix --versioning-dir /tmp/vers /tmp/vgw

# 헬스체크로 실행 확인
curl http://localhost:10000/health
```

### Docker

```bash
docker run -d --name versitygw \
  -p 10000:10000 -v /data:/data \
  -e ROOT_ACCESS_KEY=testuser \
  -e ROOT_SECRET_KEY=secret \
  versity/versitygw:latest \
  --port :10000 posix /data
```

### Kubernetes (Helm)

<details>
<summary>Helm 설치 전체 코드 보기</summary>

```bash
# Helm 차트 저장소 추가
helm repo add versitygw oci://ghcr.io/versity/versitygw/charts

# Helm으로 설치
helm install versitygw oci://ghcr.io/versity/versitygw/charts/versitygw \
  --set rootAccessKey=testuser \
  --set rootSecretKey=secret \
  --set persistence.enabled=true \
  --set persistence.size=100Gi

# 설치 상태 확인
kubectl get pods -l app=versitygw
kubectl logs -f deployment/versitygw
```

</details>

### 주요 실행 옵션

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--port` | 수신 포트 | `:7070` |
| `--iam-dir` | IAM 계정 저장 디렉토리 | 없음 |
| `--cert`, `--key` | TLS 인증서/키 파일 | 없음 (HTTP) |
| `--region` | S3 리전 설정 | `us-east-1` |
| `--debug` | 디버그 로그 활성화 | false |
| `--health` | 헬스체크 URL 경로 | `/health` |

## 클라이언트 접속 실습

![클라이언트 접속 아키텍처](/assets/images/posts/versitygw-onprem-s3/14-06-8-실전-시나리오-연구기관-데이터-공유.svg)

VersityGW는 표준 S3 API를 구현하므로, 기존 S3 클라이언트 도구를 그대로 사용할 수 있습니다. 엔드포인트 URL만 VersityGW 주소로 지정하면 됩니다.

### AWS CLI

```bash
# 환경 변수 설정
export AWS_ACCESS_KEY_ID=testuser
export AWS_SECRET_ACCESS_KEY=secret
export AWS_DEFAULT_REGION=us-east-1
export AWS_ENDPOINT_URL=http://localhost:10000

# 버킷 생성, 조회, 업로드
aws --endpoint-url http://localhost:10000 s3 ls
aws --endpoint-url http://localhost:10000 s3 mb s3://my-bucket
aws --endpoint-url http://localhost:10000 s3 cp file.txt s3://my-bucket/
```

### Python boto3

<details>
<summary>boto3 전체 코드 보기</summary>

```python
import boto3

s3 = boto3.client('s3',
    endpoint_url='http://localhost:10000',
    aws_access_key_id='testuser',
    aws_secret_access_key='secret',
    region_name='us-east-1'
)

# 버킷 생성
s3.create_bucket(Bucket='my-bucket')

# 객체 업로드
s3.put_object(Bucket='my-bucket', Key='hello.txt',
              Body=b'Hello VersityGW!')

# 객체 다운로드
response = s3.get_object(Bucket='my-bucket', Key='hello.txt')
print(response['Body'].read().decode())  # Hello VersityGW!

# 객체 목록 조회
response = s3.list_objects_v2(Bucket='my-bucket')
for obj in response.get('Contents', []):
    print(f"  {obj['Key']} ({obj['Size']} bytes)")
```

</details>

### curl로 직접 API 호출

```bash
# 버킷 생성
curl -X PUT http://localhost:10000/test-bucket
# 객체 업로드
curl -X PUT http://localhost:10000/test-bucket/hello.txt -d "Hello!"
# 객체 다운로드
curl http://localhost:10000/test-bucket/hello.txt
```

## 클러스터 배포 (고가용성)

![클러스터 아키텍처](/assets/images/posts/versitygw-onprem-s3/14-04-6-클러스터-배포-고가용성.svg)

VersityGW는 **Stateless** 아키텍처이므로, 로드밸런서 뒤에 여러 인스턴스를 배치해 고가용성을 확보할 수 있습니다. 핵심은 모든 인스턴스가 **동일한 공유 파일시스템**(NFS, GPFS, Lustre, CephFS)을 마운트하는 것입니다.

### 배포 체크리스트

- **공유 파일시스템**: 모든 인스턴스가 동일한 파일시스템 마운트
- **IAM 디렉토리**: 공유 스토리지에 배치해 모든 인스턴스가 동일 계정 정보 참조
- **버전 관리 디렉토리**: 공유 스토리지에 위치
- **헬스체크**: `/health` 엔드포인트로 인스턴스 상태 모니터링
- **TLS 종료**: 로드밸런서에서 TLS 종료 후 내부 통신은 HTTP
- **세션 어피니티**: 멀티파트 업로드 시 동일 인스턴스 라우팅 (선택사항)

### HAProxy 설정

<details>
<summary>HAProxy 설정 전체 코드 보기</summary>

```nginx
# /etc/haproxy/haproxy.cfg
frontend s3_frontend
    bind *:80
    mode http
    default_backend versitygw_backend

backend versitygw_backend
    mode http
    balance roundrobin
    option httpchk GET /health
    http-check expect status 200
    server gw1 10.0.1.11:10000 check
    server gw2 10.0.1.12:10000 check
    server gw3 10.0.1.13:10000 check
```

</details>

## 보안 설정

### TLS/SSL 설정 (HTTPS)

```bash
# 자체 서명 인증서 생성
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem \
  -days 365 -nodes -subj "/CN=s3.example.com"

# TLS로 VersityGW 실행
./versitygw --port :10000 \
  --cert /etc/ssl/certs/s3.example.com.pem \
  --key /etc/ssl/private/s3.example.com.key \
  posix /data
```

### IAM 계정 + 버킷 정책

VersityGW는 IAM 디렉토리 기반으로 계정을 관리하며, 버킷 정책(JSON)으로 세부 접근 제어를 적용합니다. 읽기 전용/읽기쓰기/관리자 역할을 계정별로 부여할 수 있고, Principal·Action·Resource 기반의 AWS 표준 정책 문법을 그대로 사용합니다.

<details>
<summary>IAM 계정 + 버킷 정책 전체 코드 보기</summary>

```bash
# 관리자 계정 생성
cat > /etc/versitygw/iam/accounts/admin.json <<EOF
{
  "access_key": "AKIAIOSFODNN7ADMIN",
  "secret_key": "wJalrXUtnFEMI/K7MDENG/adminkey",
  "role": "admin"
}
EOF

# 읽기 전용 계정 생성
cat > /etc/versitygw/iam/accounts/readonly.json <<EOF
{
  "access_key": "AKIAIOSFODNN7READER",
  "secret_key": "wJalrXUtnFEMI/K7MDENG/readerkey",
  "role": "readonly"
}
EOF
```

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {"AWS": ["*"]},
      "Action": ["s3:GetObject"],
      "Resource": ["arn:aws:s3:::public-data/*"]
    }
  ]
}
```

</details>

### 방화벽 규칙

```bash
# UFW — VersityGW 포트만 개방
ufw allow 10000/tcp
ufw allow 443/tcp
ufw enable
```

## VersityGW vs MinIO vs AWS S3 비교

![S3 솔루션 선택 가이드](/assets/images/posts/versitygw-onprem-s3/14-08-선택-가이드.svg)

세 솔루션은 모두 S3 API를 다루지만, **설계 목적이 다릅니다**. AWS S3는 완전 관리형 클라우드 스토리지, MinIO는 자체 객체 스토리지, VersityGW는 기존 파일시스템을 S3 API로 번역하는 게이트웨이입니다. 아래는 핵심 비교입니다.

| 특징 | AWS S3 | VersityGW | MinIO |
|------|--------|-----------|-------|
| **유형** | 관리형 서비스 | S3 번역 게이트웨이 | S3 호환 스토리지 |
| **백엔드** | AWS 인프라 | POSIX 파일시스템 | 자체 스토리지 |
| **데이터 위치** | AWS 리전 | 온프레미스 | 온프레미스/클라우드 |
| **S3 API 호환** | 100% | 대부분 | 대부분 |
| **상태** | 상태 저장 | Stateless | 상태 저장 |
| **클러스터** | 자동 | LB + 다중 인스턴스 | 분산 모드 |
| **파일시스템 접근** | 불가 | POSIX 동시 접근 | 불가 |
| **라이선스** | 상용 | Apache 2.0 | AGPLv3 |
| **적합 시나리오** | 클라우드 | 파일↔S3 변환 | 자체 S3 스토리지 |
| **멀티테넌시** | 완벽 지원 | IAM 기반 | 완벽 지원 |
| **데이터 중복 제거** | 자동 | 없음 | 비트 rot 보호 |
| **Erasure Coding** | 자동 | 없음 (백엔드에 의존) | 지원 |
| **웹 콘솔** | AWS 콘솔 | WebUI 제공 | 내장 콘솔 |
| **비용** | 사용량 기반 | 무료 (인프라만) | 무료 (인프라만) |

**선택 기준**: 기존 POSIX 파일시스템을 S3 API로 노출해야 한다면 **VersityGW**, 처음부터 객체 전용 자체 스토리지를 구축한다면 **MinIO**, 관리 부담 없이 클라우드를 쓴다면 **AWS S3**가 적합합니다.

## 하이브리드 아키텍처: 온프레미스 + AWS

![하이브리드 아키텍처](/assets/images/posts/versitygw-onprem-s3/14-09-12-아키텍처-패턴-versitygw-aws-opensharing-하이브리드.svg)

VersityGW는 온프레미스 S3 생태계의 핵심 구성 요소로, AWS S3와 결합해 **통합 데이터 플랫폼**을 구축할 수 있습니다. 동일한 S3 프로토콜을 공통 언어로 사용해 클라우드와 온프레미스 양쪽 데이터를 투명하게 연결합니다.

![오픈소스 S3 생태계 기여](/assets/images/posts/versitygw-onprem-s3/14-05-7-versitygw와-opensharing의-관계-핵심.svg)

### 데이터 배치 패턴

하이브리드 환경에서는 데이터의 **접근 빈도(핫/웜/콜드)** 에 따라 배치를 결정합니다.

![클라우드 우선 패턴](/assets/images/posts/versitygw-onprem-s3/14-10-121-패턴-1-클라우드-우선-cloud-first.svg)

**패턴 1 — 클라우드 우선 (Cloud-First)**: AWS S3를 주 데이터 저장소로 사용하고, VersityGW는 S3 Proxy 백엔드로 로컬 읽기 캐시 역할을 합니다. 모든 쓰기는 AWS S3로 전달됩니다.

![온프레미스 우선 패턴](/assets/images/posts/versitygw-onprem-s3/14-11-122-패턴-2-온프레미스-우선-on-premises-first.svg)

**패턴 2 — 온프레미스 우선 (On-Premises First)**: VersityGW를 주 데이터 저장소로 사용하고, AWS S3는 백업/아카이브/재해 복구 목적으로 DataSync로 동기화합니다. 데이터 주권이 중요한 환경에 적합합니다.

![데이터 레이크 통합 패턴](/assets/images/posts/versitygw-onprem-s3/14-12-123-패턴-3-데이터-레이크-통합.svg)

**패턴 3 — 데이터 레이크 통합**: 자주 접근하는 핫 데이터는 AWS S3 Standard에, 장기 보관 콜드 데이터는 VersityGW + ScoutFS에 배치합니다. Athena, Spark, Presto, Trino 같은 통합 쿼리 엔진으로 양쪽 데이터를 한 번에 분석합니다.

### 데이터 동기화

<details>
<summary>DataSync / rclone 동기화 전체 코드 보기</summary>

```bash
# AWS DataSync로 S3 ↔ VersityGW 동기화
aws datasync create-location-s3 \
  --s3-bucket-arn arn:aws:s3:::cloud-bucket \
  --s3-config BucketAccessRoleArn=arn:aws:iam::123456789012:role/MyRole

aws datasync create-location-s3 \
  --s3-bucket-arn arn:aws:s3:::onprem-bucket \
  --agent-arns arn:aws:datasync:us-east-1:123456789012:agent/agent-1 \
  --s3-config BucketAccessRoleArn=arn:aws:iam::123456789012:role/MyRole

# rclone으로 수동 동기화 (16개 병렬 전송)
rclone sync \
  :s3,endpoint=http://localhost:10000 my-bucket \
  :s3,region=us-east-1 cloud-bucket \
  --progress --transfers 16
```

</details>

## Takeaway

1. **VersityGW는 POSIX 파일시스템을 S3 API로 번역합니다** — 기존 스토리지 투자를 보존하면서 S3 생태계의 도구를 그대로 활용할 수 있습니다.
2. **바이너리 하나로 5분 안에 시작할 수 있습니다** — Docker나 Kubernetes(Helm)로 프로덕션 규모까지 쉽게 확장합니다.
3. **AWS CLI/SDK가 그대로 작동합니다** — `--endpoint-url`만 추가하면 클라우드와 온프레미스를 동일한 코드로 다룰 수 있습니다.

---

> **S3 시리즈 7/7**
>
> | | |
> |---|---|
> | ← [S3 2026 신기능 — Files, Tables, Vectors, Metadata + s3fs-fuse]({% post_url 2026-06-13-S3-New-Features-2026 %}) | |
> | | 마지막 글입니다 |
