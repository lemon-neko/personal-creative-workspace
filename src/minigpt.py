"""A small, educational decoder-only language model implemented with NumPy.

The module deliberately favours readability over speed.  It provides the full
learning loop needed for a character-level language model: tokenisation,
causal self-attention, cross-entropy, manual backpropagation and sampling.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple

import numpy as np


class CharTokenizer:
    """A deterministic character tokenizer built from a training corpus."""

    def __init__(self, vocab: Iterable[str]):
        self.vocab = sorted(set(vocab))
        if not self.vocab:
            raise ValueError("vocab must contain at least one character")
        self.char_to_id = {char: index for index, char in enumerate(self.vocab)}
        self.id_to_char = {index: char for char, index in self.char_to_id.items()}

    @classmethod
    def from_text(cls, text: str) -> "CharTokenizer":
        return cls(text)

    @property
    def vocab_size(self) -> int:
        return len(self.vocab)

    def encode(self, text: str) -> np.ndarray:
        unknown = [char for char in text if char not in self.char_to_id]
        if unknown:
            raise ValueError(f"unknown character: {unknown[0]!r}")
        return np.asarray([self.char_to_id[char] for char in text], dtype=np.int64)

    def decode(self, token_ids: Iterable[int]) -> str:
        return "".join(self.id_to_char[int(token)] for token in token_ids)


def make_language_model_batches(
    token_ids: np.ndarray, block_size: int, batch_size: int, rng: np.random.Generator
) -> Tuple[np.ndarray, np.ndarray]:
    """Sample ``(input, next-token target)`` windows from a token sequence."""
    if len(token_ids) <= block_size:
        raise ValueError("text must be longer than block_size")
    starts = rng.integers(0, len(token_ids) - block_size, size=batch_size)
    inputs = np.stack([token_ids[start : start + block_size] for start in starts])
    targets = np.stack([token_ids[start + 1 : start + block_size + 1] for start in starts])
    return inputs, targets


def _softmax(values: np.ndarray) -> np.ndarray:
    shifted = values - values.max(axis=-1, keepdims=True)
    exp_values = np.exp(shifted)
    return exp_values / exp_values.sum(axis=-1, keepdims=True)


@dataclass
class DecoderBlock:
    """One pre-normalisation-free decoder block, kept compact for teaching."""

    d_model: int
    num_heads: int
    d_ff: int
    rng: np.random.Generator

    def __post_init__(self) -> None:
        if self.d_model % self.num_heads:
            raise ValueError("d_model must be divisible by num_heads")
        scale = 1.0 / np.sqrt(self.d_model)
        self.head_size = self.d_model // self.num_heads
        self.W_q = self.rng.normal(0, scale, (self.d_model, self.d_model))
        self.W_k = self.rng.normal(0, scale, (self.d_model, self.d_model))
        self.W_v = self.rng.normal(0, scale, (self.d_model, self.d_model))
        self.W_o = self.rng.normal(0, scale, (self.d_model, self.d_model))
        self.W_1 = self.rng.normal(0, scale, (self.d_model, self.d_ff))
        self.b_1 = np.zeros(self.d_ff)
        self.W_2 = self.rng.normal(0, scale, (self.d_ff, self.d_model))
        self.b_2 = np.zeros(self.d_model)

    def parameters(self) -> Dict[str, np.ndarray]:
        return {name: getattr(self, name) for name in ("W_q", "W_k", "W_v", "W_o", "W_1", "b_1", "W_2", "b_2")}

    def forward(self, x: np.ndarray) -> Tuple[np.ndarray, dict]:
        batch, time, _ = x.shape
        q = x @ self.W_q
        k = x @ self.W_k
        v = x @ self.W_v
        def to_heads(value: np.ndarray) -> np.ndarray:
            return value.reshape(
                batch, time, self.num_heads, self.head_size
            ).transpose(0, 2, 1, 3)

        qh, kh, vh = map(to_heads, (q, k, v))
        scores = qh @ kh.transpose(0, 1, 3, 2) / np.sqrt(self.head_size)
        causal = np.tril(np.ones((time, time), dtype=bool))
        scores = np.where(causal, scores, -1e9)
        weights = _softmax(scores)
        attended = weights @ vh
        merged = attended.transpose(0, 2, 1, 3).reshape(batch, time, self.d_model)
        attention_out = merged @ self.W_o
        residual = x + attention_out
        pre_activation = residual @ self.W_1 + self.b_1
        hidden = np.maximum(pre_activation, 0)
        output = residual + hidden @ self.W_2 + self.b_2
        cache = {"x": x, "q": qh, "k": kh, "v": vh, "weights": weights, "merged": merged,
                 "residual": residual, "pre_activation": pre_activation, "hidden": hidden, "causal": causal}
        return output, cache

    def backward(self, gradient: np.ndarray, cache: dict) -> Tuple[np.ndarray, Dict[str, np.ndarray]]:
        x, residual, pre, hidden = cache["x"], cache["residual"], cache["pre_activation"], cache["hidden"]
        grads: Dict[str, np.ndarray] = {"W_2": hidden.reshape(-1, self.d_ff).T @ gradient.reshape(-1, self.d_model),
                                        "b_2": gradient.sum(axis=(0, 1))}
        d_residual = gradient.copy()
        d_hidden = gradient @ self.W_2.T
        d_pre = d_hidden * (pre > 0)
        grads["W_1"] = residual.reshape(-1, self.d_model).T @ d_pre.reshape(-1, self.d_ff)
        grads["b_1"] = d_pre.sum(axis=(0, 1))
        d_residual += d_pre @ self.W_1.T

        merged, weights, qh, kh, vh = cache["merged"], cache["weights"], cache["q"], cache["k"], cache["v"]
        grads["W_o"] = merged.reshape(-1, self.d_model).T @ d_residual.reshape(-1, self.d_model)
        d_merged = d_residual @ self.W_o.T
        batch, time, _ = d_merged.shape
        d_attended = d_merged.reshape(batch, time, self.num_heads, self.head_size).transpose(0, 2, 1, 3)
        d_v = weights.transpose(0, 1, 3, 2) @ d_attended
        d_weights = d_attended @ vh.transpose(0, 1, 3, 2)
        d_scores = weights * (d_weights - (d_weights * weights).sum(axis=-1, keepdims=True))
        d_scores *= cache["causal"]
        scale = np.sqrt(self.head_size)
        d_q = (d_scores @ kh) / scale
        d_k = (d_scores.transpose(0, 1, 3, 2) @ qh) / scale
        def from_heads(value: np.ndarray) -> np.ndarray:
            return value.transpose(0, 2, 1, 3).reshape(
                batch, time, self.d_model
            )

        d_q, d_k, d_v = map(from_heads, (d_q, d_k, d_v))
        flattened_x = x.reshape(-1, self.d_model)
        for name, value in (("W_q", d_q), ("W_k", d_k), ("W_v", d_v)):
            grads[name] = flattened_x.T @ value.reshape(-1, self.d_model)
        d_x = d_residual + d_q @ self.W_q.T + d_k @ self.W_k.T + d_v @ self.W_v.T
        return d_x, grads


class MiniGPT:
    """A trainable, causal, decoder-only Transformer language model."""

    def __init__(self, vocab_size: int, d_model: int = 48, num_heads: int = 4, d_ff: int = 96,
                 num_layers: int = 1, block_size: int = 32, seed: int = 42):
        self.vocab_size, self.d_model, self.block_size = vocab_size, d_model, block_size
        self.rng = np.random.default_rng(seed)
        scale = 1.0 / np.sqrt(d_model)
        self.token_embedding = self.rng.normal(0, scale, (vocab_size, d_model))
        self.position_embedding = self.rng.normal(0, scale, (block_size, d_model))
        self.blocks = [DecoderBlock(d_model, num_heads, d_ff, self.rng) for _ in range(num_layers)]
        self.W_out = self.rng.normal(0, scale, (d_model, vocab_size))
        self.b_out = np.zeros(vocab_size)

    def forward(self, tokens: np.ndarray) -> Tuple[np.ndarray, dict]:
        if tokens.ndim != 2 or tokens.shape[1] > self.block_size:
            raise ValueError("tokens must have shape (batch, time) with time <= block_size")
        x = self.token_embedding[tokens] + self.position_embedding[:tokens.shape[1]]
        caches: List[dict] = []
        attentions: List[np.ndarray] = []
        for block in self.blocks:
            x, cache = block.forward(x)
            caches.append(cache)
            attentions.append(cache["weights"])
        return x @ self.W_out + self.b_out, {"tokens": tokens, "hidden": x, "blocks": caches, "attentions": attentions}

    def loss_and_gradients(self, tokens: np.ndarray, targets: np.ndarray) -> Tuple[float, Dict[str, np.ndarray]]:
        logits, cache = self.forward(tokens)
        probabilities = _softmax(logits)
        batch, time = targets.shape
        loss = -np.log(probabilities[np.arange(batch)[:, None], np.arange(time), targets] + 1e-12).mean()
        d_logits = probabilities
        d_logits[np.arange(batch)[:, None], np.arange(time), targets] -= 1
        d_logits /= batch * time
        grads: Dict[str, np.ndarray] = {"W_out": cache["hidden"].reshape(-1, self.d_model).T @ d_logits.reshape(-1, self.vocab_size),
                                        "b_out": d_logits.sum(axis=(0, 1))}
        gradient = d_logits @ self.W_out.T
        for index in reversed(range(len(self.blocks))):
            gradient, block_grads = self.blocks[index].backward(gradient, cache["blocks"][index])
            grads.update({f"blocks.{index}.{name}": value for name, value in block_grads.items()})
        grads["token_embedding"] = np.zeros_like(self.token_embedding)
        np.add.at(grads["token_embedding"], tokens, gradient)
        grads["position_embedding"] = np.zeros_like(self.position_embedding)
        grads["position_embedding"][:tokens.shape[1]] = gradient.sum(axis=0)
        return float(loss), grads

    def apply_gradients(self, gradients: Dict[str, np.ndarray], learning_rate: float, clip_norm: float = 1.0) -> None:
        norm = np.sqrt(sum(float((gradient ** 2).sum()) for gradient in gradients.values()))
        scale = min(1.0, clip_norm / (norm + 1e-12))
        for name in ("token_embedding", "position_embedding", "W_out", "b_out"):
            setattr(self, name, getattr(self, name) - learning_rate * scale * gradients[name])
        for index, block in enumerate(self.blocks):
            for name, parameter in block.parameters().items():
                parameter -= learning_rate * scale * gradients[f"blocks.{index}.{name}"]

    def train_step(self, tokens: np.ndarray, targets: np.ndarray, learning_rate: float = 0.05) -> float:
        loss, gradients = self.loss_and_gradients(tokens, targets)
        self.apply_gradients(gradients, learning_rate)
        return loss

    def generate(self, prompt: np.ndarray, max_new_tokens: int = 40, temperature: float = 0.8, seed: int | None = None) -> np.ndarray:
        if temperature <= 0:
            raise ValueError("temperature must be positive")
        generated = list(map(int, prompt))
        rng = np.random.default_rng(seed)
        for _ in range(max_new_tokens):
            context = np.asarray(generated[-self.block_size:], dtype=np.int64)[None, :]
            logits, _ = self.forward(context)
            probabilities = _softmax(logits[0, -1] / temperature)
            generated.append(int(rng.choice(self.vocab_size, p=probabilities)))
        return np.asarray(generated, dtype=np.int64)
