"""
Fine-tune Qwen3.5-9B for NSP intent JSON generation using BF16 + LoRA + SFTTrainer.
Uses DDP across 2 GPUs — each GPU loads a full BF16 copy (~18GB), no quantization needed.
Launch with: accelerate launch --config_file train/accelerate_config.yaml train/train_qwen3_nsp.py
"""

import os
import csv
import torch
from datasets import load_dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainerCallback,
)
from peft import LoraConfig, TaskType
from accelerate import PartialState
from trl import SFTTrainer, SFTConfig


# --- Configuration ---
MODEL_NAME = "Qwen/Qwen3.5-9B"
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "generated")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "qwen3-nsp-intent-ft")
ADAPTER_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "qwen3-nsp-intent-adapter")
LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "output", "logs")


class EpochCSVLoggerCallback(TrainerCallback):
    """Log metrics at the end of each epoch to a CSV file."""

    def __init__(self, filename="training_log.csv"):
        self.filename = filename
        self.epoch_logs = []
        self.all_keys = set()

    def on_epoch_end(self, args, state, control, **kwargs):
        if state.log_history:
            log = state.log_history[-1].copy()
            log.pop("global_step", None)
            log["epoch"] = state.epoch
            self.all_keys.update(log.keys())
            self.epoch_logs.append(log)

    def on_train_end(self, args, state, control, **kwargs):
        with open(self.filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(self.all_keys))
            writer.writeheader()
            for log in self.epoch_logs:
                writer.writerow(log)
        print(f"Training log saved to {self.filename}")


def main():
    # Create output directories
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)

    print("=" * 60)
    print("NSP Intent Fine-Tuning: Qwen3.5-9B (BF16 + LoRA + DDP)")
    print("=" * 60)

    # --- Check GPU ---
    if torch.cuda.is_available():
        n_gpus = torch.cuda.device_count()
        for i in range(n_gpus):
            name = torch.cuda.get_device_name(i)
            mem = torch.cuda.get_device_properties(i).total_memory / 1e9
            print(f"GPU {i}: {name} ({mem:.1f} GB)")
    else:
        print("WARNING: No CUDA GPUs available!")

    # --- Load tokenizer ---
    print(f"\nLoading tokenizer from {MODEL_NAME}...")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    # --- Load model (DDP: each process loads full BF16 model to its own GPU) ---
    device_map = {"": PartialState().process_index}
    print(f"Loading model {MODEL_NAME} in BF16 on device {device_map}...")
    model = AutoModelForCausalLM.from_pretrained(
        MODEL_NAME,
        device_map=device_map,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16,
    )

    # --- LoRA config ---
    lora_config = LoraConfig(
        r=32,
        lora_alpha=64,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        lora_dropout=0.05,
        bias="none",
        task_type=TaskType.CAUSAL_LM,
    )

    # --- Load datasets ---
    print(f"\nLoading datasets from {DATA_DIR}...")
    train_dataset = load_dataset("json", data_files=os.path.join(DATA_DIR, "train.jsonl"), split="train")
    val_dataset = load_dataset("json", data_files=os.path.join(DATA_DIR, "val.jsonl"), split="train")

    print(f"Train: {len(train_dataset)} samples, Val: {len(val_dataset)} samples")

    # --- SFT config ---
    sft_config = SFTConfig(
        output_dir=OUTPUT_DIR,
        # Training
        num_train_epochs=5,
        per_device_train_batch_size=2,
        gradient_accumulation_steps=8,   # effective batch = 2 * 8 * 2 GPUs = 32
        gradient_checkpointing=True,
        gradient_checkpointing_kwargs={"use_reentrant": False},
        # Optimization
        learning_rate=2e-4,
        lr_scheduler_type="cosine",
        warmup_ratio=0.05,
        weight_decay=0.01,
        optim="adamw_torch",
        max_grad_norm=1.0,
        # Sequence -- M3 raise from 2048 to 4096. The new etree intent type
        # produces samples up to ~2700 tokens (1-2 roots x 2-3 leaves x SDP
        # mesh). 2048 was silently truncating 32 etree samples in M3 dry-run,
        # which would teach the model to emit unfinished JSON for complex
        # multipoint services. 4096 leaves comfortable headroom (Qwen3.5-9B
        # has a 32k context window).
        max_length=4096,
        # Evaluation
        per_device_eval_batch_size=1,
        eval_strategy="steps",
        eval_steps=50,
        # Saving
        save_strategy="steps",
        save_steps=100,
        save_total_limit=3,
        load_best_model_at_end=True,
        metric_for_best_model="eval_loss",
        greater_is_better=False,
        # Logging
        logging_steps=10,
        logging_dir=LOG_DIR,
        report_to="none",
        # Precision
        bf16=True,
        fp16=False,
    )

    # --- CSV logger ---
    csv_logger = EpochCSVLoggerCallback(
        filename=os.path.join(OUTPUT_DIR, "epoch_training_log.csv")
    )

    # --- Trainer ---
    print("\nInitializing SFTTrainer...")
    trainer = SFTTrainer(
        model=model,
        processing_class=tokenizer,
        args=sft_config,
        peft_config=lora_config,
        train_dataset=train_dataset,
        eval_dataset=val_dataset,
        callbacks=[csv_logger],
    )

    # Print trainable parameters
    trainable_params = sum(p.numel() for p in model.parameters() if p.requires_grad)
    total_params = sum(p.numel() for p in model.parameters())
    print(f"\nTrainable parameters: {trainable_params:,} / {total_params:,} "
          f"({100 * trainable_params / total_params:.2f}%)")

    # --- Train ---
    print("\n" + "=" * 60)
    print("Starting training...")
    print("=" * 60 + "\n")
    trainer.train()

    # --- Save ---
    print("\nSaving adapter weights...")
    trainer.save_model(ADAPTER_DIR)
    tokenizer.save_pretrained(ADAPTER_DIR)
    print(f"Adapter saved to {ADAPTER_DIR}")

    print("\n" + "=" * 60)
    print("Training complete!")
    print("=" * 60)


if __name__ == "__main__":
    main()
