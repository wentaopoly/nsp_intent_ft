"""
Run inference on the fine-tuned NSP intent model.
Takes a natural language instruction and outputs a complete API-ready JSON.
"""

import json
import re
import sys
import os
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, StoppingCriteria, StoppingCriteriaList
from peft import PeftModel

from merge_fill_values import merge_fill_values

SYSTEM_PROMPT = (
    "You are an NSP (Network Services Platform) intent configuration assistant. "
    "Given a natural language description of a network service, output a JSON object with three fields: "
    "'intent_type' (one of: epipe, tunnel, vprn), "
    "'template_name' (the NSP template to use), "
    "and 'fill_values' (a flat dictionary of field paths and their values that should be filled into the intent template). "
    "Only include fields that differ from template defaults. "
    "Use dot notation for nested paths and [N] for array indices. "
    "Output only valid JSON, no explanations."
)

DEFAULT_MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_ADAPTER = os.path.join(os.path.dirname(__file__), "..", "output", "qwen3-nsp-intent-adapter")


class JsonStoppingCriteria(StoppingCriteria):
    """Stop generation when a complete JSON object has been produced."""

    def __init__(self, tokenizer, start_len):
        self.tokenizer = tokenizer
        self.start_len = start_len
        self.brace_count = 0
        self.started = False

    def __call__(self, input_ids, scores, **kwargs):
        new_tokens = input_ids[0][self.start_len:].tolist()
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        for char in text:
            if char == '{':
                self.brace_count += 1
                self.started = True
            elif char == '}':
                self.brace_count -= 1
        if self.started and self.brace_count <= 0:
            return True
        return False


def extract_json(text):
    """Extract a JSON object from generated text."""
    text = text.strip()
    # Try fenced code block
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding JSON object directly
    m = re.search(r'(\{.*\})', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def load_model(model_name=DEFAULT_MODEL, adapter_dir=DEFAULT_ADAPTER):
    """Load the base model with fine-tuned LoRA adapter."""
    print(f"Loading tokenizer from {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)

    print(f"Loading base model {model_name}...")
    base_model = AutoModelForCausalLM.from_pretrained(
        model_name, device_map="auto", trust_remote_code=True, torch_dtype=torch.bfloat16
    )

    print(f"Loading LoRA adapter from {adapter_dir}...")
    model = PeftModel.from_pretrained(base_model, adapter_dir)
    model.eval()

    return model, tokenizer


def predict(model, tokenizer, instruction, max_new_tokens=1024, temperature=0.1):
    """Run model inference on a natural language instruction."""
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]

    stopping = StoppingCriteriaList([JsonStoppingCriteria(tokenizer, input_len)])

    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=temperature,
            top_p=0.95,
            eos_token_id=tokenizer.eos_token_id,
            pad_token_id=tokenizer.pad_token_id,
            stopping_criteria=stopping,
        )

    generated = outputs[0][input_len:]
    text = tokenizer.decode(generated, skip_special_tokens=True)
    return text


def predict_and_merge(model, tokenizer, instruction):
    """Full pipeline: instruction -> fill-values -> merged template -> API-ready JSON."""
    raw_output = predict(model, tokenizer, instruction)
    print(f"\nRaw model output:\n{raw_output}\n")

    parsed = extract_json(raw_output)
    if parsed is None:
        print("ERROR: Failed to parse model output as JSON")
        return None

    intent_type = parsed.get("intent_type")
    fill_values = parsed.get("fill_values", {})

    if not intent_type or not fill_values:
        print("ERROR: Missing intent_type or fill_values in output")
        return None

    result = merge_fill_values(intent_type, fill_values)
    return result


if __name__ == "__main__":
    model, tokenizer = load_model()

    test_instructions = [
        # Real Sarvesh tunnel
        "Create an MPLS tunnel from 192.168.0.16 to 192.168.0.37 with SDP ID 1637. "
        "Name it 'SDP-from-C2U16-to-C2U37'. Use BGP signaling with TLDP.",

        # Real Sarvesh epipe
        "Create an E-Pipe service named 'Epipe-VLAN-1001-nvlink-C2U16-to-a5000dual-C2U35' "
        "for customer 10 (NE service ID 2001). Connect device 192.168.0.37 on port 1/2/c4/1 "
        "to device 192.168.0.16 on port 1/2/c5/1 using VLAN 1001. MTU is 1492. "
        "Use SDP 3716 and 1637.",
    ]

    for i, instruction in enumerate(test_instructions):
        print(f"\n{'='*60}")
        print(f"Test {i+1}: {instruction[:80]}...")
        print(f"{'='*60}")

        result = predict_and_merge(model, tokenizer, instruction)
        if result:
            print(f"\nAPI-ready JSON:\n{json.dumps(result, indent=2)}")
        else:
            print("\nFailed to produce valid output.")
