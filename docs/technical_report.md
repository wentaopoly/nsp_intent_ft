# 基于 LoRA 微调的大语言模型实现 Nokia NSP 网络服务意图自动生成

## 1. 摘要

本项目针对 Nokia Network Services Platform (NSP) 意图配置的自动化需求，基于 Qwen3.5-9B 大语言模型，采用 LoRA (Low-Rank Adaptation) 微调技术，实现了从自然语言网络服务请求到 NSP 意图 JSON 的自动翻译。系统覆盖 9 种意图类型（epipe、tunnel、vprn、vpls、ies、etree、cpipe、evpn-epipe、evpn-vpls），经历了从 M1 到 M3.5 共五个里程碑的迭代开发。在最终评估中，测试集 330/330 样本全部通过四层 YANG 驱动验证（100%），11/11 个黄金测试样本同样达到 100% 通过率，值准确率 (value accuracy)、字段召回率 (field recall) 和 JSON 有效率均为 100%。项目构建了完整的数据生成-训练-推理-验证流水线，其中验证器基于 Nokia 官方 YANG schema 实现五层递进式校验，确保模型输出在结构和语义上均符合 NSP API 规范。

## 2. 引言

### 2.1 问题背景

Nokia NSP 是电信运营商广泛使用的网络服务管理平台，其核心抽象是"意图"(Intent) —— 一种声明式的 JSON 配置对象，描述期望的网络服务状态。每个意图包含意图类型 (intent_type)、模板名称 (template_name) 和填充值 (fill_values) 三个核心字段。fill_values 采用点分路径表示法（如 `site[0].interface[0].ipv4.primary.address`），对应 YANG schema 中的叶节点路径。

手动编写 NSP 意图 JSON 存在以下问题：

- **复杂性高**：一个典型的 VPRN 多站点配置可包含 30-50 个字段，路径深度达 5-6 层
- **容错率低**：任何路径拼写错误、类型不匹配或语义冲突（如 SDP 双向性缺失）都会导致部署失败
- **门槛高**：操作人员需要同时掌握 YANG schema 结构、NSP API 规范和特定服务类型的网络语义

### 2.2 研究目标

本项目的目标是构建一个端到端的 NL-to-JSON 自动化系统：操作人员用自然语言描述网络服务需求（如"创建一个从 192.168.0.16 到 192.168.0.37 的 E-Pipe 服务"），系统自动生成符合 NSP API 规范的完整意图 JSON。

### 2.3 覆盖范围

系统支持以下 9 种 NSP 服务意图类型：

| 意图类型 | 服务类别 | 典型场景 |
|---|---|---|
| epipe | L2 点对点 | E-Line 专线互联 |
| tunnel | MPLS 隧道 | SDP 隧道建立 |
| vprn | L3 VPN | 多站点 IP-VPN 服务 |
| vpls | L2 多点 | 以太网桥接域 |
| ies | L3 路由接入 | Internet 增强服务 |
| etree | L2 星形 | Hub-spoke 广播隔离 |
| cpipe | TDM 仿真 | E1/T1 电路仿真 |
| evpn-epipe | EVPN 点对点 | BGP 控制面的 E-Line |
| evpn-vpls | EVPN 多点 | BGP 控制面的桥接域 |

## 3. 数据来源与处理

### 3.1 数据来源

训练数据的构建基于以下四类权威来源：

**Nokia YANG Schema (`data/yang/`)**：9 种意图类型的官方 YANG 模块文件，使用 pyang 库解析。YANG schema 定义了每个字段的路径、类型（int32/string/enumeration/boolean 等）、取值范围、枚举集合和正则模式，是验证器 Tier 1-3 的权威数据源。

**Nokia 标准载荷 (`data/canonical_payloads/`)**：从 Nokia 统一服务管理包 `nsp-service-mgmt-unified-25.8.3-rel.173.zip` 中提取的 18 个标准 JSON 载荷示例，分布在 6 种意图类型中：vpls (7个)、vprn (3个)、evpn-vpls (3个)、epipe (2个)、evpn-epipe (2个)、ies (1个)。etree、cpipe 和 tunnel 在 Nokia 标准包中没有对应的标准载荷。这些标准载荷用于构建 Tier 6 验证器，评估模型输出路径与真实部署载荷的吻合度。

