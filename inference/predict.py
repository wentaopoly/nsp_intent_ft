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

# Make data/ importable so we can run the YANG-driven 4-tier validator on
# the merged JSON before returning it to the caller (Milestone 2).
_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
if _DATA_DIR not in sys.path:
    sys.path.insert(0, _DATA_DIR)
from intent_validator import validate_full  # noqa: E402

SYSTEM_PROMPT = (
    "You are an NSP (Network Services Platform) intent configuration assistant. "
    "Convert each natural language network service request into a single JSON object with three fields:\n"
    "- intent_type: one of \"epipe\", \"tunnel\", \"vprn\", \"vpls\", \"ies\", \"etree\", "
    "\"cpipe\", \"evpn-epipe\", \"evpn-vpls\"\n"
    "- template_name: the NSP template name\n"
    "- fill_values: a flat dictionary of dot-notation field paths and their values\n"
    "\n"
    "Use dot notation for nested paths and [N] for list indices. Each intent type has its own naming "
    "convention -- match exactly the field paths shown in the training examples for that intent type. "
    "Only include fields that differ from template defaults.\n"
    "\n"
    "CRITICAL OUTPUT RULES:\n"
    "1. Your entire response must be a single JSON object and absolutely nothing else.\n"
    "2. Do NOT write any preamble, reasoning, plan, or explanation.\n"
    "3. Do NOT begin with phrases like \"The user wants\", \"Let me\", \"I will\", \"Sure\", \"Here is\", or \"Field paths to fill\".\n"
    "4. Do NOT wrap the JSON in markdown code fences such as ```json.\n"
    "5. Begin your response with the character `{` immediately and end it with `}`."
)

DEFAULT_MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_ADAPTER = os.path.join(os.path.dirname(__file__), "..", "output", "qwen3-nsp-intent-adapter")


class JsonStoppingCriteria(StoppingCriteria):
    """Stop generation when a complete JSON object has been produced.

    Supports the M2.5 prefix-injection mode: when the prompt is suffixed with
    `{` to force the model to start its JSON immediately, pass `prefix_braces=1`
    so the criteria knows there is already one open brace before generation
    begins. Without this, the criteria would stop on the first inner closing
    brace and produce truncated JSON.
    """

    def __init__(self, tokenizer, start_len, prefix_braces=0):
        self.tokenizer = tokenizer
        self.start_len = start_len
        self.brace_count = prefix_braces
        self.started = prefix_braces > 0

    def __call__(self, input_ids, scores, **kwargs):
        new_tokens = input_ids[0][self.start_len:].tolist()
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        # Recompute counts from scratch each step starting from the injected
        # prefix brace state. This is O(N) per token but N is bounded by the
        # current output length and decode is the slow part anyway.
        count = self.brace_count   # initial = prefix_braces
        started = self.started     # initial = (prefix_braces > 0)
        for char in text:
            if char == '{':
                count += 1
                started = True
            elif char == '}':
                count -= 1
        return started and count <= 0


def extract_json(text):
    """Extract a JSON object from generated text.

    Tries (in order):
      1. ```json ... ``` fenced code block
      2. Greedy `{...}` substring match
      3. The whole text as JSON
      4. Prepend `{` and retry — handles M2.5 prefix injection where the
         leading brace was added to the prompt and is therefore NOT in the
         generated text.
    """
    text = text.strip()
    # 1. Fenced code block
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 2. Greedy `{...}` match
    m = re.search(r'(\{.*\})', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. Try the whole text as JSON
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 4. Prefix injection: text was generated AFTER an injected `{` in the prompt.
    if not text.lstrip().startswith("{"):
        try:
            return json.loads("{" + text)
        except json.JSONDecodeError:
            pass
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


def predict(model, tokenizer, instruction, max_new_tokens=8192, temperature=0.1,
            inject_json_prefix=True):
    """Run model inference on a natural language instruction.

    M2.5 changes:
      - max_new_tokens raised from 1024 to 8192 to absorb long VPRN multi-site
        outputs without truncation (pre-fix, ~11/17 failures were truncations).
      - Optional `inject_json_prefix=True` appends `{` to the chat-template
        prompt, forcing the model to begin its response with JSON content
        regardless of any chain-of-thought bias. The leading `{` is then
        prepended back to the decoded output so callers see a complete JSON.
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    if inject_json_prefix:
        prompt = prompt + "{"
    inputs = tokenizer(prompt, return_tensors="pt").to(model.device)
    input_len = inputs["input_ids"].shape[1]

    stopping = StoppingCriteriaList([
        JsonStoppingCriteria(tokenizer, input_len, prefix_braces=1 if inject_json_prefix else 0)
    ])

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
    if inject_json_prefix:
        # Re-attach the injected leading brace so downstream parsers see a
        # syntactically complete JSON object.
        text = "{" + text
    return text


def predict_and_merge(model, tokenizer, instruction):
    """Full pipeline: instruction -> fill-values -> merged template -> API-ready JSON.

    After merging, runs the 4-tier YANG-driven validator. Validation errors
    are printed but do NOT block the return — the caller decides what to do
    with a structurally-valid-but-imperfect intent.
    """
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

    # Post-merge validation: report (don't block) any tier failures.
    try:
        ok, tier_errors = validate_full(intent_type, fill_values, merged_json=result)
        if not ok:
            print("WARNING: Validation found issues:")
            for tier, errs in tier_errors.items():
                if errs:
                    print(f"  [{tier}]")
                    for e in errs:
                        print(f"    {e}")
    except Exception as exc:
        print(f"WARNING: Validator crashed: {exc}")

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
