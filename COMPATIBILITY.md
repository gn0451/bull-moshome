# 设备兼容性与贡献流程

设备能力登记位于 `custom_components/bull_iot/device_profiles.json`。支持等级含义：

- `profiled`：已有明确产品档案，默认启用；不等同于每个固件都完成现场控制验收。
- `verified`：该 PID 已完成控制和状态回读验收。
- `inferred-safe`：未收录 PID，但发现标准负载属性；实体默认禁用。
- `read-only`：协议用途不明确或疑似情景面板，只提供状态和诊断。
- `specialized`：充电桩、BLE 等必须走专用控制路径。

## 未知设备接入

1. 在 HA 的 Bull MosHome 集成条目中选择“下载诊断”。
2. 检查报告中不含账号、家庭 ID、设备 ID、昵称、房间和属性值。
3. 提交 `product_id`、型号、固件版本、`property_identifiers` 和期望能力。
4. 对低风险开关，可先在 HA 实体注册表中手动启用默认禁用的实验实体。
5. 只有完成真实设备控制及回读后，才能把证据等级提升为 `verified`。

充电桩、加热器及其他大功率设备不得使用通用实验控制路径，必须新增专用档案、
状态守卫和失败回读测试。
