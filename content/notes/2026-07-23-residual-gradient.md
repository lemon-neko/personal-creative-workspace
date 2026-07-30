---
id: residual-gradient
title: 残差连接不只是“防止梯度消失”
date: 2026-07-23
status: published
summary: 残差路径为信息和梯度提供了直接通道，也让每一层更像是在学习对已有表示的修正。
tags:
  - Transformer
  - 梯度
topic: transformer
---

以前我把残差连接简单记成“解决梯度消失”。手写 Transformer Block 后，更有用的理解是：

1. 前向传播时，子层不必重新构造完整表示，只需要学习一个增量。
2. 反向传播时，恒等路径让梯度可以绕过复杂的注意力或前馈变换。
3. LayerNorm 放在残差前还是残差后，会改变深层网络的优化行为。

以后回看模型结构时，我会先问：信息的主路径在哪里，当前子层究竟在补充什么？
