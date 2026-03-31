# 実装方法マニュアル

この文書は、`PythonChatBot` を実装・改修する人向けの開発メモです。  
「どこを触れば何が変わるか」「安全に機能追加するには何を見るか」を最短で把握できる形にまとめています。

## 1. 全体像

このプロジェクトは、`TwitchIO` ベースの Twitch チャットボットに、RPG システム、TTS、OBS オーバーレイ、Discord 詳細通知を載せた構成です。

実装上の主な責務は次の 4 層に分かれています。

- `bot.py`
  起動、Twitch 接続、ワーカー管理、コンポーネント登録、永続化の入口
- `bot_components/`
  チャットコマンドと通常発言への反応
- `rpg_core/`
  RPG の本体ロジック、戦闘、探索、装備、保存、オーバーレイ、Discord 連携
- `data/balance/`
  JSON ベースのバランス設定とマスターデータ

## 2. 起動フロー

起動時の流れは次のとおりです。

1. `app_config.py`
   `.env` を読み込み、`AppConfig` を組み立てます。
2. `bot.py`
   `validate_config()` で必須環境変数を確認します。
3. `StreamBot.__init__()`
   `data/runtime/botdata.json` を読み込み、`RPGManager`、TTS クライアント、オーバーレイ、Discord notifier を初期化します。
4. `StreamBot.setup_hook()`
   初期待機オーバーレイを書き出し、TTS ワーカーと探索ワーカーを起動し、`BasicCommands` と `NonCommandChat` を登録します。
5. `StreamBot.event_message()`
   チェインコマンド処理、探索の自動確定、通常のコマンド処理へ進みます。

## 3. ディレクトリごとの役割

- `app_config.py`
  環境変数の正規化、型変換、デフォルト値、実行ファイルパスの解決
- `bot.py`
  Bot 本体。保存、TTS キュー、イベント購読、ワーカー停止まで担当
- `bot_components/rpg_commands.py`
  `!状態`、`!探索`、`!装備`、`!wb` などのコマンド定義
- `bot_components/chat_listener.py`
  通常メッセージ時の EXP、キーワード応答、エモート反応、通常チャット TTS
- `rpg_core/manager.py`
  各サービスの窓口。UI 層からはまずここを呼ぶ
- `rpg_core/user_service.py`
  プレイヤー状態、育成、スキル、称号、所持品まわり
- `rpg_core/exploration_service.py`
  探索開始、探索結果、履歴、診断、自動周回
- `rpg_core/battle_service.py`
  戦闘シミュレーション、撤退判定、安全ライン計算
- `rpg_core/item_service.py`
  装備生成、自動装備、強化、売却、エンチャント
- `rpg_core/world_boss_service.py`
  ワールドボス進行、参加、ランキング、報酬
- `rpg_core/detail_overlay.py`
  OBS 向け HTML とテキスト出力
- `rpg_core/discord_notifier.py`
  Discord webhook への分割送信
- `rpg_core/storage.py`
  JSON とテキストの atomic write
- `data/balance/*.json`
  エリア、モンスター、装備、ワールドボス、スキルの定義

## 4. データの持ち方

データは大きく 2 種類あります。

- 静的データ
  `data/balance/` 配下の JSON。ゲーム仕様やマスターデータ
- 実行時データ
  `data/runtime/botdata.json`。ユーザー進行、探索状態、TTS 設定など

静的データは `rpg_core/balance_data.py` で読み込まれ、起動時に検証されます。  
JSON の形式が崩れている場合は `RuntimeError` で即停止する設計です。

実行時データは `rpg_core/storage.py` の `load_json()` / `atomic_save_json()` で扱います。  
直接 `open(..., "w")` で上書きせず、既存の atomic save を使うのが前提です。

## 5. 実装の基本方針

- UI 層のコマンドから直接複雑なロジックを書かない
- `BasicCommands` は入力解釈と返答組み立てに寄せる
- ゲームロジックは `RPGManager` または各 service に寄せる
- 永続化が必要な変更は `self.bot.save_data()` を忘れない
- 表示の詳細化が必要なら Twitch 短文と OBS / Discord 詳細表示を分けて考える
- 日本語入力の揺れは `nfkc()` を前提に吸収する
- 既存コマンド名や後方互換 alias はなるべく壊さない

## 6. コマンドを追加する手順

もっとも多い改修は `bot_components/rpg_commands.py` の編集です。

基本手順:

1. `BasicCommands` に補助メソッドが必要か確認する
2. `@commands.command(...)` を追加する
3. 必要な入力正規化を行う
4. `self.bot.rpg` 経由でロジックを呼ぶ
5. 必要なら `self.bot.save_data()` を呼ぶ
6. チャット返信と、必要に応じて詳細オーバーレイを更新する
7. `tests/test_command_routers.py` か関連テストを追加する

実装時の見どころ:

- ルーター型コマンドは `_split_subcommand()` と `_dispatch_subcommand()` を使っています
- 所有者限定は `_is_owner()` を使うのが基本です
- 対象ユーザー解決は `_get_identity()` / `_get_target_identity()` を使います
- 詳細表示を出す場合は `_show_detail_overlay()` 系の既存パターンに合わせます

## 7. 通常チャット反応を変える手順

通常発言に対する反応は `bot_components/chat_listener.py` が担当します。

