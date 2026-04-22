# 贡献指南

感谢你对 **即声 SpeakNow** 的关注！

## 提交 Issue

- Bug 报告：请描述复现步骤、系统版本、错误信息
- 功能建议：请描述使用场景和期望效果

## 提交 PR

1. Fork 本仓库
2. 创建分支：`git checkout -b feat/your-feature` 或 `fix/your-fix`
3. 提交改动：`git commit -m "简述改动内容"`
4. 推送分支：`git push origin feat/your-feature`
5. 创建 Pull Request

## 代码风格

- Python 3.10+
- 遵循现有代码风格（中文注释、docstring）
- 保持简洁，不过度抽象

## 开发环境

```bash
git clone https://github.com/simonxiao2006/speaknow.git
cd speaknow
cp .env.example .env   # 填入你的火山引擎凭证
pip install -r requirements.txt
python main.py
```
