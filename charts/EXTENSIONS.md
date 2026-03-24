# OpenClaw Helm Chart 扩展文档

## 扩展内容

基于实际部署经验，对 Helm chart 进行了以下扩展：

### 1. 支持第三方模型提供商 (providers)

在 `values.yaml` 中添加了 `openclaw.providers` 配置，支持配置额外的 LLM 提供商（如 MiniMax、OpenAI 兼容接口等）。

**配置示例：**
```yaml
openclaw:
  providers:
    minimax:
      baseUrl: "https://api.minimaxi.com/anthropic"
      apiKey: "${MINIMAX_API_KEY}"
      api: "anthropic-messages"
      models:
        - id: "MiniMax-M2.7"
          name: "MiniMax M2.7"
          reasoning: false
          input: ["text"]
          contextWindow: 200000
          maxTokens: 8192
```

**修改文件：**
- `charts/openclaw/values.yaml` - 添加 `providers` 配置项
- `charts/openclaw/templates/configmap.yaml` - 添加 providers 到配置生成逻辑

### 2. 修复 home 目录权限问题

在 init-config 容器中添加了 `chown -R 1000:1000 /home/openclaw`，解决容器内 npm 等工具因权限问题无法写入 `/home/openclaw` 目录的问题。

**修改文件：**
- `charts/openclaw/templates/deployment.yaml` - 在 init-config 命令中添加权限修复

### 3. 支持额外环境变量

在 `values.yaml` 中添加了 `extraEnv` 配置，支持直接在容器中添加额外的环境变量。

**配置示例：**
```yaml
extraEnv:
  - name: DEBUG
    value: "true"
```

**修改文件：**
- `charts/openclaw/values.yaml` - 添加 `extraEnv` 配置项
- `charts/openclaw/templates/deployment.yaml` - 添加 extraEnv 渲染逻辑

### 4. 自定义 Workspace 人设文件

添加了 `workspace` 配置，支持通过 Helm values 自定义 Agent 人设文件（SOUL.md、IDENTITY.md 等）。

**工作原理：**
- 首次安装时，将自定义文件复制到 PVC
- 后续升级/重装时，如果文件已存在则跳过（保护 Agent 经验）
- 文件持久化保存在 PVC 中

**配置示例：**
```yaml
workspace:
  enabled: true
  soul: |
    # SOUL
    ## Core Identity
    - 你是一个专业的 Kubernetes 助手
    - 使用中文回答
  identity: |
    # IDENTITY
    Name: OpenClaw-K8s-Expert
  user: |
    # USER
    Language: 中文
  extraFiles:
    TOOLS.md: |
      # TOOLS
      常用工具说明...
```

**新增文件：**
- `charts/openclaw/templates/workspace-configmap.yaml` - 存储 workspace 文件的 ConfigMap

**修改文件：**
- `charts/openclaw/values.yaml` - 添加 `workspace` 配置项
- `charts/openclaw/templates/deployment.yaml` - 添加 init-workspace initContainer

### 5. 增强持久化配置

添加了更多持久化选项，支持数据保留和重装恢复。

**新增配置项：**
```yaml
persistence:
  enabled: true
  size: 5Gi
  storageClass: ""
  accessMode: ReadWriteOnce
  annotations: {}
  existingClaim: ""     # 支持使用已存在的 PVC
  labels: {}            # PVC 标签，便于查找
  reclaimPolicy: ""     # 提示设置 Retain 策略
```

**修改文件：**
- `charts/openclaw/values.yaml` - 添加 existingClaim、labels、reclaimPolicy 配置
- `charts/openclaw/templates/pvc.yaml` - 添加 labels 支持

## 数据持久化指南

### OpenClaw 数据存储位置

```
/home/openclaw/.openclaw/
├── openclaw.json          # 主配置文件
├── agents/main/           # Agent 数据
│   ├── sessions/          # 对话历史 (JSONL)
│   └── agent/models.json  # 模型配置
├── workspace/             # 工作空间（经验文件）
│   ├── SOUL.md            # Agent 人格定义
│   ├── AGENTS.md          # Agent 使用指南
│   ├── IDENTITY.md        # 身份信息
│   ├── USER.md            # 用户信息
│   └── ...
├── cron/jobs.json         # 定时任务配置
├── canvas/                # Canvas 数据
└── devices/               # 设备配对信息
```