**领域知识值生成器 (`data/value_generators.py`)**：保留了 Sarvesh 的领域专业知识，包括真实的 IP 地址段（10.x.x.x 管理网、192.168.x.x 设备互联）、Nokia LAG 端口命名规范（如 `lag-1` 至 `lag-20` 或 `1/2/c4/1` 物理端口格式）、集群名称池（Alpha/Beta/Gamma 等 35 个希腊字母和天体名称）和项目名称池（OurAI/NetFlow/CloudX 等 26 个）。

**Nokia 服务管理指南 PDF**：第 4.7-4.19 章节用于验证参数约束和跨字段语义规则的正确性。

### 3.2 数据规模与划分

数据集总量 3300 个样本，按 80/10/10 比例划分：

| 集合 | 样本数 | 用途 |
|---|---|---|
| 训练集 (train.jsonl) | 2640 | SFT 微调 |
| 验证集 (val.jsonl) | 330 | 训练过程中的 eval_loss 监控 |
| 测试集 (test.jsonl) | 330 | 最终模型评估 |
| 黄金测试 (golden_tests.jsonl) | 11 | 手工编写的边界用例 |

每个样本采用 OpenAI chat 格式的三元组 `(system, user, assistant)`，其中 system prompt 统一定义了意图类型列表和输出规则，user 为自然语言指令，assistant 为目标 JSON 输出。

### 3.3 数据生成流程

数据生成由 `data/generate_training_data.py` 驱动，核心流程为：

1. 调用 `field_definitions.py` 中对应意图类型的生成器，产生 fill_values 字典
2. 从 `instruction_templates.py` 中随机选择一个自然语言模板，用 fill_values 中的值填充占位符
3. 调用 `validate_sample()` 对生成的样本进行验证，确保每个训练样本自身即通过 YANG 校验
4. 组装为 chat 格式并输出到 JSONL 文件

## 4. 系统架构

系统由六个核心模块组成，形成数据生成、训练、推理、验证的完整流水线。

### 4.1 YANG Schema 解析器 (`data/yang_schema.py`)

该模块负责加载和索引 Nokia 的 YANG schema 文件。核心设计：

- 使用 pyang 库解析 `data/yang/<intent_type>/` 目录下的 YANG 模块，自动解析 `import`、`uses grouping` 和 `typedef` 链
- 包含 IETF 标准模块搜索路径（`ietf-inet-types`、`ietf-yang-types` 等），确保类型定义链（如 `inet:ipv4-address-no-zone`）能够完整解析到基础类型
- 构建 `SchemaIndex` 索引，以规范化点分路径为键，`LeafMeta` 为值，支持精确匹配和后缀匹配两种查找模式
- 处理 NSP 特有的 envelope 字段（service-name、intent-type 等），这些字段不在 per-intent YANG 模块中定义，而是由 NSP 更上层模型定义

关键数据结构 `LeafMeta` 包含：

```python
@dataclass
class LeafMeta:
    base_type: str           # YANG 基础类型 (int32/string/boolean/enumeration/...)
    mandatory: bool          # 是否为必填字段
    range_expr: str | None   # 取值范围表达式 (如 "1..4094")
    length_expr: str | None  # 字符串长度约束
    pattern_list: list[str]  # 正则模式列表
    enum_values: list[str]   # 枚举值集合
    is_leaf_list: bool       # 是否为 leaf-list 类型
    union_types: list        # union 成员类型列表
```

### 4.2 意图验证器 (`data/intent_validator.py`)

验证器实现了五层递进式校验栈，是系统质量保障的核心：

**Tier 1 -- 路径有效性**：检查 fill_values 中的每个键是否对应 YANG schema 中的合法叶节点路径。使用 SchemaIndex 的后缀匹配机制处理项目中省略了中间包装容器（如 `sdp-details.`）的简写路径约定。

**Tier 2 -- 类型/范围/枚举/模式**：对每个值进行类型校验。整数类型 (int8-int64, uint8-uint64) 检查基础类型边界和 YANG `range` 表达式；字符串类型检查 `length` 约束和 `pattern` 正则匹配；枚举类型检查值是否在合法枚举集合中；联合类型 (union) 尝试每个成员类型，至少一个匹配即通过；布尔类型接受 Python bool 和字符串形式。

```python
# Tier 2 类型检查的核心分发逻辑
def _check_value(value, meta):
    if meta.base_type == "boolean":
        return _check_boolean(value)
    if meta.base_type in _INT_TYPES | _UINT_TYPES:
        return _check_integer(value, meta.base_type, meta.range_expr)
    if meta.base_type == "string":
        return _check_string(value, meta.length_expr, meta.pattern_list)
    if meta.base_type == "enumeration":
        return _check_enumeration(value, meta.enum_values)
    if meta.base_type == "union":
        return _check_union(value, meta)
```

