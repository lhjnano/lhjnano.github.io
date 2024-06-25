---
layout: post
title: 로컬 Jekyll 서버 (feat. undefined method `delegate_method_as')
categories: [Jekyll, GithubPage]
description: Jekyll 를 로컬에서 어떻게 확인할 수 있는지 설명합니다.
keywords: Jekyll, GithubPage
toc: true
toc_sticky: true
---

> 본 포스트는 Ubuntu 를 기준으로 작성되었습니다.

한동안은 매번 Github 에 푸시해서 page 변경사항을 확인하는데, 실제 반영되는데 까지 오래걸리기도 하고 `commit` 정리하기도 불편해서 local 에서 테스트하고 올리려고 [Github  페이지 가이드](https://docs.github.com/en/pages/setting-up-a-github-pages-site-with-jekyll/testing-your-github-pages-site-locally-with-jekyll)에 따라서 Local 에서 Jekyll 를 실행시키기 위해 시도해보았다. 하지만 다음과 같은 에러가 발생하였다.

```bash
# Jekyll install in ubuntu
$ sudo apt-get install ruby-full build-essential zlib1g-dev

$ echo '# Install Ruby Gems to ~/gems' >> ~/.bashrc
$ echo 'export GEM_HOME="$HOME/gems"' >> ~/.bashrc
$ echo 'export PATH="$HOME/gems/bin:$PATH"' >> ~/.bashrc
$ source ~/.bashrc

$ gem install jekyll bundler

# 의존성 설치
$ bundle install

...
An error occurred while installing forwardable-extended (2.6.0), and Bundler cannot continue.

In Gemfile:
  github-pages was resolved to 231, which depends on
    jekyll-avatar was resolved to 0.8.0, which depends on
      jekyll was resolved to 3.9.5, which depends on
        pathutil was resolved to 0.16.2, which depends on
          forwardable-extended

$ jekyll -v

/home/lhj/gems/gems/jekyll-4.3.3/lib/jekyll/drops/collection_drop.rb:10:in `<class:CollectionDrop>': undefined method `delegate_method_as' for Jekyll::Drops::CollectionDrop:Class (NoMethodError)
	from /home/lhj/gems/gems/jekyll-4.3.3/lib/jekyll/drops/collection_drop.rb:5:in `<module:Drops>'
	from /home/lhj/gems/gems/jekyll-4.3.3/lib/jekyll/drops/collection_drop.rb:4:in `<module:Jekyll>'
	from /home/lhj/gems/gems/jekyll-4.3.3/lib/jekyll/drops/collection_drop.rb:3:in `<top (required)>'
...

```

버전이 안 맞는 것 같아 종속성을 정리 후 다시 시도하였다

```bash
$ PACKAGES="$(dpkg -l |grep jekyll|cut -d" " -f3|xargs )"
$ sudo apt remove --purge $PACKAGES 
[sudo] *** 암호: 
패키지 목록을 읽는 중입니다... 완료
의존성 트리를 만드는 중입니다... 완료
상태 정보를 읽는 중입니다... 완료        
다음 패키지가 자동으로 설치되었지만 더 이상 필요하지 않습니다:
  libflashrom1 libftdi1-2 libhttp-parser2.9 ruby-addressable ruby-bundler ruby-classifier-reborn ruby-coderay ruby-colorator ruby-concurrent ruby-em-websocket ruby-eventmachine ruby-fast-stemmer ruby-ffi
  ruby-forwardable-extended ruby-http-parser.rb ruby-i18n ruby-kramdown ruby-kramdown-parser-gfm ruby-liquid ruby-listen ruby-mercenary ruby-mime-types ruby-mime-types-data ruby-pathutil
  ruby-public-suffix ruby-pygments.rb ruby-rb-inotify ruby-rdiscount ruby-redcarpet ruby-rouge ruby-safe-yaml ruby-sass ruby-tomlrb ruby-yajl
'sudo apt autoremove'를 이용하여 제거하십시오.
...

$ sudo apt autoremove
패키지 목록을 읽는 중입니다... 완료
의존성 트리를 만드는 중입니다... 완료
상태 정보를 읽는 중입니다... 완료        
다음 패키지를 지울 것입니다:
...
```

이제 재설치 해보자 :)

```bash
$ sudo gem install jekyll jekyll-feed jekyll-gist jekyll-paginate jekyll-sass-converter jekyll-coffeescript

Fetching safe_yaml-1.0.5.gem
Fetching terminal-table-3.0.2.gem
Fetching unicode-display_width-2.5.0.gem
Fetching rouge-4.3.0.gem
Fetching forwardable-extended-2.6.0.gem
Fetching pathutil-0.16.2.gem
Fetching mercenary-0.4.0.gem
Fetching liquid-4.0.4.gem
Fetching kramdown-2.4.0.gem
Fetching kramdown-parser-gfm-1.1.0.gem
Fetching ffi-1.17.0.gem
Fetching rb-inotify-0.11.1.gem
Fetching rb-fsevent-0.11.2.gem
Fetching listen-3.9.0.gem
...

$ bundle update
Fetching gem metadata from https://rubygems.org/...........
Resolving dependencies...
Fetching mercenary 0.3.6
Fetching sass-listen 4.0.0
Fetching github-pages-health-check 1.18.2
Installing mercenary 0.3.6
Installing github-pages-health-check 1.18.2
Installing sass-listen 4.0.0
Fetching sass 3.7.4
Installing sass 3.7.4
Fetching jekyll-sass-converter 1.5.2
...

$ bundle install
Bundle complete! 3 Gemfile dependencies, 95 gems now installed.
Use `bundle info [gemname]` to see where a bundled gem is installed.
```

이제 서버를 구동시키면 `Server address` 주소인 `127.0.0.1:4000` 에서 page 를 확인할 수 있다.

```bash
$ bundle exec jekyll serve
Configuration file: /Post/lhjnano.github.io/_config.yml
To use retry middleware with Faraday v2.0+, install `faraday-retry` gem
            Source: /Post/lhjnano.github.io
       Destination: /Post/lhjnano.github.io/_site
 Incremental build: disabled. Enable with --incremental
      Generating... 
       Jekyll Feed: Generating feed for posts
   GitHub Metadata: No GitHub API authentication could be found. Some fields may be missing or have incorrect data.
                    done in 21.418 seconds.
 Auto-regeneration: enabled for '/Post/lhjnano.github.io'
    Server address: http://127.0.0.1:4000
  Server running... press ctrl-c to stop.
```

---


### 참고

* [stackoverflow](https://stackoverflow.com/questions/68220028/undefined-method-delegate-method-as-for-jekylldropscollectiondropclass-n)