### 卸载重装保留数据

**方法一：使用 existingClaim（推荐）**

1. 首次安装时，记录 PVC 名称：
   ```bash
   kubectl get pvc -n <namespace>
   ```

2. 卸载时保留 PVC（不带 --purge）：
   ```bash
   helm uninstall openclaw-test -n openclaw-test
   # PVC 不会被删除
   ```

3. 重装时指定 existingClaim：
   ```yaml
   persistence:
     existingClaim: "openclaw-test"  # 使用之前的 PVC
   ```

4. 重装命令：
   ```bash
   helm install openclaw-test ./charts/openclaw -f values.yaml -n openclaw-test
   ```

**方法二：使用 Retain 策略的 StorageClass**

创建专用 StorageClass：
```yaml
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: openclaw-retain
provisioner: rancher.io/local-path  # Kind 使用的 provisioner
reclaimPolicy: Retain
```

然后在 values.yaml 中指定：
```yaml
persistence:
  storageClass: "openclaw-retain"
```

**方法三：手动备份恢复**

备份：
```bash
# 导出 PVC 数据
kubectl exec -n <namespace> deployment/<name> -c openclaw -- tar czf /tmp/backup.tar.gz -C /home/openclaw .openclaw
kubectl cp <namespace>/<pod>:/tmp/backup.tar.gz ./openclaw-backup.tar.gz
```

恢复：
```bash
# 安装后恢复数据
kubectl cp ./openclaw-backup.tar.gz <namespace>/<pod>:/tmp/backup.tar.gz
kubectl exec -n <namespace> deployment/<name> -c openclaw -- tar xzf /tmp/backup.tar.gz -C /home/openclaw
kubectl exec -n <namespace> deployment/<name> -c openclaw -- chown -R 1000:1000 /home/openclaw/.openclaw
```

### 升级版本保留数据

升级 OpenClaw 镜像版本时，数据会自动保留（PVC 不变）：

```bash
# 更新 values.yaml 中的镜像版本
image:
  tag: "2026.3.22-1"  # 新版本

# 升级
helm upgrade openclaw-test ./charts/openclaw -f values.yaml -n openclaw-test
```

### 查找卸载后的 PVC

如果 Helm 卸载后需要找回 PVC：

```bash
# 列出所有 PVC
kubectl get pvc --all-namespaces | grep openclaw

# 通过标签查找（如果安装时设置了 labels）
kubectl get pvc -l app.kubernetes.io/name=openclaw --all-namespaces
```

### Workspace 文件管理

**查看 workspace 文件：**
```bash
# 列出文件
kubectl exec -n <namespace> deployment/<name> -c openclaw -- ls -la /home/openclaw/.openclaw/workspace/

# 查看 SOUL.md
kubectl exec -n <namespace> deployment/<name> -c openclaw -- cat /home/openclaw/.openclaw/workspace/SOUL.md
```

**修改 workspace 文件：**
```bash
# 方式一：直接编辑（临时）
kubectl exec -it -n <namespace> deployment/<name> -c openclaw -- vi /home/openclaw/.openclaw/workspace/SOUL.md

# 方式二：通过 kubectl cp
# 1. 复制到本地
kubectl cp <namespace>/<pod>:/home/openclaw/.openclaw/workspace/SOUL.md ./SOUL.md -c openclaw
# 2. 编辑后复制回去
kubectl cp ./SOUL.md <namespace>/<pod>:/home/openclaw/.openclaw/workspace/SOUL.md -c openclaw
# 3. 修复权限
kubectl exec -n <namespace> deployment/<name> -c openclaw -- chown 1000:1000 /home/openclaw/.openclaw/workspace/SOUL.md
```

**更新 Helm values 中的 workspace：**
```yaml
workspace:
  enabled: true
  soul: |
    # 新的 SOUL.md 内容
```

注意：更新 Helm values 后需要删除 PVC 重新安装才能生效（因为 init-workspace 只在文件不存在时复制）。或者直接在容器中修改文件。

## 安装参数记录

以下是在 `openclaw-test` namespace 中部署时使用的参数：