**Tier 3 -- 合并后 JSON 结构校验**：在 fill_values 合并为完整意图 JSON 之后运行。检查内容包括：根键 `nsp-service-intent:intent` 数组存在且非空、envelope 层级的必填字段（如 tunnel 的 name/source-ne-id/destination-ne-id/sdp-id）均已填充、每个 YANG list 条目的 key 字段均已填充、list 条目数量符合 `max-elements`/`min-elements` 约束。

**Tier 4 -- 语义跨字段规则**：校验 YANG schema 无法表达但项目视为正确性约束的业务规则。每个意图类型有独立的语义检查函数：

| 意图类型 | 语义规则 |
|---|---|
| epipe | SDP[0] 源=site-a / SDP[1] 源=site-b（双向性）；VLAN 标签 site-a = site-b；设备 ID 不可相同 |
| tunnel | source-ne-id != destination-ne-id |
| vprn | 所有站点 device-id 互不相同；RD 格式为 `ASN:ID` |
| vpls/evpn-vpls | 站点 device-id 互不相同；所有站点外层 VLAN 标签一致 |
| etree | 至少一个 root SAP + 至少一个 leaf SAP；站点 device-id 互不相同 |
| cpipe | 设备 ID 不同；两端 time-slots 必须匹配；vc-type 在合法枚举集合中 |
| evpn-epipe | evpn-type 与 mpls/vxlan 子树匹配；eth-tag 与 access VLAN 一致 |

**Tier 6 -- 标准载荷相似度**（信息性，不阻断）：将模型输出的路径集合与 Nokia 标准载荷中的路径集合对比。路径规范化处理包括：剥离 Nokia 包装容器（如 `*-details.`）、将列表索引折叠为通配符（如 `site[0]` -> `site[*]`）。出现在标准载荷中的路径计为 "known"，未出现的计为 "novel"。由于标准载荷本身不完整（例如 vprn 的 payload2 仅 15 个字段，payload1 有 658 个），novel 路径仅作为告警参考。

### 4.3 字段定义与值生成器 (`data/field_definitions.py` + `data/value_generators.py`)

`field_definitions.py` 是每个意图类型的字段生成核心，包含 9 个生成器函数和一个统一调度器 `generate_intent_values()`。

**传统型生成器**（epipe/tunnel/vprn/vpls/ies/etree/cpipe）：内部使用 `random.*` 调用生成各字段值，通过 `value_generators.py` 提供的领域知识生成器确保值的真实性。例如 `random_device_ip()` 从 `10.x.x.x` 和 `192.168.x.x` 段中采样，`random_port_id()` 生成符合 Nokia 端口命名规范的值（如 `1/2/c4/1` 或 `lag-12`），`derive_sdp_id(src_ip, dst_ip)` 从 IP 地址确定性地推导 SDP ID。

**纯函数型生成器**（evpn-epipe/evpn-vpls）：这是 M3.5 阶段的核心设计创新。生成器签名接受所有指令可见的关键字参数，返回的每个字段值必须满足以下三条之一：

1. 直接等于某个关键字参数（即指令中可见的值）
2. 该意图类型的固定常量（如 `mtu=1500`、`ecmp=4`、`inner-vlan-tag=-1`）
3. 关键字参数的确定性函数（如 `RD = "65000:{ne_service_id}"`、`VNI = ne_service_id`）

```python
# 纯函数生成器的确定性推导规则 (evpn-epipe)
def generate_evpn_epipe_values(*, service_name, customer_id, ne_service_id,
                                evi, evpn_type, vlan, device, port,
                                local_ac, remote_ac):
    rd = f"65000:{ne_service_id}"       # 确定性：固定 ASN + 服务 ID
    rt = f"65000:{ne_service_id}"       # 与 RD 同源
    values = {
        "service-name": service_name,   # 直接来自参数
        "mtu": 1500,                    # 常量
        "description": f"{service_name} EVPN service",  # 确定性推导
        "site-a.local-ac.eth-tag": vlan,                # 确定性：等于 access VLAN
        # ...
    }
    if evpn_type == "mpls":
        values["site-a.mpls.bgp-instance.route-distinguisher"] = rd
        values["site-a.mpls.bgp-instance.vsi-import"] = [f"{service_name}-import"]
    else:  # vxlan
        values["site-a.vxlan.vni"] = ne_service_id      # VNI = 服务 ID
    return values
```

这种设计确保模型可以从指令中精确还原每个输出字段，消除了训练数据中不可预测的随机性。

