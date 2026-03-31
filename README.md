# PythonChatBot

軽量な RPG システムと棒読みちゃん / VOICEVOX TTS に対応した Twitch チャットボットです。

## 主な入口

- `bot.py`: ボットの起動処理と TwitchIO のライフサイクル
- `app_config.py`: 環境変数ベースのボット設定と実行データのパス設定
- `bot_components/`: コマンドと通常チャット処理
- `rpg_core/`: RPG のロジック、保存処理、ユーティリティ
- `rpg_core/exploration_result.py`: 探索結果の戦闘数計算、撤退情報、表示補助
- `rpg_core/rules.py`: RPG のルール定数とバランス設定
- `config.py`: 後方互換用の設定ラッパー
- `rpg.py`: 後方互換用のインポートラッパー
- `data/`: 実行データとバランスデータ
- `docs/implementation_manual.md`: 実装者向けの構成と拡張手順
- `docs/stream_description_help.md`: 配信概要欄やパネルに貼れるユーザー向けヘルプ
- `docs/discord_response_manual.md`: Discord で詳しい返答を読むための視聴者向けマニュアル
- `tests/`: 退避情報とデータ正規化の回帰確認

## 主な編集ポイント

- コマンドを追加・変更する: `bot_components/rpg_commands.py`
- 通常チャット反応や TTS キュー挙動を変更する: `bot_components/chat_listener.py`
- RPG ルールを調整する: `rpg_core/rules.py`
- 環境設定を変更する: `app_config.py` と `.env`
- RPG バランスデータを調整する: `data/balance/areas.json`, `data/balance/monsters.json`, `data/balance/equipment.json`
- OBS 用の詳細ビューを調整する: `rpg_core/detail_overlay.py`

## 整理方針

- `bot.py`, `app_config.py`, `bot_components/`, `rpg_core/` がチャットボット本体です。通常の改修はこの範囲を見れば足ります。
- `data/balance/` は手で編集する設定、`data/runtime/` は実行中に更新される保存先です。
- 必要ならバックアップはソースツリー外の任意の場所に退避してください。
- `docs/` の直下にある `.md` は共有向けドキュメントです。`docs/logs/` と `docs/notes/` はローカル運用向けの作業フォルダとして既定では Git 管理対象外です。
- `layerdivider/` は独立したオプション用サブモジュールです。チャットボット本体のセットアップには必須ではありません。
- `venv/`, `layerdivider/venv/`, 各 `__pycache__/` は生成物です。不要なら削除して再生成できます。

## RPG バランス用ファイル

- `data/balance/areas.json`: エリア tier、金額補正、ドロップ補正、レア補正、エリア別名
- `data/balance/monsters.json`: モンスターの基礎ステータス、報酬、出現率
- `data/balance/equipment.json`: レアリティ表、スロット比率、装備名、装備パワー計算、強化・エンチャント設定
- `data/runtime/botdata.json`: プレイヤー状態の保存データ
- `data/runtime/obs_detail_overlay.html`: OBS Browser Source 用の詳細ビュー
- `data/runtime/obs_detail_overlay.txt`: OBS Text Source 用の生ログ
- ソースツリー外の任意バックアップ先: 手動で保管するローカルバックアップ

バランスを変更したい場合はこれらの JSON を編集し、ボットを再起動してください。

## セットアップ

最短導線は `dev.py` を使う方法です。`python` が使えれば、依存導入、確認、テスト、起動を同じ入口に揃えられます。

GitHub から clone した直後は、次の流れで始めるのが最短です。

```powershell
git clone <repository-url>
cd <repository-directory>
python dev.py setup
Copy-Item .env.example .env
python dev.py doctor
```

```powershell
python dev.py setup
python dev.py doctor
```

`.env` は `.env.example` を元に作成し、少なくとも以下を設定してください。

