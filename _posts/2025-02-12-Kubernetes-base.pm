---
layout: post
title: Kubernetes 튜토리얼 (1) 
categories: [Linux]
description: Minikube 을 사용하여 배포하는 방법까지 설명합니다.
keywords: Kubectl, Kubelet, Kubernetes, Minikube
toc: true
toc_sticky: true
---


본 글은 `Ubuntu 24.04` 를 기준으로 작성되었습니다.

---

### 쿠버네티스의 필요성

컨테이너화를 통해 소프트웨어를 패키지하면 애플리케이션을 다운타임 없이 릴리스 및 업데이트를 할 수 있습니다. 


### 쿠버네티스의 기초 튜토리얼

1. 쿠버네티스 클러스터 생성하기 
2. 애플리케이션 배포하기 
3. 앱 조사하기 
4. 앱 외부로 노출하기
5. 애플리케이션 스케일링하기 
6. 앱 업데이트 하기


### Minikube 를 사용해서 클러스터 생성하기

Minikube  는 단일 노드 쿠버네티스 클러스터를 가상머신에서 구동하는 도구입니다.

#### 1. 쿠버네티스 클러스터

쿠버네티스는 컴퓨터들을 연결하여 단일 형상으로 동작하도록 클러스터를 구성하고 높은 가용성을 제공하도록 조율합니다. 쿠버네티스는 이러한 어플리케이션 컨테이너를 클러스터에 분산시키고 스케줄링하는 일을 자동화할 수 있습니다.

> 쿠버네티스 클러스터는 두 가지 형태의 자원으로 구성
> - 컨트롤 플레인 : 클러스터 조율
> - 노드 : 애플리케이션을 구동하는 작업자(worker)


##### 1.1. 컨트롤 플레인

`컨트롤 플레인`은 클러스터 관리를 담당합니다.

- 애플리케이션 스케줄링
- 애플리케이션 향상성 유지
- 애플리케이션 스케일링
- 변경사항 순서대로 반영

##### 1.2. 노드

`노드`는 클러스터 내 워커 머신으로 동작하는 `VM` 또는 `물리적인 컴퓨터`입니다. 운영 트래픽을 처리하는 `쿠버네티스 클러스터는 최소 세 대의 노드`를 가져야 하는데, 한 노드가 다운되면 etcd 멤버와 컨트롤 플레인 인스턴스가 사라져 중복성(redundancy) 를 잃을 수 있습니다. 컨트롤 플레인 노드를 추가하면 이러한 위험을 줄일 수 있습니다. 

* Kubelet : 컨트롤 플레인과 통신하는 에이전트
* containerd or docker : 컨테이너 운영 담당

