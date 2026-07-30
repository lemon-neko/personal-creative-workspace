# 从零理解 Transformer

这个专题不是把公式重新抄一遍，而是记录我如何通过 NumPy 实现、可视化和小模型训练，把几个容易混淆的问题连接起来。

## 最初的问题

- Q、K、V 为什么需要三组投影？
- 多头注意力相比单头究竟增加了什么？
- 残差连接和 LayerNorm 如何影响信息与梯度？
- 一个只有 NumPy 的 Decoder，能否真正完成训练和生成？

## Self-Attention：从“查找”理解加权聚合

$$
\operatorname{Attention}(Q,K,V)=\operatorname{softmax}\left(\frac{QK^\top}{\sqrt{d_k}}\right)V
$$

Query 表达当前位置想找什么，Key 表达每个位置可以如何被匹配，Value 是匹配后实际被聚合的信息。缩放因子 \(\sqrt{d_k}\) 避免维度增大时点积快速变大，让 Softmax 过早进入饱和区域。

多头机制不是简单地重复计算。每个头在更小的表示子空间中建立独立关系，再由输出投影把这些关系组合起来。

## Transformer Block：围绕信息主路径思考

一个 Block 可以拆成两次“保留原表示，再补充新信息”：

1. 注意力子层在 token 之间交换信息。
2. 前馈网络在每个 token 内部变换特征。
3. 残差连接保留主路径，LayerNorm 控制数值尺度。

理解结构时，比背诵 Encoder/Decoder 框图更重要的是持续追踪张量形状和信息来源。

## MiniGPT：最小闭环

字符级 MiniGPT 串起了 Token Embedding、位置编码、因果注意力、交叉熵、解析反向传播和采样生成。它不追求效果，而是验证一件事：只有当前向、损失、梯度和参数更新形成闭环，才算真正实现了一个可训练模型。

## 当前结论与踩坑

- `d_model` 必须能被 `num_heads` 整除，否则无法稳定拆分多头。
- 注意力热力图展示的是关系分布，不等同于可靠的因果解释。
- 小语料上的 loss 下降只证明训练链路可用，不证明模型具有泛化能力。
- 固定随机种子有利于比较实验，但不能替代多次运行。
- 写出每一步的张量形状，是排查矩阵乘法错误最快的方式。

## 对应材料

- `src/attention.py`：Self-Attention 与 Transformer Block
- `src/layers.py`：LayerNorm、FFN、位置编码和掩码
- `src/minigpt.py`：可训练的字符级 Decoder
- `notebooks/01-self-attention-from-scratch.ipynb`：推导与实验记录
- `examples/train_minigpt.py`：命令行训练示例
