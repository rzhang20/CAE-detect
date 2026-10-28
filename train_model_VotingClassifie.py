# 方法二：VotingClassifier 多模型融合训练代码
import torch
import random
import numpy as np
import pandas as pd
from tqdm import tqdm
from collections import Counter

from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder
from sklearn.ensemble import RandomForestClassifier, VotingClassifier
from sklearn.neural_network import MLPClassifier
from sklearn.metrics import classification_report, confusion_matrix
import joblib
from xgboost import XGBClassifier
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# 配置
PRETRAINED_MODEL = "Salesforce/codet5-base"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
MAX_LEN = 512

# 1. 加载数据
df = pd.read_excel("合并-总 - 奇数训练集.xlsx")  # 确保有 'code' 和 'label' 列
label_encoder = LabelEncoder()
df["label_id"] = label_encoder.fit_transform(df["label"])

# 2. 加载 CodeT5 模型
tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
model = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).to(DEVICE)
model.eval()

def get_code_embedding(code):
    inputs = tokenizer(code, return_tensors="pt", truncation=True, padding="max_length", max_length=MAX_LEN)
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        encoder_outputs = model.get_encoder()(**inputs)
        embedding = encoder_outputs.last_hidden_state.mean(dim=1)
    return embedding.squeeze(0).cpu()

# 3. 生成原始嵌入
print("生成原始 CodeT5 向量...")
embeddings = []
labels = []

for i, row in tqdm(df.iterrows(), total=len(df)):
    code = row["code"]
    if not isinstance(code, str) or code.strip() == "":
        continue
    try:
        emb = get_code_embedding(code)
        embeddings.append(emb.numpy())
        labels.append(row["label_id"])
    except Exception as e:
        print(f"第{i}行出错: {e}")

if len(embeddings) == 0:
    raise ValueError("未生成任何有效 CodeT5 向量")

# 4. 数据增强（仅增强样本偏少的类）
def gaussian_scaling(vec): return vec * np.random.normal(1.0, 0.1, size=vec.shape)
def binary_mixup(v1, v2): return np.where(np.random.rand(*v1.shape) < 0.3, v2, v1)
def linear_interpolation(v1, v2): return v1 * (1 - np.random.rand()) + v2 * np.random.rand()
def linear_extrapolation(v1, v2): return v1 * (1 - np.random.uniform(-0.5, 1.5)) + v2 * np.random.uniform(-0.5, 1.5)

print("进行表示级数据增强...")
X_aug, y_aug = [], []
label_counts = Counter(labels)
max_count = max(label_counts.values())

# 构造 label -> 向量列表
label_to_vectors = {}
for vec, label in zip(embeddings, labels):
    label_to_vectors.setdefault(label, []).append(vec)

for label, vectors in label_to_vectors.items():
    count = len(vectors)
    if count >= max_count * 0.8:
        continue
    needed = max_count - count
    print(f"增强 label {label_encoder.inverse_transform([label])[0]}: 当前 {count}, 需要增强到 {max_count}")
    for _ in range(needed):
        v1, v2 = random.choices(vectors, k=2)
        X_aug.extend([
            gaussian_scaling(v1),
            binary_mixup(v1, v2),
            linear_interpolation(v1, v2),
            linear_extrapolation(v1, v2)
        ])
        y_aug.extend([label] * 4)

# 5. 合并数据
X_all = embeddings + X_aug
y_all = labels + y_aug

# 6. 划分数据集
X_train, X_test, y_train, y_test = train_test_split(
    X_all, y_all, stratify=y_all, test_size=0.2, random_state=42
)

# 7. 定义 VotingClassifier 模型
clf_rf = RandomForestClassifier(n_estimators=100, random_state=42)
clf_xgb = XGBClassifier(n_estimators=200, learning_rate=0.05, max_depth=8,
                        use_label_encoder=False, eval_metric='mlogloss', random_state=42)
clf_mlp = MLPClassifier(hidden_layer_sizes=(512, 256), activation='relu', max_iter=300, random_state=42)

ensemble_clf = VotingClassifier(estimators=[
    ('rf', clf_rf),
    ('xgb', clf_xgb),
    ('mlp', clf_mlp)
], voting='soft')

# 8. 训练模型
print("训练 VotingClassifier 多模型融合...")
ensemble_clf.fit(X_train, y_train)

# 9. 评估模型
preds = ensemble_clf.predict(X_test)
print("Test Accuracy: {:.2%}".format((preds == y_test).mean()))
print("Classification Report:")
print(classification_report(y_test, preds, target_names=label_encoder.classes_))
print("Confusion Matrix:")
print(confusion_matrix(y_test, preds))

# 10. 保存模型和编码器
joblib.dump(ensemble_clf, "voting_code_smell_classifier.pkl")
joblib.dump(label_encoder, "voting_label_encoder.pkl")
print("已保存 voting 模型与 label 编码器。")