変更例:

- キーワード反応を増やす
  `app_config.py` の `KEYWORD_RESPONSES` を編集
- 通常メッセージ EXP を調整する
  `rpg_core/rules.py` の `CHAT_EXP_*` 定数を編集
- エモート反応や通常チャット TTS の条件を変える
  `NonCommandChat.event_message()` を編集

この層では、コマンドメッセージ・スパム・Bot 自身の発言を先に弾いているので、その順番を壊さないようにします。

## 8. RPG ロジックを変える手順

RPG ロジックは `RPGManager` 配下の service に分かれています。

- プレイヤー状態や育成
  `rpg_core/user_service.py`
- 探索
  `rpg_core/exploration_service.py`
- 戦闘
  `rpg_core/battle_service.py`
- 装備
  `rpg_core/item_service.py`
- ワールドボス
  `rpg_core/world_boss_service.py`

変更先の目安:

- 「表示だけ変えたい」
  `rpg_commands.py`
- 「返ってくる結果の文言や組み立てを変えたい」
  `rpg_core/exploration_result.py`
- 「実際のルールや計算式を変えたい」
  各 service または `rpg_core/rules.py`
- 「エリアやスキル定義を増やしたい」
  `data/balance/*.json`

## 9. データ駆動で変更できるもの

コードを触らずに済む変更は、まず `data/balance/` を確認します。

- `areas.json`
  エリア定義、初回報酬、素材ドロップ、別名
- `monsters.json`
  出現モンスター、基礎ステータス、報酬
- `equipment.json`
  レアリティ、装備名、強化、エンチャント、素材ラベル
- `world_bosses.json`
  ワールドボスの HP、報酬、制限時間、素材
- `skills.json`
  スキル、レベル、特殊効果、初期解放状態

これらは `rpg_core/balance_data.py` が読み込むので、項目追加時は既存のバリデーション規則も確認してください。

## 10. 環境変数を追加する手順

新しい設定を増やすときは、次の 3 箇所をそろえるのが基本です。

1. `.env.example`
   サンプル値を追加
2. `app_config.py`
   読み取り、型変換、デフォルト値を追加
3. `dev.py`
   `doctor` で検査したいなら optional validation に追加

必須設定にしたい場合は、`bot.py` の `validate_config()` と `dev.py` の `REQUIRED_ENV_VARS` も更新します。

## 11. OBS / Discord / TTS の実装ポイント

### OBS オーバーレイ

`rpg_core/detail_overlay.py` が HTML / text を生成します。  
単純な行配列を受け取り、通常表示とワールドボス表示を分けて書き出します。

変更に向くケース:

- HTML 見た目変更
- 表示行の構造化
- ワールドボス専用 UI の拡張

### Discord 詳細通知

`rpg_core/discord_notifier.py` は webhook URL を正規化し、2000 文字制限を超えないよう分割送信します。  
詳細を Discord に出す方針自体は `bot.py` と `rpg_commands.py` 側の導線も一緒に見ます。

### TTS

- 通常チャット
  `bot_components/chat_listener.py`
- クライアント生成
  `rpg_core/tts.py`
- 棒読みちゃん
  `rpg_core/bouyomi.py`
- VOICEVOX
  `rpg_core/voicevox.py`

RPG イベント音声は VOICEVOX、通常チャットは `TTS_PROVIDER` に応じて切り替える構成です。

## 12. テストの考え方

実装後は最低限、変更箇所に近いテストを足します。

よく使う確認:

```powershell
python dev.py doctor
python dev.py test
```

個別テスト例:

```powershell
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_command_routers.py" -v
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_environment_setup.py" -v
.\venv\Scripts\python.exe -m unittest discover -s tests -p "test_world_boss.py" -v
```

テスト追加先の目安:

- コマンド分岐
  `tests/test_command_routers.py`
- 環境変数やパス
  `tests/test_environment_setup.py`
- オーバーレイ
  `tests/test_detail_overlay.py`
- Discord 通知
  `tests/test_discord_notifier.py`
- TTS
  `tests/test_tts_clients.py`
- 探索結果や RPG 品質
  `tests/test_exploration_result.py`, `tests/test_rpg_quality_of_life.py`
- ワールドボス
  `tests/test_world_boss.py`

## 13. 改修時の注意点

- `get_user()` は新規ユーザー補完やスターター配布を含むため、素の辞書を直接触る前に意図を確認する
- 保存先 JSON が壊れている時は起動を止める設計なので、エラーを握りつぶさない
- `data/runtime/` は生成物なので、仕様変更時は初回生成も意識する
- Twitch に長文を返さず、詳細は OBS / Discord に逃がす設計を維持する
- world boss まわりは TTS、オーバーレイ、Discord 表示が連動しやすいので、単独修正でも関連テストを見る
- 既存 alias を減らすと視聴者導線を壊しやすい

## 14. 変更時のおすすめ順

機能追加は次の順で進めると安全です。

1. まずデータ変更で済むか確認する
2. だめなら service にロジックを追加する
3. その後に `RPGManager` の公開メソッドをそろえる
4. 最後に `rpg_commands.py` で UI をつなぐ
5. 近いテストを追加して `python dev.py test`

この順番にしておくと、表示層とロジック層が混ざりにくく、あとで保守しやすくなります。