`value_generators.py` 包含底层随机值生成器和领域知识词汇池。核心词汇池有：CLUSTER_NAMES (35个)、PROJECT_NAMES (26个)、LAG_PREFIXES (11个)、SITE_DESCRIPTIONS (11个)、CLUSTER_ROLES (14个)。

### 4.4 指令模板 (`data/instruction_templates.py`)

每种意图类型配有 10-15 个自然语言模板，涵盖正式、会话、简洁和带上下文推理等多种语言风格。模板使用 Python format 字符串占位符，在数据生成时由 fill_values 中的值填充。例如 epipe 的 15 个模板包括：

- 正式风格：`"Create an E-Pipe service named '{service_name}' for customer {customer_id}..."`
- 会话风格：`"I need a point-to-point Ethernet connection between {site_a_device} and {site_b_device}..."`
- 简洁风格：`"Deploy epipe: {service_name}, cust={customer_id}, svc-id={ne_service_id}..."`

多样化的模板风格使模型能够理解不同表述方式下的相同网络意图。

### 4.5 推理引擎 (`inference/predict.py`)

推理模块加载基础模型 + LoRA adapter，对自然语言指令执行推理。核心技术要点：

**Chat Template 对齐**：Qwen3.5 的 chat template 在每个 assistant 消息前自动插入 `<think>\n\n</think>\n\n` 标记。训练数据经模板渲染后，模型学习的是在 `</think>\n\n` 之后直接输出 JSON。推理时，通过设置 `enable_thinking=False` 确保 prompt 末尾的字节序列与训练时完全一致。

**JSON 停止准则**：自定义 `JsonStoppingCriteria` 跟踪花括号嵌套计数，当计数归零时立即停止生成，避免不必要的 token 浪费。

**JSON 提取**：`extract_json()` 按优先级尝试三种解析策略：整体解析、fenced code block 提取、贪心花括号匹配。

**合并与验证流水线**：`predict_and_merge()` 函数串联推理、JSON 提取、fill_values 合并和四层验证，形成完整的端到端流水线。

```python
def predict(model, tokenizer, instruction, max_new_tokens=8192):
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]
    prompt = tokenizer.apply_chat_template(
        messages, tokenize=False, add_generation_prompt=True,
        enable_thinking=False,  # 关键：确保与训练数据字节级对齐
    )
    # ...
```

### 4.6 评估系统 (`eval/evaluate_model.py`)

评估模块对每个测试样本执行完整推理+验证流程，报告以下指标：

- **JSON Valid Rate**：输出可解析为合法 JSON 的比例
- **Intent Type Accuracy**：意图类型预测正确率
- **Field Recall / Precision**：字段召回率和精确率
- **Value Accuracy**：匹配字段的值准确率
- **Tier 1+2 / Tier 3 / Tier 4 Valid**：各层验证通过率
- **All Tiers Valid**：所有层同时通过的比例
- **Tier 6 Canonical Recognition**：标准载荷路径覆盖率（信息性）
- **Per-intent breakdown**：按意图类型的细分指标

评估过程使用增量式检查点文件 (`_eval_checkpoint_*.jsonl`)，在推理过程中逐行写入，确保即使最终聚合步骤出错也不会丢失所有推理结果。

## 5. 训练方法

### 5.1 基础模型

采用 Qwen3.5-9B (Qwen/Qwen3.5-9B) 作为基础模型，参数量 90 亿，支持 32K 上下文窗口。选择该模型的原因是其在代码生成和结构化输出任务上的强大能力，以及对中英文的良好支持。

### 5.2 LoRA 配置

采用 LoRA 低秩适配技术进行参数高效微调：

```python
LoraConfig(
    r=32,                    # 秩
    lora_alpha=64,           # 缩放系数 (alpha/r = 2.0)
    target_modules=[         # 目标注意力模块 (7个)
        "q_proj", "k_proj", "v_proj", "o_proj",
        "gate_proj", "up_proj", "down_proj",
    ],
    lora_dropout=0.05,
    bias="none",
    task_type=TaskType.CAUSAL_LM,
)
```

目标模块覆盖了注意力层的全部四个投影矩阵（Q/K/V/O）和 FFN 层的三个矩阵（gate/up/down），共 7 个模块类型。LoRA 秩 r=32、alpha=64 对应有效缩放因子 2.0，提供了足够的表达能力而不过度增加参数量。

### 5.3 训练硬件与精度