**使用的 values 文件：** `openclaw-test-values.yaml`

```yaml
openclaw:
  bind: "lan"
  timezone: "UTC"
  configMode: "merge"
  
  agents:
    defaults:
      model: "minimax/MiniMax-M2.7"
      timeoutSeconds: 600
      thinkingDefault: "low"
  
  providers:
    minimax:
      baseUrl: "https://api.minimaxi.com/anthropic"
      apiKey: "${MINIMAX_API_KEY}"
      api: "anthropic-messages"
      models:
        - id: "MiniMax-M2.7"
          name: "MiniMax M2.7"
          reasoning: false
          input: ["text"]
          contextWindow: 200000
          maxTokens: 8192

  configOverrides:
    gateway:
      controlUi:
        dangerouslyAllowHostHeaderOriginFallback: true

credentials:
  anthropicApiKey: ""
  openaiApiKey: ""
  gatewayToken: ""
  extraSecrets:
    MINIMAX_API_KEY: "sk-cp-xxx...（实际密钥）"

persistence:
  enabled: true
  size: 5Gi
  storageClass: ""
  accessMode: ReadWriteOnce

service:
  type: NodePort
  port: 18789
  canvasPort: 18793

chromium:
  enabled: true

resources:
  requests:
    cpu: 100m
    memory: 512Mi
  limits:
    cpu: 2000m
    memory: 2Gi
```

**安装命令：**
```bash
helm install openclaw-test ./charts/openclaw -f openclaw-test-values.yaml -n openclaw-test --create-namespace
```

## 验证结果

部署完成后，通过以下命令验证配置：

```bash
# 检查 Pod 状态
kubectl get pods -n openclaw-test

# 检查模型配置
kubectl exec -n openclaw-test deployment/openclaw-test -c openclaw -- openclaw config get models.providers.minimax

# 检查环境变量
kubectl exec -n openclaw-test deployment/openclaw-test -c openclaw -- env | grep MINIMAX

# 检查可用模型
kubectl exec -n openclaw-test deployment/openclaw-test -c openclaw -- openclaw models list
```

**验证结果：**
```
agent model: minimax/MiniMax-M2.7
MINIMAX_API_KEY=sk-cp-xxx...

Model                                      Input      Ctx      Local Auth  Tags
minimax/MiniMax-M2.7                       text       195k     no    yes   default
```

## 访问方式

由于 Kind 集群未映射 NodePort 端口，需要使用端口转发访问：

```bash
# 端口转发（使用 18790 端口避免与 default namespace 冲突）
kubectl port-forward -n openclaw-test svc/openclaw-test 18790:18789

# 访问地址
http://localhost:18790

# Gateway Token
9JyctvOZ30xE2lziqk2d20bX8eBWgBR3
```

## 注意事项

1. **权限问题**：容器以 UID 1000 运行，需要确保 `/home/openclaw` 目录权限正确。init 容器中的 `chown` 命令解决了这个问题。

2. **MiniMax 端点**：
   - 国际版：`https://api.minimax.io/anthropic`
   - 中国版：`https://api.minimaxi.com/anthropic`

3. **环境变量引用**：在 `openclaw.json` 中使用 `${MINIMAX_API_KEY}` 格式引用环境变量，需要确保 Secret 中定义了对应的变量。

4. **配置合并**：`configMode: "merge"` 会保留已有配置，Helm values 覆盖冲突项。设置为 `"overwrite"` 会完全替换配置。

## 最佳实践

### 飞书对接

**前置条件：飞书应用配置**

