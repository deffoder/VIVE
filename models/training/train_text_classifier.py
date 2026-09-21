"""Trains the VIVE intent and behaviour classifiers.

Real training on real labelled data. Nothing here fabricates a metric: every
number reported comes from an executed evaluation on a held-out split that the
model never saw (docs/ML_SPEC.md 8.5).

Two heads, trained separately:

Base model: multilingual DistilBERT (104 languages, incl. Hindi).

Two constraints drove this choice, both real and both recorded:
  * MuRIL would be preferable for Indic coverage but ships only a .bin
    checkpoint, which transformers refuses to torch.load on torch < 2.6
    (CVE-2025-32434).
  * XLM-RoBERTa base ships safetensors but its AdamW optimizer states alone
    exhaust the 4 GB GTX 1650 Ti - verified by an actual OOM, not assumed.
DistilBERT-multilingual at 135M params trains comfortably in that budget. A
larger backbone is a cloud-GPU run, and the Colab notebook is set up for it.

  intent    single-label, 12 classes (only 7 have data - see the manifest)
  behavior  multi-label, 8 classes (only 5 have a label source + NORMAL)

Class imbalance is severe and real: NORMAL_CONVERSATION is ~64% of records and
OTP_REQUEST is ~0.1%. Class weighting is applied rather than resampling, so the
evaluation set keeps its natural distribution and the reported metrics describe
the real problem rather than a rebalanced one.

Usage:
    python models/training/train_text_classifier.py --task intent
    python models/training/train_text_classifier.py --task behavior
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import random
import sys
from datetime import datetime, timezone

import numpy as np
import torch
from sklearn.metrics import classification_report, f1_score
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    get_linear_schedule_with_warmup,
)

sys.path.insert(0, os.path.dirname(__file__))
from vive_labels import BEHAVIOR_LABELS, INTENT_LABELS  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MANIFESTS = os.path.join(ROOT, "data", "manifests")
ARTIFACTS = os.path.join(ROOT, "models", "artifacts")
EVAL_DIR = os.path.join(ROOT, "models", "evaluation")

SEED = 20260921


def set_seed(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)


def load_manifest(split: str) -> list[dict]:
    path = os.path.join(MANIFESTS, f"scamshield.{split}.jsonl")
    with open(path, encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


class TextDataset(Dataset):
    def __init__(self, rows: list[dict], tokenizer, task: str, max_length: int) -> None:
        self.rows = rows
        self.tokenizer = tokenizer
        self.task = task
        self.max_length = max_length
        self.labels = INTENT_LABELS if task == "intent" else BEHAVIOR_LABELS
        self.index = {label: i for i, label in enumerate(self.labels)}

    def __len__(self) -> int:
        return len(self.rows)

    def __getitem__(self, i: int):
        row = self.rows[i]
        encoded = self.tokenizer(
            row["text"],
            truncation=True,
            max_length=self.max_length,
        )
        item = {k: torch.tensor(v) for k, v in encoded.items()}
        if self.task == "intent":
            item["labels"] = torch.tensor(self.index[row["label_intent"]], dtype=torch.long)
        else:
            target = torch.zeros(len(self.labels), dtype=torch.float)
            for label in row["label_behaviors"]:
                target[self.index[label]] = 1.0
            item["labels"] = target
        return item


def class_weights(rows: list[dict], task: str) -> torch.Tensor:
    """Inverse-frequency weights, capped so an ultra-rare class cannot dominate."""
    labels = INTENT_LABELS if task == "intent" else BEHAVIOR_LABELS
    counts = np.zeros(len(labels), dtype=np.float64)
    index = {label: i for i, label in enumerate(labels)}

    for row in rows:
        if task == "intent":
            counts[index[row["label_intent"]]] += 1
        else:
            for label in row["label_behaviors"]:
                counts[index[label]] += 1

    # A class with zero examples gets weight 0: it cannot be learned, and
    # pretending otherwise would let it absorb gradient from nothing.
    weights = np.zeros_like(counts)
    present = counts > 0
    weights[present] = counts[present].sum() / (present.sum() * counts[present])
    weights = np.clip(weights, 0.0, 20.0)
    return torch.tensor(weights, dtype=torch.float)


@torch.no_grad()
def evaluate(model, loader, task: str, device: str) -> dict:
    model.eval()
    all_logits, all_targets = [], []
    for batch in loader:
        targets = batch.pop("labels")
        batch = {k: v.to(device) for k, v in batch.items()}
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
            logits = model(**batch).logits
        all_logits.append(logits.float().cpu())
        all_targets.append(targets)

    logits = torch.cat(all_logits)
    targets = torch.cat(all_targets)
    labels = INTENT_LABELS if task == "intent" else BEHAVIOR_LABELS

    if task == "intent":
        predictions = logits.argmax(dim=-1).numpy()
        truth = targets.numpy()
        present = sorted(set(truth.tolist()) | set(predictions.tolist()))
        report = classification_report(
            truth, predictions,
            labels=present,
            target_names=[labels[i] for i in present],
            output_dict=True, zero_division=0,
        )
        return {
            "macro_f1": float(f1_score(truth, predictions, average="macro", zero_division=0)),
            "weighted_f1": float(f1_score(truth, predictions, average="weighted", zero_division=0)),
            "per_class": report,
        }

    predictions = (torch.sigmoid(logits) >= 0.5).int().numpy()
    truth = targets.int().numpy()
    report = classification_report(
        truth, predictions, target_names=labels, output_dict=True, zero_division=0
    )
    return {
        "macro_f1": float(f1_score(truth, predictions, average="macro", zero_division=0)),
        "micro_f1": float(f1_score(truth, predictions, average="micro", zero_division=0)),
        "per_class": report,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", choices=["intent", "behavior"], required=True)
    parser.add_argument("--model", default="distilbert/distilbert-base-multilingual-cased")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--grad-accum", type=int, default=4)
    parser.add_argument("--lr", type=float, default=3e-5)
    parser.add_argument("--max-length", type=int, default=96)  # p99 of the corpus is 95 tokens
    parser.add_argument("--limit-train", type=int, default=0, help="0 = use all")
    parser.add_argument("--grad-checkpointing", action="store_true",
                        help="Trades compute for memory; needed for larger backbones on small VRAM.")
    parser.add_argument("--train-embeddings", action="store_true",
                        help="Unfreeze the embedding matrix. Off by default: on a 4 GB card its "
                             "gradients and optimizer states alone cause an OOM.")
    args = parser.parse_args()

    set_seed(SEED)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    labels = INTENT_LABELS if args.task == "intent" else BEHAVIOR_LABELS

    train_rows = load_manifest("train")
    val_rows = load_manifest("val")
    test_rows = load_manifest("test")
    if args.limit_train:
        train_rows = train_rows[: args.limit_train]

    print(f"task={args.task} model={args.model} device={device}")
    print(f"train={len(train_rows):,} val={len(val_rows):,} test={len(test_rows):,}")

    tokenizer = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model,
        num_labels=len(labels),
        problem_type="single_label_classification" if args.task == "intent"
        else "multi_label_classification",
    ).to(device)
    if args.grad_checkpointing:
        model.gradient_checkpointing_enable()

    # The multilingual vocabulary is 119k tokens, so the embedding matrix holds
    # roughly two thirds of the parameters. Freezing it removes its gradients
    # and optimizer states - the difference between OOM and training on 4 GB.
    # Subword embeddings are already well trained; the classifier learns in the
    # encoder and head.
    if not args.train_embeddings:
        for param in model.base_model.embeddings.parameters():
            param.requires_grad = False

    trainable = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total = sum(p.numel() for p in model.parameters())
    print(f"params: {total/1e6:.1f}M total, {trainable/1e6:.1f}M trainable "
          f"({100*trainable/total:.0f}%)")

    # Dynamic padding: each batch is padded to its own longest sequence rather
    # than to max_length. Same data, same model - just no wasted compute.
    collator = DataCollatorWithPadding(tokenizer, return_tensors="pt")

    train_loader = DataLoader(
        TextDataset(train_rows, tokenizer, args.task, args.max_length),
        batch_size=args.batch_size, shuffle=True, num_workers=0, collate_fn=collator,
    )
    val_loader = DataLoader(
        TextDataset(val_rows, tokenizer, args.task, args.max_length),
        batch_size=args.batch_size * 2, num_workers=0, collate_fn=collator,
    )
    test_loader = DataLoader(
        TextDataset(test_rows, tokenizer, args.task, args.max_length),
        batch_size=args.batch_size * 2, num_workers=0, collate_fn=collator,
    )

    weights = class_weights(train_rows, args.task).to(device)
    loss_fn = (
        torch.nn.CrossEntropyLoss(weight=weights)
        if args.task == "intent"
        else torch.nn.BCEWithLogitsLoss(pos_weight=weights)
    )

    # foreach=False avoids AdamW's multi-tensor temporaries, which were the
    # specific allocation that overflowed 4 GB.
    optimizer = torch.optim.AdamW(
        [p for p in model.parameters() if p.requires_grad],
        lr=args.lr, weight_decay=0.01, foreach=False,
    )
    steps = (len(train_loader) // args.grad_accum) * args.epochs
    scheduler = get_linear_schedule_with_warmup(optimizer, int(steps * 0.06), steps)
    scaler = torch.amp.GradScaler("cuda", enabled=device == "cuda")

    started = datetime.now(timezone.utc)
    for epoch in range(args.epochs):
        model.train()
        running = 0.0
        optimizer.zero_grad(set_to_none=True)
        for step, batch in enumerate(train_loader):
            targets = batch.pop("labels").to(device)
            batch = {k: v.to(device) for k, v in batch.items()}
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=device == "cuda"):
                logits = model(**batch).logits
                loss = loss_fn(logits, targets) / args.grad_accum
            scaler.scale(loss).backward()
            running += loss.item() * args.grad_accum

            if (step + 1) % args.grad_accum == 0:
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad(set_to_none=True)

            if (step + 1) % 200 == 0:
                mem = torch.cuda.max_memory_allocated() / 1e9 if device == "cuda" else 0
                print(f"  epoch {epoch+1} step {step+1}/{len(train_loader)} "
                      f"loss={running/(step+1):.4f} peak_vram={mem:.2f}GB", flush=True)

        val = evaluate(model, val_loader, args.task, device)
        print(f"  epoch {epoch+1} val macro_f1={val['macro_f1']:.4f}")

    test = evaluate(model, test_loader, args.task, device)
    finished = datetime.now(timezone.utc)

    out_dir = os.path.join(ARTIFACTS, f"{args.task}-classifier")
    os.makedirs(out_dir, exist_ok=True)
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)

    # --- reproducibility record (docs/ML_SPEC.md 8.6) ---
    record = {
        "task": args.task,
        "base_model": args.model,
        "labels": labels,
        "seed": SEED,
        "hyperparameters": {
            "epochs": args.epochs, "batch_size": args.batch_size,
            "grad_accum": args.grad_accum, "effective_batch": args.batch_size * args.grad_accum,
            "lr": args.lr, "max_length": args.max_length,
            "class_weighting": "inverse-frequency, capped at 20",
        },
        "data": {
            "manifest": "scamshield",
            "train": len(train_rows), "val": len(val_rows), "test": len(test_rows),
        },
        "environment": {
            "python": platform.python_version(),
            "torch": torch.__version__,
            "device": torch.cuda.get_device_name(0) if device == "cuda" else "cpu",
            "platform": platform.platform(),
        },
        "timing": {
            "started_utc": started.isoformat(),
            "finished_utc": finished.isoformat(),
            "duration_sec": int((finished - started).total_seconds()),
        },
        "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 1e9, 2) if device == "cuda" else None,
        "test_metrics": test,
        "artifact_path": out_dir,
        "caveat": (
            "Measured on a held-out split of the scamshield SMS corpus only. "
            "Not a call-transcript benchmark and not a VIVE end-to-end accuracy claim."
        ),
    }
    os.makedirs(EVAL_DIR, exist_ok=True)
    report_path = os.path.join(EVAL_DIR, f"{args.task}_training_report.json")
    with open(report_path, "w", encoding="utf-8") as handle:
        json.dump(record, handle, indent=2, ensure_ascii=False)

    print(f"\n  TEST macro_f1 = {test['macro_f1']:.4f}")
    if args.task == "behavior":
        print(f"  TEST micro_f1 = {test['micro_f1']:.4f}")
    print(f"  artifact: {out_dir}")
    print(f"  report:   {report_path}")


if __name__ == "__main__":
    main()
