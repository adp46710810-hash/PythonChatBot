# Data Layout

- `balance/`: RPG balance tuning files
- `runtime/`: bot save data such as `botdata.json`

Manual backups are stored outside the source tree at
`C:\Users\adp46\Documents\バックアップ\chatbot_backups`.

`data/runtime/botdata.json` is the current default save path.

探索モードや装備由来の生存補助、装飾のモード別A/D補正、探索時間計算などのルールは `rpg_core/rules.py` を参照してください。