1. 访问 [飞书开放平台](https://open.feishu.cn/app) 创建应用
2. 获取 `App ID` 和 `App Secret`
3. 添加权限：
   - `im:message` - 收发消息
   - `im:message:send_as_bot` - 以机器人身份发送
4. 事件订阅 → 选择 **WebSocket 模式**（无需公网 URL）
5. 订阅事件：`im.message.receive_v1`
6. 发布应用，等待审批

**Helm values 配置：**

```yaml
# values.yaml
openclaw:
  configOverrides:
    channels:
      feishu:
        enabled: true
        domain: "feishu"  # 国内版用 feishu，国际版用 lark
        connectionMode: "websocket"  # WebSocket 模式，无需公网 URL
        dmPolicy: "pairing"  # 首次私聊需要配对码
        accounts:
          default:
            appId: "${FEISHU_APP_ID}"
            appSecret: "${FEISHU_APP_SECRET}"

credentials:
  extraSecrets:
    FEISHU_APP_ID: "cli_xxxxxxxxxxxxx"
    FEISHU_APP_SECRET: "your_app_secret_here"
```

**验证飞书连接：**

```bash
# 查看日志确认连接成功
kubectl logs -n <namespace> deployment/<name> -c openclaw | grep -i feishu

# 应该看到类似日志：
# [feishu] WebSocket connected
# [feishu] Listening for events
```

**群聊配置（可选）：**

```yaml
openclaw:
  configOverrides:
    channels:
      feishu:
        groupAccess: "allowlist"  # open | allowlist | disabled
        allowedUsers:
          - "user_id_1"
          - "user_id_2"
```

**多账号配置（可选）：**

```yaml
openclaw:
  configOverrides:
    channels:
      feishu:
        accounts:
          default:
            appId: "${FEISHU_APP_ID_1}"
            appSecret: "${FEISHU_APP_SECRET_1}"
          work:
            appId: "${FEISHU_APP_ID_2}"
            appSecret: "${FEISHU_APP_SECRET_2}"

credentials:
  extraSecrets:
    FEISHU_APP_ID_1: "cli_xxx1"
    FEISHU_APP_SECRET_1: "secret1"
    FEISHU_APP_ID_2: "cli_xxx2"
    FEISHU_APP_SECRET_2: "secret2"
```

### 其他 Channel 配置

OpenClaw 支持多种 Channel，配置方式类似：

| Channel | connectionMode | 是否需要公网 URL |
|---------|---------------|-----------------|
| Feishu | websocket | 否 |
| Telegram | polling | 否 |
| Discord | gateway | 否 |
| Slack | websocket | 否 |
| WhatsApp | websocket | 否 |

通用配置模式：

```yaml
openclaw:
  configOverrides:
    channels:
      <channel_name>:
        enabled: true
        # channel 特定配置...

credentials:
  extraSecrets:
    <CHANNEL_API_KEY>: "your_key"
```

### Workspace 人设管理

**首次部署后自定义人设：**

```bash
# 方式一：通过 kubectl exec 直接编辑
kubectl exec -it -n <namespace> deployment/<name> -c openclaw -- vi /home/openclaw/.openclaw/workspace/SOUL.md

# 方式二：通过 kubectl cp
kubectl cp <namespace>/<pod>:/home/openclaw/.openclaw/workspace/SOUL.md ./SOUL.md -c openclaw
# 编辑后复制回去
kubectl cp ./SOUL.md <namespace>/<pod>:/home/openclaw/.openclaw/workspace/SOUL.md -c openclaw
kubectl exec -n <namespace> deployment/<name> -c openclaw -- chown 1000:1000 /home/openclaw/.openclaw/workspace/SOUL.md
```

**版本升级时保留人设：**

PVC 中的文件会自动保留，升级无需额外操作：

```bash
helm upgrade <release> ./charts/openclaw -f values.yaml -n <namespace>
```

**备份人设文件：**

```bash
# 导出所有 workspace 文件
kubectl exec -n <namespace> deployment/<name> -c openclaw -- tar czf /tmp/workspace.tar.gz -C /home/openclaw/.openclaw workspace
kubectl cp <namespace>/<pod>:/tmp/workspace.tar.gz ./workspace-backup.tar.gz -c openclaw
```

### 华为云 MaaS 大模型对接

华为云 MaaS 提供 Anthropic 兼容接口，可直接接入 OpenClaw。

**支持的模型：**

| 模型 | model 参数值 | 特性 |
|------|-------------|------|
| DeepSeek-V3 | DeepSeek-V3 | 通用对话 |
| DeepSeek-V3.1 | deepseek-v3.1-terminus | 深度思考 |
| DeepSeek-V3.2 | deepseek-v3.2 | 最新版本 |
| DeepSeek-R1 | DeepSeek-R1 | 推理增强 |
| Qwen3-Coder-480B | qwen3-coder-480b-a35b-instruct | 代码专用 |

**Helm values 配置：**

```yaml
openclaw:
  # 默认使用华为云 MaaS DeepSeek-V3
  agents:
    defaults:
      model: "huaweicloud-maas/DeepSeek-V3"
      timeoutSeconds: 600
      thinkingDefault: "low"

  providers:
    huaweicloud-maas:
      baseUrl: "https://api.modelarts-maas.com/anthropic/v1"
      apiKey: "${HUAWEICLOUD_MAAS_API_KEY}"
      api: "anthropic-messages"
      models:
        - id: "DeepSeek-V3"
          name: "DeepSeek V3"
          reasoning: false
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192
        - id: "deepseek-v3.1-terminus"
          name: "DeepSeek V3.1"
          reasoning: true
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192
        - id: "deepseek-v3.2"
          name: "DeepSeek V3.2"
          reasoning: true
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192
        - id: "DeepSeek-R1"
          name: "DeepSeek R1"
          reasoning: true
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192
        - id: "deepseek-r1-250528"
          name: "DeepSeek R1-0528"
          reasoning: true
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192

credentials:
  extraSecrets:
    HUAWEICLOUD_MAAS_API_KEY: "hO1zndLOvEctaVIfufNNrKdAdvVxen6XYZQT4ndY89roDcVVRRJi8qv40vPdxZl3CpLQNkykIeDT0fxcRUv-IQ"
```

**验证华为云 MaaS 连接：**

```bash
# 检查模型配置
kubectl exec -n <namespace> deployment/<name> -c openclaw -- openclaw config get models.providers.huaweicloud-maas

# 检查可用模型
kubectl exec -n <namespace> deployment/<name> -c openclaw -- openclaw models list | grep huaweicloud

# 测试 API 连接
kubectl exec -n <namespace> deployment/<name> -c openclaw -- curl -s -X POST \
  https://api.modelarts-maas.com/anthropic/v1/messages \
  -H "Content-Type: application/json" \
  -H "x-api-key: ${HUAWEICLOUD_MAAS_API_KEY}" \
  -d '{"model":"DeepSeek-V3","max_tokens":100,"messages":[{"role":"user","content":"Hello"}]}'
```

**同时使用多个提供商：**

```yaml
openclaw:
  agents:
    defaults:
      model: "minimax/MiniMax-M2.7"  # 默认使用 MiniMax

  providers:
    minimax:
      baseUrl: "https://api.minimaxi.com/anthropic"
      apiKey: "${MINIMAX_API_KEY}"
      api: "anthropic-messages"
      models:
        - id: "MiniMax-M2.7"
          name: "MiniMax M2.7"
          reasoning: false
          input: ["text"]
          contextWindow: 200000
          maxTokens: 8192

    huaweicloud-maas:
      baseUrl: "https://api.modelarts-maas.com/anthropic/v1"
      apiKey: "${HUAWEICLOUD_MAAS_API_KEY}"
      api: "anthropic-messages"
      models:
        - id: "DeepSeek-V3"
          name: "DeepSeek V3"
          reasoning: false
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192
        - id: "DeepSeek-R1"
          name: "DeepSeek R1"
          reasoning: true
          input: ["text"]
          contextWindow: 64000
          maxTokens: 8192

credentials:
  extraSecrets:
    MINIMAX_API_KEY: "sk-cp-xxx..."
    HUAWEICLOUD_MAAS_API_KEY: "hO1zndLOvEcta..."
```

**切换模型：**

在对话中切换使用不同模型：

```bash
# 查看所有可用模型
openclaw models list

# 临时切换到 DeepSeek-R1
openclaw models set huaweicloud-maas/DeepSeek-R1

# 恢复默认模型
openclaw models set minimax/MiniMax-M2.7
```

**注意事项：**

1. **区域限制**：华为云 MaaS Anthropic 接口仅支持"西南-贵阳一"区域
2. **鉴权方式**：使用 `x-api-key` 头部，与 Anthropic 原生接口一致
3. **模型特性**：
   - `reasoning: true` 的模型支持深度思考模式
   - `thinkingDefault: "low/high"` 控制思考深度
4. **配额管理**：注意华为云 MaaS 的调用配额限制
