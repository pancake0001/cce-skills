# 支持在cce集群上部署openclaw

## 准备工作

### 创建namespace
kubectl create ns openclaw 

### ssh秘钥，用于gateway与sandbox之间互联

手动执行：
1. 生成密钥对
ssh-keygen -t ed25519 -f /tmp/gateway_sandbox_key

2. 创建 Secret（存私钥）
kubectl create secret generic openclaw-ssh-key \
  --from-file=privateKey=/tmp/gateway_sandbox_key -n openclaw

3. 创建 ConfigMap（存公钥）
kubectl create configmap ssh-authorized-keys \
  --from-file=authorized_keys=/tmp/gateway_sandbox_key.pub -n openclaw

secret和configmap的名称固定，便于安装时引用。

### 华为云AKSK凭证准备，用于sandbox挂载和OBS磁盘挂载时的权限申请

手动执行：
1. 创建只读用户secret
kubectl create secret generic alice-huawei-credentials \
  --from-literal=HUAWEI_AK=<your_access_key> \
  --from-literal=HUAWEI_SK=<your_secret_key> \
  -n openclaw
2. 创建ops用户secret
kubectl create secret generic bob-huawei-credentials \
  --from-literal=HUAWEI_AK=<your_access_key> \
  --from-literal=HUAWEI_SK=<your_secret_key> \
  -n openclaw
3. 创建obs挂卷secret
kubectl create secret generic obs-credentials \
  --from-literal=access.key=<your_access_key> \
  --from-literal=secret.key=<your_secret_key> \
  --namespace=openclaw \
  --type="cfe/secure-opaque"
kubectl label secret obs-credentials \
  --namespace=openclaw \
  --overwrite \
  "secret.kubernetes.io/used-by=csi"
kubectl annotate secret obs-credentials \
  --namespace=openclaw \
  --overwrite \
  access-key=<your_access_key>

### 模型对接凭证

创建secret，保存对接外部大模型的凭证信息，此处以minimax为例
kubectl create secret generic maas-credentials \
  --namespace=openclaw \
  --from-literal=MINIMAX_API_KEY=your_minimax_key


## 执行安装
执行如下命令：
helm upgrade --install openclaw ./charts/openclaw   --namespace openclaw   -f ./charts/values-huawei-final.yaml

### 本地访问
在使用kubectl开启port-forward，可以直接打开web页面进行访问http://127.0.0.1:18790/，注意token需要从openclaw的容器中读取。
 kubectl port-forward --namespace openclaw svc/openclaw 18790:18789