- 硬件：2 张 NVIDIA RTX 6000 Ada (49GB 显存)
- 精度：BF16（无量化），每张 GPU 加载完整 BF16 模型 (~18GB)
- 并行策略：DDP (Distributed Data Parallel)，通过 Accelerate 库管理

### 5.4 训练超参数

```python
SFTConfig(
    num_train_epochs=5,
    per_device_train_batch_size=2,
    gradient_accumulation_steps=8,   # 有效批大小 = 2 * 8 * 2 GPU = 32
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    warmup_ratio=0.05,
    weight_decay=0.01,
    max_grad_norm=1.0,
    max_length=8192,                 # M3 从 2048 提升
    gradient_checkpointing=True,
)
```

使用 TRL 库的 `SFTTrainer` 进行有监督微调。训练日志显示 5 个 epoch 的损失从 0.095 稳步下降到 0.085，token 准确率从 96.2% 提升到 96.6%。

### 5.5 训练日志

| Epoch | Loss | Token Accuracy | Learning Rate |
|---|---|---|---|
| 1 | 0.0953 | 96.21% | 1.89e-4 |
| 2 | 0.0897 | 96.35% | 1.45e-4 |
| 3 | 0.0854 | 96.52% | 8.33e-5 |
| 4 | 0.0861 | 96.54% | 2.26e-5 |
| 5 | 0.0847 | 96.58% | 1.14e-7 |

## 6. 实验过程与问题解决

本节按时间顺序记录各里程碑的开发过程、遇到的问题及解决方案。这是项目中技术挑战最密集的部分。

### 6.1 M1: YANG 验证器 MVP

**目标**：建立基于 YANG schema 的自动化验证能力。

**工作内容**：
- 实现 `yang_schema.py`：使用 pyang 解析 Nokia YANG 模块，构建 SchemaIndex 索引
- 实现 `intent_validator.py`：Tier 1 (路径有效性) + Tier 2 (类型/范围/枚举/模式)
- 首次对模型输出运行 YANG 验证，发现了若干训练数据中隐含的路径错误

**关键技术决策**：支持后缀匹配查找，因为项目的 fill_values 路径约定省略了 Nokia 的中间包装容器（如 `epipe.sdp-details.sdp[0].sdp-id` 在 fill_values 中简写为 `sdp[0].sdp-id`）。这要求验证器在查找时能容忍路径前缀的差异。

### 6.2 M2: 替换手写 skeleton 和 path resolver

**目标**：消除硬编码的路径映射表，统一使用 YANG 驱动的路径解析。

**工作内容**：
- 移除了 `VPRN_SITE_SKELETON`、`resolve_epipe_paths` 等手写映射
- 替换为 `yang_schema.resolve_path()` 通用解析器，根据 YANG schema 自动将点分路径解析为嵌套 JSON 路径
- 实现 `test_merge_equivalence.py` 等价性测试：对原有 3 种意图类型的全部测试样本，比较手写映射和 YANG 驱动映射的合并结果

**验证结果**：307/307 个样本的合并结果字节级一致 (byte-identical)，确认 YANG 驱动路径解析的完全等价性。

### 6.3 M2.5: 推理修复

**问题**：模型在推理时生成质量严重下降，输出中出现类 JavaScript 对象字面量而非合法 JSON。

**根因分析**：Qwen3.5 的 chat template 在训练数据中自动将 assistant 消息渲染为：

```
<|im_start|>assistant
<think>

</think>

{"intent_type": ...}<|im_end|>
```

即 `<think>` 块始终为空且已关闭。但推理时默认的 `apply_chat_template(..., add_generation_prompt=True)` 生成的 prompt 末尾为：

```
<|im_start|>assistant
<think>
```

`<think>` 块处于**打开**状态。模型被要求填充推理内容，但它在训练中从未见过这种上下文。

**解决方案**：在 `apply_chat_template` 调用中设置 `enable_thinking=False`，使推理 prompt 末尾变为 `<|im_start|>assistant\n<think>\n\n</think>\n\n` —— 与训练时模型开始预测 token 的位置**字节级一致**。

**附带修复**：
- `max_new_tokens` 从 1024 提升到 8192，解决 VPRN 多站点输出截断问题（M2 评估中 11/17 个失败是截断导致）
- 移除了 prefix injection 机制（在 `<think>` 块打开状态下注入 `{` 反而导致模型在推理块内输出格式化文本）

### 6.4 M3: 横向扩展 6 种新意图类型

**目标**：从 3 种意图类型（epipe/tunnel/vprn）扩展到 9 种。

