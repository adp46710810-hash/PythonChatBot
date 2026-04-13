# DevAgent

`DevAgent` は、`Codex / ChatGPT` を主担当にしつつ、リポジトリ文脈をまとめたり、必要なときだけ `Gemini` に相談できる汎用 CLI です。

このリポジトリでは、ルートの [agent.project.yaml](/C:/Users/adp46/Documents/PythonChatBot/chatbot/agent.project.yaml) を使って安全な読取範囲と実行可能コマンドを定義しています。

## 使い方

```powershell
.\venv\Scripts\python.exe -m devagent files "TTS"
.\venv\Scripts\python.exe -m devagent context "ワールドボス"
.\venv\Scripts\python.exe -m devagent ask "探索結果表示の改善方針を整理したい"
.\\venv\\Scripts\\python.exe -m devagent challenge "WBを6分イベントにしたい"
.\\venv\\Scripts\\python.exe -m devagent spec "ワールドボスの総合貢献王仕様を固めたい"
.\\venv\\Scripts\\python.exe -m devagent note "このプロジェクトの紹介記事"
.\venv\Scripts\python.exe -m devagent review
.\venv\Scripts\python.exe -m devagent summarize --log output.txt
.\venv\Scripts\python.exe -m devagent run test
```

`ask` / `challenge` / `spec` / `review` / `summarize` は、ローカル文脈を集めたうえで Gemini へ問い合わせるか、手動相談用のプロンプトを出します。

- `ask`: 普通に相談する
- `challenge`: 反対意見や弱点洗い出しをさせる
- `spec`: 仕様書向けに整理させる
- `note`: note 記事向けに構成案や書き出し案を出させる
- `review`: 差分レビューをさせる
- `summarize`: ログを要約させる

note 記事用にプロジェクト概要をまとめた共有ブリーフは
[docs/note_article_project_context.md](/C:/Users/adp46/Documents/PythonChatBot/chatbot/docs/note_article_project_context.md)
に置いてあります。Gemini に直接貼って使っても、`devagent note` から自動で読み込ませても構いません。

`.env` に `GEMINI_API_KEY` を設定すると、`ask` / `review` / `summarize` は Gemini API を直接呼びます。キー未設定時は、従来どおり手動相談用のプロンプトを返します。

```env
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
GEMINI_BASE_URL=https://generativelanguage.googleapis.com/v1beta
GEMINI_TIMEOUT_SEC=60
```

## 方針

- `Codex` 主担当
- `V1` では自動編集しない
- 実行コマンドは `agent.project.yaml` の `allowed_commands` に完全一致したものだけ許可
- `.env` やランタイム保存先は profile でブロック
- Gemini や外部AIへ相談する場合も、最終判断は人間または Codex が行う

## AI連携デモ

2026-03-30: GitHub PR流でCopilot/Codex/Geminiと連携開発するデモを実施。
WBオーバーレイの meta 情報管理と state payload 拡張を例に、AIツール活用のワークフローを検証中。
