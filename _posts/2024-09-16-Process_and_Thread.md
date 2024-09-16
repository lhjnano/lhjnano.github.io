---
layout: post
title: 프로세스(Process) 와 쓰레드(Thread) 의 차이점
categories: [Process, Thread]
description: 프로세스와 쓰레드의 차이점에 대해서 `Perl` 코드를 통해 설명합니다.
keywords: 프로세스, 쓰레드, Process, Thread, perl
toc: true
toc_sticky: true
---

`프로세스(Process)`와 `쓰레드(Thread)`는 동시에 여러 작업을 수행하기 위한 두 가지 중요한 개념입니다. 
오늘은 그 차이점을 알아보고, Perl을 이용한 간단한 테스트 예제를 통해 이들을 비교해보겠습니다.

<br>

### 프로세스 (Process)

프로세스는 실행 중인 프로그램의 인스턴스를 의미합니다. 각 프로세스는 독립적인 메모리 공간을 가지며, 자원을 할당받아 독립적으로 실행됩니다. 프로세스 간에는 메모리를 공유하지 않기 때문에, 한 프로세스의 오류가 다른 프로세스에 영향을 미치지 않습니다.

> :bulb: **NOTE: 프로세스의 특징** <br>
> 독립적인 메모리 공간: 각 프로세스는 자신만의 메모리 공간을 가집니다. <br>
> 자원 분리: 프로세스 간에 자원이나 데이터가 공유되지 않습니다. <br>
> 안전성: 한 프로세스의 오류가 다른 프로세스에 영향을 미치지 않습니다. <br>

<br>

### 쓰레드 (Thread)

쓰레드는 프로세스 내에서 실행되는 실행 단위입니다. 같은 프로세스 내의 쓰레드는 메모리와 자원을 공유하며, 이는 쓰레드 간의 상호작용을 더 빠르고 효율적으로 만들지만 동기화 문제를 일으킬 수 있습니다.


> :bulb: **NOTE: 쓰레드의 특징** <br>
> 공유된 메모리 공간: 같은 프로세스 내의 쓰레드는 메모리를 공유합니다. <br>
> 자원 공유: 쓰레드 간에 자원이나 데이터가 공유됩니다. <br>
> 경량성: 쓰레드는 프로세스보다 가볍고, 생성 및 관리가 더 빠릅니다. <br>

<br>

### Perl을 이용한 프로세스와 쓰레드 테스트

Perl에서는 fork를 이용하여 프로세스를 생성하고, threads 모듈을 사용하여 쓰레드를 생성할 수 있습니다. 간단한 예제를 통해 프로세스와 쓰레드를 테스트해보겠습니다.

<br>

**프로세스 예제**

```perl
#!/usr/bin/perl
use strict;
use warnings;
use Time::HiRes qw(time);

my $start_time = time();

my $num_processes = 4;
my @pids;

for (1..$num_processes) {
    my $pid = fork();

    if (!defined($pid))
    {
        die "Failed to fork: $!";
    }
    elsif ($pid == 0)
    {
        # 자식 프로세스
        calculate_primes();
        exit 0;
    }
    else
    {
        push(@pids, $pid);
    }
}

foreach my $pid (@pids)
{
    waitpid($pid, 0);
}

my $end_time = time();

print "Time taken using processes: ", $end_time - $start_time, " seconds\n";

sub calculate_primes
{
    my $max = 10_000;
    my $count = 0;

    for (my $num = 2; $num <= $max; $num++) {
        my $is_prime = 1;

        for (my $i = 2; $i * $i <= $num; $i++)
        {
            if ($num % $i == 0)
            {
                $is_prime = 0;
                last;
            }
        }

        $count++ if $is_prime;
    }
}
```

<br>

```sh
# 결과
Time taken using processes: 0.0511531829833984 seconds
```

<br>

**쓰레드 예제**

```perl
#!/usr/bin/perl
use strict;
use warnings;
use Time::HiRes qw(time);
use threads;

my $start_time = time();

my $num_threads = 4;
my @threads;

for (1..$num_threads)
{
    push(@threads, threads->create(\&calculate_primes));
}

foreach my $thread (@threads)
{
    $thread->join();
}

my $end_time = time();
print "Time taken using threads: ", $end_time - $start_time, " seconds\n";

sub calculate_primes
{
    my $max = 10_000;
    my $count = 0;

    for (my $num = 2; $num <= $max; $num++)
    {
        my $is_prime = 1;

        for (my $i = 2; $i * $i <= $num; $i++)
        {
            if ($num % $i == 0)
            {
                $is_prime = 0;
                last;
            }
        }

        $count++ if $is_prime;
    }
}
```

<br>


```sh
# 결과
Time taken using threads: 0.0478110313415527 seconds
```

두 비교 코드에서는 4개의 프로세스/쓰레드를 생성하여 각각 10,000까지의 소수를 계산합니다. 모든 작업을 병렬로 수행한 뒤 총 실행 시간을 측정합니다.


<br>

* 프로세스: 프로세스 간 메모리와 자원 분리가 있어 상대적으로 오버헤드가 발생하며, 생성 및 관리 비용이 높습니다. 계산 작업이 병렬로 수행되지만, 프로세스 간의 통신 비용이 발생할 수 있습니다.
* 쓰레드: 쓰레드는 메모리와 자원을 공유하여 생성과 관리가 더 가볍고 빠릅니다. CPU 집약적인 작업을 더 효율적으로 처리할 수 있습니다.

프로세스와 쓰레드는 각각의 장점과 단점이 있으며, 적절한 선택이 중요합니다. 프로세스는 독립적인 실행 단위로 안정성이 높지만, 자원과 시간이 많이 소요됩니다. 반면, 쓰레드는 경량성과 효율성을 제공하여 CPU 집약적인 작업을 더 빠르게 수행할 수 있습니다.