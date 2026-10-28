import os
import torch
import joblib
import pandas as pd
import numpy as np
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
from datetime import datetime
from difflib import SequenceMatcher

# ====================== 模型配置 ============================
PRETRAINED_MODEL = "Salesforce/codet5-base"
MAX_LEN = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
EXCEL_PATH = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"
THRESHOLD = 0.6  # 可信度阈值，高于此值判定为核心异味

# 加载模型
tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
encoder = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).get_encoder().to(DEVICE)
clf = joblib.load("voting_code_smell_classifier.pkl")
label_encoder = joblib.load("voting_label_encoder.pkl")


# ====================== 加载已知异味样本 ======================
def load_known_smells(path):
    try:
        df_known = pd.read_excel(path)
        # 假设列名为 '异味代码'
        return df_known['异味代码'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"⚠️ 无法加载Excel样本: {e}")
        return []


KNOWN_SMELLS = load_known_smells(EXCEL_PATH)


# ====================== 相似度计算 ============================
def get_similarity(code_a, code_b):
    """计算两个代码片段的文本相似度"""
    return SequenceMatcher(None, code_a.strip(), code_b.strip()).ratio()


# ====================== 嵌入向量 =============================
def get_code_embedding(code_snippet):
    inputs = tokenizer(
        code_snippet,
        return_tensors="pt",
        truncation=True,
        padding="max_length",
        max_length=MAX_LEN
    )
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}

    with torch.no_grad():
        encoder_outputs = encoder(**inputs)
        # 取平均池化作为特征
        emb = encoder_outputs.last_hidden_state.mean(dim=1).squeeze(0).cpu().numpy()
    return emb


# ====================== 预测与可信度计算 =========================
def predict_with_confidence(code):
    embedding = get_code_embedding(code)

    # 1. 模型原始预测
    pred_id = clf.predict([embedding])[0]
    label = label_encoder.inverse_transform([pred_id])[0]

    # 基础可信度 (模型预测为异味则给 0.5 基础分，正常则 0)
    base_confidence = 0.5 if label != "正常-不使用并行" else 0.1

    # 2. 规则修正
    lowered = code.lower()
    if label == "正常-不使用并行":
        if any(kw in lowered for kw in ["for ", "for(", "while ", "while("]):
            label = "并行忽视"
            base_confidence = 0.4  # 规则触发的基础分

    # 3. 相似度加成 (计算与 Excel 中已知异味的最大相似度)
    max_sim = 0
    if KNOWN_SMELLS:
        # 为了性能，可以只对比前 500 个字符
        sims = [get_similarity(code[:500], ks[:500]) for ks in KNOWN_SMELLS]
        max_sim = max(sims) if sims else 0

    # 综合可信度 = 40% 模型规则权重 + 60% 样本相似度权重
    # 如果相似度极高，即便模型漏报，也能拉高分数
    total_confidence = (base_confidence * 0.4) + (max_sim * 0.6)

    return label, round(total_confidence, 4)


# ====================== 文件处理逻辑 ============================
def get_all_source_files(root):
    exts = (".c", ".cc", ".cpp", ".h")
    return [os.path.join(path, f) for path, _, files in os.walk(root) for f in files if f.endswith(exts)]


def split_file_into_snippets(filepath, window_size=40):
    try:
        with open(filepath, encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
        return [(i + 1, i + window_size, "".join(lines[i:i + window_size]))
                for i in range(0, len(lines), window_size)]
    except:
        return []


# ====================== 执行分析 ===============================
def analyze_project(root_dir):
    files = get_all_source_files(root_dir)
    print(f"📁 共发现 {len(files)} 个源码文件")

    results = []
    for file in files:
        snippets = split_file_into_snippets(file, window_size=40)
        for (start_line, end_line, code) in snippets:
            if not code.strip(): continue

            label, confidence = predict_with_confidence(code)

            results.append({
                "file": file,
                "location": f"L{start_line}-L{end_line}",
                "pred_label": label,
                "confidence": confidence,
                "is_core_smell": "Yes" if confidence >= THRESHOLD else "No",
                "code_snapshot": code[:200].replace("\n", " ")  # 只存简报用于CSV预览
            })

    # 按可信度降序排列
    results.sort(key=lambda x: x['confidence'], reverse=True)
    return results


# ====================== 主入口 =============================
if __name__ == "__main__":
    ROOT_DIR = r"C:\Users\dell\Desktop\检测的CAE项目\dealii-1-6"

    print("🚀 开始深度异味检测（结合专家样本库）...")
    all_results = analyze_project(ROOT_DIR)

    # 转换为 DataFrame
    df = pd.DataFrame(all_results)

    # 输出 1: 全量检测结果
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    full_output = os.path.join(ROOT_DIR, f"dealii_全量异味预测_{ts}.csv")
    df.to_csv(full_output, index=False, encoding="utf-8-sig")

    # 输出 2: 核心异味报告 (超过阈值)
    core_smells = df[df['confidence'] >= THRESHOLD]
    core_output = os.path.join(ROOT_DIR, f"dealii_核心异味清单_{ts}.csv")
    core_smells.to_csv(core_output, index=False, encoding="utf-8-sig")

    print(f"\n✅ 分析完成！")
    print(f"📊 全量结果（按可信度排序）: {full_output}")
    print(f"🔥 核心异味发现: {len(core_smells)} 处，已单独提取至: {core_output}")