**新增类型**：vpls、ies、etree、cpipe、evpn-epipe、evpn-vpls。对每种类型实现：
- 字段定义生成器 (`field_definitions.py`)
- 自然语言指令模板 (`instruction_templates.py`)
- Tier 4 语义验证规则 (`intent_validator.py`)

**遇到的问题**：

1. **评估器白名单硬编码**：`evaluate_model.py` 原先硬编码了 epipe/tunnel/vprn 三种类型的白名单，新增的 6 种类型在评估时被静默跳过。修复：移除白名单，改为对所有 `intent_type` 动态运行验证。

2. **validate_sample.py 垫片层**：旧的 `validate_sample.py` 使用正则表达式做格式校验。修改为路由到 YANG 验证器的 Tier 1+2+4，保持向后兼容接口的同时使用新的验证后端。

3. **SYSTEM_PROMPT 偏差**：早期 system prompt 仅列出 3 种意图类型，导致模型对新类型的识别能力不足。修复：在 system prompt 中显式列出全部 9 种类型。

4. **max_length 迭代**：etree 多站点配置的样本长度可达约 2700 token，2048 的 max_length 静默截断了 32 个 etree 样本。经过两轮调整（2048 -> 4096 -> 8192）最终确定 8192，为未来更复杂的意图类型预留充足空间。

**M3 评估结果**：330/330 整体通过率 98.8%，但 etree 的 value accuracy 仅 84%，成为 M3.5 的主要攻克目标。

### 6.5 M3.5: EVPN 模式重构 + 标准载荷挖掘 + Bug 修复

M3.5 是技术挑战最密集的里程碑，分四个阶段解决三个独立的质量问题。

#### Phase 1: Nokia 标准包挖掘

**工作内容**：
- 从 Nokia 统一服务管理包中解压 25 个 zip 文件
- 发现并提取 18 个标准 JSON 载荷（`payload*.ibsf.json`）
- 建立 `data/canonical_payloads/` 目录结构

**关键发现**：
- etree 在 Nokia 内部实际使用 VPLS 容器结构实现（etree 是 VPLS 的拓扑约束变体）
- tunnel 在标准包中没有任何标准载荷
- 不同载荷的字段覆盖度差异悬殊（vprn payload1 有 658 个字段，payload2 仅 15 个）

**Tier 6 验证器构建**：基于标准载荷的路径集合，实现了路径规范化（剥离包装容器 + 索引通配化）和相似度对比逻辑。

#### Phase 2: EVPN 模式修复（第一次尝试）

**工作内容**：
- 将 evpn-epipe 重写为单站点 (site-a) 模式，使用 `local-ac` / `remote-ac` 表示两个伪线端点
- 添加 BGP 子树：Route Distinguisher (RD)、Route Target (RT)、auto-bind-tunnel、VNI

**问题**：在生成器内部使用 `random.X` 生成 RD/RT/VNI/eth-tag/ecmp/mtu 等值，这些值不出现在指令模板中。模型在推理时无法从指令中推断这些随机值。

**结果**：evpn-epipe 的 value accuracy 从基线下降到 73%，evpn-vpls 为 78%。

#### Phase 3: 纯函数重构（根因修复）

**根因定位**：问题的本质是 fill_values 生成函数中存在训练数据的"信息泄漏" —— 生成器的输出中包含了指令模板中不可见的随机值，模型没有任何信号可以预测这些值。

**解决方案**：建立严格的纯函数契约：

> 生成器返回的每个字段值必须是 (a) 指令可见参数的直接拷贝，(b) 该意图类型的固定常量，或 (c) 指令可见参数的确定性函数。

将 evpn-epipe 和 evpn-vpls 的生成器重构为接受显式关键字参数的纯函数：

```python
# 重构后：所有随机性提升到调用者 (_roll_evpn_epipe_args)
# 生成器本身是纯函数，无 random 调用
args = _roll_evpn_epipe_args()    # 在此处集中随机采样
fv = generate_evpn_epipe_values(**args)  # 纯函数：output = f(args)
instruction = template.format(**args)    # 同一组 args 驱动指令
# 确保 instruction 和 fv 看到完全一致的输入
```

确定性推导规则（匹配 Nokia 运营商实践）：
- RD/RT：`"65000:{ne_service_id}"`（固定 ASN + 服务 ID）
- VNI：`ne_service_id`（VXLAN ID 等于服务 ID）
- vsi-import：`["{service_name}-import"]`
- vsi-export：`["{service_name}-export"]`
- eth-tag：`vlan`（AC 标签 = 接入 VLAN）
- mtu/ecmp：1500/4（常量）

