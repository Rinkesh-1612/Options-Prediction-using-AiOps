"""PyTorch networks of the sequence models. Module level, so a trained model can be pickled and registered."""

from __future__ import annotations

import torch
from torch import nn


class GRUNet(nn.Module):
    """GRU over the window; the last hidden state -> net rupees (CE, PE)."""

    def __init__(self, n_features: int, hidden: int, **_):
        super().__init__()
        self.rnn = nn.GRU(n_features, hidden, batch_first=True)
        self.head = nn.Linear(hidden, 2)

    def forward(self, x):
        return self.head(self.rnn(x)[0][:, -1])


class TransformerNet(nn.Module):
    """Linear projection + learned positions + self-attention encoder; the last position -> (CE, PE)."""

    def __init__(self, n_features: int, hidden: int, seq_len: int, heads: int, layers: int, **_):
        super().__init__()
        self.proj = nn.Linear(n_features, hidden)
        self.pos = nn.Parameter(torch.zeros(1, seq_len, hidden))
        layer = nn.TransformerEncoderLayer(hidden, heads, 2 * hidden, 0.1, batch_first=True)
        self.enc = nn.TransformerEncoder(layer, layers)
        self.head = nn.Linear(hidden, 2)

    def forward(self, x):
        return self.head(self.enc(self.proj(x) + self.pos)[:, -1])


def build(arch: str, n_features: int, p: dict) -> nn.Module:
    return (GRUNet if arch == "gru" else TransformerNet)(n_features, **p)
