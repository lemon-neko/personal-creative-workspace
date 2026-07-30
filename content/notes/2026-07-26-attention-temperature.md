---
id: attention-temperature
title: Temperature 如何改变注意力分布
date: 2026-07-26
status: published
summary: 用一个小实验确认温度参数控制的是注意力分布的平滑程度，而不是模型表达维度。
tags:
  - Self-Attention
  - 可视化
topic: transformer
---

在注意力分数进入 Softmax 前除以温度 \(T\)：

$$
\operatorname{softmax}\left(\frac{QK^\top}{\sqrt{d_k}T}\right)
$$

- \(T < 1\) 会放大分数差异，让注意力集中到少数 token。
- \(T > 1\) 会压缩分数差异，让分布更加平滑。
- 温度只改变同一组分数的分布形状，不改变张量维度。

这次实验提醒我：理解一个超参数时，先固定随机种子和其他变量，再观察单一变量对输出分布的影响。