**测试保障**：实现 `tests/test_generator_determinism.py`，包含两部分测试：

```python
# Part 1: 种子确定性 — 相同种子产生相同 (instruction, output)
for seed in (0, 1, 7, 42, 1729):
    random.seed(seed)
    instr1, out1 = builder()
    random.seed(seed)
    instr2, out2 = builder()
    assert instr1 == instr2 and normalize(out1) == normalize(out2)

# Part 2: 参数纯度 — 输出只依赖参数，不依赖随机状态
args = roller()  # 固定参数集
for seed in (1, 7, 42, 999, 1729, 31337):
    random.seed(seed)  # 不同随机状态
    assert normalize(gen(**args)) == baseline  # 输出必须一致
```

Part 2 的参数纯度测试是捕获 M3.5 基线 Bug 的精确手段：如果生成器内部有任何 `random.X` 调用泄漏到输出中，使用不同种子时输出会变化，测试立即失败。

**结果**：evpn-epipe 73% -> 100%，evpn-vpls 78% -> 100%。

#### Phase 4: E-Tree SDP 修复

**问题**：etree 的 value accuracy 为 79%，其中 3 站点配置为 100%，4-5 站点配置大幅下降。

**根因 1 -- 叶节点描述格式歧义**：`format_etree_leaves_desc` 使用 `/` 分隔符拼接设备和端口信息，但 port-id 本身包含 `/`（如 `1/2/c4/1`），导致解析歧义。修复：改用 `"device X on port Y"` 的无歧义格式。

**根因 2 -- 全网状 SDP 违反 E-Tree 语义**：SDP 生成逻辑从 vpls 复制了全网状 (full-mesh) 拓扑 N x (N-1)，但 E-Tree 语义要求叶节点之间不可通信。例如 5 站点配置会生成 20 个 SDP，其中叶-叶 SDP 是语义错误的。修复：仅生成 root-leaf 双向 SDP，SDP 数量从 N x (N-1) 减少到 2 x num_leaves。

**根因 3 -- 多 root 配置**：早期版本随机选择 1-2 个 root 节点。2-root 配置（含 root-root + root-leaf SDP）在 4-5 站点时产生 10-14 个 SDP 条目，超出模型的可靠枚举能力。修复：固定 1 个 root + N 个 leaf，最大 SDP 数量限制为 6（1 root + 3 leaves 时的双向对数）。

```python
# 修复后的 E-Tree SDP 生成逻辑
root_ip = site_ips[0]   # site[0] 固定为 root
for leaf_idx in range(1, total):
    leaf_ip = site_ips[leaf_idx]
    # root -> leaf (单向)
    values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(root_ip, leaf_ip)
    values[f"sdp[{sdp_idx}].source-device-id"] = root_ip
    values[f"sdp[{sdp_idx}].destination-device-id"] = leaf_ip
    sdp_idx += 1
    # leaf -> root (反向)
    values[f"sdp[{sdp_idx}].sdp-id"] = derive_sdp_id(leaf_ip, root_ip)
    values[f"sdp[{sdp_idx}].source-device-id"] = leaf_ip
    values[f"sdp[{sdp_idx}].destination-device-id"] = root_ip
    sdp_idx += 1
```

**结果**：etree 79% -> 100%。

## 7. 实验结果

### 7.1 最终评估指标

| 指标 | 测试集 (330样本) | 黄金测试 (11样本) |
|---|---|---|
| JSON Valid Rate | 330/330 (100%) | 11/11 (100%) |
| Intent Type Accuracy | 100% | 100% |
| Field Recall | 100% | 100% |
| Field Precision | 100% | 100% |
| Value Accuracy | 100% | 100% |
| Tier 1+2 Valid (路径/类型) | 100% | 100% |
| Tier 3 Valid (合并结构) | 100% | 100% |
| Tier 4 Valid (语义) | 100% | 100% |
| All Tiers Valid | 100% | 100% |

### 7.2 各意图类型细分

| 意图类型 | 样本数 | JSON Valid | Field Recall | Value Accuracy |
|---|---|---|---|---|
| epipe | ~37 | 100% | 100% | 100% |
| tunnel | ~37 | 100% | 100% | 100% |
| vprn | ~37 | 100% | 100% | 100% |
| vpls | ~37 | 100% | 100% | 100% |
| ies | ~37 | 100% | 100% | 100% |
| etree | ~37 | 100% | 100% | 100% |
| cpipe | ~37 | 100% | 100% | 100% |
| evpn-epipe | ~37 | 100% | 100% | 100% |
| evpn-vpls | ~37 | 100% | 100% | 100% |

