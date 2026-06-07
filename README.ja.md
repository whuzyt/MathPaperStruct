<p align="center">
  <img src="https://readme-typing-svg.demolab.com?font=Fira+Code&size=28&duration=3000&pause=500&color=3B82F6&center=true&vCenter=true&width=600&lines=Question+Bank+Pipeline;MinerU+%2B+DeepSeek+%E2%86%92+構造化数学問題バンク" alt="Typing SVG" />
</p>

<p align="center">
  <a href="README.md"><img src="https://img.shields.io/badge/English-3B82F6?style=for-the-badge&logo=readme&logoColor=white" alt="English" /></a>
  <a href="README.zh-CN.md"><img src="https://img.shields.io/badge/简体中文-EF4444?style=for-the-badge&logo=readme&logoColor=white" alt="简体中文" /></a>
  <a href="README.ja.md"><img src="https://img.shields.io/badge/日本語-8B5CF6?style=for-the-badge&logo=readme&logoColor=white" alt="日本語" /></a>
</p>

<p align="center">
  <a href="https://github.com/chengxudong2025/question-bank-pipeline/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow?style=flat-square" alt="License" /></a>
  <a href="#"><img src="https://img.shields.io/badge/Python-3.11+-blue?style=flat-square&logo=python&logoColor=white" alt="Python" /></a>
  <a href="#"><img src="https://img.shields.io/badge/テスト-703%20通過-brightgreen?style=flat-square" alt="Tests" /></a>
  <a href="#"><img src="https://img.shields.io/badge/状態-アクティブ-success?style=flat-square" alt="Status" /></a>
  <a href="#"><img src="https://img.shields.io/badge/PR募集中-brightgreen?style=flat-square&logo=github" alt="PRs Welcome" /></a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>

---

# 📐 Question Bank Pipeline

> **MinerU + DeepSeek バックエンド** — 数学の試験 PDF を構造化されたレビュー可能な問題バンクデータに変換します。

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## ✨ ハイライト

- 🧠 **PDF → 構造化問題** — MinerU がレイアウトを解析、DeepSeek が構造を正規化
- ✅ **決定論的フォールバック** — 選択肢解析・回答補完・問題タイプ推論をモデル推論なしで実行
- 🔍 **ルールベース品質ゲート** — 問題文・選択肢・回答・LaTeX・解説の10項目以上をチェック
- 📊 **本番可観測性** — マニフェスト駆動バッチ実行、ステップ単位の時間計測、障害分類
- 🖥️ **Web コンソール + デスクトップ GUI** — FastAPI ダッシュボードと Tkinter デスクトップアプリ
- 🐘 **PostgreSQL + MinIO** — 本番グレードの永続化とオブジェクトストレージ
- 🔁 **リトライ & レジューム** — MinerU 自動リトライ（指数バックオフ）、マニフェスト駆動クラッシュ復旧

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🚀 クイックスタート

```bash
git clone https://github.com/chengxudong2025/question-bank-pipeline.git
cd question-bank-pipeline

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env
# .env に DeepSeek API キーを設定

docker compose up -d postgres minio
question-bank db init

PYTHONPATH=src python3 -m unittest discover -s tests -v
# ✓ 703 tests passed

uvicorn question_bank.api.app:create_app --factory --reload
# http://127.0.0.1:8000/ を開く
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 🏗 アーキテクチャ

```text
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ PDFファイル│ ──► │ MinerU 解析  │ ──► │ 問題分割器    │ ──► │ DeepSeek   │
│          │     │ (レイアウト) │     │               │     │ 構造化     │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
                                                                    │
                                                                    ▼
┌──────────┐     ┌──────────────┐     ┌───────────────┐     ┌────────────┐
│ レビュー │ ◄── │ 品質ゲート   │ ◄── │ タイプ推論    │ ◄── │ 補完       │
│ キュー   │     │              │     │               │     │            │
└──────────┘     └──────────────┘     └───────────────┘     └────────────┘
```

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

## 📄 ライセンス

本プロジェクトは **MIT ライセンス** の下で提供されます — 詳細は [LICENSE](LICENSE) ファイルをご覧ください。

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/colored.png" alt="divider" />
</p>

<p align="center">
  <sub>❤️ を込めて構築</sub>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/andreasbm/readme/master/assets/lines/rainbow.png" alt="rainbow" />
</p>
