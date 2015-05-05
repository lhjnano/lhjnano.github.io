---
layout: wiki
title: Emacs
categories: Emacs
description: Emacs快捷键汇总及日常使用记录。
keywords: Emacs, 快捷键
---

约定：`C-`前缀表示Ctrl，`M-`前缀表示Alt，`S-`前缀表示Shift，上档字符比如`@`的实际按键应为`Shift+2`。

###Index

* [移动](#移动)
* [编辑](#编辑)
* [缓冲区](#缓冲区)
* [窗口](#窗口)
* [文件](#文件)
* [代码](#代码)
* [命令](#命令)
* [重复](#重复)
* [外部命令](#外部命令)
* [模式](#模式)
* [显示](#显示)
* [搜索](#搜索)
* [帮助](#帮助)
* [右键菜单](#右键菜单)
* [插件](#插件)
  * [evil-nerd-commenter](#evil-nerd-commenter)
  * [function-args](#function-args)
  * [hexl-mode](#hexl-mode)
  * [ido](#ido)
  * [jedi](#jedi)
  * [projectile](#projectile)
  * [python](#python)
  * [package](#package)

###移动

上 C-p

下 C-n

左 C-b

右 C-f

前一个词首 M-b

后一个词尾 M-f

跳到某一行 M-gg

行首 C-a

行尾 C-e

句首/前一个句首 M-a

名尾/前一个句尾 M-e

向前一个段落 M-{

向后一个段落 M-}

下翻页 C-v

上翻页 M-v

跳到文首 M-<

跳到文尾 M->

当前光标行移动到屏显上/中/下部 C-l

###编辑

选取块 C-@

复制 M-w

剪切 C-w

粘贴 C-y

全选 C-x h

切换只读/编辑模式 C-x C-q

交换当前字符与前一字符 C-t

交换当前单词与后一单词 M-t

交换当前行与上一行 C-x C-t

撤消 C-/ 或 C-x u

撤消撤消 C-g C-/

当前单词全大写 M-u

当前单词全小写 M-l

###缓冲区

查看所有打开的缓冲区 C-x C-b

切换缓冲区 C-x b

关闭缓冲区 C-x k

###窗口

关闭其它窗口 C-x 1

关闭当前窗口 C-x 0

依次切换到其它窗口 C-x o

###文件

打开文件 C-x C-f

保存文件 C-x C-s

保存所有打开的文件 C-x s

在当前位置插入某文件内容 C-x i

###代码

注释选中块 C-x r t

反注释选中块 C-x r k

格式化光标之前的代码 C-M-\

与上一行合并 M-^

带注释前缀换行 M-j

###命令

输入命令 M-x

运行SHELL shell

运行ESHELL eshell

列出elpa上可用包 list-packages

安装插件 package-install

中止一个操作 C-g

###重复

重复操作50次 M-50 命令

###外部命令

输入外部命令 M-@

###模式

打开/关闭某个模式 M-x 模式名

###显示

放大字体 C-x C-=

缩小字体 C-x C--

重置字体 C-x C-0

###搜索

递增的搜索 C-s

###帮助

查看变量的文档 C-h v

查看函数的文档 C-h f

查看某快捷键说明 C-h k

打开Tutorial C-h t

打开帮助文档 C-h i

###右键菜单

将如下代码命令为.reg文件，运行后可为鼠标右键添加菜单项“Edit with Emacs”。

```
Windows Registry Editor Version 5.00

[HKEY_CLASSES_ROOT\*\shell\Edit with Emacs]

[HKEY_CLASSES_ROOT\*\shell\Edit with Emacs\command]
@="\"D:\\emacs\\bin\\runemacs.exe\" \"%1\""
```

###插件

####evil-nerd-commenter

注释/反注释 M-;

注释多行 M-9 M-;

####function-args

提示函数参数 M-i

显示本文件大纲选择某项后跳转 C-M-j

跳转到函数定义（显示函数参数的时候有效） M-j

####hexl-mode

进入十六进制模式 M-x hexl-mode

退出十六进制模式 M-x hexl-mode-exit

输入十六进制数 M-x hexl-insert-hex-char

####ido

切换到上一个选项 C-r

切换到下一个选项 C-s

####jedi

显示光标处Python模块或函数的文档 C-c ?

####projectile

显示/刷新当前项目文件列表 C-c p f

####python

打开Python交互式Shell C-c C-p

####package

升级已安装的包 U

选择要安装的包 i

选择要删除的包 d

执行操作 x