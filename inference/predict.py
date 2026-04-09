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

    Tracks brace nesting in the generated text and stops when the count
    returns to zero after at least one opening brace has been seen.
    """

    def __init__(self, tokenizer, start_len):
        self.tokenizer = tokenizer
        self.start_len = start_len

    def __call__(self, input_ids, scores, **kwargs):
        new_tokens = input_ids[0][self.start_len:].tolist()
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        count = 0
        started = False
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
      1. The whole text as JSON (the M3 model with enable_thinking=False
         emits a clean JSON object as its entire response).
      2. ```json ... ``` fenced code block (if the model wrapped it).
      3. Greedy `{...}` substring match (if the model added stray prose
         before / after the JSON).
    """
    text = text.strip()
    # 1. Whole text — the canonical happy path for the M3 adapter.
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # 2. Fenced code block
    m = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 3. Greedy `{...}` substring
    m = re.search(r'(\{.*\})', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
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


def predict(model, tokenizer, instruction, max_new_tokens=8192, temperature=0.1):
    """Run model inference on a natural language instruction.

    Critical chat-template alignment (M3 root-cause fix):
      Qwen3.5's chat template automatically wraps every assistant message
      with `<think>\\n\\n</think>\\n\\n` BEFORE the actual content. So the
      training data, after chat-template rendering, looks like:

          <|im_start|>assistant
          <think>

          </think>

          {
            "intent_type": ...
          }<|im_end|>

      The model is trained to predict `{...JSON...}` AFTER the closing
      `</think>\\n\\n`.

      At inference time the default `apply_chat_template(..., add_generation_prompt=True)`
      produces a prompt that ends in `<|im_start|>assistant\\n<think>\\n` — i.e.
      the thinking block is OPEN and the model is expected to write reasoning
      content. This is OUT OF DISTRIBUTION for the M3 adapter which never saw
      a context where the thinking block had to be filled — its training had
      the block always already empty + closed.

      The fix is to pass `enable_thinking=False` to the chat template, which
      makes inference produce a prompt ending in `<|im_start|>assistant\\n<think>\\n\\n</think>\\n\\n`
      — BYTE-FOR-BYTE identical to where training started predicting tokens.
      The model then continues with `{...JSON...}` exactly as trained.

      This eliminates the need for prefix injection (which was a workaround
      for a problem caused by the same chat-template mismatch — and which
      actively BROKE M3 by inserting `{` INSIDE the open `<think>` block,
      causing the model to emit degraded JS-like object literals).

    Other behaviour:
      - max_new_tokens=8192 to absorb long VPRN multi-site outputs without
        truncation (pre-M2.5 fix, ~11/17 failures were truncations).
    """
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True, enable_thinking=False,
    )
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
    return tokenizer.decode(generated, skip_special_tokens=True)


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
