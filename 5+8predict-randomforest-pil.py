import torch
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM
import joblib
import numpy as np
import pandas as pd
import os

# 配置
PRETRAINED_MODEL = "Salesforce/codet5-base"
MAX_LEN = 512
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# # 加载模型和工具(随机森林)
# tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
# encoder = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).get_encoder().to(DEVICE)
# clf = joblib.load("code_smell_rf_classifier.pkl")
# label_encoder = joblib.load("label_encoder.pkl")

# 加载模型和工具（xgboost）
# tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
# encoder = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).get_encoder().to(DEVICE)
# clf = joblib.load("xgboost_code_smell_classifier.pkl")  # ✅ 加载 XGBoost 模型
# label_encoder = joblib.load("xgboost_label_encoder.pkl")  # ✅ 加载对应的编码器


# 加载模型和工具（多模型）
tokenizer = AutoTokenizer.from_pretrained(PRETRAINED_MODEL)
encoder = AutoModelForSeq2SeqLM.from_pretrained(PRETRAINED_MODEL).get_encoder().to(DEVICE)
clf = joblib.load("voting_code_smell_classifier.pkl")  # ✅ 加载 XGBoost 模型
label_encoder = joblib.load("voting_label_encoder.pkl")  # ✅ 加载对应的编码器


def get_code_embedding(code_snippet):
    inputs = tokenizer(code_snippet, return_tensors="pt", truncation=True, padding="max_length", max_length=MAX_LEN)
    inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    with torch.no_grad():
        encoder_outputs = encoder(**inputs)
        embedding = encoder_outputs.last_hidden_state.mean(dim=1).squeeze(0).cpu().numpy()
    return embedding


def predict_code(code_snippet):
    # 获取嵌入向量并进行模型预测
    embedding = get_code_embedding(code_snippet)
    pred_label_id = clf.predict([embedding])[0]
    pred_label = label_encoder.inverse_transform([pred_label_id])[0]

    # 后处理规则：若预测为“正常-不使用并行”但代码中含 for/while，则修正为“并行忽视”
    if pred_label == "正常-不使用并行":
        lowered_code = code_snippet.lower()
        if "for " in lowered_code or "for(" in lowered_code or "while " in lowered_code or "while(" in lowered_code:
            return "并行忽视"

    return pred_label


def batch_predict_from_excel(filepath):
    df = pd.read_excel(filepath)

    # 检查列数
    if df.shape[1] < 2:
        raise ValueError("Excel 文件至少需要两列：标签 和 代码")

    original_labels = df.iloc[:, 0].astype(str).tolist()
    code_snippets = df.iloc[:, 1].astype(str).tolist()

    predictions = []
    correct_count = 0

    print("开始预测...")

    for orig_label, code in zip(original_labels, code_snippets):
        pred_label = predict_code(code)
        predictions.append(pred_label)
        if pred_label == orig_label:
            correct_count += 1

    df["预测标签"] = predictions
    accuracy = correct_count / len(original_labels)
    print(f"预测正确率：{accuracy * 100:.2f}%")

    # 输出结果文件
    import os
    import datetime

    output_path = os.path.join(
        os.path.dirname(filepath),
        os.path.splitext(os.path.basename(filepath))[0]
        + "_预测结果_"
        + datetime.datetime.now().strftime("%Y%m%d_%H%M%S")  # 时间戳
        + ".xlsx"
    )

    df.to_excel(output_path, index=False)
    print(f"结果已保存至：{output_path}")


# 示例运行
if __name__ == "__main__":
    input_excel = r"C:\Users\dell\Desktop\并行忽视+过度并行\处理版本二\测试集-偶数.xlsx"  # 修改成你的实际文件路径
    batch_predict_from_excel(input_excel)