```powershell
Copy-Item .env.example .env
```

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TWITCH_BOT_ID=
TWITCH_OWNER_ID=
TWITCH_CHANNEL=
DISCORD_WEBHOOK_URL=
DISCORD_INVITE_URL=
```

`python dev.py doctor` は `venv` と必須環境変数の不足をまとめて確認できます。

`BOT_DATA_FILE` を指定しない場合、保存先は `data/runtime/botdata.json` です。`dev.py` を使わず手動で進める場合は、従来どおり以下でも構いません。

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

通常チャットTTSは `TTS_PROVIDER` で切り替えられます。RPG / WB のイベント読み上げは VOICEVOX を使います。

棒読みちゃんを使う場合:

```env
TTS_ENABLED=1
TTS_PROVIDER=bouyomi
BOUYOMI_HOST=127.0.0.1
BOUYOMI_PORT=50001
```

RPG / WB 読み上げの VOICEVOX:

```env
TTS_ENABLED=1
VOICEVOX_HOST=127.0.0.1
VOICEVOX_PORT=50021
VOICEVOX_SPEAKER=1
```

ローカルで VOICEVOX Engine か VOICEVOX 本体を起動しておいてください。Windows ではボット側が `winsound` で生成 WAV をそのまま再生します。RPG / WB 読み上げの話者は `!読み上げ話者 ずんだもん` や `!読み上げ話者 ずんだもん あまあま` で変更できます。ID指定の `!読み上げID 3` も引き続き使え、設定は保存データにも残ります。

## 起動方法

```powershell
python dev.py run
```

直接起動したい場合は `.\venv\Scripts\python.exe bot.py` でも動きます。

## テスト

```powershell
python dev.py test
```

直接実行する場合は `.\venv\Scripts\python.exe -m unittest discover -s tests -v` です。普段の入口を `python dev.py ...` に揃えると、`python` と `venv` 外の実行が混ざりにくくなります。

`layerdivider/` も使いたい場合だけ、追加で次を実行してください。

```powershell
git submodule update --init --recursive
```

## ローカル確認

最小確認はこの順で十分です。

1. `python dev.py doctor`
2. `python dev.py test`
3. `python dev.py run` で起動確認
4. チャット導線を手動確認
   `!状態`
   `!攻略 エリア`
   `!探索 開始 朝の森`
   `!探索 結果`
   `!装備 整理`
   `!攻略`

自動周回の確認をしたい場合は、進行達成後に `!探索 自動 通常 朝の森` を使ってください。旧入力の `!探索開始 自動 朝の森` も互換で残しています。

## 依存関係

- `twitchio==3.2.1`
- `python-dotenv==1.2.2`

上記は `requirements.txt` に定義しています。`dev.py setup` はこの内容をそのまま `venv` にインストールします。

## OBS / Discord 連携

- Twitch チャットには短い返答だけを返し、`!状態`、`!探索 結果`、`!探索 前回`、`!探索 履歴`、`!探索 戦利品`、`!装備 整理`、`!攻略`、`!探索 戦闘` 実行時の詳細は `data/runtime/obs_detail_overlay.html` と `data/runtime/obs_detail_overlay.txt` に出力されます。あわせて `data/runtime/obs_detail_overlay_info.html` と `data/runtime/obs_detail_overlay_wb.html` も自動生成されます。
- `DISCORD_WEBHOOK_URL` を設定すると、同じ詳細内容を Discord webhook にも送信します。Webhook が有効な間は、Twitch 側の短文案内も `詳細はDiscord` に寄せます。
- `DISCORD_WEBHOOK_USERNAME` を設定すると、Discord 側の送信名を変更できます。未指定時は `Twitch RPG Detail` です。
- `DISCORD_INVITE_URL` を設定すると、`!discord` で視聴者向けの Discord 参加URLを返せます。
- 視聴者向けの案内文が必要なら `docs/discord_response_manual.md` をそのまま共有できます。
- `!探索 結果` は受け取り待ちならそのまま受け取りまで完了し、受け取り済みでも最新探索の詳細を OBS に再表示できます。旧 `!探索詳細` は互換導線として `!探索 結果` に統合されています。
- `!探索 前回` は受取済みの最新探索、`!探索 履歴` は直近 5 件、`!探索 戦利品` は直近探索の主なドロップを見返すためのコマンドです。
- `!装備 整理` は自動装備更新と不要品売却をまとめて実行します。`!装備更新` は後方互換用に残してあり、同じ整理ロジックを使います。
- 自動周回は `星影の祭壇` の導線解放と欠片 3 個で開始できます。開始コマンドは `!探索 自動 [モード] [エリア]`、旧 `!探索開始 自動 [エリア]` も後方互換で使用できます。
- `!探索 結果` では探索全体の要約を表示し、ターンごとの戦闘ログは `!探索 戦闘` で OBS に出します。`!探索 戦闘 3` のように指定すると個別戦闘を表示でき、各ターンで敵HPと自分HPの推移を確認できます。
- `!探索 戦闘` の最下行には、常に探索を切り上げた場所と理由が `撤退情報:` として表示されます。
- Browser Source を使う場合は、統合表示なら `data/runtime/obs_detail_overlay.html`、情報だけなら `data/runtime/obs_detail_overlay_info.html`、WBビジュアルだけなら `data/runtime/obs_detail_overlay_wb.html` を読み込んでください。統合表示と情報表示は固定シェルが 2 秒ごとに中身だけ差し替えます。WBビジュアルだけは固定DOMのまま `state.js` を読み直す方式なので、立ち絵画像は定期更新で再読込されません。WBステージはWB不在時に描画されず、更新が約8秒止まった場合も自動で非表示になります。
- WB画像は弱い順に `data/runtime/1.png` `data/runtime/2.png` `data/runtime/3.png` `data/runtime/4.png` を使います。対応は `1: 灼甲帝ヴァルカラン` `2: 月蝕機卿ネメシス` `3: 魔弾妃ヘクセミア` `4: 迅剣姫ラファエラ` です。該当画像が無い場合は既存の共通画像 `data/runtime/world_boss_visual.png` を使います。
- Browser Source の幅・高さを OBS 側で変えると、オーバーレイの横幅、縦の表示量、文字サイズ、余白がその範囲に合わせて自動調整されます。
- Text Source を使う場合は `data/runtime/obs_detail_overlay.txt` をファイル読み込みしてください。
- 探索完了後は、そのユーザーが次にチャット発言した時点でも探索結果を自動受け取りします。`!探索 結果` は手動受け取りしたい場合にも使えます。
- 探索完了時のチャット通知は `!探索 結果` と `!探索 戦闘` だけを短く案内します。受け取り後のチャット返信もスマホで読みやすい短文に寄せています。