노드는 컨트롤 플레인이 제공하는 [쿠버네티스 API](https://kubernetes.io/docs/reference/kubernetes-api/) 를 통해서 컨트롤 플레인과 통신합니다.

##### 1.3 Minikube

Minikube 는 가벼운 쿠버네티스 구현체입니다. 로켈 머신에 VM 을 만들고 하나의 노드로 구성된 간단한 클러스터를 생성할 수 있습니다. 

> Minikube CLI
> - 부트스트래핑 : 클러스터 시작, 중지, 상태 조회, 삭제


#### 2. Docker 설치

[dockerdocs](https://docs.docker.com/engine/install/ubuntu/) 에서 소개하는 방법대로 docker 설치합니다.

1. apt 레포지토리에 Docker 를 추가합니다.

```bash
$ sudo apt-get update
$ sudo apt-get install ca-certificates curl
$ sudo install -m 0755 -d /etc/apt/keyrings
$ sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
$ sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
$ echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
$ sudo apt-get update
```

2. Docker 패키지를 설치합니다.

```bash
$ sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

3. Docker 를 실행합니다.

```bash
$ sudo systemctl enable docker
$ sudo systemctl start docker
```

#### 3. Kubectl 설치

[kubect 설치l](https://kubernetes.io/ko/docs/tasks/tools/install-kubectl-linux/) 에서 소개하는 대로 kubectl 를 설치합니다.

1. curl 로 최신 릴리즈를 다운로드 합니다.

```bash
$ curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
```

2. Kubectl 를 설치하고 제대로 설치되었는지 테스트합니다.

```bash
$ sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
$ kubectl version --client
```


#### 4. MiniKube 설치

[Minikube 설치](https://minikube.sigs.k8s.io/docs/start/?arch=%2Flinux%2Farm64%2Fstable%2Fbinary+download) 에서 소개하는 대로 Minikube 를 설치합니다. 

1. curl 로 패키지를 다운로드 받아 설치합니다. 

```bash
$ curl -LO https://github.com/kubernetes/minikube/releases/latest/download/minikube-linux-amd64
$ sudo install minikube-linux-amd64 /usr/local/bin/minikube && rm minikube-linux-amd64
```


2. Minikube 를 실행합니다. 

```bash
$ minikube start
* minikube v1.35.0 on Ubuntu 24.04
* Automatically selected the docker driver. Other choices: ssh, none
* Using Docker driver with root privileges
* Starting "minikube" primary control-plane node in "minikube" cluster
* Pulling base image v0.0.46 ...
* Downloading Kubernetes v1.32.0 preload ...
    > preloaded-images-k8s-v18-v1...:  333.57 MiB / 333.57 MiB  100.00% 4.07 Mi
    > gcr.io/k8s-minikube/kicbase...:  500.31 MiB / 500.31 MiB  100.00% 5.18 Mi
* Creating docker container (CPUs=2, Memory=2200MB) ...
* Preparing Kubernetes v1.32.0 on Docker 27.4.1 ...
  - Generating certificates and keys ...
  - Booting up control plane ...
  - Configuring RBAC rules ...
* Configuring bridge CNI (Container Networking Interface) ...
* Verifying Kubernetes components...
  - Using image gcr.io/k8s-minikube/storage-provisioner:v5
* Enabled addons: storage-provisioner, default-storageclass
* Done! kubectl is now configured to use "minikube" cluster and "default" namespace by default
```

3. 먄약 root 로 생성했다면 에러가 발생합니다. 사용자 계정을 생성해서 `minikube start`  를 해줍니다. 

```bash
$ sudo useradd -m -d /home/hikube -s /bin/bash hikube
$ sudo passwd hikkube 
$ sudo usermod -aG sudo hikube
$ sudo usermod -aG docker hikube
$ su hikube
```

4. minikube 의 상태를 확인하고, kubectl 로 노드를 확인해봅니다.

```bash
$ minikube status
minikube
type: Control Plane
host: Running
kubelet: Running
apiserver: Running
kubeconfig: Configured

$ kubectl get node
NAME       STATUS   ROLES           AGE     VERSION
minikube   Ready    control-plane   3m47s   v1.32.0
```


5. minikube 삭제

```
$ minikube delete
```


### Kubectl 을 사용해서 Deployment 생성

#### 1. 쿠버네티스 Deployment

쿠버네티스 클러스터를 구동시키면, 그 위에 컨테이너화된 애플리케이션을 배포할 수 있습니다. 그러기 위해서는 쿠버네티스 Deployment 설정을 만들어야 하는데, 쿠버네티스가 `애플리케이션의 인스턴스를 어떻게 생성하고 업데이트`해야 하는지를 지시할 수 있습니다.

컨트롤 플레인이 Deployment 에 포함된 애플리케이션 인스턴스가 클러스터의 개별 노드에서 실행되도록 스케줄합니다.

애플리케이션 인스턴스가 생성되면, 쿠버네티스 Deployment 컨트롤러는 지속적으로 인스턴스를 모니터링하는데, 노드가 다운되거나 삭제되면, 컨트롤러가 인스턴스를 클러스터 내부의 다른 노드의 인스턴스로 교체시켜주는 `자동 복구 매커니즘`을 제공합니다. 


#### 2. Deploy 작성

```bash
$ vim nginx-deployment.yaml
apiVersion: apps/v1  
kind: Deployment  
metadata:  
  name: nginx-deploy  
spec:  
  replicas: 3  
  selector:  
    matchLabels:  
      app: nginx-app  
  template:  
    metadata:  
      labels:  
        app: nginx-app  
    spec:  
      containers:  
      - name: nginx-container  
        image: nginx:latest  
        ports:  
        - containerPort: 80

$ vim nginx-service.yaml
apiVersion: v1  
kind: Service  
metadata:  
  name: nginx-service  
spec:  
  type: NodePort  
  selector:  
    app: nginx-app  
  ports:  
    - targetPort: 80  
      port: 80  
      nodePort: 30080
```

> 다음과 같은 에러가 난다면 yaml 문법 오류이니, 오류를 잘 읽어보고 해결할 것 ( 저는 복사과정에서 `-` 가 특수문자로 변경되었네요 ㅎㅎ)

```bash
Error from server (BadRequest): error when creating "./nginx-deployments.yaml": Deployment in version "v1" cannot be handled as a Deployment: json: cannot unmarshal object into Go struct field PodSpec.spec.template.spec.containers of type []v1.Container
```



#### 3. 배포

```bash
kubectl apply -f
```


> 다음 포스트에서는 파드와 노드로 배포된 어플리케이션을 모니터링하기 위한 방법을 알아보겠습니다~!

---


### Ref

* [Kubernetes 튜토리얼](https://kubernetes.io/ko/docs/tutorials/kubernetes-basics)
* [Minikube 튜토리얼](https://gruuuuu.github.io/cloud/minikube/)
* [Kubectl  로 배포하기](https://zerobig-k8s.tistory.com/10)
* [Minikube 로 nginx 배포하기](https://idchowto.com/minikube-%EB%A1%9C-nginx-%EB%B0%B0%ED%8F%AC/)