### 7.3 跨里程碑对比

| 里程碑 | 意图类型数 | 测试集 Value Accuracy | 关键改进 |
|---|---|---|---|
| M1 | 3 | 基线 | YANG 验证器上线 |
| M2 | 3 | 基线 | YANG 驱动路径解析替换手写映射 |
| M2.5 | 3 | 基线提升 | chat template 对齐 + max_tokens 修复 |
| M3 | 9 | 98.8% | 6 种新类型，etree 84% |
| M3.5 基线 | 9 | 97.9% | EVPN 结构修复，etree 79% |
| M3.5 最终 | 9 | **100.0%** | 纯函数重构 + root-leaf SDP |

### 7.4 训练效率

- 总训练 token 数：约 1200 万
- 5 epoch 总步数：410 步
- 训练损失变化：0.095 -> 0.085（收敛平稳）
- 最终 token 准确率：96.6%

## 8. 讨论与未来工作

### 8.1 方法论反思

**纯函数契约的重要性**：M3.5 Phase 3 的纯函数重构是项目最具方法论价值的经验教训。当生成器内部的随机性泄漏到输出中而指令模板不可见时，模型面对的是一个不可学习的任务 —— 无论训练多少 epoch，那些随机字段的准确率都无法超过随机基线。这一教训适用于所有基于模板的训练数据合成场景。

**E-Tree SDP 问题的层次性**：etree 的三个根因（格式歧义、语义错误、规模过大）分别对应了数据质量的三个层次：文本层的可解析性、领域层的语义正确性、模型层的可学习性。解决顺序是自底向上的，必须先修复语义错误（root-leaf only），再调整规模（固定 1 root），最后修复格式（无歧义描述）。

### 8.2 当前局限性

1. **离线验证的结构下限性质**：Tier 1-4 的验证通过仅意味着输出与 YANG schema 结构一致。NSP 在服务器端还会执行 JavaScript 映射引擎 (`mapping-engine="js-scripted"`) 的额外转换和验证，`valid=True` 不等于 NSP 会接受该意图。
2. **标准载荷覆盖不完整**：etree、cpipe、tunnel 在 Nokia 标准包中没有标准载荷，Tier 6 对这些类型无法提供参考。
3. **测试集与训练集同分布**：测试集由同一个生成器产生，无法评估模型对分布外指令的泛化能力。

### 8.3 未来工作

**M4: 设备意图类型扩展**：Nokia NSP 包含 181 种设备意图类型 (device-intent)，目前项目仅覆盖 9 种服务意图 (service-intent)。扩展路线已在 YANG schema 目录结构中预留。

**实机部署验证**：需要接入真实 NSP 实例，验证模型生成的意图 JSON 在实际部署环境中的接受率和成功率。

**CLI 生成**：Nokia 标准包中部分载荷附带 `payload*.cli.txt` 文件，包含对应的 SR OS CLI 命令。可利用这些配对数据训练 JSON-to-CLI 或 NL-to-CLI 的并行能力。

**复合意图与冗余意图**：当前 9 种类型均为独立服务意图。未来可探索复合意图（组合多种服务类型）和冗余意图（主备切换配置）等更复杂的场景。

## 9. 结论

本项目成功构建了一个基于 Qwen3.5-9B LoRA 微调的 NSP 意图自动生成系统，实现了从自然语言到 Nokia NSP 意图 JSON 的端到端翻译。系统覆盖 9 种意图类型，在 330 个测试样本和 11 个黄金测试上均达到 100% 的全指标通过率。

项目的核心技术贡献包括：

1. **五层 YANG 驱动验证栈**：从路径有效性到语义跨字段规则，提供了系统化的质量保障框架
2. **纯函数生成器契约**：确保训练数据中每个字段都可从指令内容精确还原，消除不可学习的随机噪声
3. **Chat template 字节级对齐**：解决了 Qwen3.5 `<think>` 标记在训练与推理间的失配问题
4. **E-Tree 拓扑感知 SDP 生成**：将网络服务的语义约束（叶节点不可互通）正确编码到训练数据中

经过 M1 到 M3.5 五个里程碑的迭代，项目从 3 种意图类型的基线系统演进为 9 种类型的全覆盖解决方案，测试准确率从 M3 的 98.8% 提升到 M3.5 的 100%，验证了 LoRA 微调在网络配置自动化这一垂直领域的有效